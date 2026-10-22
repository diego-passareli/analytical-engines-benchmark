#!/usr/bin/env python3
"""
Fix definitivo para as 13 tabelas:
- Strip de 1 trailing | (convenção dsdgen) + pad até N colunas
- Rebuild PG e DuckDB com DDL original (sem drop de colunas)
"""
import os, re, subprocess, tempfile, time
from pathlib import Path
import duckdb

BASE     = Path.home() / "bench"
DATA_DIR = BASE / "data/tpcds/sf1"
DK_DB    = str(BASE / "data/tpcds/tpcds_sf1.duckdb")
PQ_DIR   = BASE / "data/tpcds/parquet_sf1"
DDL_FILE = BASE / "data/tpcds/tpcds_pg.ddl"
PQ_DIR.mkdir(exist_ok=True)
PG_ENV  = os.environ | {"PGPASSWORD": "bench"}
PG_ARGS = ["-h","127.0.0.1","-U","bench","-d","bench_tpcds_sf1"]

def psql(sql):
    return subprocess.run(["psql"]+PG_ARGS+["-c",sql],
                          env=PG_ENV, capture_output=True, text=True)

def parse_ddl(path):
    text = Path(path).read_text()
    result = {}
    for m in re.finditer(r'CREATE TABLE (\w+)\s*\(([^;]+)\);', text, re.IGNORECASE|re.DOTALL):
        tname, body = m.group(1).lower(), m.group(2)
        cols = []
        for line in body.strip().split('\n'):
            line = line.strip().rstrip(',')
            if not line or line.upper().startswith(('PRIMARY','UNIQUE','CHECK','FOREIGN','--')):
                continue
            parts = line.split(None, 1)
            if len(parts) == 2:
                cols.append((parts[0].lower(), parts[1].strip()))
        result[tname] = cols
    return result

def normalize_dat(dat_file, n_cols):
    """Strip exatamente 1 trailing | (se houver) e pad até n_cols por linha."""
    fd, tmp = tempfile.mkstemp(suffix=".dat"); os.close(fd)
    rows = 0
    with open(dat_file, 'r', errors='replace') as fin, open(tmp, 'w') as fout:
        for line in fin:
            line = line.rstrip('\n\r')
            if not line: continue
            if line.endswith('|'):
                line = line[:-1]           # remove exatamente 1 trailing |
            fields = line.split('|')
            while len(fields) < n_cols:    # pad com '' para campos NULL
                fields.append('')
            fout.write('|'.join(fields[:n_cols]) + '\n')
            rows += 1
    return tmp, rows

def pg_to_dk(pg_type):
    t = pg_type.upper().rstrip(',').strip()
    if re.match(r'INT', t):    return 'INTEGER'
    if 'BIGINT' in t:          return 'BIGINT'
    if 'DECIMAL' in t or 'NUMERIC' in t:
        m = re.search(r'\((\d+),\s*(\d+)\)', t)
        return f"DECIMAL({m.group(1)},{m.group(2)})" if m else 'DECIMAL(15,2)'
    if 'CHARACTER VARYING' in t or 'VARCHAR' in t:
        m = re.search(r'\((\d+)\)', t); return f"VARCHAR({m.group(1)})" if m else 'VARCHAR'
    if re.match(r'CHAR', t):
        m = re.search(r'\((\d+)\)', t); return f"CHAR({m.group(1)})" if m else 'VARCHAR'
    if 'DATE' in t:  return 'DATE'
    if 'TIME' in t:  return 'TIME'
    return 'VARCHAR'

TABLES = [
    "catalog_page","catalog_returns","customer","customer_address",
    "inventory","item","promotion","store_returns","store_sales",
    "time_dim","warehouse","web_page","web_returns"
]

ddl = parse_ddl(DDL_FILE)

# ── Rebuild PG ──────────────────────────────────────────────────────────────
print("=== Rebuild PG ===")
for table in TABLES:
    if table not in ddl: print(f"  {table}: DDL ausente"); continue
    orig = ddl[table]
    n = len(orig)
    dat = DATA_DIR / f"{table}.dat"
    col_sql = ",\n    ".join(f"{c} {tp}" for c, tp in orig)
    tmp, rows = normalize_dat(dat, n)
    t0 = time.time()
    psql(f"DROP TABLE IF EXISTS {table} CASCADE")
    psql(f"CREATE TABLE {table} (\n    {col_sql}\n)")
    rc = subprocess.run(
        ["psql"]+PG_ARGS+["-c",
         f"COPY {table} FROM '{tmp}' WITH (FORMAT csv, DELIMITER '|', NULL '')"],
        env=PG_ENV, capture_output=True, text=True)
    cnt = subprocess.run(["psql"]+PG_ARGS+["-t","-c",f"SELECT COUNT(*) FROM {table}"],
                         env=PG_ENV, capture_output=True, text=True).stdout.strip()
    status = 'OK' if rc.returncode == 0 else rc.stderr[:120]
    print(f"  {table:<32} {cnt:>12}  {n} cols  {time.time()-t0:5.1f}s  {status}")
    os.unlink(tmp)

# ── Rebuild DuckDB ──────────────────────────────────────────────────────────
print("\n=== Rebuild DuckDB ===")
con = duckdb.connect(DK_DB)
con.execute("SET threads=16; SET memory_limit='40GB';")

for table in TABLES:
    if table not in ddl: continue
    orig = ddl[table]
    n = len(orig)
    dat = DATA_DIR / f"{table}.dat"
    col_defs = ",\n    ".join(f"{c} {pg_to_dk(tp)}" for c, tp in orig)
    tmp, _ = normalize_dat(dat, n)
    t0 = time.time()
    try:
        con.execute(f"DROP TABLE IF EXISTS {table}")
        con.execute(f"CREATE TABLE {table} (\n    {col_defs}\n)")
        con.execute(f"COPY {table} FROM '{tmp}' (DELIMITER '|', NULL '', HEADER false)")
        cnt = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table:<32} {cnt:>12,}  {time.time()-t0:5.1f}s")
    except Exception as e:
        print(f"  {table:<32} ERRO: {e}")
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

# ── Parquet ─────────────────────────────────────────────────────────────────
print("\n=== Parquet ===")
for table in TABLES:
    pq = PQ_DIR / f"{table}.parquet"
    try:
        con.execute(f"COPY (SELECT * FROM {table}) TO '{pq}' (FORMAT PARQUET)")
        print(f"  {table:<32} {pq.stat().st_size/1e6:6.1f} MB")
    except Exception as e:
        print(f"  {table:<32} ERRO: {e}")

con.close()
print("\nFinalizado.")
