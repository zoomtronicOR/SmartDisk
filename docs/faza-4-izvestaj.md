# Izveštaj - Faza 4: Analiza degradacije i alarmiranje

**Datum:** 28.10.2026.
**Verzija:** 0.4.0 + migracija `0004` (aplikacija je tada greškom još prikazivala 0.1.0)
**Okruženje:** LXC `Smart-Disk`, `https://192.168.88.246`

## Isporučeno (spec. §22, Faza 4)

| Stavka | Stanje | Gde |
|---|---|---|
| „Zdravlje diska” (spec. §8.8) | ✓ 6 nivoa, ocena 0-100, razlozi, preporuke (§8.12); nezavisno od SMART statusa | `health.py: disk_health`, `components/Health.tsx` |
| Trendovi 24 h / 7 d / 30 d | ✓ (iz Faze 3) + koriste se u pravilima | `health._history`, `/api/disks/{id}/trends` |
| Postepena i ubrzana degradacija | ✓ realocirani, pending i neispravljivi sektori, CRC; pragovi po prozoru | `health.evaluate_disk` |
| NVMe degradacija | ✓ critical warning, media greške između očitavanja, rezerva, istrošenost, log grešaka, nebezbedna gašenja | isto |
| Temperaturna degradacija | ✓ pragovi po tipu (HDD/SSD/NVMe, uz kritičnu granicu koju prijavljuje NVMe), ponovljena prekoračenja, histereza, nagli rast, throttling | isto |
| ZFS/RAID korelacija | ✓ disk sa SMART problemom u degradiranom pool-u → kritično, sa porukom koja ih povezuje | `health.correlate` |
| Pravila i pragovi | ✓ podesivi u UI-ju, sa preporučenim vrednostima i proverom ispravnosti | `/api/notifications/thresholds`, Podešavanja |
| Eskalacija | ✓ informativno → upozorenje → visoko → kritično; pogoršanje ponovo otvara alarm i šalje obaveštenje | `events.apply` |
| Deduplikacija i potvrda | ✓ fingerprint, brojač ponavljanja, potvrda uslova u N procena, cooldown, podsetnik, automatsko rešavanje, potvrda/komentar/ručno zatvaranje sa istorijom | `events.py`, `routers/alarms.py`, stranice Alarmi |
| Browser Push | ✓ VAPID, service worker, nivo, uređaji, utišavanje, proba, evidencija | `notify/push.py`, `public/sw.js`, `components/PushCard.tsx` |
| MQTT | ✓ LWT, retain, heartbeat, ponovno povezivanje, QoS 1 za događaje, test veze, status | `notify/mqtt.py` |
| Home Assistant Discovery | ✓ entiteti po vrsti, uključivanje/isključivanje | isto |
| **E-pošta (SMTP)** - dodato na zahtev | ✓ STARTTLS/SSL, šifrovana lozinka, primaoci, najniži nivo, probna poruka | `notify/email.py` |

Dokumentacija za korisnika: [obavestenja.md](obavestenja.md).

## Testiranje

**Automatski testovi:** ukupno 34, svi prolaze. Od toga je 18 novih testova degradacije (spec. §21.2), sa simuliranim podacima:

- rast realociranih sektora (informativno, upozorenje, visoko) i SMART PASSED sa rastućim greškama → „Ugroženo” (§21.4 tačka 8);
- rast pending i neispravljivih sektora (→ kritično);
- NVMe: media greške između dva očitavanja, rezerva ispod praga, critical warning, pragovi istrošenosti;
- temperatura: nivoi, ponovljena prekoračenja, histereza i nagli rast; NVMe ima više pragove;
- SMART FAILED, nema podataka (Nepoznato, nikad „dobro”), nestao disk;
- CRC greške su samo informativne;
- degradiran ZFS pool sa disk-korelacijom → kritično;
- zauzeće pool-a, scrub sa greškama, LVM VG bez lažnog alarma;
- spajanje pragova.

