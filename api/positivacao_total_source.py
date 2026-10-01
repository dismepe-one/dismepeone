from __future__ import annotations

from typing import Any


_INSTALLED = False


def install_positivacao_total_source() -> None:
    """Exibe no consolidado geral todas as positivações válidas da planilha.

    A Positivação Geral cruza a planilha de vendas com a carteira do PDF. Clientes
    presentes na planilha, mas ausentes da carteira, não podem ser atribuídos a um
    vendedor/televendas. Eles permanecem em `positivadosForaCarteira`, porém o card
    corporativo deve refletir o total da fonte: vinculados + fora da carteira.

    Rankings, percentuais e recortes individuais continuam intactos e usam apenas
    os clientes efetivamente vinculados à carteira.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    try:
        from . import positivacao_geral as module
    except Exception:
        return

    original = getattr(module, "_visible_data", None)
    if not callable(original) or getattr(original, "__dismepe_total_source__", False):
        _INSTALLED = True
        return

    def visible_data_with_source_total(data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        result = original(data, context)
        if not isinstance(result, dict):
            return result

        raw_indicators = data.get("indicadores") if isinstance(data, dict) else None
        if not isinstance(raw_indicators, dict):
            return result

        linked = int(raw_indicators.get("positivados") or 0)
        outside = int(raw_indicators.get("positivadosForaCarteira") or 0)
        source_total = linked + outside

        if context.get("view_all"):
            indicators = result.get("indicadores")
            if isinstance(indicators, dict):
                # Copiar para nunca mutar a fotografia persistida/cacheada.
                indicators = dict(indicators)
                indicators["positivados"] = source_total
                indicators["positivadosNaCarteira"] = linked
                indicators["positivadosForaCarteira"] = outside
                result = {**result, "indicadores": indicators}
        else:
            general = result.get("geralEmpresa")
            if isinstance(general, dict):
                general = dict(general)
                general["positivados"] = source_total
                general["positivadosNaCarteira"] = linked
                general["positivadosForaCarteira"] = outside
                result = {**result, "geralEmpresa": general}

        return result

    visible_data_with_source_total.__dismepe_total_source__ = True
    visible_data_with_source_total.__wrapped__ = original
    module._visible_data = visible_data_with_source_total
    _INSTALLED = True
