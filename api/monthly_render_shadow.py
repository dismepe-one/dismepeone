"""Leitor independente de fontes mensais no Render — execução comparativa.

Este módulo NÃO calcula nem publica premiações. A mudança de motor exige
equivalência integral das regras do Apps Script antes de qualquer escrita.
Executar somente em ambiente autorizado com credenciais de leitura do Drive.
"""
from __future__ import annotations

import asyncio
import json
import re
from decimal import Decimal, InvalidOperation
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qs, urlparse

from .cache_reads import cache_get
from .config import get_settings
from .industries_stock_sync import _service_account_info


GOOGLE_SHEET_MIME = "application/vnd.google-apps.spreadsheet"
CHANNEL_TABS = ("CAMPANHA VEND", "CAMPANHAS TLVS")
_DRIVE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{15,120}$")


class MonthlyShadowError(RuntimeError):
    """Falha controlada: a fotografia oficial nunca é alterada."""


@dataclass(frozen=True)
class MonthlySource:
    competence: str
    file_id: str
    campaign_status: str
    frozen: bool


def _sheet_file_id(url: Any) -> str:
    """Extrai um ID somente de URL legítima do Google Sheets."""
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme != "https" or parsed.hostname not in {
        "docs.google.com", "drive.google.com",
    }:
        raise MonthlyShadowError("A competência não tem URL válida do Google.")
    if parsed.hostname == "docs.google.com":
        match = re.fullmatch(r"/spreadsheets/d/([A-Za-z0-9_-]+)/?.*", parsed.path)
        value = match.group(1) if match else ""
    else:
        value = (parse_qs(parsed.query).get("id") or [""])[0]
    if not _DRIVE_ID_RE.fullmatch(value):
        raise MonthlyShadowError("O link da competência não contém um ID válido.")
    return value


def _current_source(snapshot: dict[str, Any]) -> MonthlySource:
    metas = snapshot.get("competencias")
    if not isinstance(metas, list):
        raise MonthlyShadowError("Snapshot sem competências verificáveis.")
    current = [
        row for row in metas if isinstance(row, dict)
        and str(row.get("status") or "").strip().upper() == "ATUAL"
    ]
    if len(current) != 1:
        raise MonthlyShadowError("Não há uma única competência atual identificada.")
    meta = current[0]
    competence = str(meta.get("competencia") or "").strip()
    if not re.fullmatch(r"(0[1-9]|1[0-2])/20\d{2}", competence):
        raise MonthlyShadowError("Competência atual inválida.")
    frozen = meta.get("fechada") is True or meta.get("congelada") is True
    if frozen:
        raise MonthlyShadowError("Competência congelada: nenhuma leitura de fonte ativa.")
    return MonthlySource(
        competence=competence,
        file_id=_sheet_file_id(meta.get("linkDrive")),
        campaign_status="ATUAL",
        frozen=False,
    )


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(c for c in text if not unicodedata.combining(c)).upper().strip()


def _header_index(matrix: list[list[Any]], channel: str) -> int:
    """Detecta cabeçalho sem assumir que esteja na primeira linha."""
    person_words = ("VENDEDOR", "COLABORADOR", "TELEVENDAS", "TELEVENDA")
    for i, row in enumerate(matrix[:100]):
        words = [_norm(x) for x in row]
        has_person = any(any(alias in w for alias in person_words) for w in words)
        has_lab = any("LABORATORIO" in w or "FORNECEDOR" in w for w in words)
        has_amount = any(
            "VENDA" in w or "REALIZADO" in w or "FATURAMENTO" in w for w in words
        )
        has_target = any("META" in w or "OBJETIVO" in w for w in words)
        if has_person and has_lab and (has_amount or has_target):
            return i
    raise MonthlyShadowError(f"Cabeçalho não reconhecido na aba {channel}.")


def _source_stats(matrix: list[list[Any]], tab: str) -> dict[str, Any]:
    if not isinstance(matrix, list) or not matrix:
        raise MonthlyShadowError(f"Aba {tab} sem linhas.")
    header = _header_index(matrix, tab)
    rows = sum(1 for row in matrix[header + 1:] if any(str(v).strip() for v in row))
    if rows == 0:
        raise MonthlyShadowError(f"Aba {tab} sem registros.")
    return {"linhas": rows, "linhaCabecalho": header + 1}


