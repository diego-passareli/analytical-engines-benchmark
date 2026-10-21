#!/usr/bin/env python3
"""
Adapta as 99 queries TPC-DS de sintaxe SQL Server/Sybase para PostgreSQL/DuckDB padrão.
Transformações:
  1. SELECT TOP N ... → SELECT ... LIMIT N  (move para o final do statement)
  2. Garante ponto-e-vírgula no final
  3. Remove comentários desnecessários do cabeçalho dsqgen
"""
import re, sys
from pathlib import Path

QUERIES_DIR = Path.home() / "bench/queries/tpcds"
OUT_DIR     = Path.home() / "bench/queries/tpcds/adapted"
OUT_DIR.mkdir(parents=True, exist_ok=True)

TOP_RE = re.compile(r'\bSELECT\s+TOP\s+(\d+)\b', re.IGNORECASE)

def convert(sql: str) -> str:
    """Converte SELECT TOP N → SELECT ... LIMIT N para cada ocorrência."""
    limits = []

    def replace_top(m):
        limits.append(int(m.group(1)))
        return 'SELECT'

    sql = TOP_RE.sub(replace_top, sql)

    if limits:
        # Adiciona LIMIT referente ao SELECT mais externo (último a ser processado
        # pelo parser — posição final antes do ';' ou fim de string)
        sql = sql.rstrip().rstrip(';').rstrip()
        sql += f"\nLIMIT {limits[0]}"

    # Garante terminador
    if not sql.rstrip().endswith(';'):
        sql = sql.rstrip() + '\n;\n'

    return sql


problems = []
for qfile in sorted(QUERIES_DIR.glob('query*.sql')):
    if 'adapted' in str(qfile):
        continue
    raw = qfile.read_text()
    # Remove cabeçalho do dsqgen
    raw = re.sub(r'^--\s*start query.*\n', '', raw, flags=re.MULTILINE)
    adapted = convert(raw)
    out = OUT_DIR / qfile.name
    out.write_text(adapted)

print(f"OK — {len(list(OUT_DIR.glob('*.sql')))} arquivos em {OUT_DIR}")
