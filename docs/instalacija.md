# Instalacija, nadogradnja i održavanje

## Okruženje

| Stavka | Vrednost |
|---|---|
| Kontejner | Proxmox LXC, unprivileged, Debian 13 (trixie) |
| Adresa | `192.168.88.246` (hostname `Smart-Disk`) |
| Resursi | 2 CPU, 2 GB RAM, 20 GB disk |
| Vremenska zona | `Europe/Belgrade`; sistemski locale `C.UTF-8`, generisani su `sr_RS.UTF-8`, `sr_RS@latin` i `en_US.UTF-8` |
| SSH pristup za razvoj | alias `smartdisk-lxc` u `~/.ssh/config` razvojne mašine (ključ `~/.ssh/smartdisk_lxc`, korisnik `root`) |

Docker se ne koristi: unprivileged LXC traži dodatna podešavanja za Docker, a 2 GB RAM-a je malo. Aplikacija radi kao systemd servis.

## Raspored na kontejneru

| Putanja | Sadržaj |
|---|---|
| `/opt/smartdisk/backend` | Python kod i Alembic migracije |
| `/opt/smartdisk/venv` | Python virtualno okruženje |
| `/opt/smartdisk/frontend/dist` | build-ovan frontend (servira ga Caddy) |
| `/opt/smartdisk/deploy` | instalacione skripte |
| `/etc/smartdisk/smartdisk.env` | konfiguracija i **master ključ** (`root:smartdisk`, `640`) |
| `/var/lib/smartdisk` | home sistemskog korisnika `smartdisk` |
| `/etc/systemd/system/smartdisk-api.service` | servis API-ja i scheduler-a |
| `/etc/caddy/Caddyfile` | HTTPS reverse proxy (generiše ga `install.sh`) |

Servisi:

| Servis | Uloga |
|---|---|
| `postgresql` | PostgreSQL 17, baza `smartdisk`, vlasnik `smartdisk`. Pristup preko unix socket-a i peer autentifikacije, bez lozinke |
| `smartdisk-api` | uvicorn na `127.0.0.1:8000`, jedan worker. API i scheduler rade u istom procesu |
| `caddy` | HTTPS na portu 443, preusmerava HTTP→HTTPS, servira frontend, `/api/*` prosleđuje backendu |

## Prva instalacija

Sa razvojne mašine (Git Bash ili Linux), iz korena projekta:

```bash
bash deploy/deploy.sh smartdisk-lxc
```

`deploy.sh` spakuje `backend/`, `frontend/`, `deploy/`, `docs/` i `README.md` (bez `node_modules`, `dist`, keša), raspakuje ih u `/opt/smartdisk` i pokrene `deploy/install.sh`. Skripta se može pokretati više puta i redom:

1. instalira sistemske pakete koji nedostaju (PostgreSQL, Python venv, Node.js/npm za build, Caddy);
2. podešava vremensku zonu i locale;
3. kreira sistemskog korisnika `smartdisk`, PostgreSQL rolu i bazu;
4. pravi venv i instalira `backend/requirements.txt`;
5. **samo prvi put** pravi `/etc/smartdisk/smartdisk.env` sa novim master ključem;
6. pokreće `alembic upgrade head`;
7. build-uje frontend (`npm ci && npm run build`);
8. instalira i (re)startuje `smartdisk-api`;
9. generiše Caddyfile za IP adresu kontejnera i ponovo učitava Caddy;
10. proverava `/api/health` i javlja ako još nema administratora.

Dodatna DNS imena za sertifikat zadaju se promenljivom okruženja, npr.:

```bash
ssh smartdisk-lxc 'SMARTDISK_HOSTNAMES="smartdisk.lan" bash /opt/smartdisk/deploy/install.sh'
```

### Prvi administrator

```bash
ssh -t smartdisk-lxc /opt/smartdisk/deploy/create-admin.sh admin
```

