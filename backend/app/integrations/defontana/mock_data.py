"""Simulated Defontana payloads used when DEFONTANA_MOCK=true.

Mirror the real API shapes (camelCase, "S"/"N" flags), as verified against
replapi.defontana.com, so the mock exercises the same mapper and sync path as the
real connector without any network call.
"""

# Dental products (subset of the real INSUMEDENT catalog), as returned inside
# ``Sale/GetSimpleProducts.productList``.
_ANEST_DESC = "Agente/insumo anestésico para procedimientos dentales sin dolor."


def _product(code: str, name: str) -> dict:
    return {
        "active": "S",
        "code": code,
        "externalCode": None,
        "internalCode": None,
        "name": name,
        "detailedDescription": _ANEST_DESC,
        "coinID": "PESO",
        "sellPrice": 0.0,
        "stock": 0.0,
        "type": "A",
        "unit": "UN",
        "usesLotes": False,
        "usesSeries": False,
    }


MOCK_PRODUCTS = [
    _product("ANES008", "ANESTESIA ALPHACAINE 2%"),
    _product("ANES012", "ANESTESIA ARTICAINE 4% DFL"),
    _product("ANES002", "ANESTESIA ISOCAINE 3%"),
    _product("ANES016", "ANESTESIA MEPIADRE MEPIVACAINA AL 2% DFL"),
    _product("ANES009", "ANESTESIA MEPISV 3%"),
]

# Barcode → product code for the mock barcode lookup. Match the seed
# (app/data/demo_catalog.json) so the mock stays consistent with the demo data.
MOCK_BARCODES = {
    "2000000000013": "ANES008",
    "2000000000022": "ANES012",
    "2000000000031": "ANES002",
    "2000000000040": "ANES016",
    "2000000000059": "ANES009",
}

# ``Sale/GetStorages.storageList``
MOCK_STORAGES = [
    {"code": "01", "description": "BODEGA CENTRAL", "saleAvailable": "S", "active": "S"},
    {"code": "02", "description": "BODEGA SECUNDARIA", "saleAvailable": "S", "active": "S"},
]

# ``Order/List.items``: only headers. One order still in dispatch (imported) and one
# already dispatched (ignored by the sync).
MOCK_ORDERS = [
    {
        "number": 1001,
        "creationDate": "2026-06-29T00:00:00",
        "clientFileId": "76123456-7",
        "status": "EEX (EN_DESPACHO_EN_FACTURACION)",
    },
    {
        "number": 998,
        "creationDate": "2026-06-20T00:00:00",
        "clientFileId": "76123456-7",
        "status": "DFX (DESPACHADO_FACTURADO)",
    },
]

# ``Order/Get.orderData`` by order number.
MOCK_ORDER_DETAILS = {
    1001: {
        "number": 1001,
        "creationDate": "2026-06-29T00:00:00",
        "expirationDate": "2026-07-02T00:00:00",
        "status": "EEX (EN_DESPACHO_EN_FACTURACION)",
        "client": {"fileId": "76123456-7", "name": "Clínica Dental Demo SPA"},
        "details": [
            {"line": 1, "code": "ANES008", "name": "ANESTESIA ALPHACAINE 2%", "count": 5,
             "unit": "UN", "isService": False},
            {"line": 2, "code": "ANES012", "name": "ANESTESIA ARTICAINE 4% DFL", "count": 3,
             "unit": "UN", "isService": False},
        ],
    },
    998: {
        "number": 998,
        "creationDate": "2026-06-20T00:00:00",
        "status": "DFX (DESPACHADO_FACTURADO)",
        "client": {"fileId": "76123456-7", "name": "Clínica Dental Demo SPA"},
        "details": [
            {"line": 1, "code": "ANES002", "name": "ANESTESIA ISOCAINE 3%", "count": 2,
             "unit": "UN", "isService": False},
        ],
    },
}


def mock_dispatch_response(order_number: int) -> dict:
    return {
        "success": True,
        "mock": True,
        "OrderNumber": order_number,
        "DispatchGuide": f"MOCK-GD-{order_number}",
        "Message": "Despacho simulado (DEFONTANA_MOCK=true)",
    }


def mock_inventory_response(external_document_id: str) -> dict:
    return {
        "success": True,
        "mock": True,
        "ExternalDocumentID": external_document_id,
        "DocumentId": f"MOCK-INV-{external_document_id}",
        "Message": "Documento de inventario simulado (DEFONTANA_MOCK=true)",
    }


def mock_create_product_response(sku: str) -> dict:
    return {
        "success": True,
        "mock": True,
        "Code": sku,
        "Message": "Producto creado en Defontana (simulado, DEFONTANA_MOCK=true)",
    }


def mock_create_order_response(order_number: str) -> dict:
    return {
        "success": True,
        "mock": True,
        "Number": order_number,
        "Message": "Pedido creado en Defontana (simulado, DEFONTANA_MOCK=true)",
    }
