# Migração completa: Campanhas Mensais -> Render/PostgreSQL

Status: **em desenvolvimento, não ativada em produção**. Este documento é o contrato de aceitação para retirar o Google Apps Script do processamento mensal. Não confundir snapshots existentes no PostgreSQL com cálculo independente.

## Fonte de verdade e dependências identificadas no GS V219

- Competência, estado, agendamento, linkDrive e dias úteis: `CM_COMPETENCIAS`. Competência aberta usa estritamente seu próprio `LINK_DRIVE`; competência fechada usa fotografia imutável. Nunca herdar indicadores ou métricas de outro mês.
- Vendas/metas atuais: Google Sheets do link da competência, abas `CAMPANHA VEND` e `CAMPANHAS TLVS`. Para BIOLAB, a venda de vendedores é recomposta por fornecedor usando `BASE VENDEDOR`; validar linhas de produto foco, descrições e variações de fornecedor. A fonte também pode conter `BASE TELEVENDAS` e `BASE FOCO`.
- Regras por competência, canal e laboratório: `CM_REGRAS_METRICAS`. Preservar faixas, tipos (fixo, percentual da venda/objetivo, brinde, ranking), competência, prioridade de canal, exigência de foco, gatilho de faturamento/pontuação geral e vigência. Não usar a regra de outra competência como fallback.
- Premiações especiais: `METRICA_GLOBO`, `GLOBO_CLIENTES`, `HERBAMED_REGRAS`, `HERB_COM`, `INTEGRAL_PRODUTOS`, `INTEGRAL_FAIXAS`, `INT_PONTOS`, indicadores gerais e respectivas revisões. `HERB_COM` tem fallback na planilha vinculada apenas quando ausente da administrativa; não somar duas bases. Linhas incompletas devem ser descartadas conforme a regra específica e não zerar a campanha inteira.
- Regras históricas e pontuais no GS: dupla condição objetivo + produto foco; ARTE NATIVA 08/2026 por objetivo individual; UNIPHAR por faixa do OBJETIVO; reagrupamento Integral/BRG e laboratórios equivalentes; regras especiais de positividade, faturamento geral e pontos por SKU. Preservar textos `Pendente` e tipos de prêmio não monetários.
- Premiações e fechamento: verificar rotina de `Resumo de Ganhos`, histórico e competências fechadas; não recalcular competência encerrada a partir da fonte corrente.

## Implementação de produção (não foi feita ainda)

1. Render lê todas as bases necessárias pela conta de serviço em modo leitura; nenhuma chamada ao `OPCACHE_ATUALIZAR`, `DADOS` ou worker Apps Script no novo caminho.
2. PostgreSQL registra fontes com competência, revisão, hash, horário e dados de auditoria suficientes. Leitura e cálculo usam um mesmo conjunto de revisões; se qualquer fonte mudar no meio, abortar e retentar novo trabalho, sem mesclar versões.
3. Motor Render calcula os registros de vendedores e televendas, regras normais e especiais; `SEM_DADO` e `PENDENTE` são estados distintos de premiação zero. O banco armazena os resultados e as bases utilizadas, com escopo de acesso por usuário.
4. Estado durável e idempotente por pedido: `AGENDADO -> PROCESSANDO -> VALIDADO -> PUBLICADO`, além de `SEM_MUDANCA` e `ERRO`. Identificar execução interrompida sem reenviar automaticamente cálculo incerto.
5. Validar equivalência na MESMA revisão de cada fonte: vendas, metas, objetivos/vendas de foco, todos os componentes de prêmio, regras especiais, colaboradores, canais, competência, totais e histórico. Cobrir casos de `#REF!`, ausência de dados e congelamento. Divergência bloqueia publicação.
6. Com equivalência comprovada, gravar snapshot validado e atualizar HOME de forma atômica/idempotente. Sem mudança comercial: informar 'Você já está na última versão atualizada', preservando horário, histórico e notificações.
7. Habilitar o motor novo por flag exclusivamente administrativa e com rollback. Migrar leitura/edição de regras, gestão mensal e resumo de ganhos para PostgreSQL antes de retirar de fato o Apps Script; desativar o legado somente após teste completo em produção.

## Lacunas verificadas em 24/09/2026

- `dismepe_cache_operacional.MENSAL` já guarda resultados calculados, mas isto **não** equivale a guardar todas as entradas independentes nem prova que o cálculo pode ser reproduzido no Render.
- `dismepe_cm_base_mensal` contém apenas registro de acompanhamento de 08/2026 na consulta realizada; não é a base oficial completa atual.
- A branch experimental `feature/monthly-render-shadow-20260924` lê as duas abas de vendas e compara contagens, sem cálculo de premiação, sem acesso validado a todas as bases auxiliares e sem publicação.
- O fluxo produtivo continua utilizando Apps Script enquanto a paridade integral estiver pendente; esta branch não muda esse comportamento.

Critério de aceite: demonstrar que a atualização do MENSAL, a gestão das regras, os indicadores complementares, o Resumo de Ganhos e a publicação do histórico funcionam sem qualquer solicitação ao Apps Script e reproduzem os resultados anteriores sobre fontes idênticas. **Não ativar antes disso.**
