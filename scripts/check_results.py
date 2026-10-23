#!/usr/bin/env python3
"""
check_results.py — Verifica se PostgreSQL, DuckDB e Polars retornam os mesmos
resultados para as mesmas consultas (equivalência de resultados).

Não mede tempo: executa cada consulta uma vez por motor, normaliza as linhas e
compara cada motor com o PostgreSQL (referência). Também grava a mensagem de
erro de cada falha, para documentar a causa real das falhas do Polars.

Uso (na VM, com o venv do projeto ativo):
  cd ~/bench
  python3 scripts/check_results.py real
  python3 scripts/check_results.py tpcds --sf 1
  python3 scripts/check_results.py tpch --sf 10 --ref duckdb
  python3 scripts/check_results.py clickbench --ref duckdb

  Com --ref duckdb, o PostgreSQL não é executado e o Polars é comparado com o
  DuckDB (útil quando o banco do PostgreSQL não existe mais).
  python3 scripts/check_results.py tpch --sf 1 --answers ~/caminho/tpch-dbgen/answers

  No TPC-H, --answers usa como referência as respostas oficiais do kit dbgen
  (q1.out … q22.out, SF=1) em vez do PostgreSQL. Os números dessas respostas
  têm 2 casas decimais, então a comparação tolera 0,01 de diferença absoluta.

Saída:
  ~/bench/results/equiv_<suite>_<TIMESTAMP>.csv   (uma linha por consulta e motor)
  ~/bench/results/equiv_<suite>_<TIMESTAMP>.txt   (diferenças em detalhe)

Classificação (comparação com o PostgreSQL):
  IGUAL        mesmas linhas; números iguais com tolerância relativa de 1e-6
  IGUAL_ORDEM  mesmas linhas, mas em outra ordem (só relevante sem ORDER BY total)
  APROX        mesmas linhas; números diferem até 1e-3 (relativo)
  DIFERENTE    número de linhas ou valores diferentes
  ERRO         o motor falhou (mensagem gravada)
"""

import argparse, csv, datetime, decimal, math, multiprocessing as mp, os, pathlib, queue, re, sys, time
import duckdb, polars as pl, psycopg2

BASE = pathlib.Path.home() / "bench"
RES_DIR = BASE / "results"
PG_PASS = os.environ.get("PGPASSWORD", "bench")
PG_TIMEOUT_S = 600
PL_TIMEOUT_S = 300   # mesmo timeout dos runners
PL_MEM_GB = 30       # mesmo limite de memória dos runners (RLIMIT_AS)

TPCDS_TABLES = [
    "call_center", "catalog_page", "catalog_returns", "catalog_sales",
    "customer", "customer_address", "customer_demographics", "date_dim",
    "household_demographics", "income_band", "inventory", "item",
    "promotion", "reason", "ship_mode", "store", "store_returns",
    "store_sales", "time_dim", "warehouse", "web_page", "web_returns",
    "web_sales", "web_site"]

TPCH_TABLES = ["region", "nation", "supplier", "part", "customer",
               "partsupp", "orders", "lineitem"]

# Mesma reescrita de INTERVAL usada em run_tpch.py para o Polars
_INTERVAL_RE = re.compile(r"INTERVAL\s+'(\d+)'\s+(DAY|MONTH|YEAR)S?", re.IGNORECASE)
_UNIT_MAP = {"DAY": "days", "MONTH": "months", "YEAR": "years"}
def polars_sql(sql):
    return _INTERVAL_RE.sub(
        lambda m: f"INTERVAL '{m.group(1)} {_UNIT_MAP[m.group(2).upper()]}'", sql)


