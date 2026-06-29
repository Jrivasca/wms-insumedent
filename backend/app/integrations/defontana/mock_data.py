"""Simulated Defontana payloads used when DEFONTANA_MOCK=true.

These mimic the shape of Defontana's responses closely enough for the WMS mapper
to exercise the real sync path without any network call.
"""

MOCK_PRODUCTS = [
    {
        "Id": "ERP-SKU001",
        "Code": "SKU001",
        "Name": "Polera Deportiva",
        "Description": "Polera deportiva manga corta",
        "Unit": "UN",
        "Brand": "GenericSport",
        "Family": "Vestuario",
        "BarCode": "780000000001",
        "IsService": False,
        "UseLot": False,
        "UseSerial": False,
    },
    {
        "Id": "ERP-SKU002",
        "Code": "SKU002",
        "Name": "Zapatilla Training",
        "Description": "Zapatilla de entrenamiento",
        "Unit": "UN",
        "Brand": "GenericSport",
        "Family": "Calzado",
        "BarCode": "780000000002",
        "IsService": False,
        "UseLot": False,
        "UseSerial": False,
    },
    {
        "Id": "ERP-SKU003",
        "Code": "SKU003",
        "Name": "Botella Deportiva",
        "Description": "Botella reutilizable 750ml",
        "Unit": "UN",
        "Brand": "GenericSport",
        "Family": "Accesorios",
        "BarCode": "780000000003",
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
        "Client": {"Name": "Cliente Demo SPA"},
        "Date": "2026-06-29",
        "DeliveryDate": "2026-07-02",
        "Detail": [
            {"Code": "SKU001", "Name": "Polera Deportiva", "Unit": "UN", "Quantity": 3},
            {"Code": "SKU002", "Name": "Zapatilla Training", "Unit": "UN", "Quantity": 2},
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
