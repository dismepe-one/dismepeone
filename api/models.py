from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    usuario: str = Field(min_length=1, max_length=120)
    senha: str = Field(min_length=1, max_length=256)


class UserProfile(BaseModel):
    usuario: str
    nome: str = ""
    vendedor: str = ""
    tipo: str = ""
    setor: str = ""
    permissoes: Dict[str, Any] = Field(default_factory=dict)


class LoginResponse(BaseModel):
    sucesso: bool
    usuario: UserProfile
    expiraEm: int
    banco: str = "SUPABASE"
    api: str = "DISMEPE_ONE_2_AUTH"
    elapsedMs: int
    authMs: int = 0
    bootstrapMs: int = 0
    bootstrap: Optional[Dict[str, Any]] = None


class MeResponse(BaseModel):
    autenticado: bool
    usuario: UserProfile
