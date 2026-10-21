#!/usr/bin/env python3
"""
ClickBench benchmark runner — PostgreSQL, DuckDB e Polars
Protocolo: 4 execuções mensuradas por query/engine (1 warm-up descartado).
EventDate e EventTime normalizados para DATE/TIMESTAMP em todos os motores.
"""

import csv, os, re, time, threading, subprocess, sys, resource
from pathlib import Path
from datetime import datetime, date
import multiprocessing as mp

import psutil
import duckdb
import polars as pl
import psycopg2
from codecarbon import EmissionsTracker

# ── Configuração ─────────────────────────────────────────────────────────────
PARQUET     = Path.home() / "bench/data/clickbench/hits.parquet"
QUERY_FILE  = Path.home() / "bench/queries/clickbench/queries.sql"
RESULTS_DIR = Path.home() / "bench/results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

PG_CONN  = dict(host="127.0.0.1", dbname="bench_clickbench",
                user="bench", password="bench")
DUCK_DB  = str(Path.home() / "bench/data/clickbench/hits.duckdb")
REPS     = 5          # inclui warm-up; rep=1 descartado
TIMEOUT  = 300        # segundos por query
PG_TOUT  = 270        # statement_timeout PostgreSQL (ms → s via psycopg2 option)
POLARS_MEM_GB = 30

# ── Parse queries ─────────────────────────────────────────────────────────────
def parse_queries(path: Path) -> dict[int, str]:
    text = path.read_text()
    parts = re.split(r'--\s*Q(\d+)', text)
    return {int(parts[i]): parts[i+1].strip()
            for i in range(1, len(parts), 2)}

# ── Monitor de recursos ───────────────────────────────────────────────────────
class ResourceMonitor:
    def __init__(self):
        self.cpu_samples: list[float] = []
        self.ram_peak_mb: float = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        self.cpu_samples, self.ram_peak_mb = [], 0.0
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join()

    def _loop(self):
        proc = psutil.Process()
        while not self._stop.wait(0.5):
            try:
                self.cpu_samples.append(psutil.cpu_percent(interval=None))
                rss = proc.memory_info().rss / (1024 * 1024)
                if rss > self.ram_peak_mb:
                    self.ram_peak_mb = rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                break

    @property
    def cpu_avg(self) -> float:
        return sum(self.cpu_samples) / len(self.cpu_samples) if self.cpu_samples else 0.0

# ── Disk I/O helper ───────────────────────────────────────────────────────────
def _disk_read_mb() -> float:
    return psutil.disk_io_counters().read_bytes / (1024 * 1024)

# ── Runners ───────────────────────────────────────────────────────────────────
def run_pg(sql: str) -> tuple[float, float]:
    conn = psycopg2.connect(**PG_CONN,
                            options=f"-c statement_timeout={PG_TOUT * 1000}")
    cur  = conn.cursor()
    d0   = _disk_read_mb()
    t0   = time.perf_counter()
    cur.execute(sql)
    cur.fetchall()
    elapsed = time.perf_counter() - t0
    disk_mb = _disk_read_mb() - d0
    cur.close(); conn.close()
    return elapsed, disk_mb

def run_duckdb(sql: str, con: duckdb.DuckDBPyConnection) -> tuple[float, float]:
    d0 = _disk_read_mb()
    t0 = time.perf_counter()
    con.execute(sql).fetchall()
    return time.perf_counter() - t0, _disk_read_mb() - d0

# ── Polars worker (subprocess para conter OOM) ────────────────────────────────
def _polars_worker(sql: str, parquet: str, queue: mp.Queue):
    try:
        mem_bytes = POLARS_MEM_GB * 1024**3
        resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))

        hits_lf = (
            pl.scan_parquet(parquet)
            .with_columns([
                pl.from_epoch(pl.col("EventTime"), time_unit="s").alias("EventTime"),
                pl.col("EventDate").cast(pl.Int32).cast(pl.Date).alias("EventDate"),
            ])
        )
        ctx = pl.SQLContext(hits=hits_lf)
        t0  = time.perf_counter()
        ctx.execute(sql).collect()
        queue.put(time.perf_counter() - t0)
    except Exception as e:
        queue.put(e)

def run_polars(sql: str) -> tuple[float, float]:
    q   = mp.Queue()
    p   = mp.Process(target=_polars_worker,
                     args=(sql, str(PARQUET), q), daemon=True)
    d0  = _disk_read_mb()
    p.start()
    p.join(timeout=TIMEOUT)
    disk_mb = _disk_read_mb() - d0
    if p.is_alive():
        p.kill(); p.join()
        raise TimeoutError("Polars timeout")
    result = q.get() if not q.empty() else None
    if result is None:
        raise MemoryError("Polars OOM (queue vazia)")
    if isinstance(result, Exception):
        raise result
    return result, disk_mb

