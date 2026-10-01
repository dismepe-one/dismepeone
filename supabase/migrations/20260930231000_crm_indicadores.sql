-- DISMEPE ONE — CRM / Inteligência Comercial
-- Indicadores preliminares. Não cria telas e não altera módulos existentes.

create or replace view public.dismepe_crm_produtos_desempenho as
with p as (
    select
        max(data_venda)::date as data_ref,
        date_trunc('month', max(data_venda))::date as mes_atual,
        extract(day from max(data_venda))::int as dia_corte
    from public.dismepe_crm_vendas
),
base as (
    select
        v.cod_produto,
        sum(v.venda_liquida) / 3.0 as venda_base,
        sum(v.total_unidade) / 3.0 as unidades_base,
        count(distinct v.cod_cliente)::numeric / 3.0 as clientes_base
    from public.dismepe_crm_vendas v
    cross join p
    where v.data_venda >= (p.mes_atual - interval '3 months')::date
      and v.data_venda < p.mes_atual
      and extract(day from v.data_venda) <= p.dia_corte
    group by v.cod_produto
),
atual as (
    select
        v.cod_produto,
        sum(v.venda_liquida) as venda_atual,
        sum(v.total_unidade) as unidades_atual,
        count(distinct v.cod_cliente) as clientes_atual
    from public.dismepe_crm_vendas v
    cross join p
    where v.data_venda >= p.mes_atual
      and v.data_venda <= p.data_ref
    group by v.cod_produto
),
ultima as (
    select cod_produto, max(data_venda)::date as ultima_venda
    from public.dismepe_crm_vendas
    group by cod_produto
)
select
    coalesce(b.cod_produto,a.cod_produto) as cod_produto,
    coalesce(b.venda_base,0) as venda_base,
    coalesce(a.venda_atual,0) as venda_atual,
    coalesce(b.unidades_base,0) as unidades_base,
    coalesce(a.unidades_atual,0) as unidades_atual,
    coalesce(b.clientes_base,0) as clientes_base,
    coalesce(a.clientes_atual,0) as clientes_atual,
    case when coalesce(b.venda_base,0) <> 0
        then round(((coalesce(a.venda_atual,0) / b.venda_base) - 1) * 100, 1)
    end as variacao_venda_pct,
    case when coalesce(b.unidades_base,0) <> 0
        then round(((coalesce(a.unidades_atual,0) / b.unidades_base) - 1) * 100, 1)
    end as variacao_unidades_pct,
    coalesce(a.venda_atual,0) - coalesce(b.venda_base,0) as perda_venda,
    coalesce(a.unidades_atual,0) - coalesce(b.unidades_base,0) as perda_unidades,
    u.ultima_venda,
    (p.data_ref - u.ultima_venda) as dias_sem_venda
from base b
full join atual a on a.cod_produto=b.cod_produto
left join ultima u on u.cod_produto=coalesce(b.cod_produto,a.cod_produto)
cross join p;

create or replace view public.dismepe_crm_clientes_desempenho as
with p as (
    select
        max(data_venda)::date as data_ref,
        date_trunc('month', max(data_venda))::date as mes_atual,
        extract(day from max(data_venda))::int as dia_corte
    from public.dismepe_crm_vendas
),
base as (
    select
        v.cod_cliente,
        sum(v.venda_liquida) / 3.0 as venda_base,
        sum(v.total_unidade) / 3.0 as unidades_base
    from public.dismepe_crm_vendas v
    cross join p
    where v.data_venda >= (p.mes_atual - interval '3 months')::date
      and v.data_venda < p.mes_atual
      and extract(day from v.data_venda) <= p.dia_corte
    group by v.cod_cliente
),
atual as (
    select
        v.cod_cliente,
        sum(v.venda_liquida) as venda_atual,
        sum(v.total_unidade) as unidades_atual
    from public.dismepe_crm_vendas v
    cross join p
    where v.data_venda >= p.mes_atual
      and v.data_venda <= p.data_ref
    group by v.cod_cliente
),
ultima as (
    select cod_cliente, max(data_venda)::date as ultima_compra
    from public.dismepe_crm_vendas
    group by cod_cliente
)
select
    coalesce(b.cod_cliente,a.cod_cliente) as cod_cliente,
    coalesce(b.venda_base,0) as venda_base,
    coalesce(a.venda_atual,0) as venda_atual,
    coalesce(b.unidades_base,0) as unidades_base,
    coalesce(a.unidades_atual,0) as unidades_atual,
    case when coalesce(b.venda_base,0) <> 0
        then round(((coalesce(a.venda_atual,0) / b.venda_base) - 1) * 100, 1)
    end as variacao_venda_pct,
    case when coalesce(b.unidades_base,0) <> 0
        then round(((coalesce(a.unidades_atual,0) / b.unidades_base) - 1) * 100, 1)
    end as variacao_unidades_pct,
    coalesce(a.venda_atual,0) - coalesce(b.venda_base,0) as perda_venda,
    coalesce(a.unidades_atual,0) - coalesce(b.unidades_base,0) as perda_unidades,
    u.ultima_compra,
    (p.data_ref - u.ultima_compra) as dias_sem_compra
