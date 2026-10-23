# Resultados do Benchmark

CSVs finais utilizados na dissertação e no artigo:

| Arquivo | Suíte |
|---|---|
| `tpch_sf1_20260929_014656.csv` | TPC-H SF=1 |
| `tpch_sf10_20260929_135434.csv` | TPC-H SF=10 |
| `tpch_sf100_20260929_173811.csv` | TPC-H SF=100 |
| `tpcds_sf1_20261022_221128.csv` | TPC-DS SF=1 |
| `tpcds_sf10_20260930_152117.csv` | TPC-DS SF=10 |
| `clickbench_20260929_231522.csv` | ClickBench |
| `real_20261022_191400.csv` | Dados reais (apenas tempos; o dataset não é distribuído) |

**Repetições:** nos CSVs de TPC-H, TPC-DS e ClickBench, `rep` = 1–4 são as quatro
execuções válidas (o aquecimento não é gravado). No CSV de dados reais, `rep` = 1 é o
aquecimento e deve ser descartado. `elapsed_s = -1` indica falha ou *timeout*.
Ver a seção "Protocolo de repetições" no README principal e `scripts/analyze_results.py`.

**Execução substituída:** `substituidos/real_20260930_204407.csv` é a primeira execução dos
dados reais. Naquela versão, `run_real.py` limpava o page cache com `sudo sh -c`, comando
não liberado sem senha na VM, e não havia como confirmar que a limpeza ocorreu. A suíte foi
reexecutada em 22/10/2026 com a mesma limpeza das demais suítes (`sudo -n tee`), que
interrompe o script em caso de falha. O arquivo antigo é mantido apenas para transparência;
os números publicados vêm de `real_20261022_191400.csv`.

**TPC-DS SF=1 substituído:** `substituidos/tpcds_sf1_20260930_133613.csv` foi medido com 13
das 24 tabelas do PostgreSQL vazias. `scripts/tpcds_sf1_load_fixes/fix_load.py` recriava
essas tabelas e as carregava com `COPY ... FROM '/tmp/...'`, executado pelo processo do
servidor, que não consegue ler o `/tmp` do usuário; a carga falhou sem interromper o script.
O problema foi detectado por `scripts/check_results.py` (o PostgreSQL retornava 0 linhas).
As tabelas foram recarregadas com `scripts/tpcds_sf1_load_fixes/reload_pg_sf1.py`
(contagens conferidas nas 24 tabelas, ver `verificacao/reload_pg_tpcds_sf1_20261022.txt`)
e o SF=1 foi executado novamente em 22/10/2026. DuckDB e Polars não foram afetados.

## Verificação de resultados (`verificacao/`)

Saídas de `scripts/check_results.py`, que executa cada consulta uma vez por motor e compara
os resultados com uma referência (PostgreSQL ou, no TPC-H, as respostas oficiais do
`dbgen`), registrando as mensagens de erro:

| Arquivo | Referência |
|---|---|
| `equiv_real_*.csv/.txt` | PostgreSQL |
| `equiv_tpch_sf1_*.csv/.txt` | respostas oficiais do TPC-H (`dbgen/answers`) |
| `equiv_tpcds_sf1_*.csv/.txt` | PostgreSQL (após a recarga) |
| `equiv_tpcds_sf10_*.csv/.txt` | PostgreSQL |
| `equiv_tpch_sf10_refduckdb_*`, `equiv_tpch_sf100_refduckdb_*` | DuckDB (bancos do PostgreSQL removidos) |
| `equiv_clickbench_refduckdb_2*` | DuckDB (banco do PostgreSQL removido) |
| `equiv_clickbench_refduckdb_verification_deterministic_*` | DuckDB, com as 8 consultas sem resposta única em versão determinística (`queries/clickbench/verification_deterministic.sql`) |
