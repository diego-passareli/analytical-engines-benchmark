# Benchmark Analítico On-Premise: PostgreSQL × DuckDB × Polars

Repositório de suporte à dissertação de mestrado:

> **Análise Comparativa de Engines Analíticos para Pipelines de Dados em Infraestrutura On-Premise**
> Diego Augusto Passareli — PPGI/UTFPR-CP (2026)

## Visão Geral

Este repositório contém todos os scripts de setup, execução e análise utilizados para comparar PostgreSQL 14.24, DuckDB 1.5.6 e Polars 1.44.2 em quatro suítes de benchmark executadas em infraestrutura on-premise de médio porte.

| Suíte       | Volume       | Queries | Engines        |
|-------------|--------------|---------|----------------|
| TPC-H       | SF=1/10/100  | 22      | PG, DK, PL     |
| TPC-DS      | SF=1/10      | 99      | PG, DK, PL     |
| ClickBench  | 14 GB Parquet / 100M linhas | 43 | PG, DK, PL |
| Dados Reais | 29M linhas / 668 MB Parquet | 10 | PG, DK, PL |

## Estrutura do Repositório

```
.
├── README.md                   ← este arquivo
├── requirements.txt            ← dependências Python (versões exatas)
├── Dockerfile                  ← ambiente reproduzível
├── environment.md              ← especificação de hardware e SO
│
├── scripts/
│   ├── run_tpch.py             ← runner TPC-H SF=1 e SF=10 (timeout PG 100 s)
│   ├── run_tpch_sf100.py       ← runner TPC-H SF=100 (timeout PG 270 s, Polars 300 s)
│   ├── run_tpcds.py            ← runner TPC-DS (SF como argumento)
│   ├── run_clickbench.py       ← runner ClickBench
│   ├── run_real.py             ← runner dados reais (fato_custo)
│   ├── setup_tpch.py           ← gera (dbgen) e carrega TPC-H em PG, DuckDB e Parquet
│   ├── setup_tpcds.py          ← cria banco PG, DuckDB e Parquet para TPC-DS
│   ├── setup_clickbench.py     ← cria banco PG, DuckDB e Parquet para ClickBench
│   ├── setup_real.py           ← carrega fato_custo.csv em PG, DuckDB e Parquet
│   ├── adapt_tpcds_queries.py  ← adapta queries TPC-DS (TOP N → LIMIT N, remove comentários)
│   ├── create_queries.sh       ← cria as 10 queries de dados reais em scripts/queries/real
│   ├── hits_pg.ddl             ← DDL da tabela hits (ClickBench) no PostgreSQL
│   ├── tpcds_sf1_load_fixes/   ← correções de carga do TPC-DS SF=1, incl. reload_pg_sf1.py (ver abaixo)
│   ├── analyze_results.py      ← lê os CSVs de resultado e gera tabelas/estatísticas
│   └── check_results.py        ← verifica se os motores retornam os mesmos resultados
│
├── queries/
│   ├── tpch/queries.sql        ← 22 queries TPC-H
│   ├── tpcds/                  ← 99 queries TPC-DS geradas pelo dsqgen
│   ├── tpcds/adapted/          ← as mesmas 99 após adapt_tpcds_queries.py (usadas pelo runner)
│   ├── export_fato_custo.sql   ← extração anonimizada da tabela real (executada no DW)
│   ├── clickbench/queries.sql  ← 43 queries ClickBench
│   └── real/                   ← q01.sql … q10.sql (dados reais; o runner as lê de
│                                  ~/bench/scripts/queries/real)
│
├── data/                       ← NÃO versionado (gerado pelo setup)
│   ├── tpch/
│   ├── tpcds/
│   ├── clickbench/
│   └── real/
│
└── results/                    ← CSVs finais usados na dissertação e no artigo
    ├── tpch_sf1_20260929_014656.csv
    ├── tpch_sf10_20260929_135434.csv
    ├── tpch_sf100_20260929_173811.csv
    ├── tpcds_sf1_20261022_221128.csv
    ├── tpcds_sf10_20260930_152117.csv
    ├── clickbench_20260929_231522.csv
    ├── real_20261022_191400.csv
    ├── substituidos/           ← execuções descartadas (ver results/README.md)
    └── verificacao/            ← saídas de check_results.py e da recarga do TPC-DS SF=1
```

## Requisitos

- Ubuntu 22.04 LTS (ou Docker — veja abaixo)
- Python 3.10+
- PostgreSQL 14 rodando localmente (usuário `bench`, senha `bench`, banco criado por setup)
- ~120 GB de espaço em disco para todos os datasets
- Permissão `sudo` sem senha para `tee /proc/sys/vm/drop_caches` (ex.: `/etc/sudoers.d/drop_caches` com `usuario ALL=(root) NOPASSWD: /usr/bin/tee /proc/sys/vm/drop_caches`)

## Instalação

```bash
# 1. Clonar o repositório
git clone https://github.com/diego-passareli/analytical-engines-benchmark.git
cd analytical-engines-benchmark

# 2. Instalar dependências Python
pip install -r requirements.txt

# 3. Criar usuário e banco no PostgreSQL
sudo -u postgres psql << 'SQL'
  CREATE USER bench WITH PASSWORD 'bench';
  ALTER USER bench CREATEDB;
SQL
```

## Execução

### TPC-H

