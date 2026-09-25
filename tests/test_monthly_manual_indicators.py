"""Indicadores manuais precisam vir do SQL; ausência nunca equivale a zero."""
from decimal import Decimal

import pytest

from api.monthly_manual_indicators import (
    MonthlyManualIndicatorError,
    parse_manual_indicators,
)


def _response(**override):
    data = {
        "FATURAMENTO_GERAL_MANUAL": 115076.68,
        "POSITIVACAO_GERAL_MANUAL": 335,
    }
    data.update(override)
    return {"sucesso": True, "valores": data}


def test_ler_valores_manualmente_confirmados():
    result = parse_manual_indicators(_response())
    assert result["FATURAMENTO_GERAL_MANUAL"] == Decimal("115076.68")
    assert result["POSITIVACAO_GERAL_MANUAL"] == Decimal(335)


@pytest.mark.parametrize("bad", [None, "", "invalido", float("nan"), -1, True])
def test_indicador_invalido_bloqueia(bad):
    with pytest.raises(MonthlyManualIndicatorError):
        parse_manual_indicators(_response(POSITIVACAO_GERAL_MANUAL=bad))


def test_indicador_ausente_nao_assume_zero():
    result = _response()
    del result["valores"]["FATURAMENTO_GERAL_MANUAL"]
    with pytest.raises(MonthlyManualIndicatorError):
        parse_manual_indicators(result)


def test_sql_nao_confirmado_rejeitado():
    with pytest.raises(MonthlyManualIndicatorError):
        parse_manual_indicators({"sucesso": False, "valores": _response()["valores"]})
