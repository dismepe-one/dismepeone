# DISMEPE ONE — integração financeira isolada (ainda não ativada)

**Escopo exclusivo:** premiação mensal. Não instalar/alterar o leitor de vendas,
`MENSAL_COMERCIAL`, a Central de Atualização, a publicação da HOME, horários,
histórico ou cálculos de Campanhas Extras.

**Estado:** o helper `v225_premiacao_sql_source.gs` está versionado e testado na
branch de desenvolvimento, mas **não altera sozinho o motor GS em produção**.
O arquivo do Apps Script atualmente implantado precisa ser identificado e
conferido antes de qualquer edição. Não substituir o Código.gs inteiro por uma
cópia histórica do projeto.

## Localização do motor antigo

No Código.gs legado, `resumoPremiacoesV78_` usa `opCacheContextoMensal_`,
`v210ResumoSomaLabSnapshot_` e `cm171AnotarParciais_`. O resultado mensal se
junta ao resultado de Campanhas Extras em
`resumoPremiacoesCalcularSnapshotV213_`; a fotografia final é gravada por
`v213ResumoSnapshotSalvar_` em `RESUMO_PREMIACOES`.

O cálculo existente lê `MENSAL`, mas a atualização comercial escreve em
`MENSAL_COMERCIAL`. Para preservar toda a lógica de premiação antiga, o
adaptador somente substitui as metas, vendas e flags de Produto Foco **da
competência aberta** antes de chamar o mesmo motor GS. Os dados financeiros
calculados anteriormente não são reaproveitados, e o adaptador não faz gravações.

## Pontos de integração que exigem revisão do Código.gs ATIVO

1. **Dentro apenas de `resumoPremiacoesV78_`**, após a construção de
   `contextoMensalResumo` e antes de obter `regras`, `dv` e `dt`, obter
   `v225PremioContexto_(contextoMensalResumo, competenciaOperacional,
   supabaseV198CacheGet_, cm171AnotarParciais_)`. Se ativo, substituir só a
   variável local `contextoMensalResumo` pela cópia resultante. Em caso de
   divergência de revisão, competência, identidade, linha ou Produto Foco,
   **abortar o novo cálculo**, sem fallback silencioso ao financeiro antigo.
2. Incluir a revisão `fonte.iso` na chave do cache curto do resumo mensal, para
   que uma nova venda não reaproveite o resultado calculado anteriormente.
3. Para o total do laboratório da competência aberta, usar
   `v225PremioSomaLab_(fonte, laboratorioBasePremiacao, normalizar,
   numeroPremiacao)` no lugar exclusivo da soma antiga em
   `v210ResumoSomaLabSnapshot_`. Se a revisão está ativa e o total novo é zero,
   preservar **zero** — nunca usar um total antigo como fallback. Não alterar
   as somas nem a fotografia das competências fechadas.
4. Em `resumoPremiacoesV78_` registrar junto ao resultado a **revisão
   comercial exata utilizada**. Repassar esse metadado somente no fluxo mensal
   por `resumoPremiacoesCalcularSnapshotV213_`, sem alterar o cálculo Extras.
   Imediatamente antes de `v213ResumoSnapshotSalvar_`, executar
   `v225PremioConferirRevisao_` com a revisão utilizada. Se alguma venda,
   competência ou baseline mudou enquanto o motor calculava, **não publicar
   RESUMO_PREMIACOES** e manter a fotografia financeira anterior.
5. Validar paridade financeira (regras comuns, ranking, duplo gatilho de foco,
   métricas especiais GLOBO/HERBAMED/BRG/Integral, agregação por laboratório,
   permissão individual e competências encerradas) usando uma cópia dos
   registros atuais. Em caso de diferença não explicada, não ativar o cálculo
   novo. Publicação é uma etapa separada.

## Evidência de que a integração ainda é necessária

Na verificação de 25/09/2026, `MENSAL_COMERCIAL` tinha vendas diferentes de
`MENSAL` em 119 linhas de Vendedores e 134 de Televendas; os campos de
Produto Foco diferiam em 32 e 30 linhas, respectivamente. O snapshot
`RESUMO_PREMIACOES` foi gravado antes da nova revisão comercial. Logo, a
igualdade de layout e de números na HOME **não comprova paridade de premiações**.

## Verificações antes de instalar no GS

- Confirmar a versão implantada do Código.gs e comparar cada função acima com
  a cópia de referência. Sem confirmação, não realizar substituições.
- Executar a suíte da branch (Node 22) e as métricas de paridade em modo
  somente leitura. Não acionar a Central de Atualização.
- Usar um snapshot de premiações de homologação. Não substituir a tabela
  `RESUMO_PREMIACOES` de produção na primeira execução.
- Confirmar que `MENSAL`, `MENSAL_COMERCIAL` e `HOME_PUBLICATION` não
  mudaram de versão/horário em todo o processo.
- Só então ativar o ponto financeiro no Apps Script; manter backup integral do
  código ativo e uma forma de desabilitar exclusivamente o adaptador.

**Não usar o helper sozinho como prova de cálculo realizado.**
