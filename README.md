# SmartDisk

Web aplikacija za centralizovani nadzor diskova, SMART podataka i zdravlja skladišta na TrueNAS, Proxmox VE i Synology sistemima. Radi u Debian 13 LXC kontejneru na Proxmoxu. Ceo interfejs je na srpskom (latinica).

Specifikacija projekta se vodi van repozitorijuma; oznake poput „spec. §8.8” u dokumentaciji upućuju na njena poglavlja.

## Stanje

| Faza | Sadržaj | Stanje |
|---|---|---|
| 1 – Osnova | LXC instalacija, backend, frontend, PostgreSQL, prijava i korisnici, upravljanje uređajima, SSH test, scheduler sa dinamičkim intervalima | **Završeno** – [izveštaj](docs/faza-1-izvestaj.md) |
| 2 – Prikupljanje | Adapteri za TrueNAS/Proxmox/Synology, inventar diskova, SMART/NVMe, ZFS/RAID | **Završeno** (SCALE i Synology čekaju proveru na uređaju) – [izveštaj](docs/faza-2-izvestaj.md) |
| 3 – Dashboard i analitika | Grafikoni, statistika, izvoz | **Završeno** – [izveštaj](docs/faza-3-izvestaj.md) |
| 4 – Degradacija i alarmi | Zdravlje diska, trendovi, alarmi, MQTT, Home Assistant, Web Push, e-pošta | **Završeno** – [izveštaj](docs/faza-4-izvestaj.md) |
| 5 – Napredno | Poređenje, mapa skladišta, prognoze, promene inventara, zakazani izveštaji, Telegram/Pushover/webhook, API tokeni, backup, NTP i sat, merači | **Završeno** – [izveštaj](docs/faza-5-izvestaj.md) |
| Završetak | Korisničko uputstvo (spec. §20.1), dostupno i iz aplikacije | Sledeće |

## Instalacija na LXC (u kratkim crtama)

```bash
bash deploy/deploy.sh smartdisk-lxc          # sa razvojne mašine: kopira kod i pokreće install.sh
ssh smartdisk-lxc /opt/smartdisk/deploy/create-admin.sh admin   # prvi administrator
```

Aplikacija je zatim dostupna na `https://<IP-kontejnera>`. Detalji su u [docs/instalacija.md](docs/instalacija.md).

## Dokumentacija

- [Instalacija, nadogradnja i održavanje](docs/instalacija.md)
- [Arhitektura i tehničke odluke](docs/arhitektura.md)
- [Dodavanje uređaja i SSH pristup](docs/dodavanje-uredjaja.md)
- [Izveštaj o Fazi 1](docs/faza-1-izvestaj.md)
- [Izveštaj o Fazi 2](docs/faza-2-izvestaj.md)
- [Izveštaj o Fazi 3](docs/faza-3-izvestaj.md)
- [Izveštaj o Fazi 4](docs/faza-4-izvestaj.md)
- [Izveštaj o Fazi 5](docs/faza-5-izvestaj.md)
- [Obaveštenja: e-pošta, MQTT/Home Assistant, Web Push](docs/obavestenja.md)
- API dokumentacija (OpenAPI/Swagger): `https://<IP-kontejnera>/api/docs`

## Struktura repozitorijuma

```text
backend/            FastAPI aplikacija, SQLAlchemy modeli, Alembic migracije
  app/
    routers/        API rute (auth, users, devices, storage, system)
    ssh/            SSH klijent i detekcija sistema/alata
    adapters/       komande po platformi, parseri (smartctl, zpool, LVM…), sudo profili
    persist.py      upis diskova, SMART očitavanja i skladišta
    analytics.py    serije, statistika, dostupnost, dnevni agregati
    reports.py      izveštaji; export.py – CSV/XLSX/PDF
    health.py       uslovi alarma i zdravlje diska; events.py – alarmi
    notify/         Web Push, SMTP, MQTT + Home Assistant Discovery
    collector.py    ciklus prikupljanja za jedan uređaj
    scheduler.py    APScheduler – poslovi po uređaju, heartbeat
  alembic/          migracije baze
  tests/            testovi parsera na stvarnim izlazima uređaja
frontend/           React + TypeScript + Tailwind (Vite)
deploy/             install.sh, deploy.sh, systemd unit, Caddyfile, primer .env
docs/               dokumentacija
```
