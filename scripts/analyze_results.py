#!/usr/bin/env python3
"""
analyze_results.py — Análise estatística dos resultados do benchmark analítico.

Lê um ou mais CSVs gerados pelos runners (run_tpch.py, run_tpcds.py,
run_clickbench.py, run_real.py) e produz:
  - Tabela de cobertura por engine (queries OK vs total)
  - Tabela de tempos: mediana e IQR por query e engine
  - Tabela de speedup DuckDB/PostgreSQL por query
  - Resumo agregado por engine (mediana geral, total)
  - Análise energética (estimativa via tempo × TDP)

Uso:
  python analyze_results.py results/tpcds_sf10_*.csv
  python analyze_results.py results/real_*.csv --tdp 270 --tarifa 1.03
"""

import sys
import argparse
import pandas as pd
import numpy as np
from pathlib import Path


# ── Constantes padrão ────────────────────────────────────────────────────────
DEFAULT_TDP_W   = 270      # Xeon Gold 6444Y TDP nominal (W)
DEFAULT_TARIFA  = 1.03     # R$/kWh COPEL c/ ICMS+PIS/COFINS (Paraná, 2026)
DEFAULT_CO2     = 0.0817   # kg CO2e/kWh — fator MCTI 2023
WARMUP_REP      = 1        # repetição descartada (aquecimento)


def load_csv(paths: list[str]) -> pd.DataFrame:
    frames = []
    for p in paths:
        df = pd.read_csv(p)
        df['source_file'] = Path(p).name
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    df['elapsed_s'] = pd.to_numeric(df['elapsed_s'], errors='coerce')
    df['energy_kwh'] = pd.to_numeric(df['energy_kwh'], errors='coerce').fillna(0)
    # Descartar warm-up
    df = df[df['rep'] > WARMUP_REP].copy()
    return df


def cobertura(df: pd.DataFrame) -> pd.DataFrame:
    """Queries concluídas (sem TIMEOUT/ERR) por engine."""
    total_q  = df.groupby('engine')['query'].nunique().rename('total_queries')
    ok_q     = df[df['elapsed_s'].notna()].groupby('engine')['query'].nunique().rename('ok_queries')
    result   = pd.concat([total_q, ok_q], axis=1)
    result['cobertura_pct'] = (result['ok_queries'] / result['total_queries'] * 100).round(1)
    return result.reset_index()


def tempos(df: pd.DataFrame) -> pd.DataFrame:
    """Mediana e IQR de elapsed_s por query e engine (colunas pivotadas)."""
    grp = df.groupby(['query', 'engine'])['elapsed_s'].agg(
        mediana=lambda x: x.median(),
        iqr=lambda x: x.quantile(0.75) - x.quantile(0.25),
        n='count',
    ).reset_index()
    return grp


def speedup_table(df: pd.DataFrame, ref: str = 'postgresql', target: str = 'duckdb') -> pd.DataFrame:
    """Razão de speedup (ref / target) por query."""
    med = df.groupby(['query', 'engine'])['elapsed_s'].median().reset_index()
    ref_df    = med[med['engine'] == ref   ][['query', 'elapsed_s']].rename(columns={'elapsed_s': 'ref_s'})
    target_df = med[med['engine'] == target][['query', 'elapsed_s']].rename(columns={'elapsed_s': 'tgt_s'})
    merged = ref_df.merge(target_df, on='query')
    merged['speedup'] = (merged['ref_s'] / merged['tgt_s']).round(1)
    merged = merged.sort_values('speedup', ascending=False)
    return merged


def resumo_engine(df: pd.DataFrame) -> pd.DataFrame:
    """Mediana geral, total e percentis por engine."""
    return df.groupby('engine')['elapsed_s'].agg(
        mediana_s   ='median',
        p25_s       =lambda x: x.quantile(0.25),
        p75_s       =lambda x: x.quantile(0.75),
        total_s     ='sum',
        n_runs      ='count',
    ).round(3).reset_index()


