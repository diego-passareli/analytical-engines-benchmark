#!/usr/bin/env python3
"""
TPC-DS Setup — SF=1 ou SF=10
Uso: python setup_tpcds.py 1   |   python setup_tpcds.py 10
"""
import os, sys, subprocess, tempfile, time
from pathlib import Path
import duckdb

SF       = int(sys.argv[1]) if len(sys.argv) > 1 else 1
BASE     = Path.home() / "bench"
DATA_DIR = BASE / f"data/tpcds/sf{SF}"
DDL_FILE = BASE / "data/tpcds/tpcds_pg.ddl"
PQ_DIR   = BASE / f"data/tpcds/parquet_sf{SF}"
DK_DB    = str(BASE / f"data/tpcds/tpcds_sf{SF}.duckdb")
PG_DB    = f"bench_tpcds_sf{SF}"
PG_ENV   = os.environ | {"PGPASSWORD": "bench"}
PG_ARGS  = ["-h","127.0.0.1","-U","bench"]

TABLES = [
    "call_center","catalog_page","catalog_returns","catalog_sales",
    "customer","customer_address","customer_demographics","date_dim",
    "household_demographics","income_band","inventory","item",
    "promotion","reason","ship_mode","store","store_returns",
    "store_sales","time_dim","warehouse","web_page","web_returns",
    "web_sales","web_site",
]

def pg(sql, db=PG_DB):
    return subprocess.run(["psql"]+PG_ARGS+["-d",db,"-c",sql],
                          env=PG_ENV, capture_output=True, text=True)

def row_count(table):
    r = subprocess.run(["psql"]+PG_ARGS+["-d",PG_DB,"-t","-c",
                        f"SELECT COUNT(*) FROM {table}"],
                       env=PG_ENV, capture_output=True, text=True)
    return r.stdout.strip()

# ── PostgreSQL ─────────────────────────────────────────────────────────────────
def setup_pg():
    print(f"\n{'='*55}\n  PostgreSQL — {PG_DB}\n{'='*55}")
    for cmd in [f"DROP DATABASE IF EXISTS {PG_DB};",
                f"CREATE DATABASE {PG_DB} OWNER bench;",
                f"GRANT ALL ON DATABASE {PG_DB} TO bench;"]:
        subprocess.run(["sudo","-u","postgres","psql","-c",cmd], capture_output=True)

    r = subprocess.run(["psql"]+PG_ARGS+["-d",PG_DB,"-f",str(DDL_FILE)],
                       env=PG_ENV, capture_output=True, text=True)
    print(f"DDL rc={r.returncode}")

    for table in TABLES:
        dat = DATA_DIR / f"{table}.dat"
        if not dat.exists():
            print(f"  {table:<32} SKIP"); continue
        t0  = time.time()
        sed = subprocess.Popen(["sed","s/|$//",str(dat)], stdout=subprocess.PIPE)
        psl = subprocess.Popen(
            ["psql"]+PG_ARGS+["-d",PG_DB,"-c",
             f"COPY {table} FROM STDIN WITH (FORMAT csv, DELIMITER '|', NULL '')"],
            stdin=sed.stdout, env=PG_ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        sed.stdout.close()
        rc = psl.wait(); sed.wait()
        cnt = row_count(table) if rc==0 else "ERRO"
        print(f"  {table:<32} {cnt:>12}  {time.time()-t0:6.1f}s")

    indices = [
        "CREATE INDEX ON store_sales    (ss_sold_date_sk)",
        "CREATE INDEX ON store_returns  (sr_returned_date_sk)",
        "CREATE INDEX ON catalog_sales  (cs_sold_date_sk)",
        "CREATE INDEX ON catalog_returns(cr_returned_date_sk)",
        "CREATE INDEX ON web_sales      (ws_sold_date_sk)",
        "CREATE INDEX ON web_returns    (wr_returned_date_sk)",
        "CREATE INDEX ON inventory      (inv_date_sk)",
        "CREATE INDEX ON date_dim       (d_date_sk)",
        "CREATE INDEX ON date_dim       (d_year, d_moy)",
        "CREATE INDEX ON item           (i_item_sk)",
        "CREATE INDEX ON customer       (c_customer_sk)",
        "CREATE INDEX ON store          (s_store_sk)",
    ]
    print("  Índices...", end="", flush=True)
    for idx in indices: pg(idx)
    pg("ANALYZE;")
    print(" OK")

# ── DuckDB ─────────────────────────────────────────────────────────────────────
def setup_duckdb():
    print(f"\n{'='*55}\n  DuckDB — {Path(DK_DB).name}\n{'='*55}")
    if Path(DK_DB).exists(): Path(DK_DB).unlink()

    ddl = DDL_FILE.read_text().replace(" CASCADE","")
    con = duckdb.connect(DK_DB)
    con.execute("SET threads=16; SET memory_limit='40GB';")
    con.execute(ddl)

    for table in TABLES:
        dat = DATA_DIR / f"{table}.dat"
        if not dat.exists():
            print(f"  {table:<32} SKIP"); continue
        t0  = time.time()
        fd, tmp = tempfile.mkstemp(suffix=".dat")
        os.close(fd)
        try:
            subprocess.run(["sed","s/|$//",str(dat)],
                           stdout=open(tmp,"w"), check=True)
            con.execute(f"COPY {table} FROM '{tmp}' "
                        f"WITH (DELIMITER '|', NULL '', HEADER false)")
            cnt = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  {table:<32} {cnt:>12,}  {time.time()-t0:6.1f}s")
        except Exception as e:
            print(f"  {table:<32} ERRO: {e}")
        finally:
            if os.path.exists(tmp): os.unlink(tmp)
    con.close()

# ── Parquet (Polars) ───────────────────────────────────────────────────────────
def export_parquet():
    print(f"\n{'='*55}\n  Parquet → {PQ_DIR}\n{'='*55}")
    PQ_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(DK_DB, read_only=True)
    for table in TABLES:
        pq = PQ_DIR / f"{table}.parquet"
        t0 = time.time()
        try:
            con.execute(f"COPY (SELECT * FROM {table}) TO '{pq}' (FORMAT PARQUET)")
            print(f"  {table:<32} {pq.stat().st_size/1e6:8.1f} MB  {time.time()-t0:5.1f}s")
        except Exception as e:
            print(f"  {table:<32} ERRO: {e}")
    con.close()

if __name__ == "__main__":
    print(f"TPC-DS Setup — SF={SF}  ({DATA_DIR})")
    t = time.time()
    setup_pg()
    setup_duckdb()
    export_parquet()
    print(f"\nConcluído em {(time.time()-t)/60:.1f} min")
