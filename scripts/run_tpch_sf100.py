#!/usr/bin/env python3
import argparse, csv, re, time, threading, subprocess, sys, resource, os
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeoutError
import multiprocessing as mp

import psutil, duckdb, psycopg2
from codecarbon import EmissionsTracker

BASE_DIR    = Path.home() / "bench/data/tpch"
QUERY_FILE  = Path.home() / "bench/queries/tpch/queries.sql"
RESULTS_DIR = Path.home() / "bench/results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

TIMEOUT          = 300
PG_TOUT          = 270
POLARS_MEM_GB    = 30    # limite de memória virtual para subprocess Polars
TABLES = ["region","nation","supplier","part","customer","partsupp","orders","lineitem"]

_INTERVAL_RE = re.compile(r"INTERVAL\s+'(\d+)'\s+(DAY|MONTH|YEAR)S?", re.IGNORECASE)
_UNIT_MAP    = {"DAY": "days", "MONTH": "months", "YEAR": "years"}

def polars_sql(sql):
    return _INTERVAL_RE.sub(
        lambda m: f"INTERVAL '{m.group(1)} {_UNIT_MAP[m.group(2).upper()]}'", sql)

def parse_queries(path):
    text  = Path(path).read_text()
    parts = re.split(r'--\s*Q(\d+)', text)
    return {int(parts[i]): parts[i+1].strip() for i in range(1, len(parts), 2)}

class ResourceMonitor:
    def __init__(self):
        self.cpu_samples = []; self.ram_peak_mb = 0.0
        self._stop = threading.Event()

    def start(self):
        self.cpu_samples = []; self.ram_peak_mb = 0.0; self._stop.clear()
        self._t = threading.Thread(target=self._loop, daemon=True); self._t.start()

    def stop(self):
        self._stop.set(); self._t.join()

    def _loop(self):
        proc = psutil.Process()
        while not self._stop.wait(0.5):
            try:
                self.cpu_samples.append(psutil.cpu_percent(interval=None))
                rss = proc.memory_info().rss / (1024*1024)
                if rss > self.ram_peak_mb: self.ram_peak_mb = rss
            except: break

    @property
    def cpu_avg(self):
        return sum(self.cpu_samples)/len(self.cpu_samples) if self.cpu_samples else 0.0

def _disk_mb():
    return psutil.disk_io_counters().read_bytes / (1024*1024)

def run_pg(sql, pg_conn):
    conn = psycopg2.connect(**pg_conn, options=f"-c statement_timeout={PG_TOUT*1000}")
    cur  = conn.cursor()
    d0 = _disk_mb(); t0 = time.perf_counter()
    cur.execute(sql); cur.fetchall()
    e = time.perf_counter()-t0; disk = _disk_mb()-d0
    cur.close(); conn.close(); return e, disk

def run_duckdb(sql, con):
    d0 = _disk_mb(); t0 = time.perf_counter()
    con.execute(sql).fetchall()
    return time.perf_counter()-t0, _disk_mb()-d0

# Polars roda em subprocess isolado para conter OOM
def _polars_worker(sql, data_dir, tables, q):
    try:
        limit = POLARS_MEM_GB * 1024**3
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    except Exception:
        pass
    try:
        import polars as pl
        ctx = pl.SQLContext()
        for t in tables:
            ctx.register(t, pl.scan_parquet(f"{data_dir}/{t}.parquet"))
        import psutil, time
        d0 = psutil.disk_io_counters().read_bytes / (1024*1024)
        t0 = time.perf_counter()
        ctx.execute(sql).collect()
        elapsed = time.perf_counter() - t0
        disk = psutil.disk_io_counters().read_bytes / (1024*1024) - d0
        q.put(("ok", elapsed, disk))
    except Exception as e:
        q.put(("err", str(type(e).__name__), str(e)))

def run_polars(sql, data_dir):
    q = mp.Queue()
    p = mp.Process(target=_polars_worker,
                   args=(sql, str(data_dir), TABLES, q), daemon=True)
    p.start()
    p.join(TIMEOUT)
    if p.is_alive():
        p.terminate(); p.join()
        raise TimeoutError(f"timeout >{TIMEOUT}s")
    if not q.empty():
        result = q.get()
        if result[0] == "ok":
            return result[1], result[2]
        raise Exception(f"{result[1]}: {result[2]}")
    raise MemoryError("subprocess killed (OOM)")

def measure_pg(fn, mon):
    return _measure(fn, mon)

def measure_duck(fn, mon):
    return _measure(fn, mon)

