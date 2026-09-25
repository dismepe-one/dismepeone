# Homologação mensal no Render — preparação segura

Ambiente de testes: `dismepeone-mensal-homolog`. O serviço oficial `dismepeone` (branch main) não deve receber estas configurações.

## Comando preparado (não executa publicação)

```bash
python -m api.monthly_homologation_cli
```

O comando lê somente a fotografia MENSAL e os dois indicadores manuais da base SQL, lê as planilhas pelo Google Drive e produz um relatório agregado. Não aciona CACHE_SET, não grava MENSAL, HOME_PUBLICATION ou RESUMO_PREMIACOES e não dispara o Apps Script. O comando **não está disponível como botão ou endpoint HTTP**. O serviço Render gratuito atual não disponibiliza execução interativa de comandos pelo conector; a invocação real exige um executor privado com as credenciais de leitura devidamente configuradas. NÃO trocar o startCommand do serviço público pelo CLI.

## Variáveis de configuração do serviço de homologação

- `DISMEPE_MONTHLY_HOMOLOGATION=1`
- `DISMEPE_MONTHLY_WRITE_ENABLED=0`
- `DISMEPE_MONTHLY_AUXILIARY_SHEET_ID`: ID da planilha administrativa. Este identificador não é uma credencial.
- `DISMEPE_MONTHLY_READONLY_DATABASE_URL`: endereço de conexão de **usuário exclusivo de homologação**, com SELECT restrito às colunas necessárias das tabelas dismepe_cache_operacional e dismepe_config. NÃO copiar o URL administrador, a service_role ou a senha do banco de produção para esta variável.
- `DISMEPE_GOOGLE_SERVICE_ACCOUNT_B64`: conta de serviço **separada**, compartilhada como leitora somente das planilhas mensal e administrativa. Nunca colocar o JSON, chave privada, token ou URI de conexão em arquivo Git ou em mensagens.
- Não instalar `DISMEPE_EDGE_TOKEN` ou credenciais com permissão de escrita no serviço de homologação.

O código usa transação SQL `BEGIN READ ONLY` e consulta apenas `MENSAL` e os indicadores manuais. A proteção efetiva exige que o administrador crie e configure credenciais cuja identidade no PostgreSQL tenha apenas SELECT e que a conta de serviço tenha apenas permissão de leitura no Drive. Estas duas credenciais **ainda não foram configuradas** no serviço de homologação.

## Etapas para a primeira execução

1. Criar credenciais separadas de leitura e restringir o acesso à planilha e às tabelas acima. Não usar as credenciais do serviço oficial.
2. Configurar somente essas credenciais no painel privado do Render. Confirmar que os valores não aparecem nos logs ou no GitHub.
3. Preparar um executor privado de execução única que invoque `python -m api.monthly_homologation_cli`, sem rota pública de disparo. No serviço gratuito de homologação publicado neste momento, a rota /health indica apenas que o servidor subiu; NÃO significa que o cálculo real foi executado.
4. Conferir registros válidos, linhas divergentes entre fonte viva e snapshot anterior, componentes especiais pendentes e ausência de autorização para publicar.
5. Para paridade financeira, calcular todos os campos e o Resumo de Ganhos com a MESMA revisão das fontes do cálculo de referência; contagens e prévia dos especiais não substituem essa prova.

Não realizar merge em main nem acionar deploy do serviço de produção até que os bloqueios de paridade sejam resolvidos.


## Estado efetivamente configurado após a primeira implantação

- Views exclusivas `dismepe_monthly_homolog.monthly_snapshot` e `dismepe_monthly_homolog.manual_indicators` criadas; SELECT concedido ao papel `dismepe_monthly_homolog_ro`.
- Login independente `dismepe_monthly_homolog_login` criado com privilégio de leitura herdado, sem permissão nas duas tabelas públicas originais e sem permissão de escrita nas views. A credencial foi instalada diretamente na variável privada do serviço de homologação, sem ser exibida.
- A tentativa de conexão do Render ao host direto `db.[ref].supabase.co:5432` falhou com `OperationalError`. O serviço oficial não foi alterado. O Render não suporta conexão direta IPv6 em condições comuns; o próximo teste requer o host **exato** do pooler em modo sessão (porta 5432) fornecido pelo painel Connect do projeto Supabase. O índice de cluster não pode ser inferido da região; não adivinhar ou usar host de outro projeto.
- Ao trocar o endereço, preservar a senha já instalada no Render: a substituição deverá ocorrer por atualização segura da variável, sem exibir a URL completa. No pooler, o nome do login será `dismepe_monthly_homolog_login.[PROJECT_REF]` (não usar nome curto).
- Uma conta de serviço Google exclusivamente leitora ainda precisa ser criada/autorizada no Google Cloud e receber acesso de leitura às duas planilhas. Não copiar chaves administrativas do serviço oficial.
- Não executar o cálculo financeiro real enquanto não estiverem confirmados ambos os acessos; a rota /status apenas mostra o resultado agregado da sondagem SQL e não publica.
