# Arhitektura i tehničke odluke

## Pregled

```text
Pregledač ──HTTPS──> Caddy (:443) ──┬── /api/*  ──> uvicorn/FastAPI (127.0.0.1:8000)
                                    └── ostalo ──> frontend/dist (statički React build)

FastAPI proces
 ├─ API rute (auth, users, devices, storage, analytics, alarms, system)
 ├─ MQTT veza (aiomqtt, pozadinski zadatak: stanje, događaji, HA Discovery)
 ├─ APScheduler (AsyncIO) ── posao po uređaju ──> collector ──SSH──> TrueNAS / Proxmox / Synology
 │                                                 └─ adapters/ (komande, parseri) ──> persist.py
 └─ SQLAlchemy (async, asyncpg) ──unix socket──> PostgreSQL 17
```

| Komponenta | Izbor | Napomena |
|---|---|---|
| Backend | Python 3.13, FastAPI, Pydantic 2 | |
| Baza | PostgreSQL 17, SQLAlchemy 2 (async), Alembic | migracije u `backend/alembic/versions` |
| Scheduler | APScheduler 3 (AsyncIOScheduler) | u istom procesu kao API, zato samo jedan uvicorn worker |
| SSH | AsyncSSH | obavezna provera host ključa |
| Lozinke | Argon2id (argon2-cffi) | |
| Tajne | Fernet (cryptography) | master ključ van baze |
| Frontend | React 19, TypeScript, Vite 6, Tailwind 4, TanStack Query, lucide ikone | sopstvene UI komponente umesto shadcn/ui CLI-ja |
| Proxy | Caddy 2.6 | `tls internal`, sigurnosna zaglavlja |

## Model podataka

| Tabela | Sadržaj |
|---|---|
| `users` | korisnici, uloga (`admin`/`operator`/`viewer`), Argon2id hash, brojač neuspešnih prijava, `locked_until`, `must_change_password` |
| `user_sessions` | serverske sesije: SHA-256 hash tokena, CSRF token, poslednja aktivnost, istek, IP, user-agent |
| `devices` | uređaji: veza, šifrovani privatni ključ/passphrase, javni ključ, potvrđeni i čekajući host ključ, interval, timeout-i, oznake, stanje poslednjeg kontakta, `deleted_at` (soft-delete) |
| `device_capabilities` | koji alati postoje na uređaju (`smartctl`, `lsblk`, `nvme`, `zpool`, `zfs`, `mdadm`, `lvs`, `pvesm`, `midclt`, `synodisk`) |
| `collection_runs` | svaki ciklus prikupljanja: vrsta (planirano/ručno/test), vreme, trajanje, status, vrsta i opis greške, detalji (OS, upozorenja) |
| `audit_log` | sve bitne radnje: prijave, izmene korisnika, uređaja, ključeva, podešavanja |
| `app_settings` | podešavanja iz UI-ja: globalni interval, period čuvanja merenja, vremenska zona prikaza |
| `disks` (Faza 2) | inventar: stabilni identifikator (WWN → EUI/NGUID → model+serijski broj), putanja, model, porodica, serijski broj, firmware, tip, veza, kapacitet, obrtaji, prvi/poslednji put viđen, `is_present`, id poslednjeg očitavanja, poslednji kompletan izlaz `smartctl` (`last_raw`) |
| `disk_samples` (Faza 2) | jedno SMART očitavanje: overall-health (`passed`/`failed`/`unknown`/`unavailable`/`standby`), razlog nedostupnosti, temperatura, sati rada, ključni SATA/SAS brojači, NVMe vrednosti, stanje self-testa, svi SATA/SAS atributi kao JSONB |
| `smart_tests` (Faza 2) | rezultati self-testova iz loga diska (bez duplikata) |
| `storage_pools` (Faza 2) | ZFS pool, LVM VG i thin pool, mdadm niz, Proxmox storage, Synology volumen: stanje, procena ispravnosti, redundansa, kapacitet, greške, scrub/resilver, članovi (vdev stablo, povezani diskovi) |
| `pool_samples` (Faza 2) | istorija stanja, grešaka, zauzeća i scrub/resilver napretka |
| `disk_daily`, `pool_daily` (Faza 3) | dnevni agregati (min/maks/prosek temperature, maksimumi brojača, minimum rezerve, zauzeće…) po danu u vremenskoj zoni prikaza; ostaju i posle brisanja sirovih merenja (spec. §9.2) |

