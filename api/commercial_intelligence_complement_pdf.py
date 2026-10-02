from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from pypdf import PdfReader


_INSTALLED = False


def _num(value: str) -> float:
    from . import commercial_intelligence_complement as cc
    return cc._num(value)


def _parse_product_line(line: str) -> dict[str, Any] | None:
    # Estrutura real do Rel442414.TXT no PDF:
    # Código + Descrição + Curva + UFO + Estoque + Pc.Custo + Pc.Venda +
    # JUL + AGO + SET + OUT + Media + Ult.Ent. + Quant. + Lote + Qtd + Venc. ...
    #
    # O PDF às vezes cola colunas, por exemplo:
    #   300EPCA072508 11607/2030
    # que significa Quant.=300, Lote=EPCA072508, Qtd=116, Venc.=07/2030.
    match = re.match(
        r"\s*(\d{1,3}(?:\.\d{3})*|\d+)(.*?)([A-Z]/[A-Z])\s*(.*)$",
        str(line or ""),
    )
    if not match:
        return None

    # Código no relatório usa ponto como separador de milhar (ex.: 5.445).
    # No MAPA_ESTOQUE o código correspondente é 5445.
    code = match.group(1).replace(".", "")
    rest = match.group(4)

    entry = re.search(r"(\d{2}/\d{2}/\d{2})", rest)
    if not entry:
        return None

    before_entry = rest[: entry.start()].strip()
    after_entry = rest[entry.end() :].strip()

    # Antes de Ult.Ent. existem 9 campos numéricos:
    # UFO, Estoque, Pc.Custo, Pc.Venda, JUL, AGO, SET, OUT e Media.
    numbers = re.findall(r"-?\d[\d.]*,\d+|-?\d+(?:\.\d+)?", before_entry)
    if len(numbers) < 7:
        return None

    # Pc.Custo é o 7º campo numérico contado da direita para a esquerda.
    # Essa regra continua funcionando mesmo quando UFO vem colado a outro valor
    # no texto extraído pelo pypdf.
    cost = max(0.0, _num(numbers[-7]))

    expiry_match = re.search(r"(\d{2}/\d{4})", after_entry)
    lot = ""
    qty = 0.0
    expiry = ""

    if expiry_match:
        expiry = expiry_match.group(1)
        prefix = after_entry[: expiry_match.start()]

        # Qtd é o número imediatamente anterior a Venc., mesmo quando ambos
        # aparecem colados (ex.: 11607/2030).
        qty_match = re.search(r"(-?\d[\d.]*)\s*$", prefix)
        if qty_match:
            qty = max(0.0, _num(qty_match.group(1)))
            prefix = prefix[: qty_match.start()].strip()

        # O que resta começa por Quant.; o conteúdo após Quant. é o Lote.
        # Também resolve casos colados como 300EPCA072508.
        quant_lot = re.match(r"^\s*(-?\d[\d.]*)\s*(.*)$", prefix)
        if quant_lot:
            lot = str(quant_lot.group(2) or "").strip()
            if lot == "0":
                lot = ""

        # 01/1900 é o marcador do relatório para ausência de vencimento.
        if expiry == "01/1900":
            expiry = ""
            lot = "" if lot == "0" else lot

    return {
        "codigo": code,
        "precoMedio": round(cost, 4),
        "lote": lot,
        "vencimento": expiry,
        "quantidadeUltimaEntrada": round(qty, 3),
    }


def _finalize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from . import commercial_intelligence_complement as cc

    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = str(row.get("codigo") or "").strip()
        if not code:
            continue
        target = grouped.setdefault(
            code,
            {
                "codigo": code,
                "precoMedio": 0.0,
                "lote": "",
                "vencimento": "",
                "quantidadeUltimaEntrada": 0.0,
                "lotes": [],
            },
        )

        cost = float(row.get("precoMedio") or 0)
        if cost > 0:
            target["precoMedio"] = cost

        lot = str(row.get("lote") or "").strip()
        expiry = str(row.get("vencimento") or "").strip()
        qty = float(row.get("quantidadeUltimaEntrada") or 0)
        if lot or expiry or qty > 0:
            target["lotes"].append(
                {
                    "lote": lot,
                    "vencimento": expiry,
                    "quantidadeUltimaEntrada": round(qty, 3),
                }
            )

    for target in grouped.values():
        lots = target.get("lotes") or []
        if lots:
            # Para a visão principal, mostra primeiro o lote com vencimento mais
            # próximo. A lista completa continua preservada em lotesComplemento.
            lots.sort(key=lambda item: cc._date_sort(str(item.get("vencimento") or "")))
            primary = lots[0]
            target["lote"] = str(primary.get("lote") or "")
            target["vencimento"] = str(primary.get("vencimento") or "")
            target["quantidadeUltimaEntrada"] = float(primary.get("quantidadeUltimaEntrada") or 0)

    return list(grouped.values())


def _parse_pdf(content: bytes) -> list[dict[str, Any]]:
    try:
        reader = PdfReader(io.BytesIO(content))
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Não foi possível abrir o PDF complementar.") from exc

    rows: list[dict[str, Any]] = []
    for page in reader.pages:
        # O modo layout desse relatório retorna vazio em algumas versões do
        # pypdf. A extração simples preserva melhor as linhas do Rel442414.TXT.
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        for line in text.splitlines():
            parsed = _parse_product_line(line)
            if parsed is not None:
                rows.append(parsed)

    parsed_rows = _finalize(rows)
    if not parsed_rows:
        raise HTTPException(
            status_code=400,
            detail=(
                "O PDF foi recebido, mas não consegui identificar as linhas do relatório. "
                "São esperados os campos Código, Pc.Custo, Qtd, Venc. e, quando houver, Lote."
            ),
        )
    return parsed_rows


def install_commercial_intelligence_complement_pdf() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from . import commercial_intelligence_complement as cc

    original_parse_file = cc._parse_file

    def parse_file_with_pdf(file_name: str, content: bytes) -> list[dict[str, Any]]:
        if Path(file_name).suffix.lower() == ".pdf":
            return _parse_pdf(content)
        return original_parse_file(file_name, content)

    cc._parse_file = parse_file_with_pdf
    _INSTALLED = True