# ── Configuração por suíte ───────────────────────────────────────────────
def setup(suite, sf, pgdb=None):
    if suite == "real":
        qdir = BASE / "scripts/queries/real"
        queries = {int(p.stem[1:]): p.read_text() for p in sorted(qdir.glob("q*.sql"))}
        pg = dict(host="localhost", dbname=pgdb or "bench_real", user="bench", password=PG_PASS)
        dk = duckdb.connect(str(BASE / "data/real/fato_custo.duckdb"), read_only=True)
        ctx = [("fato_custo", str(BASE / "data/real/fato_custo.parquet"))]
        pl_rewrite = lambda s: s
    elif suite == "tpcds":
        qdir = BASE / "queries/tpcds/adapted"
        queries = {}
        for f in sorted(qdir.glob("query*.sql")):
            m = re.search(r"query(\d+)\.sql$", f.name)
            if m:
                queries[int(m.group(1))] = f.read_text().strip()
        pg = dict(host="127.0.0.1", dbname=pgdb or f"bench_tpcds_sf{sf}",
                  user="bench", password=PG_PASS)
        dk = duckdb.connect(str(BASE / f"data/tpcds/tpcds_sf{sf}.duckdb"), read_only=True)
        pq_dir = BASE / f"data/tpcds/parquet_sf{sf}"
        ctx = [(t, str(pq_dir / f"{t}.parquet")) for t in TPCDS_TABLES
               if (pq_dir / f"{t}.parquet").exists()]
        pl_rewrite = lambda s: s
    elif suite == "clickbench":
        text = (BASE / "queries/clickbench/queries.sql").read_text()
        parts = re.split(r'--\s*Q(\d+)', text)
        queries = {int(parts[i]): parts[i + 1].strip() for i in range(1, len(parts), 2)}
        parquet = str(BASE / "data/clickbench/hits.parquet")
        pg = dict(host="127.0.0.1", dbname=pgdb or "bench_clickbench",
                  user="bench", password=PG_PASS)
        # Mesma VIEW de tipos normalizados usada em run_clickbench.py
        dk = duckdb.connect()
        dk.execute("SET threads=16; SET memory_limit='40GB';")
        dk.execute(f"""CREATE VIEW hits AS SELECT * REPLACE (
                         to_timestamp(EventTime) AS EventTime,
                         (DATE '1970-01-01' + EventDate::INTEGER) AS EventDate)
                       FROM read_parquet('{parquet}')""")
        ctx = [("hits", parquet, "clickbench")]
        pl_rewrite = lambda s: s
    else:
        text = (BASE / "queries/tpch/queries.sql").read_text()
        parts = re.split(r'--\s*Q(\d+)', text)
        queries = {int(parts[i]): parts[i + 1].strip() for i in range(1, len(parts), 2)}
        data_dir = BASE / f"data/tpch/sf{sf}"
        pg = dict(host="127.0.0.1", dbname=pgdb or ("bench" if sf == 1 else f"bench_sf{sf}"),
                  user="bench", password=PG_PASS)
        dk = duckdb.connect(str(data_dir / f"tpch_sf{sf}.duckdb"), read_only=True)
        dk.execute("SET threads=16; SET memory_limit='40GB';")
        ctx = [(t, str(data_dir / f"{t}.parquet")) for t in TPCH_TABLES]
        pl_rewrite = polars_sql
    return queries, pg, dk, ctx, pl_rewrite


# ── Execução ─────────────────────────────────────────────────────────────
def run_pg(sql, pg):
    conn = psycopg2.connect(**pg, options=f"-c statement_timeout={PG_TIMEOUT_S * 1000}")
    try:
        cur = conn.cursor()
        cur.execute(sql)
        return [tuple(r) for r in cur.fetchall()]
    finally:
        conn.close()

def run_dk(sql, dk):
    return [tuple(r) for r in dk.execute(sql).fetchall()]

class PolarsError(Exception):
    """Erro do Polars repassado pelo subprocesso (mensagem já inclui o tipo)."""

def _pl_worker(sql, tables, q):
    try:
        import resource
        lim = PL_MEM_GB * 1024**3
        resource.setrlimit(resource.RLIMIT_AS, (lim, lim))
    except Exception:
        pass
    try:
        ctx = pl.SQLContext()
        for name, path, *opt in tables:
            lf = pl.scan_parquet(path)
            if opt and opt[0] == "clickbench":
                # Mesma normalização de tipos usada em run_clickbench.py
                lf = lf.with_columns([
                    pl.from_epoch(pl.col("EventTime"), time_unit="s").alias("EventTime"),
                    pl.col("EventDate").cast(pl.Int32).cast(pl.Date).alias("EventDate"),
                ])
            ctx.register(name, lf)
        q.put(("ok", [tuple(r) for r in ctx.execute(sql).collect().rows()]))
    except BaseException as e:              # inclui PanicException do Polars
        q.put(("err", f"{type(e).__name__}: {str(e).strip()}"))

def run_pl(sql, tables):
    """Executa no Polars em subprocesso, com timeout (como nos runners)."""
    ctxm = mp.get_context("spawn")
    q = ctxm.Queue()
    p = ctxm.Process(target=_pl_worker, args=(sql, tables, q), daemon=True)
    p.start()
    deadline = time.time() + PL_TIMEOUT_S
    try:
        while True:
            try:
                kind, val = q.get(timeout=1)
                break
            except queue.Empty:
                if not p.is_alive():
                    raise PolarsError(f"processo encerrado (código {p.exitcode}; "
                                      "possível falta de memória)")
                if time.time() > deadline:
                    raise PolarsError(f"Timeout: excedeu {PL_TIMEOUT_S} s")
    finally:
        if p.is_alive():
            p.kill()
        p.join()
    if kind == "err":
        raise PolarsError(val)
    return val