| `events` (Faza 4) | alarmi: fingerprint, nivo i najviši nivo, kategorija, pravilo, poruka, parametar i vrednosti, status (pending/open/acknowledged/resolved), prvi i poslednji put, broj ponavljanja, ko je potvrdio ili rešio, poslednje obaveštenje |
| `event_history` (Faza 4) | istorija alarma: otvoren, eskalacija, ublažen, potvrđen, komentar, rešen, ponovo otvoren |
| `push_subscriptions` (Faza 4) | Web Push pretplate pregledača: korisnik, najniži nivo, uređaji, utišano do, poslednja greška |
| `notification_log` (Faza 4) | svako poslato ili neuspelo obaveštenje (push, e-pošta, MQTT) |

`disks` i `disk_samples` dobijaju `health_level` i `health_score` (zdravlje posle svakog očitavanja), a `disks` i razloge.

Odstupanja od predloga u spec. §9.1:

- SMART atributi su JSONB kolona u `disk_samples`, a ne posebna tabela `smart_attributes`. Jedno očitavanje sa ~25 atributa je jedan red umesto 25, a upiti po atributu i dalje rade preko JSONB operatora.
- Kompletan izlaz `smartctl` (`raw_payload`) čuva se samo za poslednje očitavanje (`disks.last_raw`), ne u svakom uzorku. Jedan izlaz ima 10–20 KB, pa bi ga godišnja istorija umnožila na više GB.
- `NULL` u uzorku znači „nije dostupno”, nikad 0 ili „ispravno”.

Sva vremena se čuvaju kao `timestamptz` u UTC-u. Frontend ih prikazuje u vremenskoj zoni iz podešavanja (podrazumevano `Europe/Belgrade`).

## Prikupljanje i scheduler

- Svaki uključen uređaj sa potvrđenim host ključem i SSH ključem ima posao `collect:<id>` u scheduler-u.
- Interval je sopstveni interval uređaja ili globalni podrazumevani (1 minut – 7 dana).
- **Promena intervala važi odmah:** API posle izmene uređaja ili globalnog intervala usklađuje poslove (`scheduler.sync_device` / `sync_all`). Sledeći ciklus je „sada + novi interval”, a UI prikazuje vreme sledećeg prikupljanja.
- Posle restarta servisa prvi ciklusi se raspoređuju nasumično u narednih 5–60 s, da se uređaji ne kontaktiraju istovremeno.
- Poslovi imaju `max_instances=1` i `coalesce`. Collector dodatno sprečava preklapanje ciklusa istog uređaja, a broj paralelnih SSH sesija ograničava semaforom (`SMARTDISK_MAX_PARALLEL_SSH`).
- Ciklus ne drži otvorenu konekciju ka bazi dok čeka SSH.
- Ako uređaj više ne postoji ili je isključen van API-ja, njegov posao se uklanja posle sledećeg pokušaja.
- Heartbeat posao na 30 s. Ako heartbeat izostane duže od 90 s, `/api/health` i `/api/system/status` prijavljuju da scheduler ne radi, a UI prikazuje crveno upozorenje (spec. §18).
- Istekle sesije briše posao na svakih sat vremena.
- Dnevni agregati se računaju svake noći u 03:15 (za završene dane, uz ponovni obračun poslednja 2 dana).
- Sirova merenja (`disk_samples`, `pool_samples`) starija od podešenog perioda (podrazumevano 365 dana) briše posao svake noći u 03:30. Agregati ostaju.