def _number(value: Any) -> Decimal:
    """Google Sheets UNFORMATTED_VALUE devolve numero, nao moeda formatada."""
    if value is None or value == "":
        return Decimal(0)
    if isinstance(value, bool):
        raise MonthlyShadowError("Coluna financeira com valor booleano.")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise MonthlyShadowError("Coluna financeira nao numerica.") from exc
    if not number.is_finite():
        raise MonthlyShadowError("Coluna financeira nao finita.")
    return number


def audit_source_rows(
    matrix: list[list[Any]],
    official_rows: list[dict[str, Any]],
    tab: str,
    competence: str,
) -> dict[str, Any]:
    """Auditoria por linha, sem nomes: divergencias reais nao sao descartadas.

    A origem oficial pode estar mais antiga do que a planilha viva. Nesse caso,
    as divergencias significam revisoes diferentes, nao falha do motor novo.
    """
    if not isinstance(official_rows, list) or not official_rows:
        raise MonthlyShadowError("Fotografia oficial sem linhas verificaveis.")
    header = _header_index(matrix, tab)
    names = [_norm(cell) for cell in matrix[header]]
    def index(aliases: tuple[str, ...]) -> int:
        hits = [i for i, name in enumerate(names) if name in aliases]
        if len(hits) != 1:
            raise MonthlyShadowError(f"Coluna comercial ambigua ou ausente em {tab}.")
        return hits[0]
    objective = index(("OBJETIVO", "META"))
    sale = index(("VENDA", "REALIZADO", "FATURAMENTO"))
    current = {}
    for line, record in enumerate(matrix[header + 1:], start=header + 2):
        if not any(str(item).strip() for item in record):
            continue
        if len(record) <= objective or record[objective] is None or record[objective] == "":
            raise MonthlyShadowError(f"Objetivo ausente na linha da aba {tab}.")
        # A API Sheets omite celulas vazias ao final da linha. Venda em branco
        # equivale a zero na fotografia legada, sem descartar o colaborador.
        current[line] = (
            _number(record[objective]),
            _number(record[sale] if len(record) > sale else None),
        )
    expected = {}
    for record in official_rows:
        if not isinstance(record, dict):
            raise MonthlyShadowError("Fotografia oficial contem linha invalida.")
        if str(record.get("__COMPETENCIA") or record.get("competencia") or "").strip() != competence:
            continue
        try:
            line = int(record.get("__linha"))
        except (ValueError, TypeError) as exc:
            raise MonthlyShadowError("Fotografia oficial sem numero de linha.") from exc
        if line in expected:
            raise MonthlyShadowError("Numero de linha duplicado na fotografia oficial.")
        expected[line] = (_number(record.get("__OBJETIVO")), _number(record.get("__VENDA")))
    if not current or not expected:
        raise MonthlyShadowError(f"Sem linhas comparaveis em {tab}.")
    changed = []
    missing = sorted(set(expected) - set(current))
    added = sorted(set(current) - set(expected))
    for line in sorted(set(current) & set(expected)):
        meta, venda = current[line]
        old_meta, old_venda = expected[line]
        if abs(meta - old_meta) > Decimal("0.015") or abs(venda - old_venda) > Decimal("0.015"):
            changed.append(line)
    return {
        "linhasFonte": len(current),
        "linhasFotografia": len(expected),
        "linhasAlteradas": len(changed),
        "numerosLinhasAlteradas": changed[:30],
        "linhasAusentes": len(missing),
        "linhasAdicionadas": len(added),
        "vendaFonte": str(sum((x[1] for x in current.values()), Decimal(0))),
        "vendaFotografia": str(sum((x[1] for x in expected.values()), Decimal(0))),
        "valoresConferidos": not (changed or missing or added),
    }


