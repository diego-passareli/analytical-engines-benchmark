-- Q02: Top-50 prestadores executantes por custo total pago (todos os anos)
-- Padrão: GROUP BY em chave de alta cardinalidade + ORDER BY + LIMIT
SELECT
    sk_prestador_executante,
    SUM(valor_pago)                        AS custo_total,
    SUM(valor_pago_honor)                  AS total_honorarios,
    COUNT(*)                               AS atendimentos,
    COUNT(DISTINCT sk_beneficiario)        AS beneficiarios_distintos
FROM fato_custo
GROUP BY 1
ORDER BY 2 DESC
LIMIT 50;
