# Dnevnik izmena

Izmene posle Faze 5 i korisničkog uputstva (0.6.0). Svaka verzija na GitHub-u ima tag `vX.Y.Z`. Šta je isporučeno u fazama opisuju [izveštaji faza](../README.md#stanje-razvoja).

## 0.6.8 - 29.10.2026.

- **Detaljno uputstvo za povezivanje uređaja** (korisničko uputstvo, poglavlje 11, i stranica Pomoć): kako SmartDisk pristupa serveru, pet koraka od dodavanja uređaja do uključivanja nadzora, priprema naloga `diskmonitor` posebno za TrueNAS SCALE, TrueNAS CORE, Proxmox VE i Synology, potvrda host ključa, provera da sve radi, tabela grešaka pri povezivanju, promena ključa i uklanjanje uređaja.
- Za TrueNAS SCALE i CORE uputstvo sadrži celu `midclt user.create` komandu sa spiskom dozvoljenih komandi, pa se menjaju samo naziv pool-a i javni ključ.
- Na stranici Pomoć svaki blok sa komandom ima dugme **Kopiraj**, a duge komande se prelamaju umesto da izlaze iz okvira.

## 0.6.7 - 29.10.2026.

- **TrueNAS SCALE proveren na stvarnom uređaju** (27.0.0-RC.1): 6 diskova sa SMART podacima, pool-ovi `datapool` (RAIDZ1) i `boot-pool`, stanje scrub-a i resilver-a. Postupak za nalog `diskmonitor` preko `midclt` je u [dodavanje-uredjaja.md](dodavanje-uredjaja.md#truenas-scale).
- **Ispravka:** na SCALE 27 `/etc/version` nema završni prelom reda, pa se oznaka sledeće sekcije zalepila za verziju sistema. Aplikacija tada nije videla nijedan alat i javljala je „smartctl nije pronađen”. Detekcija sistema sada deli izlaz po poznatim oznakama, a ne po redovima (`app/ssh/probe.py`), uz novi test.

## 0.6.6 - 29.10.2026.

- **Skrivena šala:** posle 5 uzastopnih klikova na sat u zaglavlju, sat se 30 sekundi prikazuje preko celog ekrana, sa natpisom „HOĆEŠ DA KLIKĆEŠ, EVO TI SAD!” iznad. Ne može se zatvoriti ranije. Prikazuje se kroz portal u `body`, jer zaglavlje ograničava `fixed` elemente.
- **Ispravka:** odmah posle restarta servisa, opis sata je do prve NTP provere (svakih 15 minuta) prikazivao „NTP: null”. `GET /api/system/time` sada uvek vraća podešeni NTP server.
- Zajednički brojač uzastopnih klikova: `frontend/src/components/clickBurst.ts` (5 klikova, razmak najviše 1,5 s).

## 0.6.5

Interna verzija tokom rada na 0.6.6, nije objavljena na GitHub-u.

## 0.6.4 - 29.10.2026.

- **Skrivena šala:** posle 5 uzastopnih klikova na natpis „SmartDisk” u meniju, pored njega se pojavljuje crveni ljuti smajli i ostaje 5 minuta. Vreme isteka se čuva u pregledaču (`localStorage`, ključ `sd-angry`), pa smajli ostaje i posle osvežavanja stranice.

Skrivene šale namerno nisu opisane u korisničkom uputstvu.

## 0.6.3 - 29.10.2026.

- Sve dugačke crte (em dash i en dash) u interfejsu, porukama servera i dokumentaciji zamenjene su običnom crticom „-”: 227 zamena u 70 fajlova. Prazna vrednost u tabelama je „-”. Dvostruke crtice u komandama (npr. `--scan-open`) i test fixtures sa stvarnim izlazom uređaja nisu menjani.

## 0.6.2 - 29.10.2026.

- **Logo kompanije:** Podešavanja → Izgled. PNG, JPEG ili WebP do 512 KB (SVG se odbija zbog bezbednosti), prikazuje se na dnu menija, a verzija aplikacije iznad njega.
- README sa snimcima ekrana.

## 0.6.1 - 28.10.2026.

- **Audit prijava:** svaka prijava (uspešna, neuspešna, zaključan nalog, previše pokušaja) beleži rezultat, razlog i podatke o računaru: IP adresa, ime računara iz DNS-a, pregledač, operativni sistem, vrsta uređaja, ekran, jezik, vremenska zona i drugo.
- Klik na red audit loga otvara prozor sa svim detaljima i izvornim JSON zapisom.

## Otvoreno za 1.0.0

- Provera kanala obaveštenja sa stvarnim nalozima: Web Push (korisnik odobrava u pregledaču), Home Assistant MQTT, SMTP. Po mogućstvu i Telegram, Pushover i webhook.
- Synology nije proveren, jer uređaj nije dostupan.
- Ukloniti privremeni root ključ `claude-smartdisk-setup` sa nadziranih uređaja.
- Posle postavljanja pravog logotipa osvežiti snimke ekrana u uputstvu i README-u.
