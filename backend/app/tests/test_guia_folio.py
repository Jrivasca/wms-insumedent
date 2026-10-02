"""Folio de la guía y reintentos de Dispatch/Save.

Caso real (DEV, 2026-10-02, folio 3737): Defontana rechazó la guía por falta de saldo; se
cargó el stock, se reintentó y la guía salió, pero el WMS no leyó el folio (venía en
``firstFolio`` y se buscaba ``Folio``) y la pantalla siguió con el error viejo. Un segundo
reintento la reenvió y Defontana respondió "ya fue ingresado", que quedó como fallo.
"""
import pytest
from bson import ObjectId
from fastapi import HTTPException

from app.core.database import get_database
from app.integrations.defontana.client import DefontanaApiError
from app.integrations.defontana.mapper import DefontanaMapper
from app.models import Collections
from app.services import sync_job_service
from app.workers import sync_worker

pytestmark = pytest.mark.asyncio

TENANT = "t-guia"


async def _job(guide_number=None):
    db = get_database()
    dispatch_id = ObjectId()
    await db[Collections.DISPATCHES].insert_one(
        {"_id": dispatch_id, "tenant_id": TENANT, "status": "pending", "guide_number": guide_number}
    )
    job_id = ObjectId()
    job = {"_id": job_id, "tenant_id": TENANT, "job_type": "dispatch_order", "status": "processing",
           "attempts": 0, "max_attempts": 5,
           "payload": {"dispatch_id": str(dispatch_id), "erp_order_number": "1"}}
    await db[Collections.SYNC_JOBS].insert_one(job)
    return job, dispatch_id


def _respuesta(monkeypatch, result=None, error=None):
    monkeypatch.setattr(DefontanaMapper, "build_dispatch_save", staticmethod(lambda **kw: {}))

    async def fake(tenant_id, payload):
        if error:
            raise DefontanaApiError(error)
        return result

    monkeypatch.setattr(sync_worker.dispatch_sync, "dispatch_save", fake)


async def test_lee_el_folio_de_first_folio(monkeypatch):
    _respuesta(monkeypatch, result={"firstFolio": 3737, "lastFolio": 3737, "success": True,
                                    "message": "Guia de Despacho Guardada Exitosamente"})
    job, dispatch_id = await _job()
    await sync_worker.process_job(job)

    db = get_database()
    j = await db[Collections.SYNC_JOBS].find_one({"_id": job["_id"]})
    d = await db[Collections.DISPATCHES].find_one({"_id": dispatch_id})
    assert j["status"] == "success" and j["external_document_id"] == "3737"
    assert d["guide_number"] == "3737" and d["erp_folio"] == "3737"


async def test_ya_ingresado_es_la_misma_guia(monkeypatch):
    _respuesta(monkeypatch, error=(
        "/Dispatch/Save: El ID de documento externo 'WMS-GD-x' ya fue ingresado. "
        "Tipo Doc: GDVELECT - Folio: 3737"))
    job, dispatch_id = await _job()
    await sync_worker.process_job(job)

    db = get_database()
    j = await db[Collections.SYNC_JOBS].find_one({"_id": job["_id"]})
    d = await db[Collections.DISPATCHES].find_one({"_id": dispatch_id})
    assert j["status"] == "success" and j["external_document_id"] == "3737"
    assert d["guide_number"] == "3737"


async def test_no_pisa_la_guia_escrita_a_mano(monkeypatch):
    _respuesta(monkeypatch, result={"firstFolio": 3737, "success": True})
    job, dispatch_id = await _job(guide_number="G-MANUAL")
    await sync_worker.process_job(job)
    d = await get_database()[Collections.DISPATCHES].find_one({"_id": dispatch_id})
    assert d["guide_number"] == "G-MANUAL" and d["erp_folio"] == "3737"


async def test_otro_error_sigue_siendo_error(monkeypatch):
    _respuesta(monkeypatch, error=(
        "/Dispatch/Save: Inventario > No existe saldo suficiente a la fecha 2-10-2026 en bodega "
        "BODEGACENTRAL para el articulo IVOCLAR017."))
    job, _ = await _job()
    await sync_worker.process_job(job)
    j = await get_database()[Collections.SYNC_JOBS].find_one({"_id": job["_id"]})
    assert j["status"] == "retrying" and "saldo suficiente" in j["last_error"]


async def test_no_se_reintenta_lo_que_ya_salio(monkeypatch):
    _respuesta(monkeypatch, result={"firstFolio": 3737, "success": True})
    job, _ = await _job()
    await sync_worker.process_job(job)
    with pytest.raises(HTTPException) as exc:
        await sync_job_service.retry(TENANT, str(job["_id"]))
    assert exc.value.status_code == 409
