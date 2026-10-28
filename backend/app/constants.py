PLATFORMS: dict[str, str] = {
    "truenas_scale": "TrueNAS SCALE",
    "truenas_core": "TrueNAS CORE",
    "proxmox": "Proxmox VE",
    "synology": "Synology DSM",
}

ROLES: dict[str, str] = {
    "admin": "Administrator",
    "operator": "Operater",
    "viewer": "Pregled",
}

# Granice intervala prikupljanja u minutima (1 minut - 7 dana).
INTERVAL_MIN_MINUTES = 1
INTERVAL_MAX_MINUTES = 7 * 24 * 60

DEFAULT_TIMEZONE = "Europe/Belgrade"
