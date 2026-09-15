-- DISMEPE ONE 2.0 — FASE 1
-- DIAGNÓSTICO SOMENTE LEITURA. NÃO ALTERA NADA.
-- Execute no SQL Editor do Supabase e guarde o resultado para a Fase 1B.

select
  table_schema,
  table_name
from information_schema.tables
where table_schema = 'public'
  and table_name in (
    'dismepe_usuarios',
    'dismepe_permissoes'
  )
order by table_name;

select
  table_name,
  column_name,
  data_type,
  is_nullable
from information_schema.columns
where table_schema = 'public'
  and table_name in (
    'dismepe_usuarios',
    'dismepe_permissoes'
  )
order by table_name, ordinal_position;

select
  count(*) as usuarios_total
from public.dismepe_usuarios;

select
  count(*) as permissoes_total
from public.dismepe_permissoes;
