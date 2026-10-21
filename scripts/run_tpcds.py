#!/usr/bin/env python3
"""
TPC-DS Benchmark Runner — PostgreSQL, DuckDB, Polars
Protocolo: 5 execuções (rep 1 warm-up descartada), TIMEOUT=300s.
Uso: python run_tpcds.py 1    # SF=1
     python run_tpcds.py 10   # SF=10
     python run_tpcds.py 1 5 14  # apenas queries 1, 5 e 14 no SF=1
"""

import csv, os, re, sys, time, threading, subprocess, resource
from pathlib import Path
from datetime import datetime
import multiprocessing as mp

import psutil, duckdb, polars as pl, psycopg2
from codecarbon import EmissionsTracker

# ── Configuração ───────────────────────────────────────────────────────────────
SF = int(sys.argv[1]) if len(sys.argv) > 1 else 1
filter_qs = set(int(a) for a in sys.argv[2:]) if len(sys.argv) > 2 else None

BASE        = Path.home() / "bench"
QUERY_DIR   = BASE / "queries/tpcds/adapted"
RESULTS_DIR = BASE / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

DK_DB   = str(BASE / f"data/tpcds/tpcds_sf{SF}.duckdb")
PQ_DIR  = BASE / f"data/tpcds/parquet_sf{SF}"
PG_CONN = dict(host="127.0.0.1", dbname=f"bench_tpcds_sf{SF}",
               user="bench", password="bench")

REPS          = 5      # inclui warm-up (rep 1 descartada)
TIMEOUT       = 300    # s por query
PG_TOUT       = 270    # statement_timeout PG (s)
POLARS_MEM_GB = 30

TABLES = [
    "call_center","catalog_page","catalog_returns","catalog_sales",
    "customer","customer_address","customer_demographics","date_dim",
    "household_demographics","income_band","inventory","item",
    "promotion","reason","ship_mode","store","store_returns",
    "store_sales","time_dim","warehouse","web_page","web_returns",
    "web_sales","web_site",
]

# ── Parse queries ──────────────────────────────────────────────────────────────
def load_queries():
    queries = {}
    for f in sorted(QUERY_DIR.glob("query*.sql")):
        m = re.search(r"query(\d+)\.sql$", f.name)
        if m:
            queries[int(m.group(1))] = f.read_text().strip()
    return queries

# ── Monitor de recursos ────────────────────────────────────────────────────────
class ResourceMonitor:
    def __init__(self):
        self.cpu_samples, self.ram_peak_mb = [], 0.0
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        self.cpu_samples, self.ram_peak_mb = [], 0.0
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread: self._thread.join()

    def _loop(self):
        proc = psutil.Process()
        while not self._stop.wait(0.5):
            try:
                self.cpu_samples.append(psutil.cpu_percent(interval=None))
                rss = proc.memory_info().rss / (1024**2)
                if rss > self.ram_peak_mb: self.ram_peak_mb = rss
            except: break

    @property
    def cpu_avg(self):
        return sum(self.cpu_samples)/len(self.cpu_samples) if self.cpu_samples else 0.0

def _disk_mb():
    return psutil.disk_io_counters().read_bytes / (1024**2)

# ── Runners ────────────────────────────────────────────────────────────────────
def run_pg(sql):
    conn = psycopg2.connect(**PG_CONN,
                            options=f"-c statement_timeout={PG_TOUT*1000}")
    cur  = conn.cursor()
    d0   = _disk_mb(); t0 = time.perf_counter()
    cur.execute(sql); cur.fetchall()
    elapsed = time.perf_counter() - t0
    disk = _disk_mb() - d0
    cur.close(); conn.close()
    return elapsed, disk

def run_duckdb(sql, con):
    d0 = _disk_mb(); t0 = time.perf_counter()
    con.execute(sql).fetchall()
    return time.perf_counter() - t0, _disk_mb() - d0

