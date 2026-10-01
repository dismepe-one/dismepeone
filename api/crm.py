from __future__ import annotations

import io
import json
import re
import unicodedata
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Any

import jwt
from fastapi import APIRouter, BackgroundTasks, Cookie, HTTPException, Request, Response
from fastapi.responses import FileResponse

from .cache_reads import cache_get
from .config import get_settings
from .security import decode_session_token

router = APIRouter()
settings = get_settings()
ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "frontend" / "crm.html"
CRM_BUILD = "CRM-DEV2-20261001-AUTO-FOCO"
CRM_MODULE = "CRM_VENDAS_V1"
STOCK_JSON = ROOT / "data" / "industries" / "mapa_estoque_atual.json"
STOCK_FALLBACK = ROOT / "data" / "industries" / "mapa_estoque_2026-09-16.json"


def _norm(v: Any) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFD", str(v or ""))
                  .encode("ascii", "ignore").decode("ascii").upper()).strip()


def _admin_danton(session: str | None) -> dict[str, Any]:
    if not session:
        raise HTTPException(401, "Sessão ausente.")
    try:
        profile = decode_session_token(session, secret=settings.jwt_secret, issuer=settings.jwt_issuer)
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(401, "Sessão expirada.") from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(401, "Sessão inválida.") from exc
    tipo = _norm(profile.get("tipo"))
    usuario = _norm(profile.get("usuario") or profile.get("sub"))
    if tipo not in {"ADMIN", "ADMINISTRADOR"} or usuario != "DANTON":
        raise HTTPException(403, "CRM em desenvolvimento: acesso exclusivo do administrador Danton.")
    return profile


def _json(data: dict[str, Any], status: int = 200) -> Response:
    return Response(
        content=json.dumps(data, ensure_ascii=False, separators=(",", ":")),
        status_code=status,
        media_type="application/json",
        headers={"Cache-Control": "no-store, private", "X-DISMEPE-CRM": CRM_BUILD},
    )


