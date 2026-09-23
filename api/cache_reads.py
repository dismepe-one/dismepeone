from __future__ import annotations

import copy
import json
from typing import Any

import httpx

from .config import Settings
from .security import normalizar


class CacheReadError(Exception):
    pass


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _round2(value: float) -> float:
    return round(float(value or 0), 2)


def _role(value: Any) -> str:
    return normalizar(value or "")


def _is_management(profile: dict[str, Any]) -> bool:
    role = _role(profile.get("tipo"))
    return (
        role in {
            "ADMINISTRADOR",
            "ADMIN",
            "COMERCIAL",
            "GERENTE DE VENDAS",
            "SUP VENDAS",
            "SUP TELEVENDAS",
        }
        or "SUPERVISOR" in role
    )


def _has_ped_permission(profile: dict[str, Any]) -> bool:
    if _is_management(profile):
        return True
    perms = profile.get("permissoes")
    if not isinstance(perms, dict):
        return False
    return perms.get("CLIENTES_PED_VISUALIZAR") is True


async def cache_get(
    *,
    modulo: str,
    settings: Settings,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Reads the operational snapshot directly from dismepe-admin/CACHE_GET.
    This bypasses:
      browser -> dismepe-gateway -> Apps Script

    New path:
      browser -> FastAPI -> dismepe-admin -> PostgreSQL snapshot
    """
    endpoint = (
        settings.supabase_url.rstrip("/")
        + "/functions/v1/dismepe-admin"
    )
    headers = {
        "apikey": settings.supabase_publishable_key,
        "x-dismepe-token": settings.edge_token,
        "content-type": "application/json",
        "accept": "application/json",
    }
    body = {
        "acao": "CACHE_GET",
        "modulo": str(modulo or "").strip().upper(),
    }

    try:
        async with httpx.AsyncClient(
            timeout=max(8.0, settings.request_timeout_seconds)
        ) as client:
            response = await client.post(
                endpoint,
                json=body,
                headers=headers,
            )
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise CacheReadError(
            "O snapshot não respondeu dentro do tempo esperado."
        ) from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise CacheReadError(
            f"O serviço de snapshot respondeu em formato inválido (HTTP {response.status_code})."
        ) from exc

    if response.status_code < 200 or response.status_code >= 300:
        raise CacheReadError(
            str(data.get("erro") or f"Snapshot HTTP {response.status_code}.")
        )

    if data.get("sucesso") is not True:
        raise CacheReadError(
            str(data.get("erro") or "Falha ao consultar o snapshot.")
        )

    if data.get("encontrado") is not True or not isinstance(data.get("cache"), dict):
        raise CacheReadError(
            f"Snapshot {str(modulo or '').strip().upper()} ainda não está disponível no PostgreSQL."
        )

    row = data["cache"]
    payload = row.get("payload")

    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError as exc:
            raise CacheReadError(
                f"Snapshot {str(modulo or '').strip().upper()} armazenado em formato inválido."
            ) from exc

    if not isinstance(payload, dict):
        raise CacheReadError(
            f"Snapshot {str(modulo or '').strip().upper()} não possui um payload válido."
        )

    return copy.deepcopy(payload), row


def _client_sector_code(row: dict[str, Any]) -> str:
    return normalizar(
        row.get("codigoSetorMeta")
        or row.get("codigoSetor")
        or ""
    )


def _client_sector_name(row: dict[str, Any]) -> str:
    return normalizar(
        row.get("setorMeta")
        or row.get("setor")
        or ""
    )


def _profile_candidates(profile: dict[str, Any]) -> set[str]:
    values = {
        normalizar(profile.get("vendedor") or ""),
        normalizar(profile.get("nome") or ""),
        normalizar(profile.get("usuario") or ""),
    }
    return {x for x in values if x}


def scope_clientes_ped(
    payload: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    """
    Applies a conservative access scope.

    Management roles receive the snapshot, but editing remains disabled in
    homologation.

    Individual users never receive the full snapshot unless their role is
    management. Their rows are restricted by:
      1) configured sector, or
      2) exact normalized collaborator name.

    If no safe scope can be resolved, returns an empty result instead of
    broadening access.
    """
    if not _has_ped_permission(profile):
        raise PermissionError(
            "Você não possui permissão para visualizar Clientes PED."
        )

    result = copy.deepcopy(payload)
    management = _is_management(profile)

    # Homologation is always read-only.
    meta_empresa = (
        result.get("metaEmpresa")
        if isinstance(result.get("metaEmpresa"), dict)
        else {}
    )
    meta_empresa = copy.deepcopy(meta_empresa)
    meta_empresa["podeEditar"] = False
    result["metaEmpresa"] = meta_empresa

    if management:
        result.update({
            "sucesso": True,
            "modulo": "CLIENTES_PED",
            "versao": "V2_SQL_PED",
            "origem": "SUPABASE_POSTGRESQL_DIRETO_V2",
            "banco": "SUPABASE",
            "cache": True,
            "escopoAcesso": "GESTAO",
        })
        return result

    role = _role(profile.get("tipo"))
    is_televendas = role == "TELEVENDAS" or "TELEVENDAS" in role
    candidates = _profile_candidates(profile)
    sector_profile = normalizar(profile.get("setor") or "")

    # A usuária PATRICIA GOMES pertence somente à dupla com MARCOS FELIPE
    # FERREIRA LIMA em Clientes PEDS. O nome da televendas, isoladamente,
    # aparece também em outra carteira e não autoriza essa segunda carteira.
    patricia_marcos_only = (
        is_televendas
        and normalizar(profile.get("usuario") or "") == "PATRICIA"
        and normalizar(profile.get("vendedor") or profile.get("nome") or "") == "PATRICIA GOMES"
    )

    def marcos_patricia_pair(row: Any) -> bool:
        return (
            isinstance(row, dict)
            and normalizar(row.get("vendedor") or "") in {
                "MARCOS FELIPE FERREIRA LIMA", "MARCOS FELIPE LIMA"
            }
            and normalizar(row.get("televendas") or "") == "PATRICIA GOMES"
        )

    # Resolver códigos a partir da matriz OFICIAL de metas, não apenas
    # de uma coincidência de nome em outra carteira do snapshot.
    patricia_pair_codes = (
        {
            normalizar(row.get("codigoSetor") or "")
            for row in (result.get("setoresMeta") or [])
            if marcos_patricia_pair(row) and normalizar(row.get("codigoSetor") or "")
        }
        if patricia_marcos_only else set()
    )

    clientes_all = (
        result.get("clientes")
        if isinstance(result.get("clientes"), list)
        else []
    )

    def allowed_client(row: Any) -> bool:
        if not isinstance(row, dict):
            return False

        if patricia_marcos_only:
            # Nunca usar o OR genérico por nome/setor para essa usuária.
            # Sem a dupla na matriz oficial, negar acesso ao invés de
            # atribuir outra carteira com o mesmo nome de televendas.
            return (
                bool(patricia_pair_codes)
                and _client_sector_code(row) in patricia_pair_codes
                and marcos_patricia_pair(row)
            )

        if sector_profile:
            if (
                _client_sector_code(row) == sector_profile
                or _client_sector_name(row) == sector_profile
            ):
                return True

        collaborator = normalizar(
            row.get("televendas") if is_televendas else row.get("vendedor")
        )
        return bool(collaborator and collaborator in candidates)

    clientes = [row for row in clientes_all if allowed_client(row)]

    allowed_codes = {
        _client_sector_code(row)
        for row in clientes
        if _client_sector_code(row)
    }

    setores_all = (
        result.get("setores")
        if isinstance(result.get("setores"), list)
        else []
    )
    setores_meta_all = (
        result.get("setoresMeta")
        if isinstance(result.get("setoresMeta"), list)
        else []
    )

    def allowed_sector(row: Any) -> bool:
        if not isinstance(row, dict):
            return False
        code = normalizar(row.get("codigoSetor") or "")
        name = normalizar(row.get("setor") or "")
        if patricia_marcos_only:
            return (
                bool(code)
                and code in patricia_pair_codes
                and code in allowed_codes
                and marcos_patricia_pair(row)
            )
        if code and code in allowed_codes:
            return True
        if sector_profile and sector_profile in {code, name}:
            return True
        collaborator = normalizar(
            row.get("televendas") if is_televendas else row.get("vendedor")
        )
        return bool(collaborator and collaborator in candidates)

    setores = [row for row in setores_all if allowed_sector(row)]
    setores_meta = [row for row in setores_meta_all if allowed_sector(row)]

    # Include sector codes resolved from setor metadata too.
    for row in setores_meta + setores:
        code = normalizar(row.get("codigoSetor") or "")
        if code:
            allowed_codes.add(code)

    total = len(clientes)
    positivados = sum(
        1 for row in clientes
        if str(row.get("status") or "").upper() == "POSITIVADO"
    )
    parciais = sum(
        1 for row in clientes
        if str(row.get("status") or "").upper() == "PARCIAL"
    )
    pendentes = sum(
        1 for row in clientes
        if str(row.get("status") or "").upper() == "PENDENTE"
    )

    resumo = {
        "total": total,
        "positivados": positivados,
        "parciais": parciais,
        "pendentes": pendentes,
        "percentual": _round2((positivados / total) * 100) if total else 0,
    }

    vendas_all = (
        result.get("vendasPorSetor")
        if isinstance(result.get("vendasPorSetor"), dict)
        else {}
    )
    vendas_por_setor: dict[str, Any] = {}

    allowed_names = {
        normalizar(row.get("setor") or "")
        for row in setores
        if isinstance(row, dict) and normalizar(row.get("setor") or "")
    }

    for key, value in vendas_all.items():
        nk = normalizar(key)
        if nk in allowed_codes or nk in allowed_names:
            vendas_por_setor[str(key)] = value

    valor_venda = sum(
        _num(
            vendas_all.get(str(row.get("codigoSetor") or "").strip(), 0)
        )
        for row in setores
        if isinstance(row, dict)
    )

    resumo_setor = {
        "total": total,
        "positivados": positivados,
        "parciais": parciais,
        "pendentes": pendentes,
        "percentual": resumo["percentual"],
        "valorVenda": _round2(valor_venda),
        "escopo": "SETOR",
    }

    meta_quantidade = sum(
        _num(row.get("metaQuantidade"))
        for row in setores_meta
        if isinstance(row, dict)
    )
    realizado_quantidade = sum(
        _num(row.get("realizadoQuantidade"))
        for row in setores_meta
        if isinstance(row, dict)
    )
    resumo_setor.update({
        "metaQuantidade": meta_quantidade,
        "realizadoQuantidade": realizado_quantidade,
        "faltaQuantidade": max(0, meta_quantidade - realizado_quantidade),
        "atingimentoMeta": (
            _round2((realizado_quantidade / meta_quantidade) * 100)
            if meta_quantidade > 0
            else 0
        ),
    })

    familias_all = (
        result.get("metaFamilias")
        if isinstance(result.get("metaFamilias"), list)
        else []
    )
    meta_familias: list[dict[str, Any]] = []

    for family in familias_all:
        if not isinstance(family, dict):
            continue
        family_copy = copy.deepcopy(family)
        setores_family = (
            family.get("setores")
            if isinstance(family.get("setores"), dict)
            else {}
        )
        subset: dict[str, Any] = {}

        meta = realizado = oportunidades = 0.0
        for code, data in setores_family.items():
            if normalizar(code) not in allowed_codes:
                continue
            if not isinstance(data, dict):
                continue
            subset[str(code)] = copy.deepcopy(data)
            meta += _num(data.get("metaSetor"))
            realizado += _num(data.get("realizadoSetor"))
            oportunidades += _num(data.get("oportunidades"))

        family_copy.update({
            "setores": subset,
            "metaGeral": meta,
            "realizadoGeral": realizado,
            "oportunidadesGeral": oportunidades,
            "faltaGeral": max(0, meta - realizado),
            "atingimentoGeral": (
                _round2((realizado / meta) * 100)
                if meta > 0
                else 0
            ),
            "quantidadeSetores": len(allowed_codes),
        })
        meta_familias.append(family_copy)

    meta_geral = sum(_num(x.get("metaGeral")) for x in meta_familias)
    realizado_geral = sum(
        _num(x.get("realizadoGeral")) for x in meta_familias
    )
    oportunidades = sum(
        _num(x.get("oportunidadesGeral")) for x in meta_familias
    )

    meta_empresa = {
        "metaGeral": meta_geral,
        "realizadoGeral": realizado_geral,
        "faltaGeral": max(0, meta_geral - realizado_geral),
        "atingimentoGeral": (
            _round2((realizado_geral / meta_geral) * 100)
            if meta_geral > 0
            else 0
        ),
        "totalOportunidades": oportunidades,
        "quantidadeSetores": len(allowed_codes),
        "podeEditar": False,
        "criterio": "META_POR_SETOR_ESCOPO_USUARIO_V2",
    }

    vendedores: list[str] = []
    televendas: list[str] = []
    for row in setores_meta:
        if not isinstance(row, dict):
            continue
        vendedor = str(row.get("vendedor") or "").strip()
        tlv = str(row.get("televendas") or "").strip()
        if vendedor and vendedor not in vendedores:
            vendedores.append(vendedor)
        if tlv and tlv not in televendas:
            televendas.append(tlv)

    result.update({
        "sucesso": True,
        "modulo": "CLIENTES_PED",
        "versao": "V2_SQL_PED",
        "origem": "SUPABASE_POSTGRESQL_DIRETO_V2",
        "banco": "SUPABASE",
        "cache": True,
        "clientes": clientes,
        "resumo": resumo,
        "resumoSetor": resumo_setor,
        "setores": setores,
        "setoresMeta": setores_meta,
        "vendasPorSetor": vendas_por_setor,
        "metaFamilias": meta_familias,
        "metaEmpresa": meta_empresa,
        "equipeCampanhas": {
            "vendedores": vendedores,
            "televendas": televendas,
        },
        "escopoAcesso": "SETOR",
        "setorPrincipal": next(iter(allowed_codes), ""),
        "setoresAcesso": sorted(allowed_codes),
    })
    return result


def _has_resumo_permission(profile: dict[str, Any]) -> bool:
    if _is_management(profile):
        return True

    role = _role(profile.get("tipo"))
    if role in {"CONTAS A PAGAR", "FINANCEIRO", "FINANCAS"}:
        return True

    perms = profile.get("permissoes")
    if not isinstance(perms, dict):
        return False

    return (
        perms.get("RESUMO_PREMIACOES") is True
        or perms.get("PREMIACOES_VISUALIZAR") is True
    )


def scope_resumo_ganhos(
    payload: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    """
    RESUMO_PREMIACOES is already a server-side calculated snapshot.
    Users only receive it when the same explicit summary permission exists.

    No recalculation is performed here.
    """
    if not _has_resumo_permission(profile):
        raise PermissionError(
            "Você não possui permissão para visualizar o Resumo de Ganhos."
        )

    result = copy.deepcopy(payload)

    registros = result.get("registros")
    if not isinstance(registros, list):
        result["registros"] = []

    totais = result.get("totais")
    if not isinstance(totais, dict):
        result["totais"] = {
            "total": 0,
            "vendedores": 0,
            "televendas": 0,
            "colaboradores": 0,
            "laboratorios": 0,
        }

    result.update({
        "sucesso": True,
        "modulo": "RESUMO_PREMIACOES",
        "origem": "SUPABASE_POSTGRESQL_DIRETO_V2",
        "banco": "SUPABASE",
        "cache": True,
        "transporte": "FASTAPI_SUPABASE_CACHE_GET",
    })
    return result


def _competencia_value(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("competencia") or value.get("COMPETENCIA") or ""
    text = str(value or "").strip()
    if not text:
        return ""

    # MM/YYYY
    if len(text) == 7 and text[2] == "/":
        mm, yyyy = text[:2], text[3:]
        if mm.isdigit() and yyyy.isdigit():
            return f"{int(mm):02d}/{int(yyyy):04d}"

    # YYYY-MM
    if len(text) == 7 and text[4] == "-":
        yyyy, mm = text[:4], text[5:]
        if mm.isdigit() and yyyy.isdigit():
            return f"{int(mm):02d}/{int(yyyy):04d}"

    # MM-YYYY
    if len(text) == 7 and text[2] == "-":
        mm, yyyy = text[:2], text[3:]
        if mm.isdigit() and yyyy.isdigit():
            return f"{int(mm):02d}/{int(yyyy):04d}"

    return text


def _row_competencia(row: Any) -> str:
    if not isinstance(row, dict):
        return ""
    return _competencia_value(
        row.get("__COMPETENCIA")
        or row.get("competencia")
        or row.get("Competencia")
        or row.get("Competência")
        or ""
    )


def _comp_order(comp: str) -> int:
    comp = _competencia_value(comp)
    try:
        mm, yyyy = comp.split("/")
        return int(yyyy) * 100 + int(mm)
    except Exception:
        return 0


def _latest_competencia(payload: dict[str, Any]) -> str:
    candidates: list[str] = []

    for item in payload.get("competencias") or []:
        comp = _competencia_value(item)
        if comp:
            candidates.append(comp)

    for row in list(payload.get("dadosVendedores") or []) + list(payload.get("dadosTelevendas") or []):
        comp = _row_competencia(row)
        if comp:
            candidates.append(comp)

    candidates = list(dict.fromkeys(candidates))
    candidates.sort(key=_comp_order, reverse=True)
    return candidates[0] if candidates else ""


def _profile_identity(profile: dict[str, Any]) -> str:
    return normalizar(
        profile.get("vendedor")
        or profile.get("nome")
        or profile.get("usuario")
        or ""
    )


def _row_collaborator(row: dict[str, Any], channel: str) -> str:
    if channel == "TELEVENDAS":
        return normalizar(
            row.get("__COLABORADOR")
            or row.get("colab")
            or row.get("Televendas")
            or row.get("televendas")
            or ""
        )
    return normalizar(
        row.get("__COLABORADOR")
        or row.get("colab")
        or row.get("Vendedor")
        or row.get("vendedor")
        or ""
    )


def scope_mensal_dashboard(
    payload: dict[str, Any],
    profile: dict[str, Any],
    competencia: str | None = None,
) -> dict[str, Any]:
    """
    Produz o payload inicial do painel diretamente do snapshot MENSAL.

    Objetivo:
    - não aguardar DADOS via gateway/Apps Script;
    - abrir Home/Vendedores/Televendas/Visão Geral com a fotografia pronta;
    - preservar o escopo individual de vendedor/televendas.
    """
    result = copy.deepcopy(payload)

    vend_all = (
        result.get("dadosVendedores")
        if isinstance(result.get("dadosVendedores"), list)
        else []
    )
    tlv_all = (
        result.get("dadosTelevendas")
        if isinstance(result.get("dadosTelevendas"), list)
        else []
    )

    comp = _competencia_value(competencia or "") or _latest_competencia(result)

    def in_comp(row: Any) -> bool:
        if not comp:
            return True
        return _row_competencia(row) == comp

    vend = [row for row in vend_all if in_comp(row)]
    tlv = [row for row in tlv_all if in_comp(row)]

    role = _role(profile.get("tipo"))
    identity = _profile_identity(profile)

    # Replica a regra do backend legado: somente perfis individuais são
    # reduzidos ao próprio colaborador; gestão continua vendo o conjunto.
    if role in {"VENDEDOR", "TELEVENDAS"}:
        vend = [
            row for row in vend
            if isinstance(row, dict)
            and _row_collaborator(row, "VENDEDOR") == identity
        ]
        tlv = [
            row for row in tlv
            if isinstance(row, dict)
            and _row_collaborator(row, "TELEVENDAS") == identity
        ]

    regras_all = (
        result.get("regrasPremiacao")
        if isinstance(result.get("regrasPremiacao"), list)
        else []
    )

    regras = []
    for row in regras_all:
        if not isinstance(row, dict):
            continue
        rc = _competencia_value(
            row.get("competencia")
            or row.get("COMPETENCIA")
            or ""
        )
        if not comp or not rc or rc == comp:
            regras.append(row)

    comps_raw = (
        result.get("competenciasDisponiveis")
        if isinstance(result.get("competenciasDisponiveis"), list)
        else (
            result.get("competencias")
            if isinstance(result.get("competencias"), list)
            else []
        )
    )
    competencias_disponiveis = copy.deepcopy(comps_raw)

    monthly_perms = (
        profile.get("permissoes")
        if isinstance(profile.get("permissoes"), dict)
        else {}
    )
    can_manage_monthly = _is_management(profile) or any(
        monthly_perms.get(key) is True
        for key in (
            "CAMPANHAS_MENSAIS_VISUALIZAR",
            "CAMPANHAS_MENSAIS_CRIAR",
            "CAMPANHAS_MENSAIS_EDITAR",
            "CAMPANHAS_MENSAIS_AGENDAR",
            "CADASTRO_CAMPANHAS_MENSAIS",
        )
    )

    gestao_campanhas_mensais = (
        copy.deepcopy(result.get("gestaoCampanhasMensaisLista"))
        if can_manage_monthly
        and isinstance(result.get("gestaoCampanhasMensaisLista"), list)
        else []
    )

    if competencia and comp:
        competencias_selecionadas = [comp]
    else:
        competencias_selecionadas = (
            copy.deepcopy(result.get("competenciasSelecionadas"))
            if isinstance(result.get("competenciasSelecionadas"), list)
            else ([comp] if comp else [])
        )

    campanha_mensal_atual = (
        copy.deepcopy(result.get("campanhaMensalAtual"))
        if isinstance(result.get("campanhaMensalAtual"), dict)
        else {}
    )
    campanha_original_comp = _competencia_value(
        campanha_mensal_atual.get("competencia") or ""
    )
    if competencia and campanha_original_comp and campanha_original_comp != comp:
        campanha_mensal_atual = {}

    dias_map = (
        result.get("diasUteisPorCompetencia")
        if isinstance(result.get("diasUteisPorCompetencia"), dict)
        else {}
    )
    dias = _num(dias_map.get(comp, 0))

    if not dias and comp:
        for item in comps_raw:
            if not isinstance(item, dict):
                continue
            if _competencia_value(item) != comp:
                continue
            dias = _num(
                item.get("diasUteisRestantes")
                or item.get("dias")
                or 0
            )
            break

    if not dias:
        dias = _num(
            campanha_mensal_atual.get("diasUteisRestantes")
            or 0
        )

    campanha_mensal_atual["competencia"] = (
        comp
        or _competencia_value(campanha_mensal_atual.get("competencia") or "")
    )
    campanha_mensal_atual["diasUteisRestantes"] = dias

    if not (
        isinstance(campanha_mensal_atual.get("competencias"), list)
        and campanha_mensal_atual.get("competencias")
    ):
        original_active = (
            result.get("competenciasAtivas")
            if isinstance(result.get("competenciasAtivas"), list)
            else []
        )
        campanha_mensal_atual["competencias"] = (
            copy.deepcopy(original_active)
            if original_active
            else ([comp] if comp else [])
        )

    return {
        "sucesso": True,
        "banco": "SUPABASE",
        "fonteDados": "POSTGRESQL",
        "transporte": "FASTAPI_BOOTSTRAP_MENSAL",
        "usuario": {
            "usuario": str(profile.get("usuario") or ""),
            "nome": str(profile.get("nome") or ""),
            "vendedor": str(profile.get("vendedor") or ""),
            "tipo": str(profile.get("tipo") or ""),
            "setor": str(profile.get("setor") or ""),
        },
        "permissoes": (
            copy.deepcopy(profile.get("permissoes"))
            if isinstance(profile.get("permissoes"), dict)
            else {}
        ),
        "competenciasAtivas": [comp] if comp else [],
        "competenciasSelecionadas": competencias_selecionadas,
        "competenciasDisponiveis": competencias_disponiveis,
        "competencias": competencias_disponiveis,
        "competenciaPrincipal": comp,
        "gestaoCampanhasMensaisLista": gestao_campanhas_mensais,
        "campanhaMensalAtual": campanha_mensal_atual,
        "diasUteisRestantes": dias,
        "diasUteisPorCompetencia": copy.deepcopy(dias_map),
        "dadosVendedores": vend,
        "dadosTelevendas": tlv,
        "regrasPremiacao": regras,
        "versaoCalculoVendedores": str(
            result.get("versaoCalculoVendedores") or ""
        ),
        "versaoDadosSql": str(result.get("versaoDadosSql") or ""),
    }
