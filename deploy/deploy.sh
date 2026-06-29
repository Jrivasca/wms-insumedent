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
  open_firewall

  log "Building images and starting the stack (this can take a few minutes the first time)..."
  docker compose -f "$COMPOSE_FILE" up -d --build

  log "Waiting for the app to become healthy..."
  healthy=false
  for _ in $(seq 1 60); do
    if curl -fsS --max-time 3 http://localhost/health >/dev/null 2>&1; then
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
  if curl -fsS -X POST http://localhost/api/v1/seed -H "X-Seed-Token: ${SEED_TOKEN}" >/dev/null 2>&1; then
    log "Seed OK."
  else
    log "Seed skipped (already seeded or seed disabled)."
  fi

  IP=$(public_ip)
  echo
  echo "============================================================"
  echo "  WMS Defontana desplegado"
  echo "  App:      http://${IP}/"
  echo "  Swagger:  http://${IP}/docs"
  echo "  Login:    admin@demo.cl / admin123"
  echo "------------------------------------------------------------"
  echo "  Para activar HTTPS con dominio más adelante:"
  echo "    1) Apunta un registro A de tu dominio a ${IP}"
  echo "    2) En .env:  SITE_ADDRESS=tu-dominio.cl"
  echo "    3) docker compose -f ${COMPOSE_FILE} up -d"
  echo "============================================================"
}

main "$@"
