#!/usr/bin/env python3
"""
setup_tpch.py — Gera e carrega o TPC-H (SF=1, 10 ou 100) no PostgreSQL, no
DuckDB e em Parquet.

Este script consolida, sem alterar o procedimento, os comandos executados
interativamente na VM em 28-29/09/2026 para montar os bancos usados no estudo
(a carga original não foi feita por script). Etapas:

  1. dbgen (TPC-H 2.14.0, repositório electrum/tpch-dbgen) gera os .tbl em
     ~/bench/data/tpch/sf{SF}/ (pula se os arquivos já existirem);
  2. PostgreSQL: cria o banco (bench para SF=1, bench_sf10, bench_sf100), as
     tabelas com o DDL oficial dss.ddl do dbgen, carrega cada .tbl removendo o
     '|' final de cada linha (equivalente a `sed 's/|$//' | COPY ... FROM STDIN
     DELIMITER '|' CSV`) e adiciona as chaves primárias. Não foram criados
     outros índices nem executado ANALYZE manual (as estatísticas ficam a cargo
     do autovacuum);
  3. DuckDB: lê os .tbl com o schema tipado abaixo, cria tpch_sf{SF}.duckdb e
     exporta cada tabela para Parquet (SNAPPY), usado pelo Polars.

Contagens esperadas de lineitem: 6.001.215 (SF=1), 59.986.052 (SF=10) e
600.037.902 (SF=100), conferidas na carga original.

Uso (na VM, venv do projeto ativo):
  python3 scripts/setup_tpch.py --sf 1
Requisitos: ~/tpch-dbgen compilado; sudo para criar o banco; ~200 GB livres
para SF=100 (.tbl + PostgreSQL + DuckDB + Parquet).
"""

import argparse, os, pathlib, shutil, subprocess, sys, time
import duckdb, psycopg2

HOME   = pathlib.Path.home()
DBGEN  = HOME / "tpch-dbgen"
TABLES = ["region", "nation", "supplier", "part", "customer",
          "partsupp", "orders", "lineitem"]

PKS = {
    "region": "r_regionkey", "nation": "n_nationkey", "supplier": "s_suppkey",
    "part": "p_partkey", "customer": "c_custkey",
    "partsupp": "ps_partkey, ps_suppkey", "orders": "o_orderkey",
    "lineitem": "l_orderkey, l_linenumber",
}

# Schema usado na carga original do DuckDB
SCHEMA = {
    "region":   "r_regionkey INTEGER, r_name VARCHAR, r_comment VARCHAR",
    "nation":   "n_nationkey INTEGER, n_name VARCHAR, n_regionkey INTEGER, n_comment VARCHAR",
    "supplier": "s_suppkey INTEGER, s_name VARCHAR, s_address VARCHAR, s_nationkey INTEGER, s_phone VARCHAR, s_acctbal DECIMAL(15,2), s_comment VARCHAR",
    "part":     "p_partkey INTEGER, p_name VARCHAR, p_mfgr VARCHAR, p_brand VARCHAR, p_type VARCHAR, p_size INTEGER, p_container VARCHAR, p_retailprice DECIMAL(15,2), p_comment VARCHAR",
    "customer": "c_custkey INTEGER, c_name VARCHAR, c_address VARCHAR, c_nationkey INTEGER, c_phone VARCHAR, c_acctbal DECIMAL(15,2), c_mktsegment VARCHAR, c_comment VARCHAR",
    "partsupp": "ps_partkey INTEGER, ps_suppkey INTEGER, ps_availqty INTEGER, ps_supplycost DECIMAL(15,2), ps_comment VARCHAR",
    "orders":   "o_orderkey INTEGER, o_custkey INTEGER, o_orderstatus VARCHAR, o_totalprice DECIMAL(15,2), o_orderdate DATE, o_orderpriority VARCHAR, o_clerk VARCHAR, o_shippriority INTEGER, o_comment VARCHAR",
    "lineitem": "l_orderkey INTEGER, l_partkey INTEGER, l_suppkey INTEGER, l_linenumber INTEGER, l_quantity DECIMAL(15,2), l_extendedprice DECIMAL(15,2), l_discount DECIMAL(15,2), l_tax DECIMAL(15,2), l_returnflag VARCHAR, l_linestatus VARCHAR, l_shipdate DATE, l_commitdate DATE, l_receiptdate DATE, l_shipinstruct VARCHAR, l_shipmode VARCHAR, l_comment VARCHAR",
}


