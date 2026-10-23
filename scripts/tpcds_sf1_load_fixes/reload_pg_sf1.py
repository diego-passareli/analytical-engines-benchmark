#!/usr/bin/env python3
"""
reload_pg_sf1.py — Recarrega no PostgreSQL as tabelas do TPC-DS SF=1 que
ficaram vazias.

Contexto: fix_load.py recriava 13 tabelas (DROP ... CASCADE + CREATE) e as
carregava com `COPY ... FROM '/tmp/arquivo'`. Esse COPY é executado pelo
processo do servidor PostgreSQL, que não consegue ler o /tmp do usuário; a
carga falhou e as tabelas ficaram vazias (o DROP CASCADE também removeu os
índices delas). DuckDB e Parquet foram carregados por outro caminho e estão
corretos.

Este script:
  1. encontra as tabelas vazias no PostgreSQL que têm linhas no DuckDB SF=1;
  2. exporta cada uma do DuckDB (mesma fonte usada por DuckDB e Polars no
     benchmark) e carrega no PostgreSQL com COPY FROM STDIN (lado do cliente);
  3. recria os índices de setup_tpcds.py que estiverem faltando e roda ANALYZE;
  4. confere que todas as 24 tabelas têm a mesma contagem nos dois motores.

Uso (na VM, venv do projeto ativo):
  cd ~/bench && python3 scripts/tpcds_sf1_load_fixes/reload_pg_sf1.py
"""

import os, pathlib, sys, tempfile, time
import duckdb, psycopg2

BASE  = pathlib.Path.home() / "bench"
DK_DB = str(BASE / "data/tpcds/tpcds_sf1.duckdb")
PG    = dict(host="127.0.0.1", dbname="bench_tpcds_sf1", user="bench",
             password=os.environ.get("PGPASSWORD", "bench"))

# Mesmos índices de setup_tpcds.py: (tabela, colunas)
INDEXES = [
    ("store_sales", "ss_sold_date_sk"), ("store_returns", "sr_returned_date_sk"),
    ("catalog_sales", "cs_sold_date_sk"), ("catalog_returns", "cr_returned_date_sk"),
    ("web_sales", "ws_sold_date_sk"), ("web_returns", "wr_returned_date_sk"),
    ("inventory", "inv_date_sk"), ("date_dim", "d_date_sk"),
    ("date_dim", "d_year, d_moy"), ("item", "i_item_sk"),
    ("customer", "c_customer_sk"), ("store", "s_store_sk"),
]


def pg_count(cur, t):
    cur.execute(f"SELECT count(*) FROM {t}")
    return cur.fetchone()[0]


def main():
    dk = duckdb.connect(DK_DB, read_only=True)
    conn = psycopg2.connect(**PG)
    conn.autocommit = False
    cur = conn.cursor()

    cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY 1")
    tables = [r[0] for r in cur.fetchall()]
    dk_count = {t: dk.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables}

    todo = [t for t in tables if pg_count(cur, t) == 0 and dk_count[t] > 0]
    print(f"Tabelas vazias no PostgreSQL a recarregar ({len(todo)}): {', '.join(todo)}\n")

    for t in todo:
        cur.execute("""SELECT column_name FROM information_schema.columns
                       WHERE table_schema='public' AND table_name=%s
                       ORDER BY ordinal_position""", (t,))
        pg_cols = [r[0] for r in cur.fetchall()]
        dk_cols = {r[0] for r in dk.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name=?", [t]).fetchall()}
        missing = [c for c in pg_cols if c not in dk_cols]
        if missing:
            sys.exit(f"{t}: colunas do PostgreSQL ausentes no DuckDB: {missing}")
        extra = sorted(dk_cols - set(pg_cols))

        cols = ", ".join(pg_cols)
        fd, tmp = tempfile.mkstemp(suffix=".csv"); os.close(fd)
        t0 = time.time()
        try:
            # DuckDB grava NULL como campo vazio e string vazia como "" (entre aspas),
            # o que o COPY ... NULL '' do PostgreSQL distingue corretamente.
            dk.execute(f"COPY (SELECT {cols} FROM {t}) TO '{tmp}' "
                       f"(FORMAT csv, DELIMITER '|', HEADER false)")
            with open(tmp) as f:
                cur.copy_expert(f"COPY {t} ({cols}) FROM STDIN "
                                f"WITH (FORMAT csv, DELIMITER '|', NULL '')", f)
            conn.commit()
        finally:
            os.unlink(tmp)
        n = pg_count(cur, t)
        note = f"  (colunas só no DuckDB, ignoradas: {extra})" if extra else ""
        print(f"  {t:<24} {n:>10,} linhas  {time.time()-t0:6.1f}s{note}")

    # Índices de setup_tpcds.py que estiverem faltando
    print("\nÍndices:")
    cur.execute("SELECT tablename, indexdef FROM pg_indexes WHERE schemaname='public'")
    existing = cur.fetchall()
    for t, cols in INDEXES:
        key = f"({cols})"
        if any(tt == t and key in d for tt, d in existing):
            print(f"  {t}{key}: já existe")
            continue
        cur.execute(f"CREATE INDEX ON {t} ({cols})")
        conn.commit()
        print(f"  {t}{key}: criado")

    conn.autocommit = True
    cur.execute("ANALYZE")
    print("\nANALYZE concluído.\n")

    print("Conferência final (PostgreSQL vs DuckDB):")
    bad = 0
    for t in tables:
        n = pg_count(cur, t)
        ok = n == dk_count[t]
        bad += not ok
        print(f"  {t:<24} PG={n:>10,}  DK={dk_count[t]:>10,}  {'OK' if ok else 'DIFERENTE'}")
    conn.close()
    if bad:
        sys.exit(f"\n{bad} tabela(s) com contagem diferente — não rode o benchmark.")
    print("\nTodas as tabelas conferem. Pode rodar: python3 scripts/run_tpcds.py 1")


if __name__ == "__main__":
    main()
