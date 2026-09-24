"""Translate Defontana payloads into WMS documents (DefontanaMapper).

Campos reales (camelCase) verificados contra la API de pruebas. Defontana marca los
indicadores de maestro como ``"S"``/``"N"``.
"""
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional


def _parse_datetime(value: Any) -> Optional[datetime]:
    """Fecha ISO de Defontana (``2027-12-31T00:00:00``) → datetime UTC; vacía o inválida → None."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _qty(value: Any) -> Any:
    """Defontana envía las cantidades como float (``14.0``): entero si es exacto, para que
    calce con las cantidades escaneadas en picking."""
    value = value or 0
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def _yes(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().upper() == "S"
    return bool(value)


# Estados de cierre de un pedido (confirmados por soporte Defontana, 2026-09-15).
_WITHDRAWN_ORDER_CODES = {
    "N": "anulado",
    "M": "cerrado manualmente",
    "RC": "rechazado comercialmente",
    "RF": "rechazado financieramente",
}
_APPROVAL_ORDER_CODES = {"P", "A", "AC", "AF"}


class DefontanaMapper:
    @staticmethod
    def order_status_code(status: Optional[str]) -> str:
        """``"EEX (EN_DESPACHO_EN_FACTURACION)"`` → ``"EEX"``."""
        return (status or "").split(" ", 1)[0].strip().upper()

    @staticmethod
    def is_pending_dispatch(status: Optional[str]) -> bool:
        """La 1ª letra del código es el eje despacho: ``E`` = en despacho (el WMS lo
        prepara), ``D`` = ya despachado. La 2ª es facturación y la 3ª prestación."""
        code = DefontanaMapper.order_status_code(status)
        return code[:1] == "E"

    @staticmethod
    def order_no_longer_pending_reason(status: Optional[str]) -> Optional[str]:
        """Motivo por el que un pedido ya NO debe prepararse en el WMS, o ``None`` si sigue
        pendiente de guía (``E..``) o si el estado viene vacío (no se actúa a ciegas)."""
        code = DefontanaMapper.order_status_code(status)
        if not code or code[:1] == "E":
            return None
        if code in _WITHDRAWN_ORDER_CODES:
            return f"Pedido {_WITHDRAWN_ORDER_CODES[code]} en Defontana ({code})"
        if code[:1] == "D":
            return f"Guía de despacho ya emitida en Defontana ({code})"
        if code[:1] == "X":
            return f"Pedido sin despacho pendiente en Defontana ({code})"
        if code in _APPROVAL_ORDER_CODES:
            return f"Pedido volvió a aprobación en Defontana ({code})"
        return f"Pedido sin despacho pendiente en Defontana ({code})"

    @staticmethod
    def map_product(raw: Dict[str, Any]) -> Dict[str, Any]:
        # Defontana no entrega marca, familia ni código de barras en este listado: no se
        # incluyen, para no pisar lo que haya cargado el importador de Excel.
        code = raw.get("code")
        return {
            "erp_product_id": code,
            "sku": code,
            "name": raw.get("name") or "",
            "description": raw.get("detailedDescription") or None,
            "unit": raw.get("unit") or "UN",
            "uses_lots": bool(raw.get("usesLotes", False)),
            "uses_serials": bool(raw.get("usesSeries", False)),
            # ``type``: "A" = artículo; "S" = servicio.
            "is_service": str(raw.get("type") or "A").upper() == "S",
            "is_active": _yes(raw.get("active")),
            "raw_erp_data": raw,
        }

    @staticmethod
    def map_batches(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Lotes de un artículo de ``Inventory/GetBatchesInfo`` (por bodega, con stock y
        vencimiento). Referencia de Defontana: no mueve stock del WMS."""
        sku = raw.get("code")
        batches: List[Dict[str, Any]] = []
        for storage in raw.get("storageDetail") or []:
            for batch in storage.get("batchDetail") or []:
                if not batch.get("batchNumber"):
                    continue
                batches.append({
                    "sku": sku,
                    "storage_code": batch.get("storageID") or storage.get("storageID"),
                    "lot_number": batch.get("batchNumber"),
                    "stock": batch.get("stock") or 0,
                    "expiration_date": _parse_datetime(batch.get("expirationDate")),
                })
        return batches

    @staticmethod
    def map_stock(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Filas por bodega de ``Inventory/GetFutureStockInfo``: stock actual, reservado,
        por recibir y futuro según Defontana."""
        return [
            {
                "sku": storage.get("productCode") or raw.get("productCode"),
                "name": raw.get("description"),
                "storage_code": storage.get("storageCode"),
                "erp_stock": storage.get("currentStock") or 0,
                "erp_reserved": storage.get("reservedStock") or 0,
                "erp_to_receive": storage.get("maximumStockToReceive") or 0,
                "erp_future_stock": storage.get("maximumFutureStock") or 0,
            }
            for storage in raw.get("storageInfo") or []
        ]

    @staticmethod
    def map_order(header: Dict[str, Any], order: Dict[str, Any]) -> Dict[str, Any]:
        """``header`` = ítem de ``Order/List``; ``order`` = ``orderData`` de ``Order/Get``."""
        client = order.get("client") or {}
        details = sorted(order.get("details") or [], key=lambda d: d.get("line") or 0)
        lines: List[Dict[str, Any]] = [
            {
                "sku": d.get("code"),
                "name": d.get("name"),
                "unit": d.get("unit") or "UN",
                "ordered_quantity": _qty(d.get("count")),
            }
            for d in details
            if not d.get("isService")  # los servicios no se pickean
        ]
        return {
            "erp_order_number": str(order.get("number") or header.get("number")),
            "erp_document_id": None,
            "erp_status": header.get("status") or order.get("status"),
            "customer": client.get("name") if isinstance(client, dict) else None,
            "order_date": order.get("creationDate") or header.get("creationDate"),
            "delivery_date": order.get("expirationDate"),
            "lines": lines,
            "raw_erp_data": {"header": header, "order": order},
        }

    @staticmethod
    def build_inventory_entry(
        *,
        external_document_id: str,
        document_type: str,
        reason_id: str,
        business_center: str,
        centralizable: bool,
        storage_code: Optional[str],
        movement_date: date,
        gloss: str,
        lines: List[Dict[str, Any]],
        direction: str = "in",
    ) -> Dict[str, Any]:
        """Payload de ``Inventory/Insert`` para un movimiento de inventario del WMS.

        ``direction``: ``"in"`` (recepción o ajuste de entrada) usa la bodega como destino;
        ``"out"`` (ajuste de salida o merma) la usa como origen.

        Estructura verificada en el ambiente de pruebas (documento grabado, encontrado por
        ``externalDocumentID`` y eliminado): el centro de negocio va en el análisis de la
        cabecera y de cada línea, y cliente/proveedor/bodega de origen van nulos. Cada
        línea: ``code``, ``count``, ``price`` y opcionalmente ``description``,
        ``lot_number``, ``expiration_date`` y ``serial_number``.
        """

        def analysis() -> Dict[str, Any]:
            return {
                "againstEBusinessCenter": business_center, "againstEFile": "",
                "againstEFileFieldName": "", "businessCenter": business_center,
                "clasifier1": "", "clasifier2": "", "file": "", "fileFieldName": "",
            }

        details = []
        for line in lines:
            count = _qty(line["count"])
            lot = line.get("lot_number")
            expiration = line.get("expiration_date")
            details.append({
                "articleId": line["code"],
                "description": line.get("description") or "",
                "count": count,
                "coinId": "PESO",
                "comment": "",
                "price": line.get("price") or 0,
                "serials": [line["serial_number"]] if line.get("serial_number") else [],
                "lotes": [{
                    "batchNumber": lot,
                    "amount": count,
                    "expirationDate": f"{expiration:%Y-%m-%d}T00:00:00" if expiration else None,
                }] if lot else [],
                "analysis": analysis(),
            })
        return {
            "folio": 0,  # 0 = correlativo del ERP
            "documentTypeId": document_type,
            "fiscalYear": str(movement_date.year),
            "clientId": None,
            "providerId": None,
            "gloss": gloss,
            "originStowageId": storage_code if direction == "out" else None,
            "destinationStowageId": None if direction == "out" else storage_code,
            "reasonId": reason_id,
            "total": sum(d["count"] * d["price"] for d in details),
            "isCentralizable": centralizable,
            "analysis": analysis(),
            "referenceDocumentFolio": 0,
            "referenceDocumentType": None,
            "date": f"{movement_date:%Y-%m-%d}T00:00:00",
            "externalDocumentID": external_document_id,
            "details": details,
        }

    @staticmethod
    def build_dispatch_order(
        *,
        order_number: int,
        line_count: int,
        business_center: str,
        assets_type: str,
        dispatch_type: str,
        transaction_type: str,
        motive: str,
        storage_code: str,
        emission_date: date,
        gloss: str = "",
    ) -> Dict[str, Any]:
        """Payload de ``Order/DispatchOrder``: confirma el despacho de un pedido y emite la guía.

        Estructura tomada del swagger de pruebas (``Api.Defontana.Models.Order.DispatchOrderInput``,
        OpenAPI 3) y los valores de guías GDVELECT reales leídas el 2026-09-22:
        ``dispatchInfo`` con tipo de bien (``assetsType``) y tipo de despacho (``dispatchType``),
        y el centro de negocio en el análisis contable de cliente, bodega de origen y cada línea.

        ``line_count`` es la cantidad de líneas del pedido: ``orderDetailAnalysis`` lleva una
        entrada por línea (1..N) con el mismo centro de negocio, que es como aparece en las guías
        reales (cada línea con análisis "VENTAS").

        ``transaction_type`` y ``motive`` no salen de las guías (el primero es opcional y no
        aparece; el segundo se observó como ``COMPRA`` en el movimiento de inventario de una guía
        real, raro para un egreso): son configurables y hay que confirmarlos contra una emisión de
        prueba antes de encender el envío.
        """

        def analysis() -> Dict[str, Any]:
            return {
                "accountNumber": "", "businessCenter": business_center,
                "classifier01": "", "classifier02": "",
            }

        return {
            "orderNumber": order_number,
            "clientAnalysis": analysis(),
            "emissionDate": {
                "day": emission_date.day, "month": emission_date.month, "year": emission_date.year,
            },
            "dispatchInfo": {
                "assetsType": assets_type,
                "dispatchType": dispatch_type,
                "transactionType": transaction_type,
                "isTransferDispatch": False,
            },
            "originStorageInfo": {
                "code": storage_code, "motive": motive, "storageAnalysis": analysis(),
            },
            "orderDetailAnalysis": [
                {"line": i + 1, "isExempt": False, "discount": None, "detailAnalysis": analysis()}
                for i in range(max(line_count, 0))
            ],
            "gloss": gloss,
            "isTransferDocument": False,
        }

    @staticmethod
    def build_dispatch_save(
        *,
        dispatch: Dict[str, Any],
        order_raw: Dict[str, Any],
        storage_code: str,
        document_type: str,
        business_center: str,
        client_account: str,
        sale_account: str,
        inventory_account: str,
        assets_type: str,
        dispatch_type: str,
        transaction_type: str,
        motive: str,
        is_transfer_document: bool,
        emission_date: date,
        gloss: str = "",
    ) -> Dict[str, Any]:
        """Payload de ``POST /api/Dispatch/Save`` (guía de despacho, B.1). Reemplaza a
        ``build_dispatch_order``: ``Dispatch/Save`` es un documento de venta completo que **permite
        lote y serie por línea**, que es por lo que Defontana lo recomendó (spec en
        ``docs/entregables/Dispatch-Save-campos.md``).

        Las líneas y su desglose de **lote** salen del despacho del WMS (``dispatch['lines']`` con
        ``lots``, que ya viene FEFO desde el picking, Parte 2). La cabecera (cliente, condición de
        pago, vendedor, moneda, local, giro, comuna, región, precios) sale del **pedido original**
        de Defontana (``order_raw`` = ``Order/Get``), que es la fuente de esos datos comerciales.

        Lo que el WMS **no** decide —código del tipo de documento, ``Motive`` de la bodega y las
        **cuentas contables** (``AccountNumber``)— llega por parámetro desde la config; van vacíos
        hasta que Insumedent los defina (pendientes B.1 #2 y #3). ``FirstFolio``/``LastFolio`` en
        ``0`` para que el ERP tome el correlativo; ``Contact`` en ``-1`` como pide la spec.
        """
        client = order_raw.get("client") or {}
        details_by_code = {d.get("code"): d for d in (order_raw.get("details") or [])}
        emission = {"day": emission_date.day, "month": emission_date.month, "year": emission_date.year}

        def analysis(account: str) -> Dict[str, Any]:
            return {
                "AccountNumber": account, "BusinessCenter": business_center,
                "Classifier01": "", "Classifier02": "",
            }

        def line(dl: Dict[str, Any]) -> Dict[str, Any]:
            src = details_by_code.get(dl.get("sku")) or {}
            lots = dl.get("lots") or []
            return {
                "Type": "A",
                "IsExempt": bool(src.get("isExempt", False)),
                "Code": dl.get("sku"),
                "Count": _qty(dl.get("quantity")),
                "ProductName": dl.get("sku") and (src.get("name") or dl.get("sku")),
                "Price": src.get("price") or 0,
                "Comment": "",
                "Unit": src.get("unit") or "UN",
                "Analysis": analysis(sale_account),
                "analysisInventory": analysis(inventory_account),
                "UseBatch": bool(lots),
                "BatchInfo": [
                    {"Amount": _qty(l.get("quantity")), "BatchNumber": l.get("lot_number")}
                    for l in lots
                ],
                "UseSeries": False,
                "Serials": [],
            }

        storage = {
            "Code": storage_code, "Motive": motive, "StorageAnalysis": analysis(inventory_account),
        }
        return {
            "DocumentType": document_type,
            "FirstFolio": 0,
            "LastFolio": 0,
            "ExternalDocumentID": f"WMS-GD-{dispatch.get('_id') or dispatch.get('id') or ''}",
            "EmissionDate": emission,
            "FirstFeePaid": emission,
            "ClientFile": client.get("fileId"),
            "ContactIndex": client.get("address"),
            "PaymentCondition": order_raw.get("paymentConditionID"),
            "SellerFileId": order_raw.get("sellerID"),
            "BillingCoin": order_raw.get("billingCoindID"),
            "BillingRate": order_raw.get("billingRate") or 1,
            "ShopId": order_raw.get("shopID"),
            "PriceList": order_raw.get("referenceNumberPricingID"),
            "Giro": client.get("giro"),
            "District": client.get("district"),   # comuna
            "City": client.get("region"),         # la spec: City = código de la región
            "Contact": -1,
            "Gloss": gloss or order_raw.get("dispatchComment") or "",
            "ClientAnalysis": analysis(client_account),
            "AttachedDocuments": [],
            "IsTransferDocument": is_transfer_document,
            "OriginStorage": storage,
            # No es traslado entre bodegas: destino = origen (como pide la spec).
            "DestinationStorage": storage,
            "DispatchInfo": {
                "AssetsType": assets_type,
                "DispatchType": dispatch_type,
                "TransactionType": transaction_type,
                "IsTransferDispatch": False,
            },
            "Details": [line(dl) for dl in dispatch.get("lines", [])],
            "SaleTaxes": [],
            "VentaRecDesGlobal": [],
            "CustomFields": [],
        }

    @staticmethod
    def map_product_by_barcode(raw: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not raw:
            return None
        return DefontanaMapper.map_product(raw)
