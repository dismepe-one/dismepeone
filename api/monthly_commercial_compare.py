"""Comparacao comercial mensal somente-leitura, sem premios nem publicacao."""
from decimal import Decimal, InvalidOperation
from .monthly_source_normalization import normalized


class MonthlyComparisonError(ValueError):
    pass


def _number(value):
    try:
        result = Decimal(str(0 if value in (None, "") else value))
    except (ValueError, InvalidOperation, TypeError) as exc:
        raise MonthlyComparisonError("Numero comercial invalido") from exc
    if not result.is_finite():
        raise MonthlyComparisonError("Numero comercial invalido")
    return result


def compare_rows(source_rows, snapshot_rows, competence):
    """Retorna somente contagens; nunca nomes ou valores individuais."""
    def index(rows):
        result = {}
        for row in rows:
            if row.get("__COMPETENCIA") != competence:
                continue
            line = int(row["__linha"])
            if line in result:
                raise MonthlyComparisonError("Linha de origem duplicada")
            result[line] = row
        if not result:
            raise MonthlyComparisonError("Sem registros comparaveis")
        return result

    current, previous = index(source_rows), index(snapshot_rows)
    name_errors = amount_errors = focus_errors = 0
    for line in set(current) & set(previous):
        a, b = current[line], previous[line]
        if (normalized(a["__COLABORADOR"]) != normalized(b.get("__COLABORADOR"))
                or normalized(a["__LAB"]) != normalized(b.get("__LAB"))):
            name_errors += 1
        if any(abs(_number(a[k]) - _number(b.get(k))) > Decimal("0.015")
               for k in ("__OBJETIVO", "__VENDA")):
            amount_errors += 1
        if bool(a["__TEM_FOCO"]) != bool(b.get("__TEM_FOCO")):
            focus_errors += 1
    return {
        "fonte": len(current), "sql": len(previous),
        "novas": len(set(current) - set(previous)),
        "ausentes": len(set(previous) - set(current)),
        "identidadesDivergentes": name_errors,
        "numerosDivergentes": amount_errors,
        "focoDivergente": focus_errors,
    }
