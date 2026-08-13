"""Folder-watch intake loop (Plan 1, Fase 1) — runs inside the worker container.

Every ``INTAKE_INTERVAL_SECONDS`` it scans ``INTAKE_INBOUND_DIR/pedidos`` (a local
directory kept in sync with a cloud folder via rclone/Syncthing) and hands each new
file to ``order_intake_service.process_bytes`` (hybrid: auto-create or review queue).
Processed files move to ``procesados/``; unreadable ones to ``revisar/``.

Disabled unless ``INTAKE_ENABLED=true`` and ``INTAKE_INBOUND_DIR`` is set, so the
manual PDF import via the UI keeps working unchanged when the watcher is off.
"""
import asyncio
import shutil
from pathlib import Path
from typing import Optional

from app.core.config import settings
from app.core.database import get_database
from app.core.logging import get_logger
from app.models import Collections
from app.models.notification import NotificationType
from app.services import notification_service, order_intake_service, product_import_service

logger = get_logger("app.workers.folder_intake")

# Same set the manual import route accepts (PDF digital/escaneado + fotos).
ORDER_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic"}
PRODUCT_EXTS = {".xlsx", ".xlsm"}


async def _resolve_tenant_id() -> Optional[str]:
    if settings.intake_tenant_id:
        return settings.intake_tenant_id
    # Conveniencia para un despliegue de un solo cliente: si hay un único tenant, ese.
    db = get_database()
    tenants = await db[Collections.TENANTS].find({}).to_list(length=2)
    if len(tenants) == 1:
        return str(tenants[0]["_id"])
    return None


def _dirs() -> dict:
    base = Path(settings.intake_inbound_dir)
    return {
        "pedidos": base / "pedidos",
        "productos": base / "productos",
        "procesados": base / "procesados",
        "revisar": base / "revisar",
    }


def _safe_move(path: Path, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / path.name
    n = 1
    while target.exists():
        target = dest_dir / f"{path.stem}-{n}{path.suffix}"
        n += 1
    shutil.move(str(path), str(target))


def _new_files(folder: Path, exts: set) -> list:
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for path in sorted(folder.iterdir()):
        if path.is_file() and path.suffix.lower() in exts and not path.name.startswith("."):
            out.append(path)
    return out


async def _scan_orders(tenant_id: str, dirs: dict) -> None:
    for path in _new_files(dirs["pedidos"], ORDER_EXTS):
        try:
            data = path.read_bytes()
        except OSError:
            continue  # aún copiándose (rclone); próximo ciclo
        if not data:
            continue
        try:
            result = await order_intake_service.process_bytes(
                tenant_id=tenant_id, file_name=path.name, data=data
            )
        except Exception as exc:  # noqa: BLE001 - nunca detener el loop por un archivo
            logger.exception("intake pedidos: fallo con %s: %s", path.name, exc)
            _safe_move(path, dirs["revisar"])
            continue
        dest = dirs["revisar"] if result.get("outcome") == "error" else dirs["procesados"]
        _safe_move(path, dest)
        logger.info("intake pedido: %s -> %s (%s)", path.name, dest.name, result.get("outcome"))


async def _scan_products(tenant_id: str, dirs: dict) -> None:
    for path in _new_files(dirs["productos"], PRODUCT_EXTS):
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if not data:
            continue
        try:
            report = await product_import_service.import_xlsx(
                tenant_id, data, actor="folder_intake", source="folder_intake"
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("intake productos: fallo con %s: %s", path.name, exc)
            _safe_move(path, dirs["revisar"])
            continue
        applied = report.get("applied")
        _safe_move(path, dirs["procesados"] if applied else dirs["revisar"])
        logger.info("intake catálogo: %s -> %s (%s)", path.name,
                    "procesados" if applied else "revisar", report)
        if applied:
            body = (f"{report.get('created', 0)} creados · {report.get('updated', 0)} actualizados"
                    f" · {report.get('barcodes_added', 0)} códigos")
        else:
            body = report.get("error", "No se pudo aplicar el catálogo")
        await notification_service.emit(
            tenant_id=tenant_id,
            notification_type=NotificationType.CATALOG_IMPORT.value,
            title=("Catálogo actualizado" if applied else "Catálogo rechazado"),
            body=f"{path.name}: {body}",
            entity_type="product",
            metadata={"file_name": path.name, "applied": bool(applied)},
        )


async def _scan_once(tenant_id: str) -> None:
    dirs = _dirs()
    await _scan_orders(tenant_id, dirs)
    # Productos: solo si el folder-watch de catálogo está habilitado (por defecto OFF;
    # el catálogo se importa manualmente por el botón "Importar Excel").
    if settings.intake_products_enabled:
        await _scan_products(tenant_id, dirs)
        # Recordatorio si nadie subió el catálogo en 24 h (deduplicado internamente).
        try:
            await product_import_service.catalog_staleness_check(tenant_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("intake: fallo el chequeo de obsolescencia del catálogo: %s", exc)


async def run_forever() -> None:
    if not settings.intake_enabled or not settings.intake_inbound_dir:
        logger.info("Folder intake deshabilitado (INTAKE_ENABLED / INTAKE_INBOUND_DIR)")
        return
    tenant_id = await _resolve_tenant_id()
    if not tenant_id:
        logger.warning("Folder intake sin tenant resoluble (define INTAKE_TENANT_ID)")
        return
    interval = max(15, settings.intake_interval_seconds)
    logger.info(
        "Folder intake iniciado: %s cada %ss (tenant %s)",
        settings.intake_inbound_dir, interval, tenant_id,
    )
    while True:
        try:
            await _scan_once(tenant_id)
        except Exception as exc:  # noqa: BLE001 - mantener vivo el loop
            logger.exception("intake loop error: %s", exc)
        await asyncio.sleep(interval)
