"""Regressões do novo módulo Trânsito (somente cinco campos e escopo por laboratório)."""
import io
import zipfile

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
            f'<ide><natOp>{nature}</natOp><dhEmi>2026-09-22T08:00:00-03:00</dhEmi>'
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
    geolab = transit._scope(rows, "GEOLAB")
    assert geolab == [{
        "dataEmissao": "2026-09-22", "emitente": "GEOLAB INDUSTRIA FARMACEUTICA S/A",
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
