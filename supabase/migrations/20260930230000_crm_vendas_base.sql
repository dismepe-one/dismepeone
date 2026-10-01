-- DISMEPE ONE — CRM / Inteligência Comercial
-- Somente camada de dados; nenhuma tela ou comportamento existente é alterado.

create table if not exists public.dismepe_crm_importacoes (
    id uuid primary key default gen_random_uuid(),
    nome_arquivo text not null,
    periodo_inicio date,
    periodo_fim date,
    linhas_lidas integer not null default 0,
    linhas_inseridas integer not null default 0,
    status text not null default 'EM_ANDAMENTO'
        check (status in ('EM_ANDAMENTO','CONCLUIDA','CONCLUIDA_COM_ERROS','ERRO')),
    criado_em timestamptz not null default now(),
    criado_por text not null default '',
    observacao text not null default ''
);

alter table public.dismepe_crm_importacoes enable row level security;

create table if not exists public.dismepe_crm_vendas (
    id bigint generated always as identity primary key,
    importacao_id uuid references public.dismepe_crm_importacoes(id),
    data_venda date not null,
    numero_nf bigint not null,
    cod_cliente bigint not null,
    cod_produto bigint not null,
    total_unidade numeric(18,3) not null,
    venda_liquida numeric(18,2) not null,
    fornecedor text not null default '',
    chave_origem text not null,
    origem_arquivo text not null default '',
    criado_em timestamptz not null default now()
);

alter table public.dismepe_crm_vendas enable row level security;

-- A NF pode se repetir em datas diferentes. A combinação data + NF + cliente + produto
-- foi validada na base recebida e não apresentou duplicidade.
create unique index if not exists dismepe_crm_vendas_chave_origem_uidx
    on public.dismepe_crm_vendas(chave_origem);

create unique index if not exists dismepe_crm_vendas_natural_key_uidx
    on public.dismepe_crm_vendas(data_venda, numero_nf, cod_cliente, cod_produto);

create index if not exists dismepe_crm_vendas_data_idx
    on public.dismepe_crm_vendas(data_venda);

create index if not exists dismepe_crm_vendas_cliente_data_idx
    on public.dismepe_crm_vendas(cod_cliente, data_venda desc);

create index if not exists dismepe_crm_vendas_produto_data_idx
    on public.dismepe_crm_vendas(cod_produto, data_venda desc);

create index if not exists dismepe_crm_vendas_fornecedor_data_idx
    on public.dismepe_crm_vendas(fornecedor, data_venda desc);

create index if not exists dismepe_crm_vendas_cliente_produto_idx
    on public.dismepe_crm_vendas(cod_cliente, cod_produto);

create index if not exists dismepe_crm_vendas_produto_fornecedor_idx
    on public.dismepe_crm_vendas(cod_produto, fornecedor);

create index if not exists dismepe_crm_vendas_importacao_idx
    on public.dismepe_crm_vendas(importacao_id);