### Ciklus prikupljanja

Jedna SSH konekcija po ciklusu:

1. provera potvrđenog host ključa;
2. detekcija sistema i alata (`ssh/probe.py`), jedna komanda kroz `sh -c`, jer korisnički shell može biti csh/zsh;
3. platformski adapter (`adapters/platforms.py`), samo za planirano i ručno prikupljanje (test konekcije staje na koraku 2):

| Platforma | Diskovi | Skladište |
|---|---|---|
| Proxmox VE | `smartctl --scan-open` + `smartctl -j -a` po disku, `lsblk -J` (USB i diskovi koje smartctl ne vidi) | `zpool list/status`, `lvs`/`vgs` (JSON), `pvesm status`, `/proc/mdstat` |
| TrueNAS SCALE | isto kao Proxmox | `zpool list/status -P -L` |
| TrueNAS CORE | `smartctl` + `sysctl kern.disks` | `zpool list/status`, `glabel status` (gptid → ada0p2) |
| Synology DSM | `smartctl` (JSON ako je verzija ≥ 7, inače tekstualni izlaz) | `/proc/mdstat` (RAID/SHR), `df` (`/volumeN`) |

4. parsiranje u zajednički model (`adapters/model.py`), zatim upis (`persist.py`): ažuriranje inventara, novi uzorak po disku i pool-u, novi self-testovi, označavanje nestalih diskova i pool-ova;
5. status ciklusa: `success`, `partial` (pojedini koraci nisu uspeli, npr. nedostaje sudo za `lvs`; greške su u `details.errors`) ili `failed` (SSH/konekcija).

Pravila koja sprečavaju pogrešan zaključak (spec. §6.4):

- `smartctl -n standby` ne budi uspavane diskove. Takav disk dobija stanje `standby`, ne grešku ni „ispravno”.
- Disk koji `smartctl` ne vidi (USB most, kontroler) i dalje ulazi u inventar, sa stanjem „SMART nedostupan” i razlogom.
- Disk ili pool se označava kao nestao samo kada je odgovarajuća pretraga uspela. Ako komanda padne, ništa se ne briše niti označava.
- Disk u standby-ju ne vraća WWN ni serijski broj. Zato se očitavanje bez identiteta pripisuje poznatom disku na istoj putanji (inače bi nastao „nov” disk, a pravi bi bio označen kao nestao, što je uočeno na TrueNAS CORE). Za standby disk stanje i vrednosti se prikazuju iz poslednjeg SMART očitavanja, uz jasnu napomenu.
- Član ZFS pool-a se povezuje sa diskom preko imena (`/dev/sda1` → `sda`, `nvd0p2` → `nvme0`, `gptid/…` → `ada0`).
- Ime diska i `-d` tip iz izlaza uređaja prolaze strogu proveru (`/dev/sd[a-z]`, `/dev/ada[0-9]`…, spisak tipova) pre nego što uđu u komandu.

Grubo stanje diska u Fazi 2 (`routers/storage.py: disk_findings`): **kritično** (SMART FAILED, NVMe critical warning), **upozorenje** (realocirani, pending ili neispravljivi sektori, NVMe media greške, rezerva ispod praga, istrošenost ≥ 90 %, preostali vek SSD-a ≤ 10 %), **bez upozorenja**, **nema podataka**. Ocena „Zdravlje diska” sa trendovima i pragovima dolazi u Fazi 4.

### Zdravlje diska i alarmi (Faza 4)

Posle svakog planiranog ili ručnog ciklusa `collector._evaluate` poziva `health.evaluate_device`. Ta funkcija iz istorije (prozori 24 h / 7 dana / 30 dana, prethodno očitavanje, prvo očitavanje ikad, temperature za 24 h) pravi listu **uslova**. Ista lista daje i alarme i „Zdravlje diska”, pa se ta dva prikaza nikad ne razilaze.