def measure_polars(fn, mon):
    tracker = EmissionsTracker(project_name="tpch", output_dir=str(RESULTS_DIR),
                               log_level="error", save_to_file=False)
    mon.start(); tracker.start()
    err = None; elapsed = disk = -1.0
    try:
        elapsed, disk = fn()
    except Exception as e:
        err = e
    kwh = tracker.stop() or 0.0; mon.stop()
    if err: raise err
    return elapsed, mon.cpu_avg, mon.ram_peak_mb, disk, kwh

def _measure(fn, mon):
    tracker = EmissionsTracker(project_name="tpch", output_dir=str(RESULTS_DIR),
                               log_level="error", save_to_file=False)
    mon.start(); tracker.start()
    executor = ThreadPoolExecutor(max_workers=1)
    future   = executor.submit(fn)
    timed_out = False; err = None
    try:
        elapsed, disk = future.result(timeout=TIMEOUT)
    except FutTimeoutError:
        timed_out = True
    except Exception as ex:
        err = ex
    finally:
        executor.shutdown(wait=False)
    kwh = tracker.stop() or 0.0; mon.stop()
    if timed_out: raise TimeoutError(f"timeout >{TIMEOUT}s")
    if err: raise err
    return elapsed, mon.cpu_avg, mon.ram_peak_mb, disk, kwh

def drop_caches():
    subprocess.run(["sudo","tee","/proc/sys/vm/drop_caches"],
                   input=b"3", check=False, capture_output=True)
    time.sleep(2)

def main():
    mp.set_start_method("spawn", force=True)
    parser = argparse.ArgumentParser()
    parser.add_argument("--sf", type=int, default=1, choices=[1,10,100])
    parser.add_argument("queries", nargs="*", type=int)
    args    = parser.parse_args()
    sf      = args.sf
    filter_qs = set(args.queries) if args.queries else None
    data_dir  = BASE_DIR / f"sf{sf}"
    db_name   = "bench" if sf == 1 else f"bench_sf{sf}"
    pg_conn   = dict(host="127.0.0.1", dbname=db_name, user="bench", password="bench")
    duck_db   = str(data_dir / f"tpch_sf{sf}.duckdb")

    queries = parse_queries(QUERY_FILE)
    print(f"TPC-H SF={sf}  banco={db_name}  timeout={TIMEOUT}s  polars_mem={POLARS_MEM_GB}GB")

    duck_con = duckdb.connect(duck_db)
    duck_con.execute("SET threads=16; SET memory_limit='40GB';")

    ts  = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = RESULTS_DIR / f"tpch_sf{sf}_{ts}.csv"
    fields = ["engine","suite","sf","query","rep",
              "elapsed_s","cpu_pct","ram_mb","disk_mb","energy_kwh"]
    mon = ResourceMonitor()
    dnf = set()

    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        for qnum in sorted(queries):
            if filter_qs and qnum not in filter_qs: continue
            sql = queries[qnum]
            print(f"\n=== Q{qnum:02d} ===")
            engines = [
                ("postgresql", lambda s=sql: run_pg(s, pg_conn),   measure_pg),
                ("duckdb",     lambda s=sql: run_duckdb(s, duck_con), measure_duck),
                ("polars",     lambda s=sql: run_polars(polars_sql(s), data_dir), measure_polars),
            ]
            for rep in range(1, 6):
                for eng, fn, mfn in engines:
                    key = (eng, qnum)
                    if key in dnf:
                        print(f"  rep{rep} {eng:12s} SKIP"); continue
                    drop_caches()
                    try:
                        e, cpu, ram, disk, kwh = mfn(fn, mon)
                        tag = f"{e:.3f}s"
                    except Exception as ex:
                        dnf.add(key)
                        e, cpu, ram, disk, kwh = -1.0,0.0,0.0,0.0,0.0
                        tag = f"ERRO: {type(ex).__name__}"
                    warmup = " [warm-up]" if rep==1 else ""
                    print(f"  rep{rep}{warmup} {eng:12s} {tag}")
                    if rep > 1:
                        w.writerow({"engine":eng,"suite":"tpch","sf":sf,"query":qnum,
                                    "rep":rep-1,"elapsed_s":round(e,4),"cpu_pct":round(cpu,2),
                                    "ram_mb":round(ram,1),"disk_mb":round(disk,2),
                                    "energy_kwh":round(kwh,10)})
        f.flush()
    duck_con.close()
    print(f"\nResultados em: {out}")

if __name__ == "__main__":
    main()
