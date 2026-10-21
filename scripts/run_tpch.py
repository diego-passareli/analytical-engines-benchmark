#!/usr/bin/env python3
"""
TPC-H benchmark runner — PostgreSQL, DuckDB e Polars
Protocolo: 5 execuções por query/engine, descarta warm-up (rep=1),
           reporta reps 2-5 (mediana e IQR calculados na análise).
"""

import csv, os, re, time, threading, subprocess, sys
from pathlib import Path
from datetime import datetime

import psutil
import duckdb
import polars as pl
import psycopg2
from codecarbon import EmissionsTracker

# ── Configuração ────────────────────────────────────────────────────────────
DATA_DIR    = Path.home() / "bench/data/tpch"
QUERY_FILE  = Path.home() / "bench/queries/tpch/queries.sql"
RESULTS_DIR = Path.home() / "bench/results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

PG_CONN  = dict(host="127.0.0.1", dbname="bench", user="bench", password="bench")
DUCK_DB  = str(DATA_DIR / "tpch_sf1.duckdb")
SF       = 1
REPS     = 5   # inclui warm-up; rep=1 é descartada
TABLES   = ["region","nation","supplier","part",
            "customer","partsupp","orders","lineitem"]

# ── Parsing das queries ──────────────────────────────────────────────────────
def parse_queries(path: Path) -> dict[int, str]:
    text = path.read_text()
    parts = re.split(r'--\s*Q(\d+)', text)
    queries = {}
    for i in range(1, len(parts), 2):
        qnum = int(parts[i])
        sql  = parts[i+1].strip()
        queries[qnum] = sql
    return queries

# ── Monitor de recursos (thread paralela, 500 ms) ───────────────────────────
class ResourceMonitor:
    def __init__(self):
        self.cpu_samples: list[float] = []
        self.ram_peak_mb: float = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        self.cpu_samples = []
        self.ram_peak_mb = 0.0
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

# ── Runners por engine ───────────────────────────────────────────────────────
def _disk_read_mb():
    return psutil.disk_io_counters().read_bytes / (1024 * 1024)

def run_pg(sql: str) -> tuple[float, float]:
    conn = psycopg2.connect(**PG_CONN)
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
    elapsed = time.perf_counter() - t0
    return elapsed, _disk_read_mb() - d0

def run_polars(sql: str, ctx: pl.SQLContext) -> tuple[float, float]:
    d0 = _disk_read_mb()
    t0 = time.perf_counter()
    ctx.execute(sql).collect()
    elapsed = time.perf_counter() - t0
    return elapsed, _disk_read_mb() - d0

# ── Medição com codecarbon ───────────────────────────────────────────────────
def measure(engine_fn, monitor: ResourceMonitor) -> tuple:
    tracker = EmissionsTracker(
        project_name="tpch",
        output_dir=str(RESULTS_DIR),
        log_level="error",
        save_to_file=False,
        tracking_mode="process",
    )
    monitor.start()
    tracker.start()
    elapsed, disk_mb = engine_fn()
    kwh = tracker.stop() or 0.0
    monitor.stop()
    return elapsed, monitor.cpu_avg, monitor.ram_peak_mb, disk_mb, kwh

# ── Limpeza de cache ─────────────────────────────────────────────────────────
def drop_caches():
    subprocess.run(
        ["sudo", "sh", "-c", "echo 3 > /proc/sys/vm/drop_caches"],
        check=False, capture_output=True,
    )
    time.sleep(2)

# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    # Filtro opcional: python run_tpch.py 1 6 14   → roda só Q1, Q6, Q14
    filter_qs = set(int(a) for a in sys.argv[1:]) if len(sys.argv) > 1 else None

    queries = parse_queries(QUERY_FILE)
    print(f"Queries carregadas: {len(queries)}")

    # Prepara DuckDB
    duck_con = duckdb.connect(DUCK_DB)
    duck_con.execute("SET threads=16; SET memory_limit='50GB';")

    # Prepara Polars SQLContext
    polars_ctx = pl.SQLContext()
    for t in TABLES:
        polars_ctx.register(t, pl.scan_parquet(str(DATA_DIR / f"{t}.parquet")))

    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = RESULTS_DIR / f"tpch_sf{SF}_{ts}.csv"
    fields   = ["engine","suite","sf","query","rep",
                "elapsed_s","cpu_pct","ram_mb","disk_mb","energy_kwh"]

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
                ("polars",     lambda s=sql: run_polars(s, polars_ctx)),
            ]

            for rep in range(1, REPS + 1):
                for eng_name, eng_fn in engines:
                    drop_caches()
                    try:
                        elapsed, cpu, ram, disk, kwh = measure(eng_fn, monitor)
                        tag = f"{elapsed:.3f}s"
                    except Exception as e:
                        elapsed, cpu, ram, disk, kwh = -1.0, 0.0, 0.0, 0.0, 0.0
                        tag = f"ERRO: {e}"

                    warmup = " [warm-up]" if rep == 1 else ""
                    print(f"  rep{rep}{warmup} {eng_name:12s} {tag}")

                    if rep > 1:           # descarta warm-up
                        writer.writerow({
                            "engine":     eng_name,
                            "suite":      "tpch",
                            "sf":         SF,
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
