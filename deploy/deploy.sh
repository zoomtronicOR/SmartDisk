#!/usr/bin/env bash
# Prenos koda sa razvojne mašine na LXC i pokretanje instalacije.
# Upotreba (Git Bash / Linux):  deploy/deploy.sh [ssh-host]   (podrazumevano: smartdisk-lxc)
set -euo pipefail
HOST=${1:-smartdisk-lxc}
cd "$(dirname "$0")/.."

items=()
for p in backend frontend deploy README.md docs; do [[ -e $p ]] && items+=("$p"); done

tar -czf - \
  --exclude=node_modules --exclude=dist --exclude=__pycache__ --exclude='*.pyc' --exclude=.venv \
  "${items[@]}" \
  | ssh "$HOST" 'mkdir -p /opt/smartdisk && rm -rf /opt/smartdisk/backend/app /opt/smartdisk/frontend/src && tar --no-same-owner --no-same-permissions -xzf - -C /opt/smartdisk && chmod +x /opt/smartdisk/deploy/*.sh'

ssh "$HOST" 'bash /opt/smartdisk/deploy/install.sh'
