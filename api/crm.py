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
    """Lê a fotografia comercial que o DISMEPE ONE já publica.
    Não cria nova base nem depende de upload. O valor acumulado é financeiro;
    as unidades atuais vêm do MAPA, que é a fonte de quantidade mensal.
    """
    for modulo in ("MENSAL_COMERCIAL", "MENSAL"):
        try:
            payload, _ = await cache_get(modulo=modulo, settings=settings)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        values: dict[str, float] = {}
        found = 0
        for key in ("dadosVendedores", "dadosTelevendas"):
            rows = payload.get(key) if isinstance(payload.get(key), list) else []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                is_focus = row.get("__TEM_FOCO") is True or bool(row.get("__CODIGO_FOCO"))
                code = re.sub(r"\D", "", str(row.get("__CODIGO_FOCO") or ""))
                # Algumas fotografias mensais guardam o código em campos de foco
                # diferentes; aceitar também os nomes já usados pelo módulo.
                if not code:
                    for k in ("codigoProdutoFoco","codProdutoFoco","__COD_PROD_FOCO","codigo_foco","cod_foco"):
                        code = re.sub(r"\D", "", str(row.get(k) or ""))
                        if code:
                            break
                if not is_focus and not code:
                    continue
                sale = _to_number(row.get("__VENDA_FOCO") if row.get("__VENDA_FOCO") is not None else row.get("__VENDA"))
                values[code] = values.get(code, 0.0) + sale
                found += 1
        if found:
            comp = str(payload.get("competencia") or "")
            return values, comp
    return {}, ""


async def _crm_auto_products() -> dict[str, Any]:
    stock = _stock_map()
    rows = list(stock.values())
    month_key, month_label = _map_latest_month(rows)
    foco_sales, competencia = await _produto_foco_atual()
    focus_codes = set(foco_sales)
    produtos: list[dict[str, Any]] = []
    fornecedores: set[str] = set()

    for code in sorted(focus_codes):
        row = stock.get(code)
        if not row:
            # O produto foco pode ainda não estar no MAPA; mantemos o código
            # visível, mas ele não entra em ação de estoque sem cadastro.
            produtos.append({
                "codProduto": code, "fornecedor": "", "descricao": "",
                "mediaUnidades": 0, "unidadesAtual": 0, "variacaoPct": 0,
                "estoque": 0, "vendaFocoAtual": foco_sales.get(code, 0),
                "temMapa": False, "parado": False, "emQueda": False,
            })
            continue

        media = _to_number(row.get("media"))
        atual = _to_number(row.get(month_key))
        estoque = _to_number(row.get("estoque"))
        fornecedor = str(row.get("fornecedor") or "").strip()
        if fornecedor:
            fornecedores.add(fornecedor)
        variacao = ((atual / media) - 1) * 100 if media > 0 else 0
        parado = atual <= 0 and media > 0
        queda = media > 0 and atual > 0 and variacao <= -20
        produtos.append({
            "codProduto": code,
            "fornecedor": fornecedor,
            "descricao": str(row.get("descricao") or ""),
            "mediaUnidades": media,
            "unidadesAtual": atual,
            "variacaoPct": variacao,
            "estoque": estoque,
            "vendaFocoAtual": foco_sales.get(code, 0),
            "temMapa": True,
            "parado": parado,
            "emQueda": queda,
            "curva": str(row.get("curva") or ""),
        })

    parados = sorted(
        [x for x in produtos if x["parado"] and x["estoque"] > 0],
        key=lambda x: (x["estoque"], x["mediaUnidades"]),
        reverse=True,
    )[:500]
    queda = sorted(
        [x for x in produtos if x["emQueda"]],
        key=lambda x: x["variacaoPct"],
    )[:500]
    acoes = sorted(
        [x for x in produtos if x["estoque"] > 0 and (x["parado"] or x["emQueda"])],
        key=lambda x: (0 if x["parado"] else 1, x["variacaoPct"]),
    )[:500]

    return {
        "produtosQueda": queda,
        "produtosParados": parados,
        "acoes": acoes,
        "fornecedoresProdutos": sorted(fornecedores, key=lambda x: _norm(x)),
        "resumoAuto": {
            "produtosFoco": len(focus_codes),
            "produtosNoMapa": sum(x["temMapa"] for x in produtos),
            "produtosParadosEstoque": len(parados),
            "produtosQueda20": len(queda),
            "competenciaFoco": competencia,
            "mesMapa": month_label,
            "fonteFoco": "MENSAL_COMERCIAL_POSTGRESQL",
            "fonteMapa": "MAPA_ESTOQUE",
        },
    }


@router.get("/crm/api/resumo")
async def crm_summary(session: str | None = Cookie(default=None, alias=settings.cookie_name)):
    _admin_danton(session)
    result = await _edge("CRM_RESUMO", {})
    auto = await _crm_auto_products()
    result.update(auto)
    r = result.setdefault("resumo", {})
    ar = auto["resumoAuto"]
    r["produtos"] = ar["produtosFoco"]
    r["produtosQueda20"] = ar["produtosQueda20"]
    r["produtosParados30"] = ar["produtosParadosEstoque"]
    r["baseProdutos"] = True
    r["baseProdutosAutomatica"] = True
    r["baseProdutosArquivo"] = ""
    r["baseProdutosAtualizadaEm"] = str(result.get("atualizadoEm") or "")
    r["mesMapa"] = ar["mesMapa"]
    r["competenciaFoco"] = ar["competenciaFoco"]
    r["fonteFoco"] = ar["fonteFoco"]
    r["fonteMapa"] = ar["fonteMapa"]
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


