# DISMEPE ONE 2.0 — Migração para Produção — 2I.2

## Base escolhida
FASE 2I.2 homologada. Nenhuma regra comercial, cálculo, permissão, worker, integração ou escrita foi alterada neste pacote de produção.

## O que muda neste pacote
Somente o envelope de implantação:
- Dockerfile passa a incluir `frontend/`, necessário porque o FastAPI serve `/` a partir de `frontend/portal-v2-homolog.html`.
- Porta aceita `$PORT` do provedor, com fallback 8000.
- `.dockerignore` impede envio de `.env` e caches.
- Exemplo de variáveis de produção e preflight adicionados.

## Antes do corte
1. Manter o rollback oficial 2H.12 intacto.
2. Manter a produção antiga disponível até a validação final.
3. Publicar a 2I.2 em um endereço HTTPS separado primeiro.
4. Usar exatamente os mesmos segredos já homologados; não gerar/trocar `DISMEPE_JWT_SECRET`, `DISMEPE_AUTH_PEPPER` ou `DISMEPE_EDGE_TOKEN` durante o corte.
5. Em produção usar `DISMEPE_COOKIE_SECURE=true` e `ENVIRONMENT=production`.
6. Definir `DISMEPE_CORS_ORIGINS` com o domínio HTTPS real.

## Validação antes de apontar usuários
- `GET /health` precisa retornar `ok: true`, `version: 2.0.0-phase2i2`, `environment: production`, `missingConfig: []`.
- Abrir `/` pelo mesmo domínio HTTPS.
- Testar login.
- Testar F5 após login.
- Testar Vendedores, Televendas e Visão Geral.
- Testar Resumo de Ganhos.
- Testar Campanhas Extras.
- Testar Campanhas Mensais e abrir cadastro/edição de métrica.
- Testar Histórico atual e uma fotografia anterior.
- Testar Controle de Acessos com usuário autorizado.
- Testar uma escrita administrativa crítica pelo fluxo já existente (sem alterar as regras): por exemplo salvar uma configuração já conhecida e confirmar persistência.

## Corte
Somente depois de toda a validação acima, apontar o endereço usado pelos usuários para a nova aplicação.

## Rollback
Se qualquer validação crítica falhar depois do corte:
1. Reapontar imediatamente os usuários para a produção antiga/2H.12 preservada.
2. Não apagar dados, tabelas, Apps Script, Edge Functions ou snapshots.
3. Investigar fora da janela de corte.
