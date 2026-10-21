-- Exportação anonimizada de dw.fato_custo
-- Executar: psql -U postgres -d DataWarehouse -f export_fato_custo.sql

COPY (
  SELECT
    sk_fato_custos,
    sk_beneficiario,
    sk_prestador_executante,
    sk_prestador_fornecedor,
    sk_prestador_solicitante,
    sk_item,
    sk_unimed_executora,
    sk_unimed_do_usuario,
    guia_nro_ano_solic,
    id_guia,
    id_guia_sequencia,
    tipo_guia,
    data_alta,
    data_competencia,
    data_execucao_procedimento,
    turno_atendimento,
    carater_internacao,
    participacao_profissional,
    autogerado,
    combinado,
    tipo_atendimento,
    tipo_internacao,
    tipo_despesa,
    via_acesso,
    custo_acomodacao,
    internacao,
    sistema_fonte,
    cid,
    valor_pago,
    valor_pago_honor,
    valor_pago_filme,
    valor_pago_co,
    valor_faturado,
    quantidade,
    md5(COALESCE(carteirinha, ''))                       AS carteirinha_hash,
    'PROF_' || md5(COALESCE(profissional_solicitante,'')) AS profissional_hash,
    sk_contrato
  FROM dw.fato_custo
  ORDER BY data_competencia, sk_fato_custos
) TO '/tmp/fato_custo.csv'
WITH (FORMAT CSV, HEADER true, DELIMITER '|', NULL '');
