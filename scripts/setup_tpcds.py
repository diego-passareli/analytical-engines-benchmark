#!/usr/bin/env python3
"""
TPC-DS Setup — SF=1 ou SF=10
Uso: python setup_tpcds.py 1   ou   python setup_tpcds.py 10

Etapas:
  1. PostgreSQL: cria bench_tpcds_sf{N}, aplica DDL, carrega 24 tabelas (sed strip |)
  2. DuckDB:     cria tpcds_sf{N}.duckdb, carrega 24 tabelas (temp file strip |)
  3. Parquet:    exporta cada tabela do DuckDB → parquet/ (para o Polars)
"""
import os, sys, subprocess, tempfile, time
from pathlib import Path
import duckdb

SF = int(sys.argv[1]) if len(sys.argv) > 1 else 1

BASE        = Path.home() / "bench"
DATA_DIR    = BASE / f"data/tpcds/sf{SF}"
DDL_FILE    = BASE / "data/tpcds/tpcds_pg.ddl"
PQ_DIR      = BASE / f"data/tpcds/parquet_sf{SF}"
DK_DB       = str(BASE / f"data/tpcds/tpcds_sf{SF}.duckdb")
PG_DB       = f"bench_tpcds_sf{SF}"
PG_ENV      = os.environ | {"PGPASSWORD": "bench"}
PG_ARGS     = ["-h", "127.0.0.1", "-U", "bench"]

TABLES = [
    "call_center","catalog_page","catalog_returns","catalog_sales",
    "customer","customer_address","customer_demographics","date_dim",
    "household_demographics","income_band","inventory","item",
    "promotion","reason","ship_mode","store","store_returns",
    "store_sales","time_dim","warehouse","web_page","web_returns",
    "web_sales","web_site",
]

# ─── utilitários ──────────────────────────────────────────────────────────────
def run(cmd, **kw):
    r = subprocess.run(cmd, **kw)
    if r.returncode != 0 and kw.get("check", False):
        print(f"ERRO ({r.returncode}): {getattr(r,'stderr',b'').decode()[:200]}")
    return r

def pg(sql, db=PG_DB):
    return run(["psql"] + PG_ARGS + ["-d", db, "-c", sql],
               env=PG_ENV, capture_output=True, text=True)

def row_count_pg(table):
    r = run(["psql"] + PG_ARGS + ["-d", PG_DB, "-t", "-c",
             f"SELECT COUNT(*) FROM {table}"],
            env=PG_ENV, capture_output=True, text=True)
    return r.stdout.strip()

# ─── PostgreSQL ───────────────────────────────────────────────────────────────
def setup_pg():
    print(f"\n{'='*50}")
    print(f"  PostgreSQL — {PG_DB}")
    print(f"{'='*50}")

    # Criar banco
    run(["sudo","-u","postgres","psql","-c",
         f"DROP DATABASE IF EXISTS {PG_DB};"], capture_output=True)
    run(["sudo","-u","postgres","psql","-c",
         f"CREATE DATABASE {PG_DB} OWNER bench;"], capture_output=True)
    run(["sudo","-u","postgres","psql","-c",
         f"GRANT ALL ON DATABASE {PG_DB} TO bench;"], capture_output=True)

    # DDL
    r = run(["psql"] + PG_ARGS + ["-d", PG_DB, "-f", str(DDL_FILE)],
            env=PG_ENV, capture_output=True, text=True)
    print(f"DDL rc={r.returncode}")

    # Carregar tabelas (sed strip trailing |)
    for table in TABLES:
        dat = DATA_DIR / f"{table}.dat"
        if not dat.exists():
            print(f"  {table:<30} SKIP (arquivo não encontrado)")
            continue
        t0 = time.time()
        sed = subprocess.Popen(["sed","s/|$//", str(dat)], stdout=subprocess.PIPE)
        psql = subprocess.Popen(
            ["psql"] + PG_ARGS + ["-d", PG_DB, "-c",
             f"COPY {table} FROM STDIN WITH (FORMAT csv, DELIMITER '|', NULL '')"],
            stdin=sed.stdout, env=PG_ENV, capture_output=True
        )
        sed.stdout.close()
        rc = psql.wait(); sed.wait()
        elapsed = time.time() - t0
        cnt = row_count_pg(table) if rc==0 else "ERRO"
        print(f"  {table:<30} {cnt:>12} linhas  {elapsed:6.1f}s")

    # Índices básicos (fact tables)
    print("  Criando índices...")
    indices = [
        "CREATE INDEX ON store_sales   (ss_sold_date_sk)",
        "CREATE INDEX ON store_returns  (sr_returned_date_sk)",
        "CREATE INDEX ON catalog_sales  (cs_sold_date_sk)",
        "CREATE INDEX ON catalog_returns(cr_returned_date_sk)",
        "CREATE INDEX ON web_sales      (ws_sold_date_sk)",
        "CREATE INDEX ON web_returns    (wr_returned_date_sk)",
        "CREATE INDEX ON inventory      (inv_date_sk)",
        "CREATE INDEX ON date_dim       (d_date_sk)",
    ]
    for idx in indices:
        pg(idx)
    pg("ANALYZE;")
    print("  ANALYZE OK")

