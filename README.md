# SmartDisk

Web aplikacija za centralizovani nadzor diskova, SMART podataka i zdravlja skladišta na TrueNAS, Proxmox VE i Synology sistemima. Radi u Debian 13 LXC kontejneru na Proxmoxu. Ceo interfejs je na srpskom (latinica).

**Trenutna verzija: 0.6.9**

![Pregled](docs/uputstvo-slike/01-pregled.jpg)

## Šta aplikacija radi

- **Nadzor preko SSH-a, samo čitanje.** Namenski nalog sa tačno ograničenim `sudo` komandama; aplikacija nikad ništa ne menja na serverima.
- **Diskovi i SMART.** HDD, SSD i NVMe: inventar, svi SMART atributi, self-testovi i istorija; diskovi u standby-ju se ne bude.
- **„Zdravlje diska”.** Procena iz istorije (rast grešaka, temperatura, NVMe istrošenost, stanje ZFS/RAID niza), nezavisno od SMART statusa PASSED/FAILED.
- **Skladište.** ZFS pool-ovi (vdev, greške, scrub, resilver), LVM/LVM-thin, Proxmox storage, mdadm/Synology RAID, mapa skladišta.
- **Alarmi.** Četiri nivoa, eskalacija, potvrda, automatsko rešavanje, pragovi koji se podešavaju.
- **Obaveštenja.** Web Push, e-pošta (SMTP), MQTT + Home Assistant Discovery, Telegram, Pushover, webhook; režim održavanja.
- **Analitika.** Grafikoni za period od-do, merači po disku, trendovi 24 h / 7 d / 30 d, prognoze, poređenje diskova.
- **Izveštaji.** Sedam izveštaja, izvoz u CSV, XLSX i PDF, zakazano slanje e-poštom.
- **Administracija.** Više korisnika i uloga, audit log (uključujući podatke o računaru pri prijavi), API tokeni, dnevni backup sa proverom, NTP provera vremena, logo kompanije.

## Izgled

| | |
|---|---|
| ![Diskovi](docs/uputstvo-slike/02-diskovi.jpg) **Diskovi**: zdravlje, SMART, temperatura, greške | ![Disk](docs/uputstvo-slike/03-disk.jpg) **Disk**: zdravlje sa razlozima, SMART vrednosti, trendovi |
| ![Merači](docs/uputstvo-slike/05-statistika-meraci.jpg) **Statistika**: merači po disku (ili grafikoni) | ![Mapa](docs/uputstvo-slike/07-mapa.jpg) **Mapa skladišta**: uređaj → pool → diskovi |
| ![Uređaj](docs/uputstvo-slike/04-uredjaj.jpg) **Uređaj**: SSH ključ, potvrda host ključa, nadzor | ![Izveštaji](docs/uputstvo-slike/06-izvestaji.jpg) **Izveštaji**: pregled i izvoz CSV/XLSX/PDF |
| ![Alarmi](docs/uputstvo-slike/08-alarmi.jpg) **Alarmi**: nivoi, potvrda, istorija | ![Pragovi](docs/uputstvo-slike/09-pragovi.jpg) **Podešavanja**: pragovi alarma i kanali |

Još snimaka i objašnjenje svakog ekrana: **[korisničko uputstvo](docs/korisnicko-uputstvo.md)**.

## Stanje razvoja

| Faza | Sadržaj | Stanje |
|---|---|---|
| 1 - Osnova | LXC instalacija, backend, frontend, PostgreSQL, prijava i korisnici, upravljanje uređajima, SSH test, scheduler sa dinamičkim intervalima | **Završeno** - [izveštaj](docs/faza-1-izvestaj.md) |
| 2 - Prikupljanje | Adapteri za TrueNAS/Proxmox/Synology, inventar diskova, SMART/NVMe, ZFS/RAID | **Završeno** (Synology čeka proveru na uređaju; SCALE proveren u 0.6.7) - [izveštaj](docs/faza-2-izvestaj.md) |
| 3 - Dashboard i analitika | Grafikoni, statistika, izvoz | **Završeno** - [izveštaj](docs/faza-3-izvestaj.md) |
| 4 - Degradacija i alarmi | Zdravlje diska, trendovi, alarmi, MQTT, Home Assistant, Web Push, e-pošta | **Završeno** - [izveštaj](docs/faza-4-izvestaj.md) |
| 5 - Napredno | Poređenje, mapa skladišta, prognoze, promene inventara, zakazani izveštaji, Telegram/Pushover/webhook, API tokeni, backup, NTP i sat, merači | **Završeno** - [izveštaj](docs/faza-5-izvestaj.md) |
| Završetak | Korisničko uputstvo, dostupno i iz aplikacije (stavka **Pomoć**) | **Završeno** - [uputstvo](docs/korisnicko-uputstvo.md) |
| 1.0.0 | Provera kanala obaveštenja sa stvarnim nalozima (Web Push, Home Assistant, SMTP) | sledeće |

