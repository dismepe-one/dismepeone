from __future__ import annotations


def install_industry_mes_ano_alias() -> None:
    from . import industry_competence_fields as fields

    original = getattr(fields, "_text_key", None)
    if not callable(original) or getattr(original, "__dismepe_mes_ano_alias__", False):
        return

    def text_key(value):
        key = original(value)
        # O cabeçalho oficial definido para OBJETIVO X VENDA.xlsx é "Mês/Ano".
        # A normalização remove acento e barra, resultando em "MES ANO".
        # Mapeamos apenas esse alias para "MES" para reutilizar o parser já existente.
        if key == "MES ANO":
            return "MES"
        return key

    text_key.__dismepe_mes_ano_alias__ = True
    text_key.__wrapped__ = original
    fields._text_key = text_key