- Pravila: SMART FAILED; rast realociranih, pending i neispravljivih sektora (pragovi za 24 h, 7 i 30 dana); CRC greške; NVMe critical warning, media greške između dva očitavanja, rezerva ispod praga ili u padu, istrošenost, log grešaka, nebezbedna gašenja; preostali vek SSD-a; temperatura po tipu diska (informativno, upozorenje, visoko pri ponovljenim prekoračenjima, kritično ili throttling), sa histerezom i nagli rast temperature; nestao disk; nema SMART podataka N ciklusa; pool nije ispravan, greške pool-a, scrub sa greškama, zauzeće; uređaj nedostupan N ciklusa; nepotpuno prikupljanje.
- Korelacija (spec. §8.7): disk sa SMART problemom koji je član degradiranog pool-a dobija kritičan uslov sa porukom koja povezuje oba.
- Zdravlje: najozbiljniji uslov određuje nivo (nema uslova → Odlično, informativno → Dobro, upozorenje → Pažnja, visoko → Ugroženo, kritično → Kritično). Ocena je 100 minus kazne po uslovu. Bez podataka ili za nestao disk zdravlje je Nepoznato, nikad „dobro”. Disk preko 50.000 radnih sati bez problema dobija „Dobro”.
- `events.apply`: jedan aktivan alarm po fingerprint-u, a ponavljanje povećava brojač. Opcione potvrde (`confirmations`) drže alarm u stanju `pending` dok uslov ne potraje. Pogoršanje vraća alarm u stanje „otvoren” i šalje obaveštenje. Cooldown ponovo otvara isti alarm. Za nepotvrđen alarm koji traje stiže ponovno obaveštenje. Alarm se automatski rešava kada uslov prestane, ali samo za pravila koja su stvarno proverena: kada SSH ne uspe, alarmi diskova se ne zatvaraju.
- Pragovi su u `app_settings` (`alarms.thresholds`), sa preporučenim vrednostima u `health.DEFAULT_THRESHOLDS`, i menjaju se u Podešavanjima.

### Obaveštenja (Faza 4)

- `notify/dispatcher.py` šalje obaveštenje posle commit-a za otvaranje, pogoršanje, podsetnik i (opciono) rešavanje alarma. Svaki pokušaj se beleži u `notification_log`.
- **Web Push**: VAPID par se generiše pri prvom korišćenju (privatni ključ je šifrovan). Service worker je `frontend/public/sw.js`. Pretplata ima najniži nivo, izbor uređaja i utišavanje. Nevažeća pretplata (404/410) se briše.
- **E-pošta (SMTP)**: standardni `smtplib` u posebnoj niti, sa STARTTLS, SSL ili bez šifrovanja i najnižim nivoom za slanje. Lozinka je šifrovana. Postoji probna poruka sa unetim, još nesačuvanim podešavanjima.
- **MQTT**: jedna veza (`notify/mqtt.py`) sa LWT (`<prefiks>/availability` = offline, retain), objavom stanja posle svakog ciklusa i heartbeat-om, i automatskim ponovnim povezivanjem (5 s → 5 min). Teme: `summary`, `devices/<id>/state`, `disks/<id>/state`, `pools/<id>/state` (retain) i `events` (QoS 1, bez retain). Home Assistant Discovery (`homeassistant/sensor/smartdisk_…/config`) je opcion, po vrsti entiteta; isključen entitet se uklanja praznom porukom. Nedostupne vrednosti su `null`. Serijski brojevi i SSH podaci se ne objavljuju, a komande se ne primaju.

### Profili privilegija (spec. §5.3)

`adapters/privileges.py` pravi spisak sudo komandi i gotov sudoers fajl iz **istih šablona** koje koristi adapter, pa se profil i stvarne komande ne mogu razići. Spisak je dostupan u UI-ju na stranici uređaja i preko `GET /api/platforms/{platform}/privileges`.

