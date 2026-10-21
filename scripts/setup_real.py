#!/usr/bin/env python3
"""
setup_real.py — Carga de fato_custo nos três motores de benchmark.

Pré-requisitos (em vmbench01):
  - /home/uniassis/bench/data/real/fato_custo.csv  (transferido de vmdw01)
  - Banco PostgreSQL 'bench_real' criado:
      sudo -u postgres psql -c "CREATE DATABASE bench_real OWNER bench;"
  - DuckDB file: ~/bench/data/real/fato_custo.duckdb  (criado por este script)
  - Parquet:     ~/bench/data/real/fato_custo.parquet  (criado por este script)

Uso:
  cd ~/bench && python3 scripts/setup_real.py
"""

import os, subprocess, tempfile, pathlib, sys
import duckdb

BASE    = pathlib.Path.home() / "bench"
CSV     = BASE / "data/real/fato_custo.csv"
DK_FILE = BASE / "data/real/fato_custo.duckdb"
PQ_FILE = BASE / "data/real/fato_custo.parquet"

PG_DB   = "bench_real"
PG_ARGS = ["-U", "bench", "-h", "localhost"]
PG_ENV  = {**os.environ, "PGPASSWORD": os.environ.get("PGPASSWORD", "bench")}

DDL = """
CREATE TABLE IF NOT EXISTS fato_custo (
    sk_fato_custos          INTEGER PRIMARY KEY,
    sk_beneficiario         INTEGER,
    sk_prestador_executante INTEGER,
    sk_prestador_fornecedor INTEGER,
    sk_prestador_solicitante INTEGER,
    sk_item                 INTEGER,
    sk_unimed_executora     INTEGER,
    sk_unimed_do_usuario    INTEGER,
    guia_nro_ano_solic      INTEGER,
    id_guia                 INTEGER,
    id_guia_sequencia       INTEGER,
    tipo_guia               VARCHAR(10),
    data_alta               DATE,
    data_competencia        DATE,
    data_execucao_procedimento DATE,
    turno_atendimento       VARCHAR(9),
    carater_internacao      VARCHAR(19),
    participacao_profissional VARCHAR(19),
    autogerado              VARCHAR(10),
    combinado               VARCHAR(9),
    tipo_atendimento        VARCHAR(33),
    tipo_internacao         VARCHAR(26),
    tipo_despesa            VARCHAR(20),
    via_acesso              VARCHAR(9),
    custo_acomodacao        VARCHAR(17),
    internacao              VARCHAR(7),
    sistema_fonte           VARCHAR(50),
    cid                     TEXT,
    valor_pago              NUMERIC(12,2),
    valor_pago_honor        NUMERIC(12,2),
    valor_pago_filme        NUMERIC(12,2),
    valor_pago_co           NUMERIC(12,2),
    valor_faturado          NUMERIC(12,2),
    quantidade              NUMERIC(12,2),
    carteirinha_hash        VARCHAR(32),
    profissional_hash       VARCHAR(37),
    sk_contrato             INTEGER
);
"""

INDEXES = """
CREATE INDEX IF NOT EXISTS idx_fc_data_comp   ON fato_custo (data_competencia);
CREATE INDEX IF NOT EXISTS idx_fc_benef       ON fato_custo (sk_beneficiario);
CREATE INDEX IF NOT EXISTS idx_fc_prestador   ON fato_custo (sk_prestador_executante);
CREATE INDEX IF NOT EXISTS idx_fc_contrato    ON fato_custo (sk_contrato);
"""

def pg_run(sql, db=PG_DB):
    r = subprocess.run(
        ["psql"] + PG_ARGS + ["-d", db, "-c", sql],
        env=PG_ENV, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"PG ERROR: {r.stderr[:300]}")
    return r.returncode

