from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import jwt
from fastapi import Cookie, HTTPException
from fastapi.responses import FileResponse

from .cache_reads import CacheReadError, cache_get
from .config import get_settings
from .security import decode_session_token, normalizar


settings = get_settings()
ROOT = Path(__file__).resolve().parents[1]
PAGE_FILE = ROOT / "frontend" / "commercial-intelligence.html"
PORTAL_FILE = ROOT / "frontend" / "portal-v2-homolog.html"
_TZ = ZoneInfo("America/Recife")
_SLOT_KEYS = ("jun_26", "jul_26", "ago_26", "set_26")
_MONTHS = ("JAN", "FEV", "MAR", "ABR", "MAI", "JUN", "JUL", "AGO", "SET", "OUT", "NOV", "DEZ")
_PORTAL_MARKER = "DISMEPE_COMMERCIAL_INTELLIGENCE_DANTON_V1"


def _num(value: Any) -> float:
    if value is None or isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else 0.0
    raw = str(value).strip().replace("R$", "").replace(" ", "")
    if not raw:
        return 0.0
    # Dados do Mapa usam padrão pt-BR. Inteiros como 1.920 significam 1920.
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif raw.count(".") == 1:
        left, right = raw.split(".", 1)
        if right.isdigit() and len(right) == 3 and left.replace("-", "").isdigit():
            raw = left + right
    try:
        number = float(raw)
    except ValueError:
        return 0.0
    return number if math.isfinite(number) else 0.0


def _round(value: float, digits: int = 2) -> float:
    try:
        if not math.isfinite(float(value)):
            return 0.0
        return round(float(value), digits)
    except (TypeError, ValueError):
        return 0.0


def _rolling_labels(now: datetime | None = None) -> list[str]:
    current = (now or datetime.now(_TZ)).astimezone(_TZ)
    serial = current.year * 12 + current.month - 1
    labels: list[str] = []
    for offset in (-3, -2, -1, 0):
        value = serial + offset
        year, month0 = divmod(value, 12)
        labels.append(f"{_MONTHS[month0]}/{str(year)[-2:]}")
    return labels


def _profile(session: str | None) -> dict[str, Any]:
    if not session:
        raise HTTPException(status_code=401, detail="Sessão ausente.")
    try:
        profile = decode_session_token(
            session,
            secret=settings.jwt_secret,
            issuer=settings.jwt_issuer,
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="Sessão expirada.") from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail="Sessão inválida.") from exc

    usuario = normalizar(profile.get("usuario") or profile.get("sub") or "")
    tipo = normalizar(profile.get("tipo") or "")
    if usuario != "DANTON" or ("ADMIN" not in tipo and "ADMINISTRADOR" not in tipo):
        raise HTTPException(status_code=403, detail="Tela restrita ao administrador DANTON.")
    return profile


