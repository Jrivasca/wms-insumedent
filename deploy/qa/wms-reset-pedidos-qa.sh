#!/bin/bash
# WMS Insumedent - reinicio semanal de la etapa de pruebas contra el Defontana de QA.
#
# Defontana restaura su base de QA los fines de semana (producción con ~1 semana de desfase):
# los pedidos importados la semana anterior quedan obsoletos. Este script deja el WMS "de
# vuelta" junto con el ERP: respalda, REVIERTE el stock que movieron las pruebas (picking,
# packing, despacho), borra pedidos/tareas/despachos y re-sincroniza los pedidos.
# El trabajo lo hace app/maintenance/reiniciar_qa.py (versionado y con tests).
#
# Antes (2026-09-28 a 2026-10-05) vivía solo en el droplet y no revertía el stock: dejaba
# mercadería en STAGING/PACKING sin pedido y saldos negativos.
#
# Cron (en /etc/crontab de root): cada hora de los lunes; el script corre solo a las 08 de
# Chile. CRON_TZ no se respeta en ese cron (el 2026-10-05 corrió a las 08:00 UTC = 05:00 en
# Chile) y el cambio de horario de Chile movería una hora fija en UTC.
#   0 * * * 1 /usr/bin/flock -n /run/wms-reset-pedidos.lock /root/wms-reset-pedidos-qa.sh >> /var/log/wms-reset-pedidos.log 2>&1
#
# QUITAR el cron al terminar la etapa de pruebas.
set -euo pipefail
TENANT="6a41eb18aaf610852cca7c82"

if [ "${FORZAR:-0}" != "1" ] && [ "$(TZ=America/Santiago date +%H)" != "08" ]; then
  exit 0
fi

TS=$(date +%F-%H%M)
mkdir -p /root/wms-backups
echo "[$(date)] respaldo previo..."
docker exec wms_mongo mongodump --db wms --archive=/tmp/reset-pedidos.dump >/dev/null 2>&1
docker cp wms_mongo:/tmp/reset-pedidos.dump "/root/wms-backups/wms-${TS}-antes-reset-pedidos.dump" >/dev/null
docker exec wms_mongo mongorestore --dryRun --archive=/tmp/reset-pedidos.dump >/dev/null 2>&1 \
  || { echo "[$(date)] el respaldo no valida: NO se reinicia."; exit 1; }

echo "[$(date)] revirtiendo stock de las pruebas, borrando pedidos y re-sincronizando..."
docker exec wms_backend python -m app.maintenance.reiniciar_qa --tenant "$TENANT" --reset-semanal --apply
echo "[$(date)] listo."
