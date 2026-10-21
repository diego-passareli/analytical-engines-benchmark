#!/usr/bin/env python3
"""
run_real.py — Benchmark de dados reais (dw.fato_custo) nos três motores.

Uso:
  cd ~/bench && python3 scripts/run_real.py

Saída:
  ~/bench/results/real_TIMESTAMP.csv
"""

import os, time, subprocess, pathlib, csv, datetime, statistics, signal
import duckdb, polars as pl
from codecarbon import EmissionsTracker

BASE      = pathlib.Path.home() / "bench"
Q_DIR     = BASE / "scripts/queries/real"
DK_FILE   = BASE / "data/real/fato_custo.duckdb"
PQ_FILE   = BASE / "data/real/fato_custo.parquet"
RES_DIR   = BASE / "results"
RES_DIR.mkdir(exist_ok=True)

PG_DB     = "bench_real"
PG_ARGS   = ["-U", "bench", "-h", "localhost"]
PG_ENV    = {**os.environ, "PGPASSWORD": os.environ.get("PGPASSWORD", "bench")}
TIMEOUT   = 300   # segundos
REPS      = 5     # rep 1 = aquecimento

QUERIES = [f"q{i:02d}" for i in range(1, 11)]

TS  = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
OUT = RES_DIR / f"real_{TS}.csv"

def drop_cache():
    subprocess.run(
        ["sudo", "sh", "-c", "sync; echo 3 > /proc/sys/vm/drop_caches"],
        capture_output=True)

def read_sql(qname):
    return (Q_DIR / f"{qname}.sql").read_text()

# ── PostgreSQL ──────────────────────────────────────────────
def run_pg(sql):
    t0 = time.perf_counter()
    r = subprocess.run(
        ["psql"] + PG_ARGS + ["-d", PG_DB, "-c", sql],
        env=PG_ENV, capture_output=True, text=True, timeout=TIMEOUT)
    elapsed = time.perf_counter() - t0
    if r.returncode != 0:
        raise RuntimeError(r.stderr[:200])
    return elapsed

# ── DuckDB ──────────────────────────────────────────────────
_dk_con = None
def dk_con():
    global _dk_con
    if _dk_con is None:
        _dk_con = duckdb.connect(str(DK_FILE), read_only=True)
    return _dk_con

def run_dk(sql):
    t0 = time.perf_counter()
    dk_con().execute(sql).fetchall()
    return time.perf_counter() - t0

# ── Polars ──────────────────────────────────────────────────
_pl_ctx = None
def pl_ctx():
    global _pl_ctx
    if _pl_ctx is None:
        _pl_ctx = pl.SQLContext()
        _pl_ctx.register("fato_custo", pl.scan_parquet(str(PQ_FILE)))
    return _pl_ctx

def run_pl(sql):
    t0 = time.perf_counter()
    pl_ctx().execute(sql).collect()
    return time.perf_counter() - t0

# ── Benchmark loop ──────────────────────────────────────────
ENGINES = {
    "postgresql": run_pg,
    "duckdb":     run_dk,
    "polars":     run_pl,
}

fieldnames = ["engine","suite","sf","query","rep",
              "elapsed_s","cpu_pct","ram_mb","disk_mb","energy_kwh"]

import psutil

def measure(fn, sql):
    proc = psutil.Process()
    cpu_before = proc.cpu_percent(interval=None)
    mem_before = proc.memory_info().rss
    t0   = time.perf_counter()
    fn(sql)
    elapsed = time.perf_counter() - t0
    cpu_after = proc.cpu_percent(interval=None)
    mem_after = proc.memory_info().rss
    return elapsed, (cpu_before + cpu_after) / 2, (mem_after) / 1024**2

with open(OUT, "w", newline="") as fout:
    writer = csv.DictWriter(fout, fieldnames=fieldnames)
    writer.writeheader()

    for qname in QUERIES:
        sql = read_sql(qname)
        qnum = int(qname[1:])
        print(f"\n{'='*60}")
        print(f"Query {qname}")

        for eng_name, run_fn in ENGINES.items():
            print(f"  [{eng_name}]", end="", flush=True)
            for rep in range(1, REPS + 1):
                drop_cache()
                tracker = EmissionsTracker(
                    project_name=f"real_{qname}_{eng_name}_r{rep}",
                    output_dir="/tmp", log_level="error",
                    tracking_mode="process", save_to_file=False)
                try:
                    tracker.start()
                    elapsed, cpu, ram = measure(run_fn, sql)
                    energy = tracker.stop() or 0.0
                    print(f" r{rep}={elapsed:.3f}s", end="", flush=True)
                    writer.writerow({
                        "engine": eng_name, "suite": "real", "sf": "real",
                        "query": qnum, "rep": rep,
                        "elapsed_s": f"{elapsed:.6f}",
                        "cpu_pct": f"{cpu:.1f}",
                        "ram_mb": f"{ram:.1f}",
                        "disk_mb": "0",
                        "energy_kwh": f"{energy:.8f}",
                    })
                    fout.flush()
                except Exception as e:
                    try: tracker.stop()
                    except: pass
                    print(f" r{rep}=ERR({e.__class__.__name__})", end="", flush=True)
            print()

print(f"\nResultados salvos em: {OUT}")