# ── Normalização e comparação ────────────────────────────────────────────
def norm(v):
    """Converte valores para tipos comparáveis entre motores."""
    if v is None:
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float, decimal.Decimal)):
        f = float(v)
        return None if math.isnan(f) else f
    if isinstance(v, datetime.datetime):
        if v.tzinfo is not None and v.time() != datetime.time(0):
            v = v.astimezone(datetime.timezone.utc).replace(tzinfo=None)   # timestamptz → UTC
        if v.time() == datetime.time(0):
            return v.date().isoformat()          # DATE_TRUNC → meia-noite = data (com ou sem fuso)
        return v.replace(tzinfo=None).isoformat()
    if isinstance(v, datetime.date):
        return v.isoformat()
    if isinstance(v, str):
        return v.strip()                         # CHAR(n) do PG e respostas do dbgen diferem só em espaços
    return str(v)

def _num(v):
    if isinstance(v, float):
        return v
    try:
        return float(v)
    except (TypeError, ValueError):
        return None

def close(a, b, rel, ab):
    if a is None or b is None:
        return a is None and b is None
    if type(a) is not type(b):              # ex.: '13' (texto) vs 13.0 nas respostas
        fa, fb = _num(a), _num(b)
        if fa is not None and fb is not None:
            return math.isclose(fa, fb, rel_tol=rel, abs_tol=ab)
        return str(a) == str(b)
    if isinstance(a, float) and isinstance(b, float):
        return math.isclose(a, b, rel_tol=rel, abs_tol=ab)
    return a == b

def rows_close(r1, r2, rel, ab):
    return len(r1) == len(r2) and all(
        len(x) == len(y) and all(close(a, b, rel, ab) for a, b in zip(x, y))
        for x, y in zip(r1, r2))

def sort_key(row):
    return tuple((0, "") if v is None else
                 (1, f"{v:.6g}") if isinstance(v, float) else (2, str(v))
                 for v in row)

def compare(ref, got, base_abs=1e-9):
    """Retorna (status, detalhe). base_abs: tolerância absoluta (0,01 p/ respostas oficiais)."""
    ref = [tuple(norm(v) for v in r) for r in ref]
    got = [tuple(norm(v) for v in r) for r in got]
    if len(ref) != len(got):
        return "DIFERENTE", f"linhas: ref={len(ref)} motor={len(got)}"
    if ref and len(ref[0]) != len(got[0]):
        return "DIFERENTE", f"colunas: ref={len(ref[0])} motor={len(got[0])}"
    if rows_close(ref, got, 1e-6, base_abs):
        return "IGUAL", ""
    if rows_close(ref, got, 1e-3, base_abs):
        return "APROX", first_diff(ref, got)
    rs, gs = sorted(ref, key=sort_key), sorted(got, key=sort_key)
    if rows_close(rs, gs, 1e-6, base_abs):
        return "IGUAL_ORDEM", "mesmas linhas em outra ordem"
    if rows_close(rs, gs, 1e-3, base_abs):
        return "APROX", "outra ordem; " + first_diff(rs, gs)
    return "DIFERENTE", first_diff(rs, gs)

def first_diff(r1, r2):
    n = 0; out = []
    for i, (x, y) in enumerate(zip(r1, r2)):
        if not all(close(a, b, 1e-6, 1e-9) for a, b in zip(x, y)):
            out.append(f"linha {i}: ref={x} | motor={y}")
            n += 1
            if n == 3:
                break
    return " || ".join(out)


def read_answer(path):
    """Lê qN.out do dbgen: cabeçalho + linhas separadas por '|'."""
    lines = [l.rstrip("\n") for l in open(path) if l.strip()]
    rows = []
    for l in lines[1:]:
        vals = [v.strip() for v in l.rstrip("|").split("|")]
        row = []
        for v in vals:
            if v in ("", "NULL"):
                row.append(None)
            elif re.fullmatch(r"-?\d+(\.\d+)?", v):
                row.append(float(v))
            else:
                row.append(v)
        rows.append(tuple(row))
    return rows


