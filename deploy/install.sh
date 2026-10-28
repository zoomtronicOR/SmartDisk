#!/usr/bin/env bash
# Instalacija / nadogradnja SmartDisk aplikacije na Debian 13 LXC.
# Pokreće se kao root iz /opt/smartdisk (kod je već iskopiran tamo). Bezbedno je pokrenuti više puta.
set -euo pipefail

APP_DIR=/opt/smartdisk
ENV_DIR=/etc/smartdisk
ENV_FILE=$ENV_DIR/smartdisk.env
DATA_DIR=/var/lib/smartdisk
APP_USER=smartdisk
VENV=$APP_DIR/venv

log() { echo -e "\n==> $*"; }

[[ $EUID -eq 0 ]] || { echo "Pokrenuti kao root."; exit 1; }
cd "$APP_DIR"

log "Sistemski paketi"
export DEBIAN_FRONTEND=noninteractive
PKGS=(postgresql python3-venv python3-dev build-essential libpq-dev nodejs npm caddy curl ca-certificates locales fonts-dejavu-core)
missing=()
for p in "${PKGS[@]}"; do dpkg -s "$p" >/dev/null 2>&1 || missing+=("$p"); done
if ((${#missing[@]})); then
  apt-get update -q
  apt-get install -y -q "${missing[@]}"
fi

log "Vremenska zona i locale"
if [[ "$(timedatectl show -p Timezone --value 2>/dev/null)" != "Europe/Belgrade" ]]; then
  timedatectl set-timezone Europe/Belgrade
fi
if ! locale -a 2>/dev/null | grep -qi '^sr_RS.utf8$'; then
  sed -i -E 's/^# *(sr_RS.UTF-8|sr_RS@latin UTF-8|en_US.UTF-8)/\1/' /etc/locale.gen
  locale-gen
fi

log "Sistemski korisnik $APP_USER"
if ! id "$APP_USER" >/dev/null 2>&1; then
  useradd --system --home-dir "$DATA_DIR" --create-home --shell /usr/sbin/nologin "$APP_USER"
fi
install -d -o "$APP_USER" -g "$APP_USER" -m 750 "$DATA_DIR"
install -d -o "$APP_USER" -g "$APP_USER" -m 700 "$DATA_DIR/backups"  # backup baze (spec. §16.5)

log "PostgreSQL baza"
systemctl enable --now postgresql >/dev/null
if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$APP_USER'" | grep -q 1; then
  runuser -u postgres -- createuser "$APP_USER"
fi
if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='$APP_USER'" | grep -q 1; then
  runuser -u postgres -- createdb -O "$APP_USER" -E UTF8 "$APP_USER"
fi

log "Python okruženje"
[[ -d $VENV ]] || python3 -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r backend/requirements.txt

log "Konfiguracija $ENV_FILE"
install -d -o root -g "$APP_USER" -m 750 "$ENV_DIR"
if [[ ! -f $ENV_FILE ]]; then
  MASTER_KEY=$("$VENV/bin/python" -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')
  sed "s|^SMARTDISK_MASTER_KEY=.*|SMARTDISK_MASTER_KEY=$MASTER_KEY|" deploy/smartdisk.env.example > "$ENV_FILE"
  echo "Kreiran $ENV_FILE sa novim master ključem. NAPRAVITE REZERVNU KOPIJU OVOG FAJLA!"
fi
chown root:"$APP_USER" "$ENV_FILE"
chmod 640 "$ENV_FILE"

log "Migracije baze"
(cd backend && runuser -u "$APP_USER" -- env $(grep -v '^#' "$ENV_FILE" | xargs) "$VENV/bin/alembic" upgrade head)

log "Frontend"
if [[ -f frontend/package.json ]]; then
  (cd frontend && npm ci --no-audit --no-fund --loglevel=error && npm run build)
fi

log "systemd servis"
install -m 644 deploy/smartdisk-api.service /etc/systemd/system/smartdisk-api.service
systemctl daemon-reload
systemctl enable smartdisk-api >/dev/null
systemctl restart smartdisk-api

log "Caddy (HTTPS reverse proxy)"
IP=$(hostname -I | awk '{print $1}')
SITES="https://$IP"
[[ -n ${SMARTDISK_HOSTNAMES:-} ]] && SITES="$SITES, $(echo "$SMARTDISK_HOSTNAMES" | sed -E 's/([^ ,]+)/https:\/\/\1/g; s/ +/, /g')"
sed "s|__SITES__|$SITES|" deploy/Caddyfile > /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null
systemctl enable caddy >/dev/null
systemctl reload-or-restart caddy

log "Provera"
for i in {1..20}; do
  if curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then break; fi
  sleep 1
done
curl -fsS http://127.0.0.1:8000/api/health && echo
systemctl --no-pager --lines=0 status smartdisk-api | head -n 3
echo -e "\nGotovo. Aplikacija: $SITES"
if ! runuser -u postgres -- psql -d "$APP_USER" -tAc "SELECT 1 FROM users WHERE role='admin' LIMIT 1" | grep -q 1; then
  echo "Nema administratora. Kreirajte ga:  $APP_DIR/deploy/create-admin.sh <korisnicko_ime>"
fi
