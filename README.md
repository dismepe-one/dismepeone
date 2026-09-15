# DISMEPE ONE 2.0 — FASE 2I.2

Base: FASE 2I.1 homologada.

## Objetivo
Migrar mais uma leitura administrativa de baixo risco para o caminho 2.0, sem alterar nenhuma escrita.

## Mudança
- Regras/Métricas da Campanha Mensal passam a carregar laboratórios e regras existentes via `GET /data/monthly-rule-options`.
- Fonte: snapshot `MENSAL` no PostgreSQL.
- A rota respeita sessão HttpOnly 2.0 e permissões administrativas de Regras/Métricas.
- `CM70_LISTARMODELOSREGRAS` permanece apenas como fallback de compatibilidade em indisponibilidade da leitura direta e quando existe token legado.
- HTTP 401/403 nunca usam fallback.
- Cadastrar, editar, duplicar e excluir métricas permanecem no fluxo de escrita existente.

## Validação
- 177/177 testes aprovados.
- Python compileall aprovado.
- 68/68 blocos JavaScript executáveis com sintaxe válida.

Versão esperada em `/health`: `2.0.0-phase2i2`.
Badge: `HOMOLOGAÇÃO 2.0 • I2 • SOMENTE LEITURA`.