def _product(row: dict[str, Any], labels: list[str]) -> dict[str, Any]:
    sales = [_num(row.get(key)) for key in _SLOT_KEYS]
    stock = max(0.0, _num(row.get("estoque")))
    price = max(0.0, _num(row.get("preco")))
    map_average = max(0.0, _num(row.get("media")))

    # Tendência: último mês FECHADO versus os dois meses fechados anteriores.
    baseline = (sales[0] + sales[1]) / 2.0
    last_closed = sales[2]
    current = sales[3]

    if baseline > 0:
        variation = ((last_closed - baseline) / baseline) * 100.0
    elif last_closed > 0:
        variation = 100.0
    else:
        variation = 0.0

    # Média usada no DDE: usa a média oficial do Mapa; caso venha zerada,
    # calcula a média dos três meses fechados visíveis.
    completed_average = (sales[0] + sales[1] + sales[2]) / 3.0
    average_units = map_average if map_average > 0 else completed_average

    # Fórmula solicitada pelo usuário: média de unidades / estoque * 30.
    dde = (average_units / stock) * 30.0 if stock > 0 else 0.0

    low_sales = bool(baseline >= 2 and last_closed < baseline * 0.70)
    strong_drop = bool(baseline >= 2 and last_closed < baseline * 0.50)
    high_sales = bool(
        (baseline >= 2 and last_closed > baseline * 1.30)
        or (baseline <= 0 and last_closed >= 5)
    )
    no_turnover = bool(stock > 0 and average_units <= 0)
    out_of_stock = bool(stock <= 0 and average_units > 0)
    high_stock = bool(average_units > 0 and stock >= average_units * 4)
    stock_pressure = bool(stock > 0 and dde >= 30)
    severe_stock_pressure = bool(stock > 0 and dde >= 60)

    reasons: list[str] = []
    if out_of_stock:
        reasons.append("Sem estoque com histórico de venda")
    if severe_stock_pressure:
        reasons.append("Pressão alta de venda sobre o estoque")
    if strong_drop:
        reasons.append("Venda caiu mais de 50% no último mês fechado")
    if no_turnover:
        reasons.append("Estoque sem giro")
    critical = bool(out_of_stock or severe_stock_pressure or strong_drop or no_turnover)

    if out_of_stock:
        action = "REPOR / VERIFICAR RUPTURA"
    elif severe_stock_pressure or (high_sales and stock < max(1.0, average_units)):
        action = "GARANTIR ESTOQUE"
    elif no_turnover:
        action = "AÇÃO DE GIRO"
    elif low_sales and high_stock:
        action = "AÇÃO COMERCIAL + REVER ESTOQUE"
    elif low_sales:
        action = "INVESTIGAR QUEDA"
    elif high_sales:
        action = "MONITORAR ACELERAÇÃO"
    elif high_stock:
        action = "REVER COBERTURA"
    else:
        action = "MONITORAR"

    return {
        "codigo": str(row.get("codigo") or "").strip(),
        "ean": str(row.get("ean") or "").strip(),
        "produto": str(row.get("descricao") or "").strip(),
        "fornecedor": str(row.get("fornecedor") or row.get("laboratorio") or "").strip(),
        "curva": str(row.get("curva") or "").strip(),
        "preco": _round(price),
        "estoque": _round(stock, 3),
        "valorEstoque": _round(stock * price),
        "mediaUnidades": _round(average_units, 2),
        "mediaMapa": _round(map_average, 2),
        "meses": {labels[index]: _round(sales[index], 2) for index in range(4)},
        "historico": [_round(value, 2) for value in sales],
        "mediaAnterior": _round(baseline, 2),
        "ultimoMesFechado": _round(last_closed, 2),
        "mesAtual": _round(current, 2),
        "variacaoPct": _round(variation, 1),
        "dde": _round(dde, 1),
        "baixo": low_sales,
        "alta": high_sales,
        "critico": critical,
        "semGiro": no_turnover,
        "estoqueAlto": high_stock,
        "pressaoEstoque": stock_pressure,
        "ruptura": out_of_stock,
        "motivosCriticos": reasons,
        "acao": action,
        "estAte": str(row.get("est_ate") or "").strip(),
        "ultimaEntrada": str(row.get("ultima_entrada") or "").strip(),
        "bloqCompra": str(row.get("bloq_compra") or "").strip(),
    }