def pg_load(csv_path):
    """COPY fato_custo via STDIN."""
    p = subprocess.Popen(
        ["psql"] + PG_ARGS + ["-d", PG_DB, "-c",
         "COPY fato_custo FROM STDIN WITH (FORMAT CSV, HEADER, DELIMITER '|', NULL '')"],
        stdin=subprocess.PIPE, env=PG_ENV,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    with open(csv_path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            p.stdin.write(chunk)
    p.stdin.close()
    rc = p.wait()
    return rc, p.stderr.read().decode()

def main():
    if not CSV.exists():
        print(f"CSV não encontrado: {CSV}")
        sys.exit(1)

    # ── PostgreSQL ──────────────────────────────────────────────
    print("=== PostgreSQL ===")
    pg_run("DROP TABLE IF EXISTS fato_custo;")
    pg_run(DDL)
    print("  Carregando CSV via STDIN...")
    rc, err = pg_load(CSV)
    if rc != 0:
        print(f"  ERRO: {err[:400]}")
    else:
        print("  Criando índices...")
        pg_run(INDEXES)
        rows = subprocess.run(
            ["psql"] + PG_ARGS + ["-d", PG_DB, "-tAc", "SELECT COUNT(*) FROM fato_custo"],
            env=PG_ENV, capture_output=True, text=True).stdout.strip()
        print(f"  OK — {rows} linhas")

    # ── DuckDB ──────────────────────────────────────────────────
    print("\n=== DuckDB ===")
    if DK_FILE.exists():
        DK_FILE.unlink()
    con = duckdb.connect(str(DK_FILE))
    con.execute(f"""
        CREATE TABLE fato_custo AS
        SELECT * FROM read_csv(
            '{CSV}',
            header=true, delim='|', nullstr='',
            columns={{
                'sk_fato_custos': 'INTEGER',
                'sk_beneficiario': 'INTEGER',
                'sk_prestador_executante': 'INTEGER',
                'sk_prestador_fornecedor': 'INTEGER',
                'sk_prestador_solicitante': 'INTEGER',
                'sk_item': 'INTEGER',
                'sk_unimed_executora': 'INTEGER',
                'sk_unimed_do_usuario': 'INTEGER',
                'guia_nro_ano_solic': 'INTEGER',
                'id_guia': 'INTEGER',
                'id_guia_sequencia': 'INTEGER',
                'tipo_guia': 'VARCHAR',
                'data_alta': 'DATE',
                'data_competencia': 'DATE',
                'data_execucao_procedimento': 'DATE',
                'turno_atendimento': 'VARCHAR',
                'carater_internacao': 'VARCHAR',
                'participacao_profissional': 'VARCHAR',
                'autogerado': 'VARCHAR',
                'combinado': 'VARCHAR',
                'tipo_atendimento': 'VARCHAR',
                'tipo_internacao': 'VARCHAR',
                'tipo_despesa': 'VARCHAR',
                'via_acesso': 'VARCHAR',
                'custo_acomodacao': 'VARCHAR',
                'internacao': 'VARCHAR',
                'sistema_fonte': 'VARCHAR',
                'cid': 'VARCHAR',
                'valor_pago': 'DECIMAL(12,2)',
                'valor_pago_honor': 'DECIMAL(12,2)',
                'valor_pago_filme': 'DECIMAL(12,2)',
                'valor_pago_co': 'DECIMAL(12,2)',
                'valor_faturado': 'DECIMAL(12,2)',
                'quantidade': 'DECIMAL(12,2)',
                'carteirinha_hash': 'VARCHAR',
                'profissional_hash': 'VARCHAR',
                'sk_contrato': 'INTEGER'
            }}
        )
    """)
    rows = con.execute("SELECT COUNT(*) FROM fato_custo").fetchone()[0]
    print(f"  OK — {rows:,} linhas")

    # ── Parquet ──────────────────────────────────────────────────
    print("\n=== Parquet ===")
    con.execute(f"COPY fato_custo TO '{PQ_FILE}' (FORMAT PARQUET, COMPRESSION SNAPPY)")
    size_mb = PQ_FILE.stat().st_size / 1024**2
    print(f"  OK — {PQ_FILE.name}  ({size_mb:.0f} MB)")
    con.close()

    print("\nSetup concluído.")

if __name__ == "__main__":
    main()