def energia(df: pd.DataFrame, tdp_w: float, tarifa: float, co2: float) -> pd.DataFrame:
    """Estimativa energética via tempo × TDP (proxy conservador)."""
    agg = df.groupby('engine').agg(
        total_s=('elapsed_s', 'sum'),
        n_runs =('elapsed_s', 'count'),
    ).reset_index()
    agg['energia_mWh']   = (agg['total_s'] * tdp_w / 3600).round(3)
    agg['energia_kWh']   = (agg['energia_mWh'] / 1000).round(6)
    agg['custo_brl']     = (agg['energia_kWh'] * tarifa).round(4)
    agg['co2_g']         = (agg['energia_kWh'] * co2 * 1000).round(4)
    # Razão vs DuckDB (se presente)
    if 'duckdb' in agg['engine'].values:
        dk_e = agg.loc[agg['engine'] == 'duckdb', 'energia_mWh'].values[0]
        agg['razao_vs_duckdb'] = (agg['energia_mWh'] / dk_e).round(1)
    return agg


def print_section(title: str, df: pd.DataFrame):
    print(f"\n{'='*70}")
    print(f"  {title}")
    print('='*70)
    print(df.to_string(index=False))


def main():
    parser = argparse.ArgumentParser(description='Analisa CSVs de benchmark analítico.')
    parser.add_argument('files', nargs='+', help='Arquivos CSV de resultado')
    parser.add_argument('--tdp',    type=float, default=DEFAULT_TDP_W,
                        help=f'TDP do servidor em Watts (padrão: {DEFAULT_TDP_W})')
    parser.add_argument('--tarifa', type=float, default=DEFAULT_TARIFA,
                        help=f'Tarifa elétrica R$/kWh (padrão: {DEFAULT_TARIFA})')
    parser.add_argument('--co2',    type=float, default=DEFAULT_CO2,
                        help=f'Fator de emissão kg CO2e/kWh (padrão: {DEFAULT_CO2})')
    parser.add_argument('--ref',    default='postgresql',
                        help='Engine de referência para speedup (padrão: postgresql)')
    parser.add_argument('--target', default='duckdb',
                        help='Engine alvo para speedup (padrão: duckdb)')
    parser.add_argument('--out',    default=None,
                        help='Salvar resumo em CSV (opcional)')
    args = parser.parse_args()

    print(f"Carregando {len(args.files)} arquivo(s)...")
    df = load_csv(args.files)
    print(f"  {len(df)} linhas carregadas | engines: {sorted(df['engine'].unique())}")
    print(f"  Suite(s): {sorted(df['suite'].unique())} | SF: {sorted(df['sf'].astype(str).unique())}")

    print_section("COBERTURA POR ENGINE", cobertura(df))
    print_section("RESUMO POR ENGINE (mediana, IQR, total)", resumo_engine(df))

    sp = speedup_table(df, ref=args.ref, target=args.target)
    if len(sp):
        print_section(f"SPEEDUP {args.ref.upper()} / {args.target.upper()} (top 20)", sp.head(20))
        print(f"\n  Mediana de speedup: {sp['speedup'].median():.1f}×")
        print(f"  Máximo:             {sp['speedup'].max():.1f}× (Q{sp.loc[sp['speedup'].idxmax(), 'query']})")
        print(f"  Mínimo:             {sp['speedup'].min():.1f}×")
        dk_wins = (sp['speedup'] > 1).sum()
        pg_wins = (sp['speedup'] < 1).sum()
        print(f"  DuckDB vence:       {dk_wins}/{len(sp)} queries")
        print(f"  PostgreSQL vence:   {pg_wins}/{len(sp)} queries")

    eng_df = energia(df, tdp_w=args.tdp, tarifa=args.tarifa, co2=args.co2)
    print_section(
        f"ENERGIA (TDP={args.tdp}W × tempo) | Tarifa R${args.tarifa}/kWh | CO2 {args.co2} kg/kWh",
        eng_df
    )

    # Extrapolação anual (500 consultas/dia)
    print(f"\n── Extrapolação anual @ 500 consultas/dia ──────────────────────────")
    for _, row in eng_df.iterrows():
        e_per_run = row['energia_kWh'] / row['n_runs'] if row['n_runs'] else 0
        anual_kwh = e_per_run * 500 * 365
        print(f"  {row['engine']:12s}: {anual_kwh:.3f} kWh/ano | "
              f"R$ {anual_kwh * args.tarifa:.2f}/ano | "
              f"{anual_kwh * args.co2:.3f} kg CO2e/ano")

    if args.out:
        resumo_engine(df).to_csv(args.out, index=False)
        print(f"\nResumo salvo em: {args.out}")


if __name__ == '__main__':
    main()