Lozinka se unosi interaktivno: najmanje 10 znakova, a ako je kraća od 16, mora imati bar tri vrste znakova. Ostale korisnike dodaje administrator kroz aplikaciju (Korisnici). Javne registracije nema.

Zaboravljena lozinka administratora (postavlja novu, otključava i aktivira nalog):

```bash
ssh -t smartdisk-lxc /opt/smartdisk/deploy/create-admin.sh admin --reset
```

## HTTPS sertifikat

Caddy koristi `tls internal`, tj. sopstveni lokalni CA, pa pregledač prikazuje upozorenje dok se taj CA ne proglasi pouzdanim. Rešenje:

1. Preuzeti root sertifikat:
   ```bash
   scp smartdisk-lxc:/var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt smartdisk-root-ca.crt
   ```
2. Windows: dvoklik → *Install Certificate* → *Local Machine* → *Trusted Root Certification Authorities*. Na telefonu i drugim uređajima: instalirati kao CA sertifikat.

   Antivirus koji proverava HTTPS (npr. Kaspersky) bez ovog koraka može da blokira aplikaciju kao „untrustworthy website”. Posle instalacije CA-a treba ponovo pokrenuti pregledač.

Pouzdan sertifikat je **neophodan za Web Push notifikacije** (Faza 4). Druga opcija je pravi domen sa ACME/DNS izazovom, ili sertifikat sa postojećeg reverse proxy-ja.

## Konfiguracija (`/etc/smartdisk/smartdisk.env`)

| Promenljiva | Podrazumevano | Značenje |
|---|---|---|
| `SMARTDISK_MASTER_KEY` | generiše se | Fernet ključ za šifrovanje SSH privatnih ključeva u bazi |
| `SMARTDISK_DATABASE_URL` | unix socket | konekcija ka bazi |
| `SMARTDISK_SESSION_IDLE_MINUTES` | 30 | odjava posle neaktivnosti |
| `SMARTDISK_SESSION_MAX_HOURS` | 12 | najduže trajanje sesije |
| `SMARTDISK_COOKIE_SECURE` | true | kolačići samo preko HTTPS-a |
| `SMARTDISK_LOGIN_MAX_FAILURES` | 5 | posle toliko neuspešnih prijava nalog se zaključava |
| `SMARTDISK_LOGIN_LOCK_MINUTES` | 15 | trajanje zaključavanja |
| `SMARTDISK_MAX_PARALLEL_SSH` | 4 | najviše paralelnih SSH sesija |
| `SMARTDISK_LOG_LEVEL` | INFO | nivo logovanja |

Posle izmene: `systemctl restart smartdisk-api`.

> **Master ključ.** Bez `SMARTDISK_MASTER_KEY` sačuvani SSH ključevi uređaja ne mogu da se dešifruju, pa bi sve ključeve trebalo ponovo generisati i rasporediti. Kopiju `smartdisk.env` čuvati **odvojeno** od backup-a baze, npr. u menadžeru lozinki.

## Nadogradnja

Ista komanda kao instalacija:

```bash
bash deploy/deploy.sh smartdisk-lxc
```

Postojeći `smartdisk.env` se ne menja, migracije se primenjuju automatski, a servis se restartuje.

Pre nadogradnje koja menja šemu baze napraviti backup:

```bash
ssh smartdisk-lxc 'runuser -u postgres -- pg_dump -Fc smartdisk > /root/smartdisk-$(date +%F).dump'
```

## Vraćanje prethodne verzije

1. Na razvojnoj mašini vratiti kod na prethodnu verziju i pokrenuti `deploy.sh`.
2. Ako je nova verzija menjala šemu, prvo vratiti bazu:
   ```bash
   ssh smartdisk-lxc 'systemctl stop smartdisk-api && runuser -u postgres -- pg_restore --clean -d smartdisk /root/smartdisk-<datum>.dump'
   ```
   Druga opcija je `alembic downgrade <revizija>` (pokreće se kao korisnik `smartdisk`, uz promenljive iz `smartdisk.env`).

