#!/usr/bin/env python3
"""
Adapta 99 queries TPC-DS: SELECT TOP N → LIMIT N, remove comentários dsqgen.
"""
import re
from pathlib import Path

QUERIES_DIR = Path.home() / "bench/queries/tpcds"
OUT_DIR     = Path.home() / "bench/queries/tpcds/adapted"
OUT_DIR.mkdir(parents=True, exist_ok=True)

TOP_RE = re.compile(r'\bselect\s+top\s+(\d+)\b', re.IGNORECASE)

def convert(sql):
    # Remove comentários do dsqgen (início e fim)
    sql = re.sub(r'^--\s*(start|end) query.*\n?', '', sql, flags=re.MULTILINE)
    sql = sql.strip()

    limits = []
    def replace_top(m):
        limits.append(int(m.group(1)))
        return 'SELECT'
    sql = TOP_RE.sub(replace_top, sql)

    if limits:
        # Remove ';' final para inserir LIMIT antes dele
        sql = sql.rstrip().rstrip(';').rstrip()
        sql += f"\nLIMIT {limits[0]}"

    if not sql.rstrip().endswith(';'):
        sql = sql.rstrip() + '\n;\n'
    return sql

for qfile in sorted(QUERIES_DIR.glob('query*.sql')):
    if 'adapted' in str(qfile):
        continue
    out = OUT_DIR / qfile.name
    out.write_text(convert(qfile.read_text()))

count = len(list(OUT_DIR.glob('*.sql')))
print(f"OK — {count} queries em {OUT_DIR}")
