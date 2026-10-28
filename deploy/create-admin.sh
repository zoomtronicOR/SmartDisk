#!/usr/bin/env bash
# Kreiranje administratora ili reset lozinke:  create-admin.sh <korisnicko_ime> [--reset]
set -euo pipefail
[[ $# -ge 1 ]] || { echo "Upotreba: $0 <korisnicko_ime> [--reset]"; exit 1; }
cmd=create-admin
[[ ${2:-} == "--reset" ]] && cmd=reset-password
cd /opt/smartdisk/backend
exec runuser -u smartdisk -- env $(grep -v '^#' /etc/smartdisk/smartdisk.env | xargs) \
  /opt/smartdisk/venv/bin/python -m app.cli "$cmd" "$1"
