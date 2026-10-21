-- Q04: Análise de internações — custo médio e total por caráter e tipo
-- Padrão: filtro seletivo (internacao = 'SIM') + GROUP BY + COUNT DISTINCT
SELECT
    carater_internacao,
    tipo_internacao,
    custo_acomodacao,
    COUNT(DISTINCT sk_beneficiario)        AS pacientes,
    COUNT(*)                               AS registros,
    SUM(valor_pago)                        AS custo_total,
    AVG(valor_pago)                        AS custo_medio,
    SUM(valor_pago_filme)                  AS total_filme,
    SUM(valor_pago_co)                     AS total_co
FROM fato_custo
WHERE internacao = 'SIM'
GROUP BY 1, 2, 3
ORDER BY 6 DESC;
