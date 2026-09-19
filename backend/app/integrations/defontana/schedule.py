"""Hora local y ventana horaria para las tareas automáticas de Defontana."""
from datetime import datetime, time, timezone
from typing import Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def local_now() -> datetime:
    """Ahora en ``DEFONTANA_TIMEZONE`` (Chile por defecto). Si el sistema no tiene la base
    de zonas horarias, cae a UTC con un aviso en vez de detener el worker."""
    try:
        return datetime.now(ZoneInfo(settings.defontana_timezone))
    except ZoneInfoNotFoundError:
        logger.warning("Zona horaria %s no disponible; se usa UTC", settings.defontana_timezone)
        return datetime.now(timezone.utc)


def parse_hours(value: str) -> Tuple[time, time]:
    """``"08:00-19:00"`` → (08:00, 19:00)."""
    start, end = (part.strip() for part in value.split("-", 1))
    return time.fromisoformat(start), time.fromisoformat(end)


def within_schedule(now: datetime, hours: str, weekdays_only: bool) -> bool:
    """¿``now`` (hora local) cae dentro del horario configurado? Un horario mal escrito no
    bloquea la sincronización: se avisa y se permite."""
    if weekdays_only and now.weekday() >= 5:
        return False
    try:
        start, end = parse_hours(hours)
    except ValueError:
        logger.warning("Horario inválido %r (formato HH:MM-HH:MM); se ignora", hours)
        return True
    current = now.time().replace(tzinfo=None)
    return start <= current <= end