from base b
full join atual a on a.cod_cliente=b.cod_cliente
left join ultima u on u.cod_cliente=coalesce(b.cod_cliente,a.cod_cliente)
cross join p;

create or replace view public.dismepe_crm_fornecedores_desempenho as
with p as (
    select
        max(data_venda)::date as data_ref,
        date_trunc('month', max(data_venda))::date as mes_atual,
        extract(day from max(data_venda))::int as dia_corte
    from public.dismepe_crm_vendas
),
base as (
    select
        v.fornecedor,
        sum(v.venda_liquida) / 3.0 as venda_base,
        sum(v.total_unidade) / 3.0 as unidades_base,
        count(distinct v.cod_cliente)::numeric / 3.0 as clientes_base,
        count(distinct v.cod_produto)::numeric / 3.0 as produtos_base
    from public.dismepe_crm_vendas v
    cross join p
    where v.data_venda >= (p.mes_atual - interval '3 months')::date
      and v.data_venda < p.mes_atual
      and extract(day from v.data_venda) <= p.dia_corte
    group by v.fornecedor
),
atual as (
    select
        v.fornecedor,
        sum(v.venda_liquida) as venda_atual,
        sum(v.total_unidade) as unidades_atual,
        count(distinct v.cod_cliente) as clientes_atual,
        count(distinct v.cod_produto) as produtos_atual
    from public.dismepe_crm_vendas v
    cross join p
    where v.data_venda >= p.mes_atual
      and v.data_venda <= p.data_ref
    group by v.fornecedor
)
select
    coalesce(b.fornecedor,a.fornecedor) as fornecedor,
    coalesce(b.venda_base,0) as venda_base,
    coalesce(a.venda_atual,0) as venda_atual,
    coalesce(b.unidades_base,0) as unidades_base,
    coalesce(a.unidades_atual,0) as unidades_atual,
    coalesce(b.clientes_base,0) as clientes_base,
    coalesce(a.clientes_atual,0) as clientes_atual,
    coalesce(b.produtos_base,0) as produtos_base,
    coalesce(a.produtos_atual,0) as produtos_atual,
    case when coalesce(b.venda_base,0) <> 0
        then round(((coalesce(a.venda_atual,0) / b.venda_base) - 1) * 100, 1)
    end as variacao_venda_pct,
    case when coalesce(b.unidades_base,0) <> 0
        then round(((coalesce(a.unidades_atual,0) / b.unidades_base) - 1) * 100, 1)
    end as variacao_unidades_pct,
    coalesce(a.venda_atual,0) - coalesce(b.venda_base,0) as perda_venda
from base b
full join atual a on a.fornecedor=b.fornecedor;

create or replace view public.dismepe_crm_produtos_parados as
select *
from public.dismepe_crm_produtos_desempenho
where venda_base >= 500
  and dias_sem_venda >= 30;

create or replace view public.dismepe_crm_clientes_em_risco as
select *
from public.dismepe_crm_clientes_desempenho
where venda_base >= 500
  and dias_sem_compra >= 30;
