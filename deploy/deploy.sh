#!/usr/bin/env bash
#
# WMS Defontana — one-shot deploy/provision for a DigitalOcean (Ubuntu) droplet.
#
# Usage (run from the repository root, as root):
#     sudo ./deploy/deploy.sh
#
# Idempotent: safe to re-run to apply updates (git pull && sudo ./deploy/deploy.sh).
set -euo pipefail

COMPOSE_FILE="docker-compose.prod.yml"
ENV_FILE=".env"
ENV_EXAMPLE=".env.production.example"

log() { echo -e "\033[1;36m[deploy]\033[0m $*"; }
err() { echo -e "\033[1;31m[deploy]\033[0m $*" >&2; }

require_root() {
  if [ "$(id -u)" -ne 0 ]; then
    err "Run as root:  sudo ./deploy/deploy.sh"
    exit 1
  fi
}

install_docker() {
  if command -v docker >/dev/null 2>&1; then
    log "Docker already installed."
  else
    log "Installing Docker Engine..."
    curl -fsSL https://get.docker.com | sh
  fi
  if ! docker compose version >/dev/null 2>&1; then
    log "Installing Docker Compose plugin..."
    apt-get update -y && apt-get install -y docker-compose-plugin
  fi
  systemctl enable --now docker >/dev/null 2>&1 || true
}

ensure_swap() {
  local mem_kb
  mem_kb=$(awk '/MemTotal/ {print $2}' /proc/meminfo)
  if [ "${mem_kb:-0}" -lt 2000000 ] && [ ! -f /swapfile ]; then
    log "Low RAM detected (<2GB); creating a 2GB swapfile for the build..."
    fallocate -l 2G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=2048
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  fi
}

gen_secret() { openssl rand -hex 32; }
# Fernet-compatible key: 32 random bytes, url-safe base64.
gen_fernet() { openssl rand -base64 32 | tr '+/' '-_'; }

set_kv() {
  local key="$1" value="$2"
  if grep -q "^${key}=" "$ENV_FILE"; then
    # Use a non-/ delimiter because values may contain '/'.
    sed -i "s|^${key}=.*|${key}=${value}|" "$ENV_FILE"
  else
    echo "${key}=${value}" >> "$ENV_FILE"
  fi
}

setup_env() {
  if [ ! -f "$ENV_FILE" ]; then
    log "Creating .env from $ENV_EXAMPLE"
    cp "$ENV_EXAMPLE" "$ENV_FILE"
  fi
  # Replace placeholder secrets with strong generated values (only if still default).
  if grep -qE '^JWT_SECRET=(change-me)?$' "$ENV_FILE"; then
    log "Generating JWT_SECRET"
    set_kv JWT_SECRET "$(gen_secret)"
  fi
  if grep -qE '^ENCRYPTION_KEY=$' "$ENV_FILE"; then
    log "Generating ENCRYPTION_KEY"
    set_kv ENCRYPTION_KEY "$(gen_fernet)"
  fi
  if grep -qE '^SEED_TOKEN=(seed-me)?$' "$ENV_FILE"; then
    log "Generating SEED_TOKEN"
    set_kv SEED_TOKEN "$(gen_secret)"
  fi
}

# Apply optional published-port / bind / site overrides passed as env vars.
# Lets the deploy run behind an existing reverse proxy without editing .env by hand.
apply_overrides() {
  if [ -n "${WMS_HTTP_PORT:-}" ]; then log "Set WMS_HTTP_PORT=$WMS_HTTP_PORT"; set_kv WMS_HTTP_PORT "$WMS_HTTP_PORT"; fi
  if [ -n "${WMS_HTTPS_PORT:-}" ]; then log "Set WMS_HTTPS_PORT=$WMS_HTTPS_PORT"; set_kv WMS_HTTPS_PORT "$WMS_HTTPS_PORT"; fi
  if [ -n "${WMS_BIND_HOST:-}" ]; then log "Set WMS_BIND_HOST=$WMS_BIND_HOST"; set_kv WMS_BIND_HOST "$WMS_BIND_HOST"; fi
  if [ -n "${SITE_ADDRESS:-}" ]; then log "Set SITE_ADDRESS=$SITE_ADDRESS"; set_kv SITE_ADDRESS "$SITE_ADDRESS"; fi
}

open_firewall() {
  if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
    log "Opening firewall ports 22, 80, 443"
    ufw allow 22/tcp  >/dev/null 2>&1 || true
    ufw allow 80/tcp  >/dev/null 2>&1 || true
    ufw allow 443/tcp >/dev/null 2>&1 || true
  fi
}

public_ip() {
  curl -fsS --max-time 3 http://169.254.169.254/metadata/v1/interfaces/public/0/ipv4/address 2>/dev/null \
    || hostname -I | awk '{print $1}'
}

main() {
  require_root
  cd "$(dirname "$0")/.."

  install_docker
  ensure_swap
  setup_env
  apply_overrides
  open_firewall

  # Resolve the locally-reachable base URL from the configured port.
  local_port=$(grep '^WMS_HTTP_PORT=' "$ENV_FILE" | cut -d= -f2-)
  local_port=${local_port:-80}
  bind_host=$(grep '^WMS_BIND_HOST=' "$ENV_FILE" | cut -d= -f2-)
  base="http://localhost:${local_port}"

  log "Building images and starting the stack (this can take a few minutes the first time)..."
  docker compose -f "$COMPOSE_FILE" up -d --build

  log "Waiting for the app to become healthy at ${base} ..."
  healthy=false
  for _ in $(seq 1 60); do
    if curl -fsS --max-time 3 "${base}/health" >/dev/null 2>&1; then
      healthy=true
      break
    fi
    sleep 3
  done
  if [ "$healthy" != true ]; then
    err "App did not become healthy in time. Check logs:  docker compose -f $COMPOSE_FILE logs"
    exit 1
  fi
  log "App is healthy."

  SEED_TOKEN=$(grep '^SEED_TOKEN=' "$ENV_FILE" | cut -d= -f2-)
  log "Seeding demo data..."
  if curl -fsS -X POST "${base}/api/v1/seed" -H "X-Seed-Token: ${SEED_TOKEN}" >/dev/null 2>&1; then
    log "Seed OK."
  else
    log "Seed skipped (already seeded or seed disabled)."
  fi

  IP=$(public_ip)
  echo
  echo "============================================================"
  echo "  WMS Defontana desplegado"
  if [ "$bind_host" = "127.0.0.1" ]; then
    echo "  El WMS escucha solo en 127.0.0.1:${local_port} (detrás de tu proxy)."
    echo "  Enruta tu reverse proxy (un subdominio) -> http://127.0.0.1:${local_port}"
    echo "  Login:    admin@demo.cl / admin123"
  else
    suffix=""; [ "$local_port" != "80" ] && suffix=":${local_port}"
    echo "  App:      http://${IP}${suffix}/"
    echo "  Swagger:  http://${IP}${suffix}/docs"
    echo "  Login:    admin@demo.cl / admin123"
  fi
  echo "============================================================"
}

main "$@"
