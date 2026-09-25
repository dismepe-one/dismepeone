# Migração mensal para Render + PostgreSQL — implantação protegida

Situação: **desenvolvimento em branch isolada**, sem publicação na HOME e sem troca do cálculo produtivo.

## Inventário conferido em 24/09/2026

O snapshot MENSAL existente contém dadosVendedores, dadosTelevendas, competencias, regrasPremiacao e diasUteisPorCompetencia. As 76 regras consultadas incluem FATURAMENTO, OBJETIVO, ATINGIMENTO e métricas auxiliares POSITIVACAO_CLIENTES, POSITIVACAO_GERAL, FATURAMENTO_LABORATORIO e PONTUACAO_PRODUTO. A fonte ativa identificada é a planilha de setembro, com abas CAMPANHA VEND e CAMPANHAS TLVS, além de BASE VENDEDOR, BASE TELEVENDAS e BASE FOCO. A fotografia de agosto deve permanecer histórica, sem recomputação por mudança de fontes auxiliares.

## Código criado

- `api/monthly_render_shadow.py`: leitor de fontes em modo somente leitura.
- `api/monthly_awards_engine.py`: porta **parcial** dos cálculos de faixas por faturamento, objetivo e atingimento, com condições de foco e exceções UNIPHAR/ARTE NATIVA. O código não contém endpoints nem chama CACHE_SET.
- `api/monthly_render_parity.py`: comparação bloqueante entre fotografia oficial e candidata, exigindo revisões de fontes iguais e equivalência dos resultados.
- `tests/test_monthly_awards_engine.py`: casos isolados de premiação e rejeição de regras não migradas.

## Bloqueios antes de colocar em produção

1. Implementar e comparar com a mesma revisão de fonte o parser completo das planilhas por competência, normalização do produto foco, faturamento geral e bases históricas.
2. Reproduzir regras especiais e suas fontes auxiliares: GLOBO_CLIENTES, METRICA_GLOBO, HERBAMED_REGRAS, HERB_COM, indicadores manuais HERBAMED, INT_PONTOS e INTEGRAL_PRODUTOS. Não converter indicadores ausentes em zero; preservar comportamento de competência fechada.
3. Reproduzir Resumo de Ganhos, faixas, brindes e ranking, e comparar as premiações por pessoa/laboratório/canal/competência, além de vendas/metas, valores de foco e histórico.
4. Verificar permissões da conta de serviço no Drive; a leitura não deve imprimir chaves, tokens nem dados individuais em logs.
5. Fazer testes de integração e paridade de **todas** as regras com fontes imutáveis e então preparar o worker do Render com trava por competência/revisão, idempotência, gravação atômica validada no PostgreSQL e publicação na HOME apenas após confirmação.
6. Integrar o novo caminho ao botão da Central somente depois de uma aprovação de paridade. Manter rollback e snapshot anterior; nunca repetir o cálculo automaticamente após resultado incerto.

A migração **não está pronta para ativação**. A branch de desenvolvimento foi criada a partir de uma referência anterior à HEAD de main, portanto qualquer integração deve reconciliar primeiro as alterações posteriores de produção.
