-- Q08: Comparação de canais de pagamento — valor pago vs faturado por sistema_fonte e ano
-- Padrão: aritmética entre colunas, GROUP BY multi-coluna, ordenação por diferença
SELECT
    sistema_fonte,
    EXTRACT(YEAR FROM data_competencia)    AS ano,
    SUM(valor_faturado)                    AS total_faturado,
    SUM(valor_pago)                        AS total_pago,
    SUM(valor_faturado - valor_pago)       AS total_glosa,
    ROUND(
        100.0 * SUM(valor_faturado - valor_pago) / NULLIF(SUM(valor_faturado), 0),
        2
    )                                      AS pct_glosa,
    COUNT(*)                               AS registros
FROM fato_custo
GROUP BY 1, 2
ORDER BY 2, 5 DESC;