Verzije: svaka faza podiže manju verziju (0.N.0), ispravke poslednji broj (0.N.x). Izmene su po verzijama označene tagovima (`v0.5.0`, `v0.6.0`…), a posle 0.6.0 opisane u [dnevniku izmena](docs/izmene.md).

## Instalacija na LXC (u kratkim crtama)

```bash
bash deploy/deploy.sh smartdisk-lxc          # sa razvojne mašine: kopira kod i pokreće install.sh
ssh smartdisk-lxc /opt/smartdisk/deploy/create-admin.sh admin   # prvi administrator
```

Aplikacija je zatim dostupna na `https://<IP-kontejnera>`. Detalji su u [docs/instalacija.md](docs/instalacija.md), uključujući HTTPS sertifikat, backup i vraćanje i NTP.

## Dokumentacija

- **[Korisničko uputstvo](docs/korisnicko-uputstvo.md)** - i u aplikaciji, stavka **Pomoć**
- [Instalacija, nadogradnja, backup i održavanje](docs/instalacija.md)
- [Povezivanje uređaja korak po korak](docs/korisnicko-uputstvo.md#11-uređaji-dodavanje-i-podešavanje) (ključevi, nalog `diskmonitor`, sve platforme)
- [Dodavanje uređaja i SSH pristup](docs/dodavanje-uredjaja.md) (nalog `diskmonitor`, sudo profili po platformi)
- [Obaveštenja: e-pošta, MQTT/Home Assistant, Web Push, Telegram, Pushover, webhook](docs/obavestenja.md)
- [Arhitektura i tehničke odluke](docs/arhitektura.md)
- [Dnevnik izmena](docs/izmene.md) (verzije posle 0.6.0)
- Izveštaji o fazama: [1](docs/faza-1-izvestaj.md) · [2](docs/faza-2-izvestaj.md) · [3](docs/faza-3-izvestaj.md) · [4](docs/faza-4-izvestaj.md) · [5](docs/faza-5-izvestaj.md)
- API dokumentacija (OpenAPI/Swagger): `https://<IP-kontejnera>/api/docs`

Specifikacija projekta se vodi van repozitorijuma; oznake poput „spec. §8.8” u dokumentaciji upućuju na njena poglavlja.

## Struktura repozitorijuma

```text
backend/            FastAPI aplikacija, SQLAlchemy modeli, Alembic migracije
  app/
    routers/        API rute (auth, users, devices, storage, analytics, alarms, advanced, tokens, branding, system)
    ssh/            SSH klijent i detekcija sistema/alata
    adapters/       komande po platformi, parseri (smartctl, zpool, LVM…), sudo profili
    persist.py      upis diskova, SMART očitavanja i skladišta, promene inventara
    analytics.py    serije, statistika, dostupnost, prognoze, dnevni agregati
    reports.py      izveštaji; export.py - CSV/XLSX/PDF; schedules.py - zakazano slanje
    health.py       uslovi alarma i zdravlje diska; events.py - alarmi
    notify/         Web Push, SMTP, MQTT + Home Assistant, Telegram, Pushover, webhook
    collector.py    ciklus prikupljanja za jedan uređaj
    scheduler.py    APScheduler - poslovi po uređaju, NTP, backup, izveštaji, heartbeat
    backup.py       backup baze; timesync.py - NTP; clientinfo.py - podaci o računaru pri prijavi
  alembic/          migracije baze
  tests/            testovi (parseri na stvarnim izlazima uređaja, degradacija, izvoz…)
frontend/           React + TypeScript + Tailwind (Vite)
deploy/             install.sh, deploy.sh, systemd unit, Caddyfile, primer .env
docs/               dokumentacija, korisničko uputstvo i slike
```
