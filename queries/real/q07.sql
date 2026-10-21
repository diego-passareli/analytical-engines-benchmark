-- Q07: Custo acumulado anual por contrato (full-scan + GROUP BY sk_contrato + ano)
-- Padrão: GROUP BY duas chaves numéricas, agregação de valor e contagem
SELECT
    sk_contrato,
    EXTRACT(YEAR FROM data_competencia)    AS ano,
    SUM(valor_pago)                        AS custo_ano,
    SUM(valor_faturado)                    AS faturado_ano,
    COUNT(DISTINCT sk_beneficiario)        AS beneficiarios_ativos,
    COUNT(*)                               AS registros
FROM fato_custo
GROUP BY 1, 2
ORDER BY 1, 2;