# ─── DuckDB ───────────────────────────────────────────────────────────────────
def setup_duckdb():
    print(f"\n{'='*50}")
    print(f"  DuckDB — {Path(DK_DB).name}")
    print(f"{'='*50}")

    if Path(DK_DB).exists():
        Path(DK_DB).unlink()

    # Ler DDL e adaptar para DuckDB (remover CASCADE, IF NOT EXISTS já é suportado)
    ddl = DDL_FILE.read_text()
    # DuckDB não precisa de CASCADE em DROP TABLE
    ddl_dk = ddl.replace(" CASCADE", "")
    # DuckDB usa VARCHAR em vez de CHAR para melhor compatibilidade
    # (mantemos CHAR — DuckDB aceita CHAR como alias de VARCHAR)

    con = duckdb.connect(DK_DB)
    con.execute("SET threads=16; SET memory_limit='40GB';")
    con.execute(ddl_dk)

    for table in TABLES:
        dat = DATA_DIR / f"{table}.dat"
        if not dat.exists():
            print(f"  {table:<30} SKIP")
            continue
        t0 = time.time()
        # Criar arquivo temporário sem trailing pipe
        fd, tmp = tempfile.mkstemp(suffix=".dat")
        os.close(fd)
        try:
            subprocess.run(["sed","s/|$//", str(dat)],
                           stdout=open(tmp,"w"), check=True)
            con.execute(f"""
                COPY {table} FROM '{tmp}'
                WITH (DELIMITER '|', NULL '', HEADER false)
            """)
            cnt = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  {table:<30} {cnt:>12,} linhas  {time.time()-t0:6.1f}s")
        except Exception as e:
            print(f"  {table:<30} ERRO: {e}")
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    con.close()

# ─── Parquet (para Polars) ────────────────────────────────────────────────────
def export_parquet():
    print(f"\n{'='*50}")
    print(f"  Parquet (Polars) — {PQ_DIR}")
    print(f"{'='*50}")
    PQ_DIR.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(DK_DB, read_only=True)
    for table in TABLES:
        pq = PQ_DIR / f"{table}.parquet"
        t0 = time.time()
        try:
            con.execute(f"COPY (SELECT * FROM {table}) TO '{pq}' (FORMAT PARQUET)")
            size = pq.stat().st_size / (1024**2)
            print(f"  {table:<30} {size:8.1f} MB  {time.time()-t0:5.1f}s")
        except Exception as e:
            print(f"  {table:<30} ERRO: {e}")
    con.close()

# ─── main ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print(f"TPC-DS Setup — SF={SF}  ({DATA_DIR})")
    t_total = time.time()
    setup_pg()
    setup_duckdb()
    export_parquet()
    print(f"\nConcluído em {(time.time()-t_total)/60:.1f} min")
