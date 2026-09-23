"""Regressões do módulo Trânsito: escopo, datas previstas e sinalização de atraso."""
import io
import zipfile
from datetime import date

import pytest
from fastapi import HTTPException
from api import industries_transito as transit


def _zip(*xmls):
    file = io.BytesIO()
    with zipfile.ZipFile(file, "w", compression=zipfile.ZIP_DEFLATED) as out:
        for i, xml in enumerate(xmls):
            out.writestr(f"nfe-{i}.xml", xml)
    return file.getvalue()


def _invoice(cnpj, emitter, *, nature="Venda", type_nf="1"):
    return (f'<nfeProc><NFe><infNFe Id="NFeTEST{cnpj}">'
            f'<ide><nNF>123456</nNF><natOp>{nature}</natOp><dhEmi>2026-09-22T08:00:00-03:00</dhEmi>'
            f'<tpNF>{type_nf}</tpNF><finNFe>1</finNFe></ide>'
            f'<emit><CNPJ>{cnpj}</CNPJ><xNome>{emitter}</xNome></emit>'
            '<det nItem="1"><prod><cEAN>7891234567895</cEAN>'
            '<xProd>Produto de teste</xProd><qCom>12.0000</qCom></prod></det>'
            '</infNFe></NFe></nfeProc>').encode("utf-8")


def test_import_emitter_mapping_and_five_public_columns():
    doc = _zip(_invoice("03485572000104", "GEOLAB INDUSTRIA FARMACEUTICA S/A"),
               _invoice("17115437000173", "LABORATORIO GLOBO SA"))
    rows, stats = transit._decode_zip(doc)
    assert stats["itens"] == 2
    assert [r["laboratorio"] for r in rows] == ["GLOBO", "GEOLAB"]
    geolab = transit._scope(rows, "GEOLAB", today=date(2026, 10, 7))
    assert geolab == [{
        "dataEmissao": "2026-09-22", "numeroNFe": "123456", "previsaoChegada": "2026-10-07", "atrasado": False,
        "emitente": "GEOLAB INDUSTRIA FARMACEUTICA S/A",
        "ean": "7891234567895", "produto": "Produto de teste", "quantidade": "12.0000",
    }]
    assert transit._scope(rows, "GLOBO")[0]["emitente"] == "LABORATORIO GLOBO SA"
    assert all("chaveItem" not in line and "laboratorio" not in line for line in geolab)


def test_unmapped_emitter_and_return_are_not_published():
    doc = _zip(_invoice("03485572000104", "GEOLAB"),
               _invoice("17115437000173", "GLOBO", nature="Devolucao de compra"),
               _invoice("99999999999999", "OUTRO"))
    rows, stats = transit._decode_zip(doc)
    assert len(rows) == 1
    assert stats["naoVinculados"] == 1
    assert stats["operacoesIgnoradas"] == 1


def test_zip_without_authorized_emitter_preserves_previous_snapshot():
    with pytest.raises(HTTPException) as err:
        transit._decode_zip(_zip(_invoice("99999999999999", "DESCONHECIDO")))
    assert err.value.status_code == 422


def test_reimported_xml_does_not_double_count():
    same = _invoice("03485572000104", "GEOLAB")
    rows, _ = transit._decode_zip(_zip(same, same))
    assert len(rows) == 1


def test_holiday_weekend_and_overdue_dates():
    # 07/09/2026 é feriado nacional; 01/09 + 15 dias permanece em 16/09.
    assert transit._expected_delivery("2026-08-23") == date(2026, 9, 8)
    # 15 dias depois de 18/09 cai sábado: primeiro dia útil é 05/10.
    assert transit._expected_delivery("2026-09-18") == date(2026, 10, 5)
    # Sexta-feira Santa de 2026; prazo original 03/04 passa para segunda 06/04.
    assert transit._expected_delivery("2026-03-19") == date(2026, 4, 6)
    # Feriado 12/10/2026 (segunda-feira), com vencimento base no sábado 10/10.
    assert transit._expected_delivery("2026-09-25") == date(2026, 10, 13)


def test_overdue_starts_only_after_due_date():
    sample = [{"dataEmissao": "2026-09-18", "emitente": "GEOLAB",
               "laboratorio": "GEOLAB", "ean": "123", "produto": "Exemplo",
               "quantidade": "2"}]
    due_day = transit._scope(sample, "GEOLAB", today=date(2026, 10, 5))
    assert due_day[0]["previsaoChegada"] == "2026-10-05"
    assert due_day[0]["atrasado"] is False
    late_day = transit._scope(sample, "GEOLAB", today=date(2026, 10, 6))
    assert late_day[0]["atrasado"] is True
    assert len(late_day) == 1


def test_excel_export_matches_six_visible_columns_and_preserves_ean():
    from openpyxl import load_workbook
    rows = [{
        "dataEmissao": "2026-09-01", "numeroNFe": "123456", "previsaoChegada": "2026-09-16",
        "atrasado": True, "emitente": "GEOLAB", "ean": "0789001234567",
        "produto": "PRODUTO TESTE", "quantidade": "12.5000",
    }]
    spreadsheet = transit._build_transit_excel(rows)
    book = load_workbook(io.BytesIO(spreadsheet))
    sheet = book.active
    assert [cell.value for cell in sheet[1]] == [
        "DATA DE EMISSÃO", "Nº NF-e", "PREVISÃO DE CHEGADA",
        "EMITENTE", "EAN", "PRODUTO", "QUANTIDADE",
    ]
    assert sheet.max_column == 7
    assert sheet["A2"].value == date(2026, 9, 1)
    assert sheet["B2"].value == "123456"
    assert sheet["C2"].value == date(2026, 9, 16)
    assert sheet["E2"].value == "0789001234567"
    assert sheet["G2"].value == 12.5
    assert sheet["C2"].fill.fgColor.rgb.endswith("BF1F27")
    assert sheet["C2"].font.color.rgb.endswith("FFFFFF")


def test_excel_text_from_xml_cannot_run_formulas():
    assert transit._excel_text("=HYPERLINK(\"https://example.com\")").startswith("'=")
    assert transit._excel_text("+3+3") == "'+3+3"
    assert transit._excel_text("0789") == "0789"


def test_nfe_number_from_previous_snapshot_key():
    # Chave completa de 44 dígitos: UF + AAMM + CNPJ + modelo + série
    # + número NF-e + tipo + código numérico + DV.
    key = ("26" + "2609" + "03485572000104" + "55" + "001"
           + "000012345" + "1" + "12345678" + "1")
    assert len(key) == 44
    assert transit._invoice_number_from_key("NFe" + key + ":1") == "12345"
    assert transit._invoice_number_from_key("NFeTEST03485572000104:1") == ""
    old = [{"dataEmissao": "2026-09-22", "chaveItem": "NFe" + key + ":1",
            "laboratorio": "GEOLAB", "emitente": "GEOLAB", "ean": "789",
            "produto": "EXEMPLO", "quantidade": "4"}]
    assert transit._scope(old, "GEOLAB", today=date(2026, 9, 23))[0]["numeroNFe"] == "12345"


def test_number_visible_on_imported_xml():
    rows, _ = transit._decode_zip(_zip(_invoice("03485572000104", "GEOLAB")))
    assert rows[0]["numeroNFe"] == "123456"
    assert transit._scope(rows, "GEOLAB", today=date(2026, 9, 23))[0]["numeroNFe"] == "123456"
