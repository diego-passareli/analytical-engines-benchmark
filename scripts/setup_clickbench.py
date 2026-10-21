#!/usr/bin/env python3
"""
Setup ClickBench no PostgreSQL:
1. Cria banco bench_clickbench
2. Cria tabela hits (EventDate DATE, EventTime TIMESTAMP)
3. Carrega via DuckDB → pipe → PostgreSQL COPY (~30-45 min)
"""
import subprocess, sys, os
from pathlib import Path

PARQUET = Path.home() / "bench/data/clickbench/hits.parquet"
DDL     = Path.home() / "bench/data/clickbench/hits_pg.ddl"

def run(cmd, **kw):
    print(f"$ {' '.join(cmd) if isinstance(cmd, list) else cmd}")
    result = subprocess.run(cmd, **kw)
    if result.returncode != 0:
        print(f"ERRO (rc={result.returncode})")
        sys.exit(1)
    return result

# 1. Criar banco
print("=== 1. Criando banco bench_clickbench ===")
run(["sudo", "-u", "postgres", "psql", "-c",
     "CREATE DATABASE bench_clickbench OWNER bench;"],
    capture_output=True, text=True)   # OK se já existir
run(["sudo", "-u", "postgres", "psql", "-c",
     "GRANT ALL PRIVILEGES ON DATABASE bench_clickbench TO bench;"])

# 2. Criar tabela
print("\n=== 2. Criando tabela hits ===")
env = os.environ | {"PGPASSWORD": "bench"}
run(["psql", "-h", "127.0.0.1", "-U", "bench", "-d", "bench_clickbench",
     "-f", str(DDL)], env=env)

# 3. Carregar via pipe DuckDB → PostgreSQL
print("\n=== 3. Carregando 100M linhas via pipe DuckDB → PostgreSQL ===")
print("(pode levar 30-45 minutos — acompanhe no tmux)")

duckdb_sql = f"""
COPY (
    SELECT * REPLACE (
        to_timestamp(EventTime) AS EventTime,
        (DATE '1970-01-01' + EventDate::INTEGER) AS EventDate
    )
    FROM read_parquet('{PARQUET}')
) TO '/dev/stdout' (FORMAT CSV, HEADER false, TIMESTAMP_FORMAT '%Y-%m-%d %H:%M:%S')
"""

duckdb_proc = subprocess.Popen(
    ["duckdb", "-c", duckdb_sql.strip()],
    stdout=subprocess.PIPE,
)
psql_proc = subprocess.Popen(
    ["psql", "-h", "127.0.0.1", "-U", "bench", "-d", "bench_clickbench",
     "-c", "COPY hits FROM STDIN WITH (FORMAT CSV, TIMESTAMP_FORMAT 'YYYY-MM-DD HH24:MI:SS')"],
    stdin=duckdb_proc.stdout,
    env=env,
)
duckdb_proc.stdout.close()
psql_rc   = psql_proc.wait()
duckdb_rc = duckdb_proc.wait()

if psql_rc != 0 or duckdb_rc != 0:
    print(f"ERRO: duckdb rc={duckdb_rc}, psql rc={psql_rc}")
    sys.exit(1)

# 4. Índices básicos (opcional, melhora Q37-Q43)
print("\n=== 4. Criando índices ===")
run(["psql", "-h", "127.0.0.1", "-U", "bench", "-d", "bench_clickbench",
     "-c", "CREATE INDEX ON hits (CounterID, EventDate);"], env=env)

# 5. ANALYZE
print("\n=== 5. ANALYZE ===")
run(["psql", "-h", "127.0.0.1", "-U", "bench", "-d", "bench_clickbench",
     "-c", "ANALYZE hits;"], env=env)

# 6. Contagem de verificação
result = subprocess.run(
    ["psql", "-h", "127.0.0.1", "-U", "bench", "-d", "bench_clickbench",
     "-t", "-c", "SELECT COUNT(*) FROM hits;"],
    capture_output=True, text=True, env=env
)
count = result.stdout.strip()
print(f"\n=== Setup concluído: {count} linhas carregadas ===")
