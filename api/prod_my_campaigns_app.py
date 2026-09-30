from __future__ import annotations

# Camada mínima sobre a aplicação oficial: preserva integralmente o PROD atual
# e apenas registra as rotas privadas de "Minhas campanhas".
from .prod597_app import app, settings  # noqa: F401
from .my_campaigns import router as my_campaigns_router


app.include_router(my_campaigns_router)