```bash
# Setup: gera os dados com dbgen (TPC-H 2.14.0) e carrega PG, DuckDB e Parquet
# (consolida os comandos usados na carga original; ver docstring do script)
python scripts/setup_tpch.py --sf 1      # e --sf 10, --sf 100

python scripts/run_tpch.py --sf 1
python scripts/run_tpch.py --sf 10
python scripts/run_tpch_sf100.py --sf 100   # mesmo runner, timeouts maiores
```

### TPC-DS

```bash
# Setup (SF=1): cria banco PG, DuckDB e Parquet
python scripts/setup_tpcds.py 1

# Benchmark SF=1
python scripts/run_tpcds.py 1

# Benchmark SF=10 (requer setup separado)
python scripts/setup_tpcds.py 10
python scripts/run_tpcds.py 10
```

### Correções de carga do TPC-DS SF=1

Os arquivos gerados pelo `dsdgen` terminam cada linha com `|` e algumas tabelas
apresentaram divergência no número de colunas. Os scripts em
`scripts/tpcds_sf1_load_fixes/` (`fix_duckdb.py`, `fix_load.py`, `final_fix.py`)
foram usados para recarregar essas tabelas no PostgreSQL e no DuckDB e regenerar os
arquivos Parquet do SF=1. A versão final de `setup_tpcds.py` já incorpora o
tratamento do `|` final.

**Atenção:** no PostgreSQL, a carga de `fix_load.py` falhou (o `COPY` do lado do servidor
não lê arquivos em `/tmp` do usuário) e deixou 13 tabelas vazias. Depois de rodar os
scripts acima, execute `reload_pg_sf1.py`, que recarrega essas tabelas a partir do DuckDB
com `COPY FROM STDIN`, recria os índices e confere as contagens das 24 tabelas.

### Verificação de resultados

```bash
python scripts/check_results.py real
python scripts/check_results.py tpch --sf 1 --answers ~/tpch-dbgen/answers
python scripts/check_results.py tpcds --sf 1
```

### ClickBench

```bash
python scripts/setup_clickbench.py
python scripts/run_clickbench.py
```

### Dados Reais (fato_custo)

```bash
# 1. Exportar e anonimizar do banco de origem (vmdw01)
#    Ver: queries/export_fato_custo.sql — carteirinha e profissional solicitante
#    são substituídos por hashes MD5 antes da exportação. O dataset real NÃO é
#    distribuído; apenas os tempos de execução estão em results/.

# 2. Setup no servidor de benchmark
python scripts/setup_real.py

# 3. Executar benchmark
python scripts/run_real.py
```

### Analisar resultados

```bash
# Gera tabelas de estatísticas (mediana, IQR, speedup) a partir dos CSVs
python scripts/analyze_results.py results/tpcds_sf10_20260930_152117.csv
python scripts/analyze_results.py results/real_20261022_191400.csv
```

## Protocolo de repetições (importante para reanalisar os CSVs)

Cada query foi executada **5 vezes** por engine; a 1ª execução (aquecimento) é descartada
e a métrica reportada é a **mediana das 4 execuções seguintes**.

- `run_tpch.py`, `run_tpcds.py` e `run_clickbench.py` **não gravam** o aquecimento:
  os CSVs dessas suítes contêm apenas as 4 execuções válidas, numeradas `rep` = 1–4.
- `run_real.py` grava as 5 execuções: no CSV de dados reais, `rep` = 1 é o aquecimento.
- Execuções com falha ou *timeout* são gravadas com `elapsed_s = -1`; o par
  (engine, query) é então tratado como não concluído.

`analyze_results.py` já aplica essas regras.
```

## Com Docker

```bash
docker build -t bench-analytics .

# Exemplo: rodar TPC-DS SF=1 com PostgreSQL no host
docker run --rm \
  -v $(pwd)/results:/bench/results \
  -v $(pwd)/data:/bench/data \
  -e PGHOST=host.docker.internal \
  bench-analytics \
  python scripts/run_tpcds.py 1
```

## Formato dos Resultados

Cada execução gera um CSV com as colunas:

| Coluna        | Descrição                                         |
|---------------|---------------------------------------------------|
| `engine`      | `postgresql`, `duckdb` ou `polars`               |
| `suite`       | `tpch`, `tpcds`, `clickbench` ou `real`          |
| `sf`          | Fator de escala (`1`, `10`, `100` ou `real`)     |
| `query`       | Número da query (1–99 para TPC-DS)               |
| `rep`         | Repetição (ver "Protocolo de repetições" acima) |
| `elapsed_s`   | Tempo de execução em segundos (-1 = falha/timeout) |
| `cpu_pct`     | Uso médio de CPU do processo Python (%)          |
| `ram_mb`      | Uso de RAM ao final da execução (MB)             |
| `disk_mb`     | I/O de disco (MB); 0 no runner de dados reais     |
| `energy_kwh`  | Estimativa de energia pelo codecarbon (kWh)      |

> **Atenção:** `energy_kwh` (codecarbon, modo processo) só reflete o trabalho do DuckDB, que roda dentro do processo Python. PostgreSQL (servidor separado) e Polars (subprocesso) são subestimados. As comparações de energia da dissertação e do artigo usam `elapsed_s × 270 W` (TDP) como proxy. Ver `environment.md`.

## Citação

Se você utilizar este repositório, cite:

```
PASSARELI, Diego Augusto. Análise Comparativa de Engines Analíticos para Pipelines
de Dados em Infraestrutura On-Premise. Dissertação (Mestrado em Informática) —
Universidade Tecnológica Federal do Paraná, Cornélio Procópio, 2026.
```

## Licença

MIT — veja `LICENSE`.
