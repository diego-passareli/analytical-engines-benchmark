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
    print(f"$ {' '.join(cmd)}")
    result = subprocess.run(cmd, **kw)
    if result.returncode != 0:
        print(f"ERRO (rc={result.returncode})")
        sys.exit(1)
    return result

env = os.environ | {"PGPASSWORD": "bench"}

# 1. Criar banco
print("=== 1. Criando banco bench_clickbench ===")
subprocess.run(["sudo", "-u", "postgres", "psql", "-c",
     "CREATE DATABASE bench_clickbench OWNER bench;"], capture_output=True)
subprocess.run(["sudo", "-u", "postgres", "psql", "-c",
     "GRANT ALL PRIVILEGES ON DATABASE bench_clickbench TO bench;"], capture_output=True)
print("OK")

# 2. Criar tabela
print("\n=== 2. Criando tabela hits ===")
run(["psql", "-h", "127.0.0.1", "-U", "bench", "-d", "bench_clickbench",
     "-f", str(DDL)], env=env)

# 3. Carregar via pipe DuckDB → PostgreSQL
print("\n=== 3. Carregando 100M linhas via pipe DuckDB → PostgreSQL ===")
print("(pode levar 30-45 minutos)")

duckdb_sql = (
    "COPY ("
    "SELECT * REPLACE ("
    "to_timestamp(EventTime) AS EventTime,"
    "(DATE '1970-01-01' + EventDate::INTEGER) AS EventDate"
    ") FROM read_parquet('" + str(PARQUET) + "')"
    ") TO '/dev/stdout' (FORMAT CSV, HEADER false)"
)

duckdb_proc = subprocess.Popen(
    ["duckdb", "-c", duckdb_sql],
    stdout=subprocess.PIPE,
)
psql_proc = subprocess.Popen(
    ["psql", "-h", "127.0.0.1", "-U", "bench", "-d", "bench_clickbench",
     "-c", "COPY hits FROM STDIN CSV"],
    stdin=duckdb_proc.stdout,
    env=env,
)
duckdb_proc.stdout.close()
psql_rc   = psql_proc.wait()
duckdb_rc = duckdb_proc.wait()

if psql_rc != 0 or duckdb_rc != 0:
    print(f"ERRO: duckdb rc={duckdb_rc}, psql rc={psql_rc}")
    sys.exit(1)
print("Carga concluída.")

# 4. Índice + ANALYZE
print("\n=== 4. Índice e ANALYZE ===")
run(["psql", "-h", "127.0.0.1", "-U", "bench", "-d", "bench_clickbench",
     "-c", "CREATE INDEX ON hits (CounterID, EventDate);"], env=env)
run(["psql", "-h", "127.0.0.1", "-U", "bench", "-d", "bench_clickbench",
     "-c", "ANALYZE hits;"], env=env)

# 5. Verificação
r = subprocess.run(
    ["psql", "-h", "127.0.0.1", "-U", "bench", "-d", "bench_clickbench",
     "-t", "-c", "SELECT COUNT(*) FROM hits;"],
    capture_output=True, text=True, env=env
)
print(f"\n=== Concluído: {r.stdout.strip()} linhas ===")
