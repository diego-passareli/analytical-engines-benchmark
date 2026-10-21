-- Q06: Top-20 CIDs com maior impacto financeiro acumulado
-- Padrão: filtro em coluna TEXT + GROUP BY alta cardinalidade + ORDER + LIMIT
SELECT
    cid,
    COUNT(*)                               AS ocorrencias,
    COUNT(DISTINCT sk_beneficiario)        AS pacientes_distintos,
    SUM(valor_pago)                        AS custo_total,
    AVG(valor_pago)                        AS custo_medio_por_registro,
    SUM(valor_pago) / COUNT(DISTINCT sk_beneficiario) AS custo_medio_por_paciente
FROM fato_custo
WHERE cid IS NOT NULL
  AND cid <> ''
GROUP BY 1
ORDER BY 4 DESC
LIMIT 20;
