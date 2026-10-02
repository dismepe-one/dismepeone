from __future__ import annotations

from typing import Any


_INSTALLED = False
_TARGET_ROW_COUNT = 4333
_MAX_QTY_CURRENT_FILE = 23632


def install_commercial_intelligence_complement_repair() -> None:
    global _INSTALLED
    if _INSTALLED:
        return

    from . import commercial_intelligence_complement as cc

    original_rpc = cc._rpc

    async def rpc_with_current_file_repair(
        action: str,
        owner: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        data = await original_rpc(action, owner, payload)
        if str(action or "").upper() != "GET":
            return data
        if data.get("encontrado") is not True:
            return data

        record = data.get("complemento") if isinstance(data.get("complemento"), dict) else {}
        row_count = int(record.get("row_count") or 0)
        file_name = str(record.get("file_name") or "")
        if row_count != _TARGET_ROW_COUNT or "Sugest" not in file_name or "lote" not in file_name.lower():
            return data

        comp_payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        lines = comp_payload.get("linhas") if isinstance(comp_payload.get("linhas"), list) else []
        changed = False

        for item in lines:
            if not isinstance(item, dict):
                continue
            try:
                qty = int(round(float(item.get("quantidadeUltimaEntrada") or 0)))
            except (TypeError, ValueError):
                qty = 0
            if qty > _MAX_QTY_CURRENT_FILE:
                qty = int(round(qty / 1000.0))
                item["quantidadeUltimaEntrada"] = qty
                changed = True

            lots = item.get("lotes") if isinstance(item.get("lotes"), list) else []
            for lot in lots:
                if not isinstance(lot, dict):
                    continue
                try:
                    lot_qty = int(round(float(lot.get("quantidadeUltimaEntrada") or 0)))
                except (TypeError, ValueError):
                    lot_qty = 0
                if lot_qty > _MAX_QTY_CURRENT_FILE:
                    lot["quantidadeUltimaEntrada"] = int(round(lot_qty / 1000.0))
                    changed = True
                elif lot_qty != qty and qty >= 0:
                    # O arquivo atual possui apenas um lote por código.
                    lot["quantidadeUltimaEntrada"] = qty
                    changed = True

        if changed:
            try:
                stored = await original_rpc(
                    "UPSERT",
                    owner,
                    {
                        "fileName": file_name[:240],
                        "rowCount": len(lines),
                        "payload": {"linhas": lines},
                    },
                )
                if isinstance(stored, dict):
                    record["payload"] = {"linhas": lines}
                    record["row_count"] = len(lines)
            except Exception:
                # Mesmo que a persistência falhe, a leitura corrente já sai corrigida.
                record["payload"] = {"linhas": lines}

        return data

    cc._rpc = rpc_with_current_file_repair
    _INSTALLED = True
