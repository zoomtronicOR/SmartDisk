# Izveštaj – Faza 5: Napredne funkcije

**Datum:** 28.10.2026.
**Verzija:** 0.5.0 + migracija `0005` (korisničko uputstvo: 0.6.0)
**Okruženje:** LXC `Smart-Disk`, `https://192.168.88.246`

## Isporučeno (spec. §22, Faza 5, i dodatni zahtevi)

| Stavka | Stanje | Gde |
|---|---|---|
| Poređenje diskova (§10.6) | ✓ do 6 diskova jedan pored drugog, zajednički SMART atributi, upozorenje za različite proizvođače | stranica Poređenje |
| Detekcija promena inventara (§16.2) | ✓ nov disk, zamena na istoj putanji, promena modela, kapaciteta ili putanje, promena sastava pool-a → događaj; istorija ostaje | `persist.py`, alarmi kategorije „inventory” |
| Prediktivni trendovi (§16.1) | ✓ linearni trend (regresija u bazi), procena dostizanja granice, kvalitet podataka, jasno označeno kao procena | `/api/predictions`, Statistika, stranica diska |
| Mapa skladišta (§16.3) | ✓ uređaj → pool/RAID → vdev → diskovi, statusi, klik na disk; napomena da kontroleri nisu dostupni | stranica Mapa skladišta |
| Zakazani izveštaji | ✓ dnevno, nedeljno, mesečno; PDF/XLSX/CSV u prilogu e-pošte; „Pošalji sada” | `schedules.py`, Podešavanja |
| Dodatni kanali (§16.6) | ✓ Telegram, Pushover, webhook (HMAC); probno slanje | `notify/channels.py` |
| API tokeni (§16.7) | ✓ čitanje/operater, rok, opoziv, poslednja upotreba; token se prikazuje jednom | `routers/tokens.py`, Moj nalog |
| Backup i vraćanje (§16.5, kriterijum 16) | ✓ dnevni i ručni backup, provera integriteta, rotacija, alarm pri neuspehu; vraćanje dokumentovano i provereno | `backup.py`, [instalacija.md](instalacija.md#backup-i-vraćanje-spec-165) |
| Režim održavanja (§16.4) | ✓ samo kritična obaveštenja do zadatog vremena | Podešavanja |
| **NTP i prikaz vremena (§18.1, novi zahtev)** | ✓ SNTP provera, status hosta, alarmi za odstupanje, sat nadziranih uređaja, datum i vreme u zaglavlju | `timesync.py`, `components/Clock.tsx` |
| **Merači po disku (novi zahtev)** | ✓ prekidač Grafikon/Merači pored izbora intervala; zone iz pragova alarma | `components/Gauges.tsx` |
| **Statičan meni (novi zahtev)** | ✓ meni sa strane stoji u mestu, a pomera se samo sadržaj | `components/Layout.tsx` |

## Testiranje

- **Automatski testovi:** 39, svi prolaze (5 novih: tačnost vremena, raspored izveštaja, kanali bez mreže).
- **Na kontejneru i u Chrome-u:**

| Provera | Rezultat |
|---|---|
| NTP | `pool.ntp.org`, odstupanje 0,4 ms, stratum 2–3, host sinhronizovan; sat u zaglavlju |
| Prognoze | 15 procena za diskove i 13 za pool-ove, sve označene „nepouzdano” (istorija je kraća od dana), što je ispravno |
| Merači | 13 diskova; zone po tipu (Kingston NVMe na 49 °C je „normalno”, jer NVMe ima više pragove); standby diskovi prikazuju poslednje očitavanje |
| Mapa skladišta | DataPool raidz2 sa 7 diskova, MediaPool, boot-pool; Proxmox thin pool i diskovi van pool-a |
| Poređenje | 3 diska različitih proizvođača, upozorenje o raw vrednostima |
| Backup | ručni backup 136 KB, provera 171 stavke; **vraćanje u privremenu bazu**: svih 8 proverenih tabela vraćeno (razlike su samo upisi posle backup-a), privremena baza obrisana |

Ispravke tokom faze:

1. Upit za prognoze imao je dvosmislenu kolonu `used_bytes` (500). Kolone su sada vezane za tabelu.
2. Stranica Podešavanja je padala („Invalid time value”), jer su sat u zaglavlju i kartica NTP-a delili ključ keša sa različitim oblikom podataka. Ključevi su odvojeni, a formatiranje datuma više ne može da obori ekran.
3. Lukovi merača su bili pogrešno nacrtani (oznaka `large-arc`).
4. Polja u karticama backup-a i održavanja su se razvlačila preko celog reda.
5. Verzija je od Faze 1 stajala na 0.1.0. Sada je 0.5.0, a pravilo verzija je zapisano.

## Nije provereno

- Telegram, Pushover i webhook sa stvarnim nalozima (nema podataka); proverena je validacija i obrada grešaka bez mreže.
- Zakazani izveštaj u stvarnom slanju (SMTP još nije podešen); generisanje izveštaja je provereno u Fazi 3.
- Promene inventara na stvarnoj zameni diska (logika je pokrivena, a zamena nije izvođena).
- Web Push (čeka vaše odobrenje u Chrome-u), stvarni Home Assistant i SMTP, kao u Fazi 4.

## Ograničenja i odluke

- Kalendar SMART testova i scrub-ova (§16.4) nije urađen. Aplikacija ne zakazuje testove, a datum poslednjeg scrub-a se vidi na pool-u.
- Prognoze su linearne. Za pouzdanu procenu potrebno je bar nekoliko nedelja istorije.
- Kontroleri (HBA/RAID) se ne prikazuju na mapi, jer ih read-only komande ne izlažu pouzdano.
- Backup ne sadrži master ključ. Ključ se mora čuvati posebno (uputstvo u instalacija.md).
- Pragovi su globalni, a ne po disku.