- U argumentima nema džokera `*`, jer u sudoers-u hvata i razmake i dozvolio bi npr. `-t long`. Za ime diska se koriste klase znakova (`/dev/sd[a-z]`), koje hvataju tačno jedan znak.
- Sa sudo-om idu samo `smartctl` (pretraga i čitanje), `lvs`, `vgs` i `pvesm status`. `zpool`, `lsblk`, `glabel` i `/proc/mdstat` rade kao običan korisnik.
- Kada je SSH korisnik `root`, sudo se ne koristi, ali se root nalog ne preporučuje.

## SSH bezbednost

- **Host ključ se nikad ne prihvata automatski** (spec. §5.2). Tok je: administrator preuzme ključ (`/host-key/fetch`) → aplikacija ga čuva kao *čekajući* i prikazuje otisak i komandu za proveru na uređaju → administrator potvrđuje otisak (`/host-key/confirm`, server ga ponovo poredi sa čekajućim ključem).
- Pri povezivanju se prihvata samo potvrđeni ključ. Ako se ključ uređaja promeni, ciklus pada sa greškom „host ključ se ne poklapa” dok administrator ponovo ne potvrdi novi ključ. Svaka takva promena se beleži u audit log-u (`device.host_key_changed`).
- Pri preuzimanju se traži prvo ed25519, zatim ECDSA, a RSA tek na kraju.
- Promena adrese ili porta uređaja briše potvrđeni host ključ i isključuje nadzor.
- Koristi se samo prijava ključem (`preferred_auth=publickey`, bez SSH agenta). Ključ se može generisati u aplikaciji (ed25519) ili uneti postojeći (OpenSSH/PEM, uz opcioni passphrase).
- Privatni ključ i passphrase se čuvaju šifrovani Fernet-om. Master ključ je u `/etc/smartdisk/smartdisk.env`, van baze i van repozitorijuma. API nikad ne vraća privatni ključ, samo javni.
- Komande se sastavljaju isključivo iz šablona u kodu. Korisnički unos (host, korisnik) ide samo u parametre SSH konekcije, nikad u shell.
- Svaka komanda ima timeout, a stdout/stderr su ograničeni na `max_command_output_bytes`.
- Greške se razvrstavaju u vrste: `unreachable`, `dns`, `timeout`, `auth_failed`, `host_key_mismatch`, `command_timeout`, `credentials`, `ssh_error`, `unexpected`. UI ih prikazuje sa objašnjenjem na srpskom. Neuspeh se nikad ne prikazuje kao ispravno stanje.

## Autentifikacija i autorizacija

- Prijava korisničkim imenom i lozinkom (Argon2id). Za nepostojećeg korisnika se proverava lažni hash, da vreme odgovora ne otkrije da li nalog postoji.
- Ograničenje: 10 pokušaja u 5 minuta po IP adresi. Posle 5 uzastopnih neuspeha nalog se zaključava na 15 minuta.
- Sesija je slučajni token u kolačiću `sd_session` (`HttpOnly`, `Secure`, `SameSite=Strict`). U bazi se čuva samo njegov SHA-256 hash.
- Sesija ističe posle 30 minuta neaktivnosti ili najkasnije posle 12 h. Pozadinsko osvežavanje ekrana šalje `X-Background: 1` i ne produžava sesiju.
- CSRF: double-submit. Kolačić `sd_csrf` (čitljiv JS-u) mora se poklapati sa zaglavljem `X-CSRF-Token` za svaki zahtev koji menja stanje.
- Korisnik kome je administrator postavio lozinku (novi nalog ili reset) mora da je promeni pre bilo koje druge radnje.
- Uloge:

| Radnja | Administrator | Operater | Pregled |
|---|:-:|:-:|:-:|
| Pregled uređaja, istorije, dashboard-a | ✓ | ✓ | ✓ |
| Test konekcije, ručno prikupljanje | ✓ | ✓ | |
| Dodavanje/izmena/brisanje uređaja, SSH i host ključevi | ✓ | | |
| Korisnici, podešavanja, audit log | ✓ | | |

