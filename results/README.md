# Resultados do Benchmark

CSVs finais utilizados na dissertação e no artigo:

| Arquivo | Suíte |
|---|---|
| `tpch_sf1_20260929_014656.csv` | TPC-H SF=1 |
| `tpch_sf10_20260929_135434.csv` | TPC-H SF=10 |
| `tpch_sf100_20260929_173811.csv` | TPC-H SF=100 |
| `tpcds_sf1_20260930_133613.csv` | TPC-DS SF=1 |
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