def _read_current_source(source: MonthlySource, snapshot: dict[str, Any]) -> dict[str, Any]:
    # Usa a mesma conta de serviço já configurada para o portal de indústrias.
    # Não imprime, persiste ou expõe os campos sensíveis da conta.
    info = _service_account_info()
    if not info:
        raise MonthlyShadowError("Conta de serviço do Google não configurada no Render.")
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    credentials = Credentials.from_service_account_info(
        info,
        scopes=(
            "https://www.googleapis.com/auth/drive.metadata.readonly",
            "https://www.googleapis.com/auth/spreadsheets.readonly",
        ),
    )
    drive = build("drive", "v3", credentials=credentials, cache_discovery=False)
    sheets = build("sheets", "v4", credentials=credentials, cache_discovery=False)
    metadata = drive.files().get(
        fileId=source.file_id,
        fields="id,mimeType,modifiedTime",
        supportsAllDrives=True,
    ).execute(num_retries=2)
    if metadata.get("mimeType") != GOOGLE_SHEET_MIME:
        raise MonthlyShadowError("Fonte da competência não é uma planilha Google.")
    ranges = ["'" + tab.replace("'", "''") + "'!A1:AZ6000" for tab in CHANNEL_TABS]
    result = sheets.spreadsheets().values().batchGet(
        spreadsheetId=source.file_id,
        ranges=ranges,
        valueRenderOption="UNFORMATTED_VALUE",
    ).execute(num_retries=2)
    matrices = result.get("valueRanges") or []
    if len(matrices) != len(CHANNEL_TABS):
        raise MonthlyShadowError("Faltam abas operacionais da competência atual.")
    counts = {}
    audits = {}
    for tab, item, key in zip(
        CHANNEL_TABS, matrices, ("dadosVendedores", "dadosTelevendas")
    ):
        matrix = item.get("values") or []
        counts[tab] = _source_stats(matrix, tab)
        audits[tab] = audit_source_rows(
            matrix, snapshot.get(key), tab, source.competence,
        )
    # Rele metadata: fonte editada durante a leitura invalida a comparacao.
    end_meta = drive.files().get(
        fileId=source.file_id,
        fields="id,modifiedTime",
        supportsAllDrives=True,
    ).execute(num_retries=2)
    if str(end_meta.get("modifiedTime") or "") != str(metadata.get("modifiedTime") or ""):
        raise MonthlyShadowError("Planilha alterada durante a leitura; teste cancelado.")
    return {
        "competencia": source.competence,
        "modificadoEm": str(metadata.get("modifiedTime") or ""),
        "abas": counts,
        "auditoria": audits,
    }


async def run_shadow_comparison() -> dict[str, Any]:
    """Lê fontes e fotografia, sem CACHE_SET nem HOME_PUBLICATION/publish."""
    snapshot, row = await cache_get(modulo="MENSAL", settings=get_settings())
    source = _current_source(snapshot)
    source_stats = await asyncio.to_thread(_read_current_source, source, snapshot)
    official = {}
    for channel, key in (("VENDEDORES", "dadosVendedores"), ("TELEVENDAS", "dadosTelevendas")):
        rows = snapshot.get(key)
        if not isinstance(rows, list) or not rows:
            raise MonthlyShadowError(f"Snapshot {key} ausente ou vazio.")
        official[channel] = sum(
            1 for entry in rows if isinstance(entry, dict)
            and str(entry.get("__COMPETENCIA") or entry.get("competencia") or "") == source.competence
        )
    # Não comparar diretamente contagens de linhas: o legado aplica regras de
    # normalização, linhas de produto foco e cálculos especiais de premiação.
    return {
        "modo": "SOMENTE_LEITURA",
        "etapa": "FONTES_LIDAS_CALCULO_PENDENTE",
        "competencia": source.competence,
        "fonteModificadaEm": source_stats["modificadoEm"],
        "snapshotAtualizadoEm": str(row.get("atualizado_em") or ""),
        "linhasFonte": source_stats["abas"],
        "linhasSnapshot": official,
        "auditoriaFonteVsFotografia": source_stats["auditoria"],
        # Fonte viva e fotografia antiga podem ter revisoes diferentes:
        # igualdade de contagem nao autoriza recalculo de premios.
        "paridadeNumericaConfirmada": False,
        "publicacaoAutorizada": False,
    }


def main() -> None:
    # Diagnóstico seguro: nenhum conteúdo de cliente ou segredo é registrado.
    result = asyncio.run(run_shadow_comparison())
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