# ── Polars worker ──────────────────────────────────────────────────────────────
def _polars_worker(sql, pq_dir, queue):
    try:
        mem = POLARS_MEM_GB * 1024**3
        resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
        ctx = pl.SQLContext()
        for tbl in TABLES:
            pq = Path(pq_dir) / f"{tbl}.parquet"
            if pq.exists():
                ctx.register(tbl, pl.scan_parquet(str(pq)))
        t0 = time.perf_counter()
        ctx.execute(sql).collect()
        queue.put(time.perf_counter() - t0)
    except Exception as e:
        queue.put(e)

def run_polars(sql):
    q  = mp.Queue()
    p  = mp.Process(target=_polars_worker, args=(sql, str(PQ_DIR), q), daemon=True)
    d0 = _disk_mb()
    p.start(); p.join(timeout=TIMEOUT)
    disk = _disk_mb() - d0
    if p.is_alive():
        p.kill(); p.join()
        raise TimeoutError("Polars timeout")
    result = q.get() if not q.empty() else None
    if result is None:     raise MemoryError("Polars OOM")
    if isinstance(result, Exception): raise result
    return result, disk

# ── Medição ────────────────────────────────────────────────────────────────────
def measure(fn, monitor):
    tracker = EmissionsTracker(project_name="tpcds", output_dir=str(RESULTS_DIR),
                               log_level="error", save_to_file=False,
                               tracking_mode="process")
    monitor.start(); tracker.start()
    elapsed, disk = fn()
    kwh = tracker.stop() or 0.0
    monitor.stop()
    return elapsed, monitor.cpu_avg, monitor.ram_peak_mb, disk, kwh

def drop_caches():
    subprocess.run(["sudo","tee","/proc/sys/vm/drop_caches"],
                   input=b"3", capture_output=True, check=False)
    time.sleep(2)

# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    mp.set_start_method("spawn", force=True)
    queries = load_queries()
    print(f"TPC-DS runner — SF={SF} — {len(queries)} queries carregadas")

    # DuckDB conexão
    duck_con = duckdb.connect(DK_DB)
    duck_con.execute("SET threads=16; SET memory_limit='40GB';")

    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = RESULTS_DIR / f"tpcds_sf{SF}_{ts}.csv"
    fields   = ["engine","suite","sf","query","rep",
                "elapsed_s","cpu_pct","ram_mb","disk_mb","energy_kwh"]

    monitor = ResourceMonitor()
    dnf: set[tuple[str,int]] = set()

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

            from concurrent.futures import ThreadPoolExecutor, TimeoutError as FTE

            for rep in range(1, REPS+1):
                for eng, fn in engines:
                    if (eng, qnum) in dnf:
                        continue
                    drop_caches()
                    try:
                        if eng == "postgresql":
                            with ThreadPoolExecutor(max_workers=1) as ex:
                                fut = ex.submit(lambda: measure(fn, monitor))
                                try:
                                    elapsed,cpu,ram,disk,kwh = fut.result(TIMEOUT)
                                    tag = f"{elapsed:.3f}s"
                                except FTE:
                                    elapsed,cpu,ram,disk,kwh = -1,0,0,0,0
                                    tag = "TIMEOUT"; dnf.add((eng,qnum))
                        else:
                            elapsed,cpu,ram,disk,kwh = measure(fn, monitor)
                            tag = f"{elapsed:.3f}s"
                    except Exception as e:
                        elapsed,cpu,ram,disk,kwh = -1,0,0,0,0
                        tag = f"ERRO:{type(e).__name__}"; dnf.add((eng,qnum))

                    wu = " [wu]" if rep==1 else ""
                    print(f"  rep{rep}{wu:5s} {eng:12s} {tag}")

                    if rep > 1:
                        writer.writerow({
                            "engine":eng,"suite":"tpcds","sf":SF,
                            "query":qnum,"rep":rep-1,
                            "elapsed_s":round(elapsed,4),
                            "cpu_pct":round(cpu,2),
                            "ram_mb":round(ram,1),
                            "disk_mb":round(disk,2),
                            "energy_kwh":round(kwh,10),
                        })
                f.flush()

    duck_con.close()
    print(f"\nResultados em: {out_file}")

if __name__ == "__main__":
    main()