- Zaštite: ne može se deaktivirati sopstveni nalog niti ukloniti poslednji aktivni administrator. Deaktivacija ili reset lozinke odjavljuje sve sesije korisnika.

## API

Kompletna OpenAPI dokumentacija: `/api/docs`. Rute:

```text
POST   /api/auth/login                 POST /api/auth/logout
GET    /api/me                         POST /api/auth/change-password

GET    /api/users                      POST /api/users
PUT    /api/users/{id}                 POST /api/users/{id}/reset-password
POST   /api/users/{id}/unlock          POST /api/users/{id}/logout-all

GET    /api/devices                    POST /api/devices
GET    /api/devices/{id}               PUT  /api/devices/{id}
DELETE /api/devices/{id}               (soft-delete, istorija ostaje)
POST   /api/devices/{id}/generate-key  POST /api/devices/{id}/credentials
POST   /api/devices/{id}/host-key/fetch
POST   /api/devices/{id}/host-key/confirm
POST   /api/devices/{id}/test-connection
POST   /api/devices/{id}/collect       GET  /api/devices/{id}/runs

GET    /api/dashboard/summary          GET  /api/system/status
GET    /api/settings/collection        PUT  /api/settings/collection
GET    /api/settings/general           PUT  /api/settings/general
GET    /api/audit                      GET  /api/meta
GET    /api/health                     (javno, bez detalja)

GET    /api/disks?device_id=&include_missing=
GET    /api/disks/{id}                 (poslednje očitavanje sa atributima, self-testovi, pool-ovi)
GET    /api/disks/{id}/samples?from=&to=&limit=
GET    /api/disks/{id}/raw             (poslednji kompletan izlaz smartctl)
GET    /api/pools?device_id=           GET  /api/pools/{id}
GET    /api/platforms/{platform}/privileges

GET    /api/metrics/catalog            (spisak metrika za diskove i pool-ove)
GET    /api/metrics/disks?ids=1,2&metric=&from=&to=&bucket=auto|raw|hour|day|week&format=json|csv|xlsx
GET    /api/metrics/pools?ids=&metric=&from=&to=&bucket=&format=
GET    /api/metrics/availability?device_ids=&from=&to=&bucket=
GET    /api/disks/{id}/trends          (promena za 24 h, 7 dana, 30 dana)
GET    /api/stats/overview?from=&to=   (temperature, radni sati, istrošenost, pool-ovi, dostupnost)
GET    /api/reports                    (vrste izveštaja)
GET    /api/reports/{kind}?from=&to=&device_id=&format=json|csv|xlsx|pdf
```

### Analitika (Faza 3)

- Serije se agregiraju u bazi (`date_trunc` po vremenskoj zoni prikaza): temperatura kao prosek (sa min/maks u tooltip-u), brojači i sati rada kao maksimum, rezerva kao minimum. Imena metrika i agregacija dolaze iz rečnika u `analytics.py`, nikad iz zahteva.
- `bucket=auto`: do 2 dana sirovo, do 31 dan satno, do ~13 meseci dnevno, preko toga nedeljno. Sirovo je dozvoljeno za najviše 3 meseca. Na jednom grafikonu može biti najviše 8 serija.
- Za dnevne i nedeljne prikaze starijeg perioda, gde sirovih merenja više nema, koristi se `disk_daily`/`pool_daily`.
- Statistika za period: min, maks, prosek, prva, prethodna i poslednja vrednost, promena i brzina promene po danu. Trendovi diska se računaju za poslednjih 24 h, 7 dana i 30 dana. Ako prozor nije pokriven podacima, UI navodi od kada postoje.
- Dostupnost uređaja se računa iz `collection_runs` (planirani i ručni ciklusi; testovi se ne računaju, a delimično uspešan ciklus znači da je uređaj dostupan). Nedostupnost traje od prvog neuspelog do prvog sledećeg uspešnog ciklusa.
- Izvoz (`export.py`): CSV sa `;` i BOM-om (Excel sa srpskim podešavanjima), XLSX (openpyxl, datumi kao Excel datumi), PDF (reportlab, font DejaVu Sans zbog č/ć/đ; paket `fonts-dejavu-core` instalira `install.sh`). Vremena su u vremenskoj zoni prikaza.
- Izveštaji (`reports.py`): stanje uređaja, inventar diskova, diskovi sa upozorenjima, SMART promene u periodu, stanje skladišta i greške, nedostupnost uređaja. Isti podaci idu u pregled na ekranu i u izvoz.

