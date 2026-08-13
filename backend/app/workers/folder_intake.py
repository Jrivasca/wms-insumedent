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
from app.services import order_intake_service

logger = get_logger("app.workers.folder_intake")

# Same set the manual import route accepts (PDF digital/escaneado + fotos).
ORDER_EXTS = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff", ".heic"}


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


async def _scan_once(tenant_id: str) -> None:
    dirs = _dirs()
    dirs["pedidos"].mkdir(parents=True, exist_ok=True)
    for path in sorted(dirs["pedidos"].iterdir()):
        if not path.is_file() or path.suffix.lower() not in ORDER_EXTS:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            # El archivo puede estar aún copiándose (rclone); se reintenta el próximo ciclo.
            continue
        if not data:
            continue
        try:
            result = await order_intake_service.process_bytes(
                tenant_id=tenant_id, file_name=path.name, data=data
            )
        except Exception as exc:  # noqa: BLE001 - nunca detener el loop por un archivo
            logger.exception("intake: fallo procesando %s: %s", path.name, exc)
            _safe_move(path, dirs["revisar"])
            continue
        dest = dirs["revisar"] if result.get("outcome") == "error" else dirs["procesados"]
        _safe_move(path, dest)
        logger.info("intake: %s -> %s (%s)", path.name, dest.name, result.get("outcome"))


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