async def _edge(acao: str, payload: dict[str, Any]) -> dict[str, Any]:
    import httpx
    url = settings.supabase_url.rstrip("/") + "/functions/v1/dismepe-admin"
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        response = await client.post(
            url,
            json={"acao": acao, **payload},
            headers={
                "apikey": settings.supabase_publishable_key,
                "x-dismepe-token": settings.edge_token,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError("Serviço de dados não retornou JSON válido.") from exc
    if not response.is_success or not isinstance(data, dict) or data.get("sucesso") is not True:
        raise RuntimeError(str(data.get("erro") if isinstance(data, dict) else "Falha no serviço de dados."))
    return data


def _stock_map() -> dict[str, dict[str, Any]]:
    for path in (STOCK_JSON, STOCK_FALLBACK):
        try:
            obj = json.loads(path.read_text(encoding="utf-8"))
            rows = obj.get("linhas") if isinstance(obj, dict) else []
            if isinstance(rows, list):
                return {re.sub(r"\D", "", str(r.get("codigo") or "")): r for r in rows if r.get("codigo")}
        except Exception:
            continue
    return {}


async def _positivacao_owner_map() -> dict[str, dict[str, Any]]:
    try:
        payload, _ = await cache_get(modulo="POSITIVACAO_GERAL_V1", settings=settings)
        if payload.get("schema") != "POSITIVACAO_GERAL_V1" or not payload.get("zip"):
            return {}
        import base64, zlib
        raw = zlib.decompress(base64.b64decode(payload["zip"], validate=True))
        data = json.loads(raw)
        rows = data.get("clientes") if isinstance(data, dict) else []
        return {str(r.get("codigo")): r for r in rows if isinstance(r, dict) and r.get("codigo")}
    except Exception:
        return {}


def _row_to_db(row: dict[str, Any], source: str) -> dict[str, Any]:
    def num(v, default=0):
        try:
            return float(v)
        except Exception:
            return default
    data = row.get("Data")
    if isinstance(data, datetime):
        d = data.date().isoformat()
    elif isinstance(data, date):
        d = data.isoformat()
    else:
        d = str(data or "").strip()[:10]
        if "/" in d:
            try:
                d = datetime.strptime(d, "%d/%m/%Y").date().isoformat()
            except ValueError:
                pass
    nf = int(float(row.get("Número NF") or 0))
    cliente = int(float(row.get("Cód. Cliente") or 0))
    produto = int(float(row.get("Cód. Produto") or 0))
    return {
        "data_venda": d,
        "numero_nf": nf,
        "cod_cliente": cliente,
        "cod_produto": produto,
        "total_unidade": num(row.get("Total Unidade")),
        "venda_liquida": num(row.get("Venda Líquida (R$)")),
        "fornecedor": str(row.get("Fornecedor") or "").strip(),
        "chave_origem": f"{d}|{nf}|{cliente}|{produto}|{num(row.get('Total Unidade'))}|{num(row.get('Venda Líquida (R$)'))}",
        "origem_arquivo": source,
    }


@router.get("/crm", include_in_schema=False)
async def crm_page(session: str | None = Cookie(default=None, alias=settings.cookie_name)):
    _admin_danton(session)
    return FileResponse(PAGE, media_type="text/html", headers={"Cache-Control": "no-store, private"})


@router.get("/crm/api/acesso")
async def crm_access(session: str | None = Cookie(default=None, alias=settings.cookie_name)):
    _admin_danton(session)
    return _json({"sucesso": True, "usuario": "DANTON", "build": CRM_BUILD})


def _month_number(label: str) -> int:
    names = {"jan":1,"fev":2,"mar":3,"abr":4,"mai":5,"jun":6,"jul":7,"ago":8,"set":9,"out":10,"nov":11,"dez":12}
    m = re.match(r"^([a-z]{3})_(\d{2})$", str(label or "").strip().lower())
    if not m:
        return 0
    return 2000 + int(m.group(2)), names.get(m.group(1), 0)


def _map_latest_month(rows: list[dict[str, Any]]) -> tuple[str, str]:
    candidates: set[str] = set()
    for row in rows:
        for key in row:
            if re.fullmatch(r"[a-z]{3}_\d{2}", str(key or "").lower()):
                if _month_number(str(key)) != 0:
                    candidates.add(str(key))
    if not candidates:
        return "", ""
    latest = max(candidates, key=_month_number)
    return latest, latest.replace("_", "/").upper()


def _to_number(value: Any) -> float:
    text = str(value or "").strip().replace(".", "").replace(",", ".")
    try:
        return float(text)
    except Exception:
        try:
            return float(value or 0)
        except Exception:
            return 0.0


async def _produto_foco_atual() -> tuple[dict[str, float], str]:
    # Mantém compatibilidade apenas para diagnóstico; a tela usa o snapshot SQL.
    return {}, ""


async def _crm_auto_products() -> dict[str, Any]:
    try:
        snapshot, _ = await cache_get(modulo="CRM_AUTO_PRODUTOS", settings=settings)
    except Exception:
        snapshot = None
    if isinstance(snapshot, dict):
        snapshot = dict(snapshot)
        snapshot["fonteSnapshot"] = "SQL"
        return snapshot
    return {
        "produtosQueda": [],
        "produtosParados": [],
        "acoes": [],
        "fornecedoresProdutos": [],
        "resumoAuto": {
            "produtosFoco": 0,
            "produtosNoMapa": 0,
            "produtosParadosEstoque": 0,
            "produtosQueda20": 0,
            "competenciaFoco": "",
            "mesMapa": "",
            "fonteFoco": "MENSAL_COMERCIAL_POSTGRESQL",
            "fonteMapa": "MAPA_ESTOQUE",
            "fonteSnapshot": "SQL",
            "semSnapshot": True,
        },
    }


@router.get("/crm/api/resumo")
async def crm_summary(session: str | None = Cookie(default=None, alias=settings.cookie_name)):
    _admin_danton(session)
    result = await _edge("CRM_RESUMO", {})
    auto = await _crm_auto_products()
    result.update(auto)
    r = result.setdefault("resumo", {})
    ar = auto.get("resumoAuto") if isinstance(auto.get("resumoAuto"), dict) else {}
    r["produtos"] = int(ar.get("produtosFoco") or 0)
    r["produtosQueda20"] = int(ar.get("produtosQueda20") or 0)
    r["produtosParados30"] = int(ar.get("produtosParadosEstoque") or 0)
    r["baseProdutos"] = True
    r["baseProdutosAutomatica"] = True
    r["baseProdutosArquivo"] = ""
    r["baseProdutosAtualizadaEm"] = str(ar.get("atualizadoEm") or "")
    r["mesMapa"] = str(ar.get("mesMapa") or "")
    r["competenciaFoco"] = str(ar.get("competenciaFoco") or "")
    r["fonteFoco"] = str(ar.get("fonteFoco") or "")
    r["fonteMapa"] = str(ar.get("fonteMapa") or "")
    r["fonteSnapshot"] = str(auto.get("fonteSnapshot") or "SQL")
    result["build"] = CRM_BUILD
    return _json(result)


@router.get("/crm/api/produtos")
async def crm_products(session: str | None = Cookie(default=None, alias=settings.cookie_name)):
    _admin_danton(session)
    result = await _edge("CRM_PRODUTOS", {})
    result["build"] = CRM_BUILD
    return _json(result)


@router.get("/crm/api/clientes")
async def crm_clients(session: str | None = Cookie(default=None, alias=settings.cookie_name)):
    _admin_danton(session)
    result = await _edge("CRM_CLIENTES", {})
    result["build"] = CRM_BUILD
    return _json(result)