**E2E na kontejneru, sa stvarnim diskovima** (privremeni Mosquitto broker na kontejneru, posle testa uklonjen):

| Korak | Rezultat |
|---|---|
| MQTT test veze: ispravna / pogrešna lozinka | „Veza … uspešni” / „Broker je odbio prijavu (korisničko ime/lozinka)” |
| SMTP proba bez servera | „SMTP server 127.0.0.1:2525 nije dostupan (Connection refused)” |
| Neispravni pragovi (opadajući) | odbijeni sa porukom na srpskom (422) |
| Privremeno spušteni pragovi HDD 30/36/44 °C, prikupljanje | 8 alarma: 3 visoka (ponovljeno prekoračenje), 5 informativnih; zdravlje 3 diska „Ugroženo”, 5 „Dobro” |
| Potvrda alarma / ponovna potvrda / komentar | 200 / 409 / 200; istorija „otvoren → potvrđen → komentar” |
| MQTT | `availability online`, `summary`, stanja diskova, pool-ova i uređaja, HA Discovery konfiguracije i 8 događaja na `diskmonitor/events` |
| Vraćeni pragovi, prikupljanje | svih 8 alarma automatski rešeno, svi diskovi „Odlično” |

**U Chrome-u:** pregled (zdravlje diskova, aktivni alarmi), stranica Alarmi, kartica zdravlja na stranici diska, podešavanja (pragovi, SMTP, MQTT, opšte, evidencija).

**Stanje na stvarnim uređajima:** svih 13 diskova je „Odlično” i nema aktivnih alarma. To odgovara podacima: nema rasta grešaka, a temperature su ispod pragova.

## Napomene

- Test alarma je izveden privremenom sesijom pod nalogom `admin`, direktno na kontejneru. Zato u audit logu oko 22:20 postoje zapisi `settings.mqtt_updated`, `settings.thresholds_updated` i `alarm.acknowledged` od korisnika `admin`. Audit log se ne briše. Podešavanja su posle testa vraćena (pragovi podrazumevani, MQTT isključen), a test alarmi su obrisani.
- Tokom razvoja instalacija paketa u globalni Python na Windows računaru podigla je `paho-mqtt` na 2.1, što ESPHome ne podržava. Vraćeno je na 1.6.1, a lokalni testovi se od tada pokreću samo u `backend/.venv`.

## Nije provereno

- **Web Push u pregledaču**: zahteva da korisnik u Chrome-u odobri obaveštenja (*Moj nalog → Uključi obaveštenja*). Slanje je provereno samo do generisanja VAPID ključeva.
- **Stvarni SMTP server i Home Assistant**: podešavaju se vašim podacima (adresa HA i MQTT korisnik, SMTP nalog). Mehanizam je proveren sa lokalnim brokerom i sa nedostupnim SMTP serverom.
- Alarmi „uređaj nedostupan” i „nepotpuno prikupljanje” na stvarnom ispadu uređaja (pokriveni logikom, nije izazivan ispad).

## Ograničenja i odluke

- Pravila su podesiva globalno, a ne posebno po uređaju ili disku (spec. §11.1 traži i po uređaju/disku). Izbor uređaja postoji za Web Push. Pragovi po disku mogu se dodati u Fazi 5.
- Pragovi za temperaturu SAS diska koriste HDD pragove, a za USB diskove pragove po tipu medija.
- Komande iz Home Assistant-a (osvežavanje, potvrda alarma), opcione po spec. §12.4, nisu urađene. MQTT je samo telemetrija.
- Grafikon „broj upozorenja po danu” postoji kao `per_day` u `/api/alarms/summary`, ali još nije nacrtan.
- Za pool bez redundanse (stripe, npr. MediaPool) nema alarma, samo upozorenje na stranici skladišta. To je stanje konfiguracije, a ne degradacija.
