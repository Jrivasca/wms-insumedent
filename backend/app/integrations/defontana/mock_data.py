"""Simulated Defontana payloads used when DEFONTANA_MOCK=true.

These mimic the shape of Defontana's responses closely enough for the WMS mapper
to exercise the real sync path without any network call.
"""

# Dental products (subset of the real INSUMEDENT catalog). Barcodes match the
# seed (app/data/demo_catalog.json) so a mock sync stays consistent with what the
# demo already has loaded.
_ANEST_DESC = "Agente/insumo anestésico para procedimientos dentales sin dolor."

MOCK_PRODUCTS = [
    {
        "Id": "ERP-ANES008",
        "Code": "ANES008",
        "Name": "ANESTESIA ALPHACAINE 2%",
        "Description": _ANEST_DESC,
        "Unit": "UN",
        "Brand": "",
        "Family": "Anestesia",
        "BarCode": "2000000000013",
        "IsService": False,
        "UseLot": False,
        "UseSerial": False,
    },
    {
        "Id": "ERP-ANES012",
        "Code": "ANES012",
        "Name": "ANESTESIA ARTICAINE 4% DFL",
        "Description": _ANEST_DESC,
        "Unit": "UN",
        "Brand": "",
        "Family": "Anestesia",
        "BarCode": "2000000000022",
        "IsService": False,
        "UseLot": False,
        "UseSerial": False,
    },
    {
        "Id": "ERP-ANES002",
        "Code": "ANES002",
        "Name": "ANESTESIA ISOCAINE 3%",
        "Description": _ANEST_DESC,
        "Unit": "UN",
        "Brand": "",
        "Family": "Anestesia",
        "BarCode": "2000000000031",
        "IsService": False,
        "UseLot": False,
        "UseSerial": False,
    },
    {
        "Id": "ERP-ANES016",
        "Code": "ANES016",
        "Name": "ANESTESIA MEPIADRE MEPIVACAINA AL 2% DFL",
        "Description": _ANEST_DESC,
        "Unit": "UN",
        "Brand": "",
        "Family": "Anestesia",
        "BarCode": "2000000000040",
        "IsService": False,
        "UseLot": False,
        "UseSerial": False,
    },
    {
        "Id": "ERP-ANES009",
        "Code": "ANES009",
        "Name": "ANESTESIA MEPISV 3%",
        "Description": _ANEST_DESC,
        "Unit": "UN",
        "Brand": "",
        "Family": "Anestesia",
        "BarCode": "2000000000059",
        "IsService": False,
        "UseLot": False,
        "UseSerial": False,
    },
]

MOCK_STORAGES = [
    {"Code": "01", "Name": "BODEGA CENTRAL", "SaleAvailable": True},
    {"Code": "02", "Name": "BODEGA SECUNDARIA", "SaleAvailable": True},
]

MOCK_ORDERS = [
    {
        "Number": 1001,
        "DocumentId": "DOC-1001",
        "Client": {"Name": "Clínica Dental Demo SPA"},
        "Date": "2026-06-29",
        "DeliveryDate": "2026-07-02",
        "Detail": [
            {"Code": "ANES008", "Name": "ANESTESIA ALPHACAINE 2%", "Unit": "UN", "Quantity": 5},
            {"Code": "ANES012", "Name": "ANESTESIA ARTICAINE 4% DFL", "Unit": "UN", "Quantity": 3},
        ],
    }
]


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
