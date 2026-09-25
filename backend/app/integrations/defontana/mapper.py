"""Translate Defontana payloads into WMS documents (DefontanaMapper).

Campos reales (camelCase) verificados contra la API de pruebas. Defontana marca los
indicadores de maestro como ``"S"``/``"N"``.
"""
import re
from datetime import date, datetime, timedelta, timezone
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


def _erp_date(value: Any) -> Dict[str, int]:
    """Fecha en la forma que usa Defontana (``{day, month, year}``); acepta date o datetime."""
    return {"day": value.day, "month": value.month, "year": value.year}


def _credit_days(payment_condition: Any) -> int:
    """Días de plazo de una condición de pago de Defontana, para calcular el vencimiento
    (``firstFeePaid``). Al contado son 0; a crédito los días van en el propio código
    (``CREDITO30`` → 30, ``CREDITO60`` → 60). Confirmado por Luis (Defontana) el 2026-09-25: el ERP
    **no** calcula el vencimiento, hay que enviarlo. Si el código no trae número, se asume contado."""
    if not payment_condition:
        return 0
    match = re.search(r"\d+", str(payment_condition))
    return int(match.group()) if match else 0


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
        storage_account: str,
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
        lote y serie por línea**, que es por lo que Defontana lo recomendó.

        Estructura y valores alineados al ejemplo que Defontana (Luis) devolvió el 2026-09-25
        (``docs/entregables/Dispatch-Save-ejemplo.json``):

        - **claves en camelCase con minúscula inicial** (``documentType``, ``clientFile``…);
        - ``attachedDocuments`` referencia la **Nota de Pedido** (``documentTypeId`` ``"802"``,
          folio = nº de pedido) que da origen a la guía. La Orden de Compra (``"801"``), cuando
          exista, la suma Insumedent: el WMS no siempre la tiene (pendiente confirmar si es obligatoria);
        - ``businessCenter`` **solo** en el análisis de la bodega; vacío en cliente y líneas;
        - ``saleTaxes`` con el **IVA 19 %** cuando hay al menos una línea afecta.

        Las líneas y su desglose de **lote** salen del despacho del WMS (``dispatch['lines']`` con
        ``lots``, que ya viene FEFO desde el picking, Parte 2). La cabecera (cliente, condición de
        pago, vendedor, moneda, local, giro, comuna, región, precios) sale del **pedido original**
        de Defontana (``order_raw`` = ``Order/Get``).

        Lo que el WMS **no** decide —código del tipo de documento, ``motive`` de la bodega y las
        **cuentas contables**— llega por parámetro desde la config. ``firstFolio``/``lastFolio`` en
        ``0`` para que el ERP tome el correlativo; ``contact`` en ``-1`` como pide la spec.
        """
        client = order_raw.get("client") or {}
        details_by_code = {d.get("code"): d for d in (order_raw.get("details") or [])}
        emission = _erp_date(emission_date)
        # Vencimiento del primer pago: al contado = emisión; a crédito = emisión + los días del plazo.
        first_fee_paid = _erp_date(emission_date + timedelta(days=_credit_days(order_raw.get("paymentConditionID"))))

        def analysis(account: str, bc: str = "") -> Dict[str, Any]:
            return {
                "accountNumber": account, "businessCenter": bc,
                "classifier01": "", "classifier02": "",
            }

        def line(dl: Dict[str, Any]) -> Dict[str, Any]:
            src = details_by_code.get(dl.get("sku")) or {}
            lots = dl.get("lots") or []
            return {
                "type": "A",
                "isExempt": bool(src.get("isExempt", False)),
                "code": dl.get("sku"),
                "count": _qty(dl.get("quantity")),
                "productName": src.get("name") or dl.get("sku"),
                "productNameBarCode": "",
                "price": src.get("price") or 0,
                "comment": "",
                "discount": {"type": 0, "value": 0},
                "especificTax": {"value": 0},
                "unit": src.get("unit") or "UN",
                # cliente y líneas van sin centro de negocio (según el ejemplo de Defontana).
                "analysis": analysis(sale_account),
                "analysisInventory": analysis(inventory_account),
                "useBatch": bool(lots),
                "batchInfo": [
                    {"amount": _qty(l.get("quantity")), "batchNumber": l.get("lot_number")}
                    for l in lots
                ],
                "useSeries": False,
                "serials": [],
                "serialStart": "",
                "serialSufix": "",
                "serialPrefix": "",
            }

        # La bodega de origen sí lleva el centro de negocio. Origen = destino: no es traslado.
        storage = {
            "code": storage_code, "motive": motive,
            "storageAnalysis": analysis(storage_account, business_center),
        }
        details = [line(dl) for dl in dispatch.get("lines", [])]

        # La Nota de Pedido que origina la guía (folio = nº de pedido de Defontana).
        attached: List[Dict[str, Any]] = []
        order_number = order_raw.get("number")
        if order_number is not None:
            pedido_date = _parse_datetime(order_raw.get("creationDate"))
            attached.append({
                "date": _erp_date(pedido_date.date() if pedido_date else emission_date),
                "documentTypeId": "802",
                "folio": str(order_number),
                "reason": f"Nota de Pedido {order_number}",
            })

        # IVA 19 % si hay al menos una línea afecta; las cuentas de impuesto las resuelve el ERP.
        sale_taxes: List[Dict[str, Any]] = []
        if any(not d["isExempt"] for d in details):
            sale_taxes.append({
                "code": "IVA", "value": 19,
                "taxAnalysis": {"accountNumber": "", "businessCenter": "",
                                "classifier01": "", "classifier02": ""},
            })

        return {
            "documentType": document_type,
            "firstFolio": 0,
            "lastFolio": 0,
            "externalDocumentID": f"WMS-GD-{dispatch.get('_id') or dispatch.get('id') or ''}",
            "emissionDate": emission,
            "firstFeePaid": first_fee_paid,
            "clientFile": client.get("fileId"),
            "contactIndex": client.get("address"),
            "paymentCondition": order_raw.get("paymentConditionID"),
            "sellerFileId": order_raw.get("sellerID"),
            "clientAnalysis": analysis(client_account),
            "billingCoin": order_raw.get("billingCoindID"),
            "billingRate": order_raw.get("billingRate") or 1,
            "shopId": order_raw.get("shopID"),
            "priceList": order_raw.get("referenceNumberPricingID"),
            "giro": client.get("giro"),
            "district": client.get("district"),   # comuna
            "city": client.get("region"),         # la spec: city = código de la región
            "contact": -1,
            "attachedDocuments": attached,
            "originStorage": storage,
            "destinationStorage": storage,
            "dispatchInfo": {
                "assetsType": assets_type,
                "dispatchType": dispatch_type,
                "transactionType": transaction_type,
                "isTransferDispatch": False,
            },
            "details": details,
            "saleTaxes": sale_taxes,
            "ventaRecDesGlobal": [],
            "gloss": gloss or order_raw.get("dispatchComment") or "",
            "customFields": [],
            "isTransferDocument": is_transfer_document,
        }

    @staticmethod
    def map_product_by_barcode(raw: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not raw:
            return None
        return DefontanaMapper.map_product(raw)
