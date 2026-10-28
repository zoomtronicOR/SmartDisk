# Izveštaj – Faza 1: Osnova aplikacije

**Datum:** 28.10.2026.
**Verzija:** 0.1.0
**Okruženje:** LXC `Smart-Disk`, `https://192.168.88.246`

## Isporučeno (spec. §22, Faza 1)

| Stavka | Stanje | Gde |
|---|---|---|
| LXC instalacija | ✓ | `deploy/install.sh`, `deploy/deploy.sh`, [instalacija.md](instalacija.md) |
| Backend (FastAPI) | ✓ | `backend/app` |
| PostgreSQL + migracije | ✓ | `backend/app/models.py`, `backend/alembic/versions/0001_pocetna_sema.py` |
| Frontend (React) | ✓ | `frontend/src` |
| HTTPS reverse proxy | ✓ | `deploy/Caddyfile` (lokalni CA) |
| Prvi administrator | ✓ | `deploy/create-admin.sh` (`python -m app.cli create-admin`) |
| Prijava, sesije, uloge | ✓ | Argon2id, HttpOnly/Secure/SameSite kolačići, CSRF, istek sesije, zaključavanje naloga, ograničenje pokušaja |
| Više administratora i korisnika | ✓ | uloge administrator, operater, pregled; reset lozinke, otključavanje, odjava sesija |
| Upravljanje uređajima | ✓ | dodavanje, izmena, soft-delete, uključivanje/isključivanje, oznake, lokacija, napomena, timeout-i |
| SSH ključevi | ✓ | generisanje ed25519 ili unos postojećeg; šifrovano čuvanje |
| Provera host ključa | ✓ | preuzimanje → ručna potvrda otiska; bez automatskog prihvatanja |
| SSH test konekcije | ✓ | prepoznavanje sistema i dostupnih alata, upozorenja o nedostajućim funkcijama (spec. §5.4) |
| Scheduler sa dinamičkim intervalima | ✓ | globalni i interval po uređaju, promena bez restarta, prikaz sledećeg ciklusa |
| Ručno prikupljanje | ✓ | pozadinski zadatak, zaštita od preklapanja |
| Evidencija ciklusa | ✓ | `collection_runs`: početak, trajanje, status, razlog neuspeha |
| Audit log | ✓ | prijave, korisnici, uređaji, ključevi, podešavanja |
| Nadzor same aplikacije | delimično | health-check, heartbeat scheduler-a sa upozorenjem u UI-ju, veličina baze, slobodan prostor (spec. §18) |
| Svetla/tamna tema, mobilni prikaz | ✓ | |

## Testiranje

End-to-end test kroz API je izvršen na kontejneru, preko HTTPS-a kroz Caddy. Kao SSH cilj je korišćen sam kontejner, sa privremenim nalogom `diskmonitor`.

| Scenario | Rezultat |
|---|---|
| Prijava pogrešnom lozinkom | odbijeno, poruka „Pogrešno korisničko ime ili lozinka.” |
| Pristup bez prijave | 401 „Niste prijavljeni.” |
| Izmena bez CSRF tokena | 403 |
| Neispravan host (`bad host;rm`) | 422 „Neispravna IP adresa ili DNS ime.” |
| Uključivanje nadzora pre ključeva | odbijeno sa objašnjenjem |
| Generisanje ključa i dodavanje u `authorized_keys` | ✓ |
| Preuzimanje host ključa | ed25519, otisak se poklapa sa `ssh-keygen -lf` na kontejneru |
| Potvrda pogrešnog otiska | odbijeno |
| Test konekcije | uspešno za 111 ms; prepoznat „Debian GNU/Linux 13 (trixie)”, tačna upozorenja za `smartctl`, `zpool`, `lvs` |
| Uključivanje nadzora, interval 1 → 2 min | sledeći ciklus odmah pomeren |
| Planirano prikupljanje | izvršeno automatski (117 ms) |
| Dashboard, sistemski status, audit (22 zapisa) | ✓ |
| Odjava | sesija poništena |
| Frontend | `tsc` bez grešaka; Caddy servira SPA rute, HTTP→HTTPS preusmerenje (308) |

Ispravke tokom testiranja:

- `test-connection` je vraćao grešku 500 jer je posle `expire_all()` lenjo učitavanje pokrenuto izvan async konteksta. Ispravljeno.
- Pri preuzimanju host ključa birao se RSA umesto ed25519. Sada se traže moderni algoritmi.
- Posao za uređaj obrisan direktno u bazi ostajao je u scheduler-u. Sada se sam uklanja.

Posle testa su obrisani svi test podaci: test korisnik, uređaj, ciklusi, audit zapisi i nalog `diskmonitor` na kontejneru. Baza je prazna i čeka prvog administratora.

Interfejs je zatim pregledan u Chrome-u, prijavljen kao prvi administrator (28.10.2026.): pregled, uređaji (forma za novi uređaj), korisnici, podešavanja sa stanjem aplikacije, audit log i moj nalog. Proverene su tamna i svetla tema, a konzola je bez grešaka.

**Nije provereno:** mobilni prikaz uživo u pregledaču (raspored postoji u kodu: meni koji se uvlači i tabele sa horizontalnim pomeranjem). Rad na stvarnim TrueNAS/Proxmox/Synology uređajima.

## Poznata ograničenja i odluke

- Samo prijava SSH ključem. Prijava lozinkom (spec. §5.2, „samo ako je izričito omogućena”) nije implementirana. Može se dodati ako zatreba.
- Ograničenje pokušaja prijave po IP adresi čuva se u memoriji procesa i briše se restartom. Zaključavanje naloga se čuva u bazi i ostaje.
- Komanda se izvršava u celosti, pa se izlaz skraćuje tek posle prijema. Za fiksne read-only komande to je prihvatljivo. Za veće izlaze u Fazi 2 razmotriti čitanje u delovima.
- Posle promene intervala sledeći ciklus je „sada + novi interval”, a ne „poslednji ciklus + novi interval”.
- Sertifikat je iz lokalnog Caddy CA. Za Web Push (Faza 4) potreban je pouzdan sertifikat ([instalacija.md](instalacija.md#https-sertifikat)).
- Backup i restore zasad postoje samo kao ručne komande. Automatizacija i provera integriteta su planirane za kasnije.
- TOTP dvofaktorska autentifikacija (opciono po spec. §14.2) nije urađena.
- PostgreSQL podaci su na sistemskom disku kontejnera. Specifikacija preporučuje poseban volumen (§4.1); to je moguće uraditi pre punjenja istorije.

## Otvorena pitanja za Fazu 2 (spec. §23)

Pre početka Faze 2 potrebno je od administratora:

1. Tačne verzije TrueNAS (SCALE ili CORE), Proxmox VE i Synology DSM.
2. Da li su diskovi direktno povezani, preko HBA ili RAID kontrolera.
3. Koji su diskovi SATA, SAS, NVMe ili USB.
4. Kreirani `diskmonitor` nalozi na uređajima, da bi se na stvarnim sistemima utvrdile potrebne komande i `sudoers` profili.
5. Koliko dugo čuvati sirova merenja.