Automatizovan backup i restore iz aplikacije stiže u kasnijoj fazi. Do tada važe ručne komande iznad.

## Backup i vraćanje (spec. §16.5)

Aplikacija pravi backup baze svake noći (podrazumevano u 02:05, čuva se poslednjih 14), a backup se može napraviti i ručno: *Podešavanja → Backup baze → Napravi backup sada*. Svaki backup se odmah proverava (`pg_restore --list` mora pročitati podatke svih tabela). Ako backup ne uspe, otvara se alarm „Backup baze nije uspeo”.

- Fajlovi: `/var/lib/smartdisk/backups/smartdisk-GGGGMMDD-HHMMSS.dump` (custom format `pg_dump`, prava 0600).
- Backup sadrži sve: uređaje, istoriju, alarme, korisnike, podešavanja i šifrovane kredencijale.
- **Ne sadrži master ključ** (`/etc/smartdisk/smartdisk.env`). Njega treba čuvati posebno, van kontejnera (npr. u menadžeru lozinki). Bez njega se baza može vratiti, ali šifrovani SSH ključevi, SMTP i MQTT lozinke nisu upotrebljivi: ključeve uređaja treba ponovo generisati, a lozinke ponovo uneti.
- Backup kopirati i van kontejnera, npr. Proxmox backup-om celog LXC-a ili `scp`:
  ```bash
  scp smartdisk-lxc:/var/lib/smartdisk/backups/smartdisk-*.dump .
  ```

Vraćanje (na kontejneru, kao root). Postupak je proveren na kopiji baze:

```bash
systemctl stop smartdisk-api
F=/var/lib/smartdisk/backups/smartdisk-20261028-233426.dump       # izabrani backup
runuser -u postgres -- dropdb smartdisk
runuser -u postgres -- createdb -O smartdisk smartdisk
runuser -u postgres -- pg_restore --no-owner --role=smartdisk -d smartdisk < "$F"   # fajl čita root (prava 0600)
systemctl start smartdisk-api
```

Na novom kontejneru: prvo `install.sh` (pravi bazu i korisnika), zatim vratiti **isti** `/etc/smartdisk/smartdisk.env` iz rezervne kopije, pa izvršiti korake iznad. Probno vraćanje bez diranja produkcije: `createdb smartdisk_restore_test`, `pg_restore` u nju, provera broja redova, pa `dropdb`.

## Vreme (NTP)

Kontejner je unprivileged i koristi sat Proxmox hosta, pa se vreme podešava NTP-om **na hostu** (na Proxmox VE 9 radi `chrony`). Aplikacija na svakih 15 minuta proverava `timedatectl` i odstupanje od NTP servera (podrazumevano `pool.ntp.org`, menja se u *Podešavanja → Vreme i NTP*). Ako je odstupanje preko 2 s, otvara se upozorenje, a preko 30 s kritičan alarm. Datum i vreme servera stalno se vide u zaglavlju aplikacije.

## Logovi i dijagnostika

```bash
journalctl -u smartdisk-api -f          # API, scheduler, collector, SSH
journalctl -u caddy -f                   # HTTPS / proxy
curl -sk https://192.168.88.246/api/health
```

Logeri u aplikaciji: `smartdisk.api`, `smartdisk.scheduler`, `smartdisk.collector`, `smartdisk.ssh`. Lozinke, privatni ključevi i passphrase se nikad ne upisuju u log. Rotaciju i ograničenje veličine logova obavlja journald.

## Lokalni razvoj

```bash
cd frontend && npm install && npm run dev     # Vite na :5173, /api prosleđuje na 127.0.0.1:8000
cd frontend && npm run build                  # provera tipova + produkcioni build
cd backend && pip install -r requirements-dev.txt && python -m pytest -q tests   # testovi parsera
```

Backend je napravljen za rad na kontejneru (PostgreSQL preko socket-a). Za razvoj je najjednostavnije menjati kod lokalno i pokretati `deploy.sh`.