Greške se vraćaju kao `{"detail": "<poruka na srpskom>"}`. I greške validacije su prevedene (`main.py`).

## Frontend

- Stranice: Pregled (brojači, „Zahteva pažnju”), Uređaji, detalj uređaja (vodič za podešavanje u tri koraka, stanje, alati, diskovi, skladište, profil privilegija, istorija), Diskovi (filteri po uređaju, stanju i tekstu), detalj diska (identitet, ključne SMART/NVMe vrednosti, atributi, self-testovi, istorija očitavanja, izvorni podaci), Skladište (pool-ovi po uređaju sa članovima), Korisnici, Podešavanja, Audit log, Moj nalog.
- Serijski brojevi su podrazumevano maskirani i otkrivaju se klikom (spec. §6.2, §9.2).
- Faza 3: Statistika (poređenje do 8 diskova na jednom grafikonu, tabela statistike, temperature, radni sati, istrošenost, trend zauzeća pool-ova sa procenom „puno za”, dostupnost uređaja), Izveštaji (pregled i preuzimanje CSV/XLSX/PDF; dnevni, nedeljni i mesečni period), detalj pool-a sa istorijom, dostupnost na stranici uređaja, trendovi i grafikoni na stranici diska. Tabela diskova ima sortiranje, filtere (uređaj, stanje, SMART, tip, prisutnost, tekst), straničenje i izvoz.
- Grafikoni (`components/charts.tsx`, Recharts): linije od 2 px, tooltip sa svim serijama za isti trenutak, legenda za 2+ serije, zumiranje prevlačenjem donje trake, prikaz kao tabela i izvoz podataka. Paleta serija je proverena za razlikovanje kod daltonizma u obe teme (`index.css`, `--series-1…8`). Boje se dodeljuju redom, nikad ciklično. Grafikoni nikad nemaju dve y-ose.
- Izbor perioda: 24 sata, 7, 30 i 90 dana, 1 godina i proizvoljno od–do, uz interval agregacije (automatski, sirovo, satno, dnevno, nedeljno).
- Stranice sa grafikonima se učitavaju tek kada zatrebaju (Recharts je zaseban paket).
- Faza 4: Alarmi (brojači po nivou, filteri, potvrda, ručno zatvaranje, detalj sa istorijom, komentarima i poslatim obaveštenjima), značka sa brojem aktivnih alarma u meniju, „Zdravlje diska” (kartica sa razlozima i preporukama po spec. §8.12, kolona u tabeli diskova, brojači na pregledu), oznake trenutka alarma na grafikonima diska, Podešavanja (pragovi, SMTP, MQTT/HA, adresa aplikacije, evidencija obaveštenja), Web Push u „Moj nalog”.
- Pool bez redundanse (ZFS stripe) dobija upozorenje. Zauzeće LVM volume grupe se prikazuje neutralno, kao „dodeljeno volumenima”, jer je visok procenat na Proxmoxu uobičajen.
- Svetla i tamna tema (podrazumevano prema sistemu, izbor se pamti u pregledaču). Prilagođeno mobilnom ekranu.
- Status se uvek prikazuje bojom, ikonom **i** tekstom (spec. §10.1).
- Pregled i lista uređaja se osvežavaju na 15 s, a detalj uređaja na 10 s.
