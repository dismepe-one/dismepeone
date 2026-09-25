"""Motor de calculo mensal em modo sombra (sem publicar ou modificar caches).

Migracao parcial, com bloqueio explicito para regras ainda nao reproduzidas.
Nunca usar para publicar o MENSAL sem paridade integral das fontes e premios.
"""
from __future__ import annotations
from collections import defaultdict
from decimal import Decimal, InvalidOperation
import re
import unicodedata
from typing import Any

class MonthlyAwardUnsupported(ValueError):
    pass

SIMPLE_METRICS = frozenset({"FATURAMENTO","OBJETIVO","ATINGIMENTO"})
SIMPLE_TYPES = frozenset({"VALOR_FIXO","PERCENTUAL_OBJETIVO","PERCENTUAL_VENDA"})

def normalized(value: Any) -> str:
    s=unicodedata.normalize("NFKD",str(value or ""))
    return "".join(c for c in s if not unicodedata.combining(c)).upper().strip()

def amount(value: Any) -> Decimal:
    if value is None or value=="": return Decimal(0)
    if isinstance(value,bool): raise MonthlyAwardUnsupported("Campo financeiro booleano.")
    s=str(value).replace("R$","").replace(" ","")
    if "," in s and "." in s:
        s=s.replace(".","").replace(",",".") if s.rfind(",")>s.rfind(".") else s.replace(",","")
    elif "," in s: s=s.replace(".","").replace(",",".")
    try:
        result=Decimal(s)
        if not result.is_finite(): raise InvalidOperation()
        return result
    except (InvalidOperation,ValueError) as e:
        raise MonthlyAwardUnsupported("Campo financeiro invalido.") from e

def channel(value: Any) -> str:
    name=normalized(value).replace(" ","_")
    if name in ("VENDEDOR","VENDEDORES","VENDAS"): return "VENDEDOR"
    if name in ("TELEVENDAS","TELE_VENDAS","TELEVENDA"): return "TELEVENDAS"
    if name in ("TODOS","AMBOS",""): return "TODOS"
    raise MonthlyAwardUnsupported("Canal invalido.")

def laboratory(value: Any) -> str:
    name=normalized(re.sub(r"\\s*-\\s*Prod\\.\\s*Foco\\s*\\(\\d+\\)\\s*$","",str(value or ""),flags=re.I))
    if name=="AGAPLASTIC" or name.startswith("AGAPLASTIC INDUSTRIA E COMERCIO"): return "AGAPLASTIC"
    if name=="BIOLAB" or name.startswith("BIOLAB "): return "BIOLAB"
    return name

def metric(value: Any) -> str:
    name=normalized(value).replace(" ","_").replace("-","_")
    return {"":"FATURAMENTO","VENDA":"FATURAMENTO","VENDAS":"FATURAMENTO",
            "REALIZADO":"FATURAMENTO","META":"OBJETIVO",
            "PERCENTUAL_META":"ATINGIMENTO","PERCENTUAL_ATINGIMENTO":"ATINGIMENTO"}.get(name,name)

def prize_type(value: Any) -> str:
    name=normalized(value).replace(" ","_").replace("-","_")
    return {"FIXO":"VALOR_FIXO","VALOR":"VALOR_FIXO",
            "PERCENTUAL_META":"PERCENTUAL_OBJETIVO",
            "PERCENTUAL_DA_META":"PERCENTUAL_OBJETIVO",
            "PERCENTUAL_DA_VENDA":"PERCENTUAL_VENDA"}.get(name,name)

def rule_coverage(rules: list[dict[str,Any]]) -> dict[str,Any]:
    if not isinstance(rules,list) or not rules: raise MonthlyAwardUnsupported("Regras mensais ausentes.")
    counts: dict[str,int]=defaultdict(int)
    pending: dict[str,int]=defaultdict(int)
    for r in rules:
        if not isinstance(r,dict): raise MonthlyAwardUnsupported("Regra invalida.")
        m=metric(r.get("metrica"));t=prize_type(r.get("tipo") or r.get("tipoPremiacao"))
        key=m+"/"+(t or "(SEM_TIPO)")
        counts[key]+=1
        if m not in SIMPLE_METRICS or t not in SIMPLE_TYPES: pending[key]+=1
    return {"total":len(rules),"por_tipo":dict(sorted(counts.items())),
            "nao_migradas":dict(sorted(pending.items())),"publicacao_permitida":False}