# ── Programa principal ───────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("suite", choices=["real", "tpch", "tpcds", "clickbench"])
    ap.add_argument("--sf", type=int, default=1, choices=[1, 10, 100])
    ap.add_argument("--queries", help="arquivo .sql alternativo (blocos '-- Qn'), p. ex. "
                    "queries/clickbench/verification_deterministic.sql")
    ap.add_argument("--ref", choices=["postgresql", "duckdb"], default="postgresql",
                    help="referência da comparação; 'duckdb' dispensa o PostgreSQL")
    ap.add_argument("--pgdb", help="nome do banco PostgreSQL (se diferente do padrão)")
    ap.add_argument("--answers", help="pasta answers/ do dbgen (TPC-H SF=1): usa as respostas oficiais como referência")
    args = ap.parse_args()

    RES_DIR.mkdir(exist_ok=True)
    if args.answers and args.suite != "tpch":
        sys.exit("--answers só se aplica ao TPC-H")
    answers = pathlib.Path(args.answers).expanduser() if args.answers else None
    if answers and not (answers / "q1.out").exists():
        sys.exit(f"q1.out não encontrado em {answers}")
    base_abs = 0.01 if answers else 1e-9
    queries, pg, dk, ctx, pl_rewrite = setup(args.suite, args.sf, args.pgdb)
    if args.queries:
        qf = pathlib.Path(args.queries).expanduser()
        if not qf.is_absolute():
            qf = BASE / qf
        parts = re.split(r'--\s*Q(\d+)', qf.read_text())
        queries = {int(parts[i]): parts[i + 1].strip() for i in range(1, len(parts), 2)}
    tag = args.suite if args.suite in ("real", "clickbench") else f"{args.suite}_sf{args.sf}"
    if args.ref == "duckdb" and not answers:
        tag += "_refduckdb"
    if args.queries:
        tag += "_" + pathlib.Path(args.queries).stem
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_csv = RES_DIR / f"equiv_{tag}_{ts}.csv"
    out_txt = RES_DIR / f"equiv_{tag}_{ts}.txt"
    print(f"Suíte {tag}: {len(queries)} consultas | "
          f"duckdb {duckdb.__version__} | polars {pl.__version__}")

    with open(out_csv, "w", newline="") as fc, open(out_txt, "w") as ft:
        w = csv.writer(fc)
        w.writerow(["suite", "query", "engine", "status", "rows", "detail"])
        for q in sorted(queries):
            sql = queries[q]
            res = {}
            runners = {"postgresql": lambda s: run_pg(s, pg),
                       "duckdb": lambda s: run_dk(s, dk),
                       "polars": lambda s: run_pl(pl_rewrite(s), ctx)}
            if answers:
                ref_name = "oficial"
                runners = {"oficial": lambda s, q=q: read_answer(answers / f"q{q}.out"),
                           "duckdb": runners["duckdb"], "polars": runners["polars"]}
            elif args.ref == "duckdb":
                ref_name = "duckdb"
                runners = {"duckdb": runners["duckdb"], "polars": runners["polars"]}
            else:
                ref_name = "postgresql"
            for eng, fn in runners.items():
                try:
                    res[eng] = ("ok", fn(sql))
                except Exception as e:
                    msg = str(e) if isinstance(e, PolarsError) else f"{type(e).__name__}: {str(e).strip()}"
                    msg = msg.replace("\n", " ")[:500]
                    res[eng] = ("err", msg)

            line = [f"Q{q:02d}"]
            ref_ok = res[ref_name][0] == "ok"
            for eng in runners:
                kind, val = res[eng]
                if kind == "err":
                    status, rows, detail = "ERRO", "", val
                elif eng == ref_name:
                    status, rows, detail = "REFERENCIA", len(val), ""
                elif not ref_ok:
                    # sem referência do PG, compara com o DuckDB
                    ref = res.get("duckdb") if eng == "polars" else None
                    if ref and ref[0] == "ok":
                        status, detail = compare(ref[1], val)
                        status += "_vs_DUCKDB"
                    else:
                        status, detail = "SEM_REFERENCIA", ""
                    rows = len(val)
                else:
                    status, detail = compare(res[ref_name][1], val, base_abs)
                    rows = len(val)
                w.writerow([tag, q, eng, status, rows, detail])
                line.append(f"{eng}={status}")
                if detail:
                    ft.write(f"Q{q:02d} {eng} {status}: {detail}\n")
            print("  ".join(line), flush=True)

    print(f"\nResultados: {out_csv}\nDetalhes:   {out_txt}")

if __name__ == "__main__":
    main()
