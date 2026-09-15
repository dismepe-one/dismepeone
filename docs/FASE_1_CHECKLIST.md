# Checklist — Fase 1 Login

## Antes
- [ ] Backup fixo conferido
- [ ] Produção atual funcionando
- [ ] WorkerV216 não alterado
- [ ] diagnosticoV216 não alterado
- [ ] Nenhum SQL destrutivo executado

## API
- [ ] Criar serviço FastAPI separado
- [ ] Configurar variáveis secretas
- [ ] Confirmar `/health`
- [ ] Confirmar HTTPS
- [ ] Configurar CORS apenas para domínio de homologação

## Testes
- [ ] Login administrador
- [ ] Login vendedor
- [ ] Login televendas
- [ ] Senha incorreta
- [ ] Usuário inexistente
- [ ] Logout
- [ ] F5 com sessão
- [ ] 20 logins consecutivos
- [ ] Registrar mediana e p95

## Produção
- [ ] NÃO mudar a produção na Fase 1A
- [ ] NÃO trocar FRONTEND_RELEASE
- [ ] NÃO alterar Código.gs
- [ ] NÃO alterar diagnosticoV216
