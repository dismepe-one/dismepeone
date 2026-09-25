"""Fontes auxiliares do calculo mensal no Render (somente leitura).

O leitor e deliberadamente independente do Apps Script. Ausencia de dados
obrigatorios aborta a simulacao; nenhuma tabela CACHE ou HOME e modificada.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from .industries_stock_sync import _service_account_info

AUXILIARY_TABS = {
    "METRICA_GLOBO": ("VENDEDOR_TELEVENDAS", "TIPO", "META_CLIENTES", "PREMIO"),
    "GLOBO_CLIENTES": ("VENDEDOR", "COD_CLIENTE", "PEDIDOS_POR", "POSITIVACAO", "DATA"),
    "HERBAMED_REGRAS": ("INDICADOR", "META", "PREMIO"),
    "HERB_COM": ("VENDEDOR", "COD_CLIENTE", "CNPJ", "DATA", "PEDIDOS_POR"),
    "INTEGRAL_PRODUTOS": ("COD_PRODUTO", "PONTOS"),
    "INTEGRAL_FAIXAS": ("PONTOS", "PREMIO"),
    "INT_PONTOS": ("DATA", "PEDIDOS_POR", "VENDEDOR", "COD_PRODUTO", "TOTAL_UNIDADE", "FATURADO"),
}

ALIASES = {
    "COD_PRODUTO": {"CODPRODUTO", "CODIGOPRODUTO"},
    "COD_CLIENTE": {"CODCLIENTE", "CODIGOCLIENTE"},
    "TOTAL_UNIDADE": {"TOTALUNIDADE", "TOTALUNIDADES", "QUANTIDADE", "QTD", "QTDE"},
    "VENDEDOR_TELEVENDAS": {"VENDEDORTELEVENDAS", "COLABORADOR"},
    "PEDIDOS_POR": {"PEDIDOSPOR", "CANAL"},
    "VENDEDOR": {"VENDEDOR", "RESPONSAVEL", "COLABORADOR"},
    "PREMIO": {"PREMIO"},
    "META_CLIENTES": {"METACLIENTES"},
    "POSITIVACAO": {"POSITIVACAO"},
    "FATURADO": {"FATURADO", "STATUS"},
    "INDICADOR": {"INDICADOR"},
    "META": {"META"},
    "PONTOS": {"PONTOS", "PONTO", "PONTUACAO"},
    "CNPJ": {"CNPJ"},
    "DATA": {"DATA", "DATAFATURAMENTO", "COMPETENCIA"},
    "TIPO": {"TIPO"},
}
IGNORABLE_MISSING = frozenset({"GLOBO_CLIENTES", "HERB_COM", "INT_PONTOS"})


class MonthlyAuxiliaryError(RuntimeError):
    pass


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return re.sub(r"[^A-Z0-9]", "", "".join(c for c in text if not unicodedata.combining(c)).upper())


def parse_auxiliary_tab(name: str, matrix: list[list[Any]]) -> dict[str, Any]:
    """Conferencia estrutural; nunca publica nem substitui linhas invalidadas."""
    if name not in AUXILIARY_TABS or not isinstance(matrix, list) or len(matrix) < 2:
        raise MonthlyAuxiliaryError("Base auxiliar ausente ou desconhecida.")
    header = [_norm(v) for v in matrix[0]]
    resolved: dict[str, int] = {}
    for field in AUXILIARY_TABS[name]:
        positions = [i for i, col in enumerate(header) if col in ALIASES[field]]
        # HERB_COM permite COD_CLIENTE vazio caso exista CNPJ, mas exige as colunas.
        if len(positions) != 1:
            raise MonthlyAuxiliaryError(f"{name}: cabecalho obrigatorio ausente ou duplicado: {field}.")
        resolved[field] = positions[0]
    rows = [r for r in matrix[1:] if any(str(v).strip() for v in r)]
    if not rows:
        raise MonthlyAuxiliaryError(f"{name}: base auxiliar sem registros.")
    invalid = 0
    for row in rows:
        missing = [key for key, idx in resolved.items()
                   if idx >= len(row) or row[idx] is None or str(row[idx]).strip() == ""]
        if name == "HERB_COM":
            missing = [key for key in missing if key not in {"COD_CLIENTE", "CNPJ"}]
            if not any(idx < len(row) and str(row[idx] or "").strip()
                       for idx in (resolved["COD_CLIENTE"], resolved["CNPJ"])):
                missing.append("COD_CLIENTE/CNPJ")
        if missing:
            if name in IGNORABLE_MISSING:
                invalid += 1
            else:
                raise MonthlyAuxiliaryError(f"{name}: registro incompleto em campos obrigatorios.")
    if invalid == len(rows):
        raise MonthlyAuxiliaryError(f"{name}: nenhum registro valido.")
    return {"registros": len(rows), "validos": len(rows) - invalid, "ignorados": invalid,
            "cabecalhoVerificado": True, "calculoConcluido": False}


def read_auxiliary_sources(spreadsheet_id: str) -> dict[str, Any]:
    """Usa Service Account do Render, exigindo acesso a todas as abas."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{15,120}", spreadsheet_id or ""):
        raise MonthlyAuxiliaryError("ID administrativo nao configurado.")
    info = _service_account_info()
    if not info:
        raise MonthlyAuxiliaryError("Service Account nao configurada no Render.")
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    credentials = Credentials.from_service_account_info(
        info, scopes=("https://www.googleapis.com/auth/spreadsheets.readonly",),
    )
    sheets = build("sheets", "v4", credentials=credentials, cache_discovery=False)
    ranges = [f"'{name}'!A1:AZ25000" for name in AUXILIARY_TABS]
    result = sheets.spreadsheets().values().batchGet(
        spreadsheetId=spreadsheet_id, ranges=ranges,
        valueRenderOption="UNFORMATTED_VALUE",
    ).execute(num_retries=2)
    values = result.get("valueRanges") or []
    if len(values) != len(AUXILIARY_TABS):
        raise MonthlyAuxiliaryError("Uma ou mais abas auxiliares indisponiveis.")
    return {name: parse_auxiliary_tab(name, item.get("values") or [])
            for name, item in zip(AUXILIARY_TABS, values)}