def _summary(products: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(products)
    with_stock = sum(1 for item in products if item["estoque"] > 0)
    criticals = sum(1 for item in products if item["critico"])
    lows = sum(1 for item in products if item["baixo"])
    highs = sum(1 for item in products if item["alta"])
    no_turnover = sum(1 for item in products if item["semGiro"])
    ruptures = sum(1 for item in products if item["ruptura"])
    stock_value = sum(float(item["valorEstoque"]) for item in products)
    units_stock = sum(float(item["estoque"]) for item in products)
    return {
        "produtos": total,
        "comEstoque": with_stock,
        "criticos": criticals,
        "queda": lows,
        "alta": highs,
        "semGiro": no_turnover,
        "rupturas": ruptures,
        "valorEstoque": _round(stock_value),
        "unidadesEstoque": _round(units_stock, 0),
    }


def _suppliers(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    data: dict[str, dict[str, Any]] = {}
    for item in products:
        name = str(item.get("fornecedor") or "SEM FORNECEDOR").strip() or "SEM FORNECEDOR"
        target = data.setdefault(name, {
            "fornecedor": name,
            "produtos": 0,
            "criticos": 0,
            "queda": 0,
            "alta": 0,
            "semGiro": 0,
            "valorEstoque": 0.0,
        })
        target["produtos"] += 1
        target["criticos"] += 1 if item["critico"] else 0
        target["queda"] += 1 if item["baixo"] else 0
        target["alta"] += 1 if item["alta"] else 0
        target["semGiro"] += 1 if item["semGiro"] else 0
        target["valorEstoque"] += float(item["valorEstoque"])
    rows = list(data.values())
    for row in rows:
        row["valorEstoque"] = _round(row["valorEstoque"])
    rows.sort(key=lambda row: (-row["criticos"], -row["queda"], row["fornecedor"].upper()))
    return rows


def _analyze(payload: dict[str, Any], row_meta: dict[str, Any]) -> dict[str, Any]:
    labels = _rolling_labels()
    rows = payload.get("linhas") if isinstance(payload.get("linhas"), list) else []
    products = [
        _product(row, labels)
        for row in rows
        if isinstance(row, dict)
        and (str(row.get("codigo") or "").strip() or str(row.get("descricao") or "").strip())
    ]
    products.sort(key=lambda item: (item["produto"].upper(), item["codigo"]))
    return {
        "sucesso": True,
        "fonte": "MAPA_ESTOQUE",
        "atualizadoEm": str(row_meta.get("atualizado_em") or ""),
        "versaoFonte": str(row_meta.get("versao") or ""),
        "meses": labels,
        "mesFechadoAnalisado": labels[2],
        "mesAtual": labels[3],
        "criterioTendencia": (
            f"{labels[2]} comparado à média de {labels[0]} e {labels[1]}. "
            f"{labels[3]} é exibido, mas não entra na tendência enquanto o mês estiver aberto."
        ),
        "formulaDDE": "média de unidades vendidas ÷ estoque × 30; em erro ou estoque zero, resultado 0",
        "resumo": _summary(products),
        "fornecedores": _suppliers(products),
        "produtos": products,
    }


def _patch_portal() -> None:
    try:
        text = PORTAL_FILE.read_text(encoding="utf-8")
    except Exception:
        return
    if _PORTAL_MARKER in text:
        return

    # Botão-base invisível no cabeçalho; o menu "Mais" replica essa ação.
    button_anchor = '<button id="btnResumoPremiacao"'
    if button_anchor in text and 'id="btnCommercialIntelligence"' not in text:
        button = (
            '<button id="btnCommercialIntelligence" onclick="location.href=\'/inteligencia-comercial\'" '
            'title="Inteligência Comercial" aria-label="Inteligência Comercial" '
            'class="hidden w-8 h-8 rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-200">'
            '<i class="fa-solid fa-chart-line"></i></button>\n                '
        )
        text = text.replace(button_anchor, button + button_anchor, 1)

    secondary_old = "    'btnIndustries',\n    'btnResumoPremiacao'"
    secondary_new = "    'btnIndustries',\n    'btnCommercialIntelligence',\n    'btnResumoPremiacao'"
    if secondary_old in text:
        text = text.replace(secondary_old, secondary_new, 1)

    css_old = "#userSessionBox > #btnIndustries,\n#userSessionBox > #btnResumoPremiacao"
    css_new = "#userSessionBox > #btnIndustries,\n#userSessionBox > #btnCommercialIntelligence,\n#userSessionBox > #btnResumoPremiacao"
    if css_old in text:
        text = text.replace(css_old, css_new, 1)

    script = r'''
<script>
// DISMEPE_COMMERCIAL_INTELLIGENCE_DANTON_V1
(function(){
  function norm(v){
    return String(v||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').trim().toUpperCase();
  }
  function allowed(){
    try{
      const u=(typeof currentUser!=='undefined'&&currentUser)?currentUser:window.currentUser;
      if(!u||norm(u.usuario)!=='DANTON')return false;
      if(typeof isAdmin==='function')return !!isAdmin(u);
      return norm(u.tipo).includes('ADMIN');
    }catch(e){return false;}
  }
  function sync(){
    const btn=document.getElementById('btnCommercialIntelligence');
    if(!btn)return;
    btn.classList.toggle('hidden',!allowed());
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',sync,{once:true});
  else sync();
  [300,800,1600,3000,5000].forEach(ms=>setTimeout(sync,ms));
  const box=document.getElementById('userSessionBox');
  if(box&&typeof MutationObserver!=='undefined'){
    new MutationObserver(sync).observe(box,{childList:true,subtree:true,attributes:true,attributeFilter:['class']});
  }
})();
</script>
'''
    pos = text.lower().rfind("</body>")
    if pos >= 0:
        text = text[:pos] + script + "\n" + text[pos:]

    try:
        temp = PORTAL_FILE.with_name(PORTAL_FILE.name + ".commercial-intelligence.tmp")
        temp.write_text(text, encoding="utf-8")
        temp.replace(PORTAL_FILE)
    except Exception:
        pass


def install_commercial_intelligence(app: Any) -> None:
    if getattr(app.state, "commercial_intelligence_installed", False):
        return
    app.state.commercial_intelligence_installed = True

    async def page(session: str | None = Cookie(default=None, alias=settings.cookie_name)):
        _profile(session)
        if not PAGE_FILE.exists():
            raise HTTPException(status_code=503, detail="Tela de Inteligência Comercial indisponível.")
        return FileResponse(
            PAGE_FILE,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )

    async def data(session: str | None = Cookie(default=None, alias=settings.cookie_name)):
        _profile(session)
        try:
            payload, row = await cache_get(modulo="MAPA_ESTOQUE", settings=settings)
        except CacheReadError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return _analyze(payload, row)

    app.add_api_route("/inteligencia-comercial", page, methods=["GET"], include_in_schema=False)
    app.add_api_route("/data/inteligencia-comercial", data, methods=["GET"])
    _patch_portal()
