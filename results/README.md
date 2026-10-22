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
| `real_20260930_204407.csv` | Dados reais (apenas tempos; o dataset não é distribuído) |

**Repetições:** nos CSVs de TPC-H, TPC-DS e ClickBench, `rep` = 1–4 são as quatro
execuções válidas (o aquecimento não é gravado). No CSV de dados reais, `rep` = 1 é o
aquecimento e deve ser descartado. `elapsed_s = -1` indica falha ou *timeout*.
Ver a seção "Protocolo de repetições" no README principal e `scripts/analyze_results.py`.