# ── Medição com codecarbon ────────────────────────────────────────────────────
def measure(engine_fn, monitor: ResourceMonitor) -> tuple:
    tracker = EmissionsTracker(
        project_name="clickbench", output_dir=str(RESULTS_DIR),
        log_level="error", save_to_file=False, tracking_mode="process",
    )
    monitor.start()
    tracker.start()
    elapsed, disk_mb = engine_fn()
    kwh = tracker.stop() or 0.0
    monitor.stop()
    return elapsed, monitor.cpu_avg, monitor.ram_peak_mb, disk_mb, kwh

# ── Cache drop ────────────────────────────────────────────────────────────────
def drop_caches():
    subprocess.run(["sudo", "tee", "/proc/sys/vm/drop_caches"],
                   input=b"3", capture_output=True, check=False)
    time.sleep(2)

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    mp.set_start_method("spawn", force=True)

    # filtro opcional: python run_clickbench.py 1 5 21
    filter_qs = set(int(a) for a in sys.argv[1:]) if len(sys.argv) > 1 else None

    queries = parse_queries(QUERY_FILE)
    print(f"Queries carregadas: {len(queries)}")

    # DuckDB — VIEW com tipos normalizados
    duck_con = duckdb.connect(DUCK_DB)
    duck_con.execute("SET threads=16; SET memory_limit='40GB';")
    duck_con.execute(f"""
        CREATE OR REPLACE VIEW hits AS
        SELECT * REPLACE (
            to_timestamp(EventTime) AS EventTime,
            (DATE '1970-01-01' + EventDate::INTEGER) AS EventDate
        )
        FROM read_parquet('{PARQUET}')
    """)
    print("DuckDB VIEW criada.")

    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = RESULTS_DIR / f"clickbench_{ts}.csv"
    fields   = ["engine", "suite", "sf", "query", "rep",
                "elapsed_s", "cpu_pct", "ram_mb", "disk_mb", "energy_kwh"]

    dnf: set[tuple[str, int]] = set()   # (engine, qnum) que já falharam
    monitor = ResourceMonitor()

    with open(out_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()

        for qnum in sorted(queries):
            if filter_qs and qnum not in filter_qs:
                continue
            sql = queries[qnum]
            print(f"\n=== Q{qnum:02d} ===")

            engines = [
                ("postgresql", lambda s=sql: run_pg(s)),
                ("duckdb",     lambda s=sql: run_duckdb(s, duck_con)),
                ("polars",     lambda s=sql: run_polars(s)),
            ]

            for rep in range(1, REPS + 1):
                for eng_name, eng_fn in engines:
                    if (eng_name, qnum) in dnf:
                        continue

                    drop_caches()
                    try:
                        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FTE
                        if eng_name == "postgresql":
                            with ThreadPoolExecutor(max_workers=1) as ex:
                                fut = ex.submit(lambda: measure(eng_fn, monitor))
                                try:
                                    elapsed, cpu, ram, disk, kwh = fut.result(timeout=TIMEOUT)
                                    tag = f"{elapsed:.3f}s"
                                except FTE:
                                    elapsed, cpu, ram, disk, kwh = -1.0, 0, 0, 0, 0
                                    tag = "TIMEOUT"
                                    dnf.add((eng_name, qnum))
                        else:
                            elapsed, cpu, ram, disk, kwh = measure(eng_fn, monitor)
                            tag = f"{elapsed:.3f}s"
                    except Exception as e:
                        elapsed, cpu, ram, disk, kwh = -1.0, 0, 0, 0, 0
                        tag = f"ERRO: {type(e).__name__}"
                        dnf.add((eng_name, qnum))

                    warmup = " [warm-up]" if rep == 1 else ""
                    print(f"  rep{rep}{warmup} {eng_name:12s} {tag}")

                    if rep > 1:
                        writer.writerow({
                            "engine":     eng_name,
                            "suite":      "clickbench",
                            "sf":         1,
                            "query":      qnum,
                            "rep":        rep - 1,
                            "elapsed_s":  round(elapsed, 4),
                            "cpu_pct":    round(cpu, 2),
                            "ram_mb":     round(ram, 1),
                            "disk_mb":    round(disk, 2),
                            "energy_kwh": round(kwh, 10),
                        })
                f.flush()

    duck_con.close()
    print(f"\nResultados em: {out_file}")

if __name__ == "__main__":
    main()
