#!/usr/bin/env python3
"""
TPC-DS Benchmark Runner — PostgreSQL, DuckDB, Polars
Uso: python run_tpcds.py 1       # SF=1, todas as 99 queries
     python run_tpcds.py 10      # SF=10
     python run_tpcds.py 1 5 14  # SF=1, apenas Q5 e Q14
"""
import csv, os, re, sys, time, threading, subprocess, resource
from pathlib import Path
from datetime import datetime
import multiprocessing as mp

import psutil, duckdb, polars as pl, psycopg2
from codecarbon import EmissionsTracker

SF        = int(sys.argv[1]) if len(sys.argv) > 1 else 1
filter_qs = set(int(a) for a in sys.argv[2:]) if len(sys.argv) > 2 else None

BASE        = Path.home() / "bench"
QUERY_DIR   = BASE / "queries/tpcds/adapted"
RESULTS_DIR = BASE / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

DK_DB   = str(BASE / f"data/tpcds/tpcds_sf{SF}.duckdb")
PQ_DIR  = BASE / f"data/tpcds/parquet_sf{SF}"
PG_CONN = dict(host="127.0.0.1", dbname=f"bench_tpcds_sf{SF}",
               user="bench", password="bench")

REPS          = 5
TIMEOUT       = 300
PG_TOUT       = 270
POLARS_MEM_GB = 30

TABLES = [
    "call_center","catalog_page","catalog_returns","catalog_sales",
    "customer","customer_address","customer_demographics","date_dim",
    "household_demographics","income_band","inventory","item",
    "promotion","reason","ship_mode","store","store_returns",
    "store_sales","time_dim","warehouse","web_page","web_returns",
    "web_sales","web_site",
]

def load_queries():
    qs = {}
    for f in sorted(QUERY_DIR.glob("query*.sql")):
        m = re.search(r"query(\d+)\.sql$", f.name)
        if m: qs[int(m.group(1))] = f.read_text().strip()
    return qs

class ResourceMonitor:
    def __init__(self):
        self.cpu_samples, self.ram_peak_mb = [], 0.0
        self._stop = threading.Event(); self._thread = None
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

def run_pg(sql):
    conn = psycopg2.connect(**PG_CONN,
                            options=f"-c statement_timeout={PG_TOUT*1000}")
    cur = conn.cursor()
    d0 = _disk_mb(); t0 = time.perf_counter()
    cur.execute(sql); cur.fetchall()
    e = time.perf_counter()-t0; d = _disk_mb()-d0
    cur.close(); conn.close()
    return e, d

def run_duckdb(sql, con):
    d0 = _disk_mb(); t0 = time.perf_counter()
    con.execute(sql).fetchall()
    return time.perf_counter()-t0, _disk_mb()-d0

def _polars_worker(sql, pq_dir, tables, queue):
    try:
        resource.setrlimit(resource.RLIMIT_AS,
                           (POLARS_MEM_GB*1024**3,)*2)
        ctx = pl.SQLContext()
        for tbl in tables:
            pq = Path(pq_dir) / f"{tbl}.parquet"
            if pq.exists():
                ctx.register(tbl, pl.scan_parquet(str(pq)))
        t0 = time.perf_counter()
        ctx.execute(sql).collect()
        queue.put(time.perf_counter()-t0)
    except Exception as e:
        queue.put(e)

def run_polars(sql):
    q = mp.Queue()
    p = mp.Process(target=_polars_worker,
                   args=(sql, str(PQ_DIR), TABLES, q), daemon=True)
    d0 = _disk_mb(); p.start(); p.join(timeout=TIMEOUT)
    disk = _disk_mb()-d0
    if p.is_alive(): p.kill(); p.join(); raise TimeoutError("timeout")
    r = q.get() if not q.empty() else None
    if r is None:            raise MemoryError("OOM")
    if isinstance(r,Exception): raise r
    return r, disk

def measure(fn, mon):
    tr = EmissionsTracker(project_name="tpcds", output_dir=str(RESULTS_DIR),
                          log_level="error", save_to_file=False,
                          tracking_mode="process")
    mon.start(); tr.start()
    e, d = fn()
    kwh = tr.stop() or 0.0; mon.stop()
    return e, mon.cpu_avg, mon.ram_peak_mb, d, kwh

def drop_caches():
    subprocess.run(["sudo","tee","/proc/sys/vm/drop_caches"],
                   input=b"3", capture_output=True)
    time.sleep(2)

def main():
    mp.set_start_method("spawn", force=True)
    queries = load_queries()
    print(f"TPC-DS runner — SF={SF} — {len(queries)} queries")

    con = duckdb.connect(DK_DB)
    con.execute("SET threads=16; SET memory_limit='40GB';")

    ts      = datetime.now().strftime("%Y%m%d_%H%M%S")
    outfile = RESULTS_DIR / f"tpcds_sf{SF}_{ts}.csv"
    fields  = ["engine","suite","sf","query","rep",
               "elapsed_s","cpu_pct","ram_mb","disk_mb","energy_kwh"]

    mon = ResourceMonitor()
    dnf: set[tuple[str,int]] = set()

    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FTE

    with open(outfile,"w",newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()

        for qnum in sorted(queries):
            if filter_qs and qnum not in filter_qs: continue
            sql = queries[qnum]
            print(f"\n=== Q{qnum:02d} ===")

            engines = [
                ("postgresql", lambda s=sql: run_pg(s)),
                ("duckdb",     lambda s=sql: run_duckdb(s, con)),
                ("polars",     lambda s=sql: run_polars(s)),
            ]

            for rep in range(1, REPS+1):
                for eng, fn in engines:
                    if (eng, qnum) in dnf: continue
                    drop_caches()
                    try:
                        if eng == "postgresql":
                            with ThreadPoolExecutor(1) as ex:
                                fut = ex.submit(lambda: measure(fn, mon))
                                try:
                                    el,cpu,ram,dsk,kwh = fut.result(TIMEOUT)
                                    tag = f"{el:.3f}s"
                                except FTE:
                                    el,cpu,ram,dsk,kwh = -1,0,0,0,0
                                    tag="TIMEOUT"; dnf.add((eng,qnum))
                        else:
                            el,cpu,ram,dsk,kwh = measure(fn, mon)
                            tag = f"{el:.3f}s"
                    except Exception as e:
                        el,cpu,ram,dsk,kwh = -1,0,0,0,0
                        tag = f"ERRO:{type(e).__name__}"; dnf.add((eng,qnum))

                    wu = " [wu]" if rep==1 else ""
                    print(f"  rep{rep}{wu:5s} {eng:12s} {tag}")
                    if rep > 1:
                        w.writerow({"engine":eng,"suite":"tpcds","sf":SF,
                                    "query":qnum,"rep":rep-1,
                                    "elapsed_s":round(el,4),
                                    "cpu_pct":round(cpu,2),
                                    "ram_mb":round(ram,1),
                                    "disk_mb":round(dsk,2),
                                    "energy_kwh":round(kwh,10)})
                f.flush()

    con.close()
    print(f"\nResultados: {outfile}")

if __name__ == "__main__":
    main()