def group_rows(rows: list[dict[str,Any]]) -> list[dict[str,Any]]:
    if not isinstance(rows,list) or not rows: raise MonthlyAwardUnsupported("Fonte mensal ausente.")
    groups: dict[tuple[str,str,str,str],dict[str,Any]]={}
    for r in rows:
        if not isinstance(r,dict): raise MonthlyAwardUnsupported("Linha mensal invalida.")
        comp=str(r.get("__COMPETENCIA") or r.get("competencia") or "").strip()
        name=normalized(r.get("__COLABORADOR") or r.get("colab"))
        lab=laboratory(r.get("__LAB") or r.get("lab"))
        c=channel(r.get("__CANAL") or r.get("canal"))
        if not re.fullmatch(r"(?:0[1-9]|1[0-2])/20\\d{2}",comp) or not name or not lab or c=="TODOS":
            raise MonthlyAwardUnsupported("Linha mensal sem chave comercial valida.")
        k=(comp,name,lab,c)
        g=groups.setdefault(k,dict(competencia=comp,colaborador=name,laboratorio=lab,canal=c,
                                    objetivo=Decimal(0),venda=Decimal(0),objetivo_foco=Decimal(0),
                                    venda_foco=Decimal(0),tem_foco=False))
        foco_obj=amount(r.get("__OBJETIVO_FOCO"));foco_venda=amount(r.get("__VENDA_FOCO"))
        foco=r.get("__TEM_FOCO") is True and (bool(str(r.get("__CODIGO_FOCO") or "").strip()) or foco_obj>0 or foco_venda>0)
        if foco:
            g["tem_foco"]=True;g["objetivo_foco"]+=foco_obj;g["venda_foco"]+=foco_venda
        else:
            g["objetivo"]+=amount(r.get("__OBJETIVO",r.get("objetivo")))
            g["venda"]+=amount(r.get("__VENDA",r.get("venda")))
    return [groups[k] for k in sorted(groups)]

def simple_award(group: dict[str,Any], rules: list[dict[str,Any]]) -> Decimal:
    """Premio de referencia apenas para regras simples, jamais publica resultado."""
    selected=[r for r in rules if isinstance(r,dict) and r.get("ativo") is not False
              and str(r.get("competencia") or "")==group["competencia"]
              and laboratory(r.get("laboratorio"))==group["laboratorio"]
              and channel(r.get("canal")) in ("TODOS",group["canal"])]
    specific=[r for r in selected if channel(r.get("canal"))==group["canal"]]
    if specific: selected=specific
    if not selected:return Decimal(0)
    if group["laboratorio"] in ("HERBAMED","GLOBO","INTEGRALMEDICA"):
        raise MonthlyAwardUnsupported("Premiacao especial depende de bases auxiliares.")
    if any(metric(r.get("metrica")) not in SIMPLE_METRICS or
           prize_type(r.get("tipo") or r.get("tipoPremiacao")) not in SIMPLE_TYPES or
           r.get("exigeSomaLaboratorio") is True for r in selected):
        raise MonthlyAwardUnsupported("Regra ou fonte auxiliar nao migrada.")
    meta=group["objetivo"];venda=group["venda"]
    if group["tem_foco"] and (meta<=0 or venda<meta or group["objetivo_foco"]<=0 or group["venda_foco"]<group["objetivo_foco"]):
        return Decimal(0)
    if any(r.get("exigeFoco") is True for r in selected) and not group["tem_foco"]:
        raise MonthlyAwardUnsupported("Produto foco exigido sem fonte verificavel.")
    ating=venda/meta*100 if meta>0 else Decimal(0)
    eligible=[]
    for r in selected:
        m=metric(r.get("metrica"))
        base={"FATURAMENTO":venda,"OBJETIVO":meta,"ATINGIMENTO":ating}[m]
        minimum=amount(r.get("minAtingimento"))
        if group["laboratorio"]=="UNIPHAR":
            if meta<=0 or venda<meta:continue
            base=meta
        if group["competencia"]=="08/2026" and group["laboratorio"]=="ARTE NATIVA" and group["canal"]=="VENDEDOR" and m=="FATURAMENTO":
            if meta<=0 or venda<meta or minimum<meta:continue
        maximum=r.get("maxAtingimento")
        if base>=minimum and (maximum is None or base<=amount(maximum)):
            eligible.append((minimum,r))
    if not eligible:return Decimal(0)
    chosen=sorted(eligible,key=lambda item:item[0],reverse=True)[0][1]
    value=amount(chosen.get("valor"))
    kind=prize_type(chosen.get("tipo") or chosen.get("tipoPremiacao"))
    return meta*value/100 if kind=="PERCENTUAL_OBJETIVO" else venda*value/100 if kind=="PERCENTUAL_VENDA" else value
