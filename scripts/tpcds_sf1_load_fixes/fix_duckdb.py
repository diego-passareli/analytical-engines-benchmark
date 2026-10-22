#!/usr/bin/env python3
"""
1. Diagnóstico: conta colunas reais em cada .dat
2. Restaura wr_net_loss em PG (se arquivo web_returns tem 24 colunas)
3. DROP + recreate de cada tabela DuckDB via read_csv com nomes do PG
4. Exporta Parquet
"""
import os, subprocess, tempfile, time
from pathlib import Path
import duckdb

BASE     = Path.home() / "bench"
DATA_DIR = BASE / "data/tpcds/sf1"
DK_DB    = str(BASE / "data/tpcds/tpcds_sf1.duckdb")
PQ_DIR   = BASE / "data/tpcds/parquet_sf1"
PQ_DIR.mkdir(exist_ok=True)

PG_ENV  = os.environ | {"PGPASSWORD": "bench"}
PG_ARGS = ["-h","127.0.0.1","-U","bench","-d","bench_tpcds_sf1"]

def psql(sql):
    return subprocess.run(["psql"]+PG_ARGS+["-c",sql],
                          env=PG_ENV, capture_output=True, text=True)

def pg_row_count(table):
    r = subprocess.run(["psql"]+PG_ARGS+["-t","-c",f"SELECT COUNT(*) FROM {table}"],
                       env=PG_ENV, capture_output=True, text=True)
    return r.stdout.strip()

def pg_columns(table):
    r = subprocess.run(
        ["psql"]+PG_ARGS+["-t","-c",
         f"SELECT column_name FROM information_schema.columns "
         f"WHERE table_name='{table}' AND table_schema='public' "
         f"ORDER BY ordinal_position"],
        env=PG_ENV, capture_output=True, text=True)
    return [c.strip() for c in r.stdout.strip().split('\n') if c.strip()]

# ─── PASSO 0: contar colunas reais nos arquivos ────────────────────────────
print("=== Colunas reais nos arquivos .dat ===")
actual = {}
for dat in sorted(DATA_DIR.glob("*.dat")):
    t = dat.stem
    with open(dat) as f:
        line = f.readline().rstrip('\n').rstrip('|')
    n = len(line.split('|')) if line else 0
    actual[t] = n
    print(f"  {t:<32} {n:>3}")

TABLES = [
    "catalog_page","catalog_returns","customer","customer_address",
    "inventory","item","promotion","store_returns","store_sales",
    "time_dim","warehouse","web_page","web_returns"
]

# ─── PASSO 1: corrigir PG web_returns se necessário ───────────────────────
wr_file = actual.get('web_returns', 0)
wr_pg   = len(pg_columns('web_returns'))
print(f"\nweb_returns: arquivo={wr_file}  PG atual={wr_pg}")
if wr_file == 24 and wr_pg == 23:
    print("  → restaurando wr_net_loss em PG...")
    psql("ALTER TABLE web_returns ADD COLUMN wr_net_loss DECIMAL(7,2)")
    psql("TRUNCATE web_returns")
    dat = DATA_DIR / "web_returns.dat"
    sed = subprocess.Popen(["sed","s/|$//",str(dat)], stdout=subprocess.PIPE)
    p   = subprocess.Popen(
        ["psql"]+PG_ARGS+["-c",
         "COPY web_returns FROM STDIN WITH (FORMAT csv, DELIMITER '|', NULL '')"],
        stdin=sed.stdout, env=PG_ENV,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    sed.stdout.close(); rc = p.wait(); sed.wait()
    print(f"  PG web_returns: {pg_row_count('web_returns')} rows  {'OK' if rc==0 else p.stderr.read().decode()[:300]}")
elif wr_file == 23 and wr_pg == 23:
    # Arquivo tem 23 e PG tem 23 — recarregar se estiver vazio
    cnt = pg_row_count('web_returns').strip()
    if cnt == '0':
        print("  → recarregando (estava vazio)...")
        dat = DATA_DIR / "web_returns.dat"
        sed = subprocess.Popen(["sed","s/|$//",str(dat)], stdout=subprocess.PIPE)
        p   = subprocess.Popen(
            ["psql"]+PG_ARGS+["-c",
             "COPY web_returns FROM STDIN WITH (FORMAT csv, DELIMITER '|', NULL '')"],
            stdin=sed.stdout, env=PG_ENV,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        sed.stdout.close(); rc = p.wait(); sed.wait()
        print(f"  PG web_returns: {pg_row_count('web_returns')} rows")

# ─── PASSO 2: situação PG ─────────────────────────────────────────────────
print("\n=== Situação PG (tabelas que foram alteradas) ===")
for t in TABLES:
    cols = pg_columns(t)
    cnt  = pg_row_count(t)
    print(f"  {t:<32} {len(cols):>3} cols  {cnt:>12} rows")

# ─── PASSO 3: rebuild DuckDB via read_csv ─────────────────────────────────
print("\n=== Recriando tabelas DuckDB ===")
con = duckdb.connect(DK_DB)
con.execute("SET threads=16; SET memory_limit='40GB';")

for table in TABLES:
    dat   = DATA_DIR / f"{table}.dat"
    cols  = pg_columns(table)
    n_pg  = len(cols)
    n_file= actual.get(table, 0)
    
    if n_pg != n_file:
        print(f"  {table:<32} MISMATCH: PG={n_pg} arquivo={n_file} — pulando")
        continue
    
    t0 = time.time()
    fd, tmp = tempfile.mkstemp(suffix=".dat"); os.close(fd)
    try:
        subprocess.run(["sed","s/|$//",str(dat)], stdout=open(tmp,"w"), check=True)
        col_str = ", ".join(f"'{c}'" for c in cols)
        con.execute(f"DROP TABLE IF EXISTS {table}")
        con.execute(f"""
            CREATE TABLE {table} AS
            SELECT * FROM read_csv('{tmp}',
                delim='|', header=false,
                null_padding=true,
                names=[{col_str}])
        """)
        cnt = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table:<32} {cnt:>12,}  {time.time()-t0:5.1f}s")
    except Exception as e:
        print(f"  {table:<32} ERRO: {e}")
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

# ─── PASSO 4: exportar Parquet ────────────────────────────────────────────
print("\n=== Exportando Parquet ===")
for table in TABLES:
    pq = PQ_DIR / f"{table}.parquet"
    try:
        con.execute(f"COPY (SELECT * FROM {table}) TO '{pq}' (FORMAT PARQUET)")
        mb = pq.stat().st_size / 1e6
        print(f"  {table:<32} {mb:6.1f} MB")
    except Exception as e:
        print(f"  {table:<32} ERRO: {e}")

con.close()
print("\nConcluído.")
