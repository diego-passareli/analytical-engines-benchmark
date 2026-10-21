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
| ClickBench  | 14 GB (~1B linhas) | 43 | PG, DK, PL  |
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
│   ├── run_tpch.py             ← runner TPC-H
│   ├── run_tpcds.py            ← runner TPC-DS (SF como argumento)
│   ├── run_clickbench.py       ← runner ClickBench
│   ├── run_real.py             ← runner dados reais (fato_custo)
│   ├── setup_tpcds.py          ← cria banco PG, DuckDB e Parquet para TPC-DS
│   ├── setup_clickbench.py     ← cria banco PG, DuckDB e Parquet para ClickBench
│   ├── setup_real.py           ← carrega fato_custo.csv em PG, DuckDB e Parquet
│   ├── adapt_tpcds_queries.py  ← adapta queries TPC-DS para os três dialetos SQL
│   └── analyze_results.py      ← lê os CSVs de resultado e gera tabelas/estatísticas
│
├── queries/
│   ├── tpch/                   ← queries TPC-H (adaptadas para PG, DK, PL)
│   ├── tpcds/adapted/          ← queries TPC-DS adaptadas por engine
│   ├── clickbench/             ← queries ClickBench
│   └── real/                   ← q01.sql … q10.sql (dados reais)
│
├── data/                       ← NÃO versionado (gerado pelo setup)
│   ├── tpch/
│   ├── tpcds/
│   ├── clickbench/
│   └── real/
│
└── results/                    ← CSVs de saída de cada execução
    ├── tpch_sf1_TIMESTAMP.csv
    ├── tpch_sf10_TIMESTAMP.csv
    ├── tpcds_sf1_TIMESTAMP.csv
    ├── tpcds_sf10_TIMESTAMP.csv
    ├── clickbench_TIMESTAMP.csv
    └── real_TIMESTAMP.csv
```

## Requisitos

- Ubuntu 22.04 LTS (ou Docker — veja abaixo)
- Python 3.10+
- PostgreSQL 14 rodando localmente (usuário `bench`, senha `bench`, banco criado por setup)
- ~120 GB de espaço em disco para todos os datasets
- Permissão `sudo` sem senha para: `sync; echo 3 > /proc/sys/vm/drop_caches`

## Instalação

```bash
# 1. Clonar o repositório
git clone https://github.com/SEU_USUARIO/bench-analytics.git
cd bench-analytics

# 2. Instalar dependências Python
pip install -r requirements.txt

# 3. Criar usuário e banco no PostgreSQL
sudo -u postgres psql << 'SQL'
  CREATE USER bench WITH PASSWORD 'bench';
  ALTER USER bench CREATEDB;
SQL
```

## Execução

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

### ClickBench

```bash
python scripts/setup_clickbench.py
python scripts/run_clickbench.py
```

### Dados Reais (fato_custo)

```bash
# 1. Exportar e anonimizar do banco de origem (vmdw01)
#    Ver: scripts/export_fato_custo.sql

# 2. Setup no servidor de benchmark
python scripts/setup_real.py

# 3. Executar benchmark
python scripts/run_real.py
```

### Analisar resultados

```bash
# Gera tabelas de estatísticas (mediana, IQR, speedup) a partir dos CSVs
python scripts/analyze_results.py results/tpcds_sf10_*.csv
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
| `rep`         | Número da repetição (1 = warm-up, descartado)    |
| `elapsed_s`   | Tempo de execução em segundos                    |
| `cpu_pct`     | Uso médio de CPU do processo Python (%)          |
| `ram_mb`      | Uso de RAM ao final da execução (MB)             |
| `disk_mb`     | Sempre 0 (não coletado nesta versão)             |
| `energy_kwh`  | Estimativa de energia pelo codecarbon (kWh)      |

> **Atenção:** `energy_kwh` é confiável apenas para DuckDB e Polars (in-process). Para PostgreSQL, use `elapsed_s × TDP_W` como proxy energético. Ver `environment.md`.

## Citação

Se você utilizar este repositório, cite:

```
PASSARELI, Diego Augusto. Análise Comparativa de Engines Analíticos para Pipelines
de Dados em Infraestrutura On-Premise. Dissertação (Mestrado em Informática) —
Universidade Tecnológica Federal do Paraná, Cornélio Procópio, 2026.
```

## Licença

MIT — veja `LICENSE`.