class StripTrailingPipe:
    """Arquivo-like que remove o '|' final de cada linha (como `sed 's/|$//'`)."""
    def __init__(self, path):
        self.f = open(path, "r", encoding="latin-1")
    def readline(self, *_):
        line = self.f.readline()
        return line[:-2] + "\n" if line.endswith("|\n") else line
    def read(self, size=-1):
        out = []
        n = 0
        while size < 0 or n < size:
            line = self.readline()
            if not line:
                break
            out.append(line)
            n += len(line)
        return "".join(out)
    def close(self):
        self.f.close()


def generate(sf, data):
    if all((data / f"{t}.tbl").exists() for t in TABLES):
        print("Arquivos .tbl já existem; dbgen não será executado.")
        return
    data.mkdir(parents=True, exist_ok=True)
    shutil.copy(DBGEN / "dists.dss", data / "dists.dss")
    print(f"dbgen -s {sf} ...")
    subprocess.run([str(DBGEN / "dbgen"), "-s", str(sf), "-f"], cwd=data, check=True)


def load_pg(sf, data):
    dbname = "bench" if sf == 1 else f"bench_sf{sf}"
    pw = os.environ.get("PGPASSWORD", "bench")
    r = subprocess.run(["sudo", "-u", "postgres", "psql", "-c",
                        f"CREATE DATABASE {dbname} OWNER bench;"],
                       capture_output=True, text=True)
    if r.returncode != 0 and "already exists" not in r.stderr:
        sys.exit("Falha ao criar o banco: " + r.stderr.strip())
    conn = psycopg2.connect(host="127.0.0.1", dbname=dbname, user="bench", password=pw)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM pg_tables WHERE schemaname='public'")
    if cur.fetchone()[0] > 0:
        sys.exit(f"O banco {dbname} já tem tabelas; remova-o antes de recarregar.")
    cur.execute((DBGEN / "dss.ddl").read_text())
    for t in TABLES:
        t0 = time.time()
        src = StripTrailingPipe(data / f"{t}.tbl")
        try:
            cur.copy_expert(f"COPY {t} FROM STDIN DELIMITER '|' CSV", src)
        finally:
            src.close()
        cur.execute(f"SELECT count(*) FROM {t}")
        print(f"  PG {t:<9} {cur.fetchone()[0]:>12,}  ({time.time()-t0:.0f}s)")
    for t, cols in PKS.items():
        cur.execute(f"ALTER TABLE {t} ADD PRIMARY KEY ({cols})")
    print("  PG chaves primárias criadas.")
    conn.close()


def load_duckdb(sf, data):
    db = data / f"tpch_sf{sf}.duckdb"
    con = duckdb.connect(str(db))
    con.execute("SET threads=16; SET memory_limit='40GB';")
    for t, cols in SCHEMA.items():
        t0 = time.time()
        coldef = ", ".join(f"'{c.split()[0]}': '{' '.join(c.split()[1:])}'"
                           for c in cols.split(", "))
        con.execute(f"DROP TABLE IF EXISTS {t}")
        con.execute(f"CREATE TABLE {t} AS SELECT * FROM read_csv("
                    f"'{data / (t + '.tbl')}', delim='|', header=false, columns={{{coldef}}})")
        con.execute(f"COPY {t} TO '{data / (t + '.parquet')}' (FORMAT PARQUET, COMPRESSION SNAPPY)")
        n = con.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
        print(f"  DK {t:<9} {n:>12,}  ({time.time()-t0:.0f}s)")
    con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sf", type=int, required=True, choices=[1, 10, 100])
    ap.add_argument("--skip-pg", action="store_true")
    ap.add_argument("--skip-duckdb", action="store_true")
    args = ap.parse_args()
    data = HOME / f"bench/data/tpch/sf{args.sf}"
    generate(args.sf, data)
    if not args.skip_pg:
        load_pg(args.sf, data)
    if not args.skip_duckdb:
        load_duckdb(args.sf, data)
    print("Concluído.")


if __name__ == "__main__":
    main()
