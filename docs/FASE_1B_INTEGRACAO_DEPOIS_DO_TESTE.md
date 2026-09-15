# Fase 1B — depois que o login isolado estiver aprovado

Somente após o login 2.0 atingir a meta de performance:

1. Integrar o novo login ao frontend principal em homologação.
2. Abrir a Home imediatamente com a sessão 2.0.
3. Criar sessão legada em segundo plano somente enquanto módulos 1.x ainda existirem.
4. Migrar módulo a módulo para a API 2.0.
5. Retirar a sessão legada quando o último módulo sair do Apps Script.

O objetivo é evitar um "big bang": o usuário vê o ganho do login agora, enquanto
Resumo, Clientes PED, Campanhas e demais módulos são migrados gradualmente.
