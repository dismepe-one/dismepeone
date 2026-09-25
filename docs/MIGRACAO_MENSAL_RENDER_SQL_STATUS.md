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

## Primeira auditoria de fontes (sem publicação)

Na competência 09/2026, a leitura conectada do Google Sheets encontrou 335 linhas de vendedores e 315 linhas de televendas, iguais às respectivas quantidades do snapshot no PostgreSQL. A comparação comercial por número de linha detectou **uma única divergência nas vendas dos vendedores** (linha 308 da aba CAMPANHA VEND, célula E308): fonte atual R$ 3.931.852,00; fotografia SQL anterior R$ 3.931,64. A venda vem de XLOOKUP sobre BASE VENDEDOR. O usuário confirmou que a mudança no valor da fonte é real. As demais 649 linhas tinham vendas e objetivos correspondentes no momento da conferência. Isso representa mudança de versão da fonte, e não erro a corrigir substituindo a célula.

O leitor-sombra agora audita objetivos e vendas por linha de origem, reporta divergências de forma agregada sem nomes de colaboradores e revalida a revisão do Google Drive após a leitura. `tests/test_monthly_source_audit.py` contém casos de divergência real, linhas novas, fonte inválida e cabeçalho ambíguo. **Estes testes foram adicionados, mas ainda não foram executados no ambiente Render.** A leitura realizada pelo conector Google Drive não substitui prova de acesso pela Service Account configurada no Render.

**Nunca comparar premiações de revisões diferentes como se fossem uma regressão do motor.** O motor novo deve primeiro ler a mesma revisão de todas as fontes da referência ou comparar contra um cálculo de referência atualizado e imutável; o snapshot anterior é somente linha de base histórica.


## Mapeamento das métricas especiais — 25/09/2026

Foram encontradas cinco regras especiais ativas na competência 09/2026: uma GLOBO (POSITIVACAO_CLIENTES), três HERBAMED (POSITIVACAO_CLIENTES, POSITIVACAO_GERAL, FATURAMENTO_LABORATORIO) e uma BRG/Integral (PONTUACAO_PRODUTO).

Fontes oficiais rastreadas no GS:
- GLOBO: abas `METRICA_GLOBO` (meta individual e prêmio) e `GLOBO_CLIENTES` (cliente único, competência, canal e positivação válida). Linha com cliente/data ausente é ignorada, não contamina toda a base.
- HERBAMED: `HERBAMED_REGRAS`, `HERB_COM` (responsável + competência + canal e cliente único, COD CLIENTE/CNPJ), mais `FATURAMENTO_GERAL_MANUAL` e `POSITIVACAO_GERAL_MANUAL`. Ambos os indicadores manuais existem em `public.dismepe_config` no PostgreSQL. Não inventar zero se o indicador estiver ausente; preservar a leitura por competência e os registros históricos fechados.
- Integral Médica/BRG: `INT_PONTOS` (movimentos faturados por data, canal, SKU, quantidade), `INTEGRAL_PRODUTOS` (pontos por SKU) e `INTEGRAL_FAIXAS` (faixas de premiação). A normalização unifica BRG SUPLEMENTOS e INTEGRALMEDICA. Linhas incompletas devem ser tratadas individualmente conforme a regra de origem, sem zerar indevidamente a base.
- Regras auxiliares ainda necessitam ser reproduzidas fielmente na geração de `metricasParcial`, `metricasDetalhes`, `metricaPendente` e Resumo de Ganhos. Nenhuma regra especial pode ser premiada como zero silenciosamente.

A aba administrativa BASES DISMEPE ONE está acessível via conector Google Drive e contém METRICA_GLOBO (31 linhas), GLOBO_CLIENTES (1044), HERBAMED_REGRAS (3), HERB_COM (1504), INTEGRAL_PRODUTOS (10), INTEGRAL_FAIXAS (4) e INT_PONTOS (345). A conferência de cabeçalhos das sete abas foi positiva. Existem registros incompletos nas fontes GLOBO_CLIENTES e HERB_COM; a validação permite ignorar linhas individualmente, mas rejeita base inteira inválida. Esse teste do conector **não** demonstra acesso pela Service Account em execução no Render.

O módulo `api/monthly_auxiliary_sources.py` realiza validação estrutural e leitura somente-leitura das sete abas pela Service Account; `api/monthly_render_shadow.py` exige `DISMEPE_MONTHLY_AUXILIARY_SHEET_ID` no ambiente de teste e produz somente resumo das fontes e cobertura de regras, sem registrar nomes, documentos ou valores de clientes em logs. O módulo ainda não está instalado no serviço Render de produção, que segue branch main, e tampouco realiza o cálculo integral das métricas especiais.

A validação unitária isolada usa GitHub Actions em `.github/workflows/monthly-shadow-validation.yml` na branch de desenvolvimento. Resultados de CI atestam apenas sintaxe e casos simulados, **não** paridade financeira de todas as premiações nem execução com credenciais no Render. O próximo passo técnico é implementar as fórmulas especiais e ler os indicadores manuais do SQL com controle de revisão, depois comparar fotografias calculadas sobre as mesmas revisões da fonte sem gravar MENSAL/HOME_PUBLICATION.
