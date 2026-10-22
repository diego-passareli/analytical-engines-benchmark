#!/usr/bin/env python3
"""Fix definitivo: PG warehouse/web_page + DuckDB via DDL parseado"""
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
    return subprocess.run(["psql"]+PG_ARGS+["-c",sql], env=PG_ENV, capture_output=True, text=True)

def pg_load(table, dat):
    sed = subprocess.Popen(["sed","s/|$//",str(dat)], stdout=subprocess.PIPE)
    p   = subprocess.Popen(["psql"]+PG_ARGS+["-c",
          f"COPY {table} FROM STDIN WITH (FORMAT csv, DELIMITER '|', NULL '')"],
          stdin=sed.stdout, env=PG_ENV, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    sed.stdout.close(); rc = p.wait(); sed.wait()
    err = p.stderr.read().decode()
    r = subprocess.run(["psql"]+PG_ARGS+["-t","-c",f"SELECT COUNT(*) FROM {table}"],
                       env=PG_ENV, capture_output=True, text=True)
    return rc, r.stdout.strip(), err

def parse_ddl(path):
    text = Path(path).read_text()
    result = {}
    for m in re.finditer(r'CREATE TABLE (\w+)\s*\(([^;]+)\);', text, re.IGNORECASE|re.DOTALL):
        tname, body = m.group(1).lower(), m.group(2)
        cols = []
        for line in body.strip().split('\n'):
            line = line.strip().rstrip(',')
            if not line or line.upper().startswith(('PRIMARY','UNIQUE','CHECK','FOREIGN','--')): continue
            parts = line.split(None, 1)
            if len(parts) == 2:
                cols.append((parts[0].lower(), parts[1].strip()))
        result[tname] = cols
    return result

def pg_to_dk(pg_type):
    t = pg_type.upper().rstrip(',').strip()
    if re.match(r'INT', t):        return 'INTEGER'
    if 'BIGINT' in t:              return 'BIGINT'
    if 'DECIMAL' in t or 'NUMERIC' in t:
        m = re.search(r'\((\d+),\s*(\d+)\)', t)
        return f"DECIMAL({m.group(1)},{m.group(2)})" if m else 'DECIMAL(15,2)'
    if 'CHARACTER VARYING' in t or 'VARCHAR' in t:
        m = re.search(r'\((\d+)\)', t); return f"VARCHAR({m.group(1)})" if m else 'VARCHAR'
    if re.match(r'CHAR', t):
        m = re.search(r'\((\d+)\)', t); return f"CHAR({m.group(1)})" if m else 'VARCHAR'
    if 'DATE' in t:   return 'DATE'
    if 'TIME' in t:   return 'TIME'
    return 'VARCHAR'

TABLES = [
    "catalog_page","catalog_returns","customer","customer_address",
    "inventory","item","promotion","store_returns","store_sales",
    "time_dim","warehouse","web_page","web_returns"
]

# ── PG: corrigir warehouse e web_page (remover coluna restaurada erroneamente) ──
print("=== Corrigindo PG warehouse e web_page ===")
psql("ALTER TABLE warehouse DROP COLUMN IF EXISTS w_gmt_offset")
psql("TRUNCATE warehouse")
rc, cnt, err = pg_load("warehouse", DATA_DIR/"warehouse.dat")
print(f"  warehouse: {cnt}  {'OK' if rc==0 else err[:200]}")

psql("ALTER TABLE web_page DROP COLUMN IF EXISTS wp_max_ad_count")
psql("TRUNCATE web_page")
rc, cnt, err = pg_load("web_page", DATA_DIR/"web_page.dat")
print(f"  web_page:  {cnt}  {'OK' if rc==0 else err[:200]}")

# ── PG: status final ───────────────────────────────────────────────────────────
print("\n=== Status PG ===")
for t in TABLES:
    r1 = subprocess.run(["psql"]+PG_ARGS+["-t","-c",f"SELECT COUNT(*) FROM {t}"],
                        env=PG_ENV, capture_output=True, text=True)
    r2 = subprocess.run(["psql"]+PG_ARGS+["-t","-c",
         f"SELECT COUNT(*) FROM information_schema.columns "
         f"WHERE table_name='{t}' AND table_schema='public'"],
         env=PG_ENV, capture_output=True, text=True)
    print(f"  {t:<32} {r2.stdout.strip():>3} cols  {r1.stdout.strip():>12} rows")

# ── DuckDB: rebuild via DDL explícito ─────────────────────────────────────────
print("\n=== Rebuild DuckDB ===")
ddl = parse_ddl(DDL_FILE)
con = duckdb.connect(DK_DB)
con.execute("SET threads=16; SET memory_limit='40GB';")

for table in TABLES:
    dat = DATA_DIR / f"{table}.dat"
    if table not in ddl:
        print(f"  {table:<32} DDL não encontrado"); continue

    orig = ddl[table]
    # Contar colunas reais no arquivo
    with open(dat) as f:
        line = f.readline().rstrip('\n').rstrip('|')
    n_file = len(line.split('|'))

    if len(orig) - 1 == n_file:
        use_cols = orig[:-1]          # drop última coluna
    elif len(orig) == n_file:
        use_cols = orig               # DDL bate com arquivo (ex: web_returns)
    else:
        print(f"  {table:<32} MISMATCH DDL={len(orig)} file={n_file}"); continue

    col_defs = ",\n    ".join(f"{c} {pg_to_dk(tp)}" for c, tp in use_cols)
    fd, tmp = tempfile.mkstemp(suffix=".dat"); os.close(fd)
    t0 = time.time()
    try:
        subprocess.run(["sed","s/|$//",str(dat)], stdout=open(tmp,"w"), check=True)
        con.execute(f"DROP TABLE IF EXISTS {table}")
        con.execute(f"CREATE TABLE {table} (\n    {col_defs}\n)")
        con.execute(f"COPY {table} FROM '{tmp}' (DELIMITER '|', NULL '', HEADER false)")
        cnt = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table:<32} {cnt:>12,}  {time.time()-t0:5.1f}s")
    except Exception as e:
        print(f"  {table:<32} ERRO: {e}")
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

# ── Parquet ────────────────────────────────────────────────────────────────────
print("\n=== Exportando Parquet ===")
for table in TABLES:
    pq = PQ_DIR / f"{table}.parquet"
    try:
        con.execute(f"COPY (SELECT * FROM {table}) TO '{pq}' (FORMAT PARQUET)")
        print(f"  {table:<32} {pq.stat().st_size/1e6:6.1f} MB")
    except Exception as e:
        print(f"  {table:<32} ERRO: {e}")

con.close()
print("\nFinalizado.")
