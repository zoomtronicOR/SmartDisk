# Izveštaj – Faza 3: Dashboard i analitika

**Datum:** 28.10.2026.
**Verzija:** 0.1.0 + migracija `0003`
**Okruženje:** LXC `Smart-Disk`, `https://192.168.88.246`

## Isporučeno (spec. §22, Faza 3)

| Stavka | Stanje | Gde |
|---|---|---|
| Dashboard | ✓ uređaji, diskovi po stanju, SMART FAILED, diskovi ≥ 50 °C, najviša temperatura, skladište sa problemom, „Zahteva pažnju”, poslednja i sledeća prikupljanja | `pages/Dashboard.tsx`, `/api/dashboard/summary` |
| Tabele diskova i uređaja | ✓ diskovi: sortiranje po kolonama, filteri (uređaj, stanje, SMART, tip, prisutnost, tekst), straničenje, izvoz CSV/XLSX/PDF; uređaji: broj diskova i upozorenja | `pages/Disks.tsx`, `pages/Devices.tsx` |
| Detaljna stranica diska | ✓ trendovi 24 h / 7 dana / 30 dana, grafikoni po metrici, statistika za period | `components/DiskAnalytics.tsx` |
| Grafikoni i statistika | ✓ poređenje do 8 diskova na jednom grafikonu; temperature (min/prosek/maks), radni sati, istrošenost SSD/NVMe, trend zauzeća pool-ova sa procenom „puno za”, dostupnost uređaja | `pages/Statistics.tsx`, `/api/metrics/*`, `/api/stats/overview` |
| Period od–do | ✓ 24 sata, 7, 30, 90 dana, 1 godina, proizvoljno od–do; interval: automatski, sirovo, satno, dnevno, nedeljno | `components/charts.tsx: PeriodPicker` |
| Izvoz izveštaja | ✓ CSV, XLSX, PDF za 6 izveštaja i za podatke svakog grafikona | `export.py`, `reports.py`, `pages/Reports.tsx` |
| Dnevni agregati (spec. §9.2) | ✓ `disk_daily`, `pool_daily`, noćni obračun u 03:15; ostaju posle brisanja sirovih merenja | `analytics.aggregate_daily` |
| Detalj pool-a | ✓ istorija zauzeća, slobodnog prostora, R/W/CKSUM grešaka i napretka scrub-a/resilver-a | `pages/PoolDetail.tsx` |
| Dostupnost uređaja | ✓ uspešni/neuspeli ciklusi po intervalu, procenat, periodi nedostupnosti sa razlogom | `components/Availability.tsx`, `/api/metrics/availability` |

Izveštaji (spec. §10.7): stanje uređaja, inventar diskova, diskovi sa upozorenjima, SMART promene u periodu, stanje skladišta i greške, nedostupnost uređaja. Dnevni, nedeljni i mesečni pregled se dobija izborom perioda (24 sata, 7 ili 30 dana).

Grafikoni prate pravila za čitljivost i pristupačnost:

- paleta serija je proverena validatorom za daltonizam (protan/deutan/tritan) u svetloj i tamnoj temi;
- boja prati disk, a ne redosled: kada se disk ukloni sa poređenja, ostali zadržavaju svoje boje;
- grafikon nema dve y-ose, a za 2+ serije ima legendu;
- tooltip prikazuje sve serije za isti trenutak, uz raspon (min–maks) agregiranog intervala;
- zumiranje prevlačenjem donje trake;
- prikaz kao tabela, jer tri svetle boje imaju kontrast ispod 3:1 na beloj pozadini.

## Ispravke otkrivene tokom faze

1. **Disk u standby-ju postajao je „nov” disk.** Diskovi u DataPool-u (TrueNAS CORE) ulaze u standby. Tada `smartctl -n standby` (namerno, da ih ne budi) ne vraća WWN ni serijski broj, pa je aplikacija pravila zapis po putanji i označavala prave diskove kao nestale. Rešeno je tako da se očitavanje bez identiteta pripisuje poznatom disku na istoj putanji. Za standby disk stanje i vrednosti se prikazuju iz poslednjeg SMART očitavanja, uz napomenu. 7 postojećih duplikata je spojeno u bazi, a istorija je sačuvana.
2. **Standby očitavanje je brisalo tip diska** (HDD → „nepoznat”). Tip utvrđen ranije se sada ne prepisuje, a 7 diskova je vraćeno na HDD.
3. **Boje na poređenju se nisu slagale** između liste diskova i grafikona (grafikon je bojio po redosledu ID-a). Boja sada prati disk.
4. „Upisano” je jednom bilo prikazano decimalno (11,8 TB), a drugi put binarno (10,7 TB). Ujednačeno je na binarne jedinice. Izuzetak je kapacitet diska, koji je decimalan, kao na nalepnici.
5. Y-osa zauzeća je za skoro konstantnu vrednost imala sve oznake „7,4 TB”. Količine u bajtovima sada počinju od nule.
6. Ugrađene kontrole (checkbox, datum) pratile su temu Windows-a umesto teme aplikacije. Sada prate temu aplikacije.
7. Kartica izveštaja bila je šira od ekrana, pa su dugmad za preuzimanje bila sakrivena. Ispravljeno.

## Testiranje

- **Automatski testovi:** 16, svi prolaze (13 parsera iz Faze 2 + 3 testa izvoza). Izvoz proverava srpska slova (čćžšđ ČĆŽŠĐ) u CSV, XLSX i PDF, lokalno vreme, decimalni zarez i prazno polje umesto „0” za nedostupne vrednosti.
- **API na kontejneru** (kroz aplikaciju, privremena sesija koja je posle obrisana): serije (auto/satno/dnevno), pool serije, trendovi, dostupnost, statistika, svih 6 izveštaja u JSON-u i svaki izveštaj u CSV, XLSX i PDF formatu, izvoz serije u XLSX. Proverene su i greške: nepoznata metrika, sirov prikaz za period duži od 3 meseca i obrnut period odbijaju se sa porukom na srpskom (422).
- **U Chrome-u** (posle instalacije lokalnog CA): Statistika (poređenje, promena izbora i boje, tabele), stranica diska (trendovi, grafikoni, metrike po tipu diska), Izveštaji, detalj pool-a, dostupnost na stranici uređaja, pregled, svetla i tamna tema. Konzola je bez grešaka.

**Nije provereno:**

- preuzimanje fajlova klikom u pregledaču, jer bi se fajl sačuvao na vaš računar (izvoz je proveren na serveru);
- grafikoni sa dužom istorijom: podaci postoje tek od 28.10.2026, pa su prikazi za 30, 90 dana i godinu tek delimično popunjeni;
- noćni obračun agregata i brisanje starih merenja: prvi put se izvršavaju u 03:15 i 03:30. Upiti su provereni, ali ne na danima koji su završeni.

## Ograničenja i odluke

- „Broj otvorenih alarma”, „Kratak pregled najvažnijih događaja” i „Broj upozorenja po danu” (spec. §10.1, §10.5) zavise od alarma iz Faze 4. Do tada pregled prikazuje „Zahteva pažnju” iz trenutnog stanja.
- Prag „povišene temperature” je privremeno fiksan (50 °C). Podesivi pragovi po tipu diska dolaze u Fazi 4.
- Izveštaj o diskovima sa ubrzanom degradacijom (spec. §10.7) zahteva detekciju degradacije iz Faze 4.
- Izvoz samog grafikona kao slike i PDF grafikona nisu urađeni. Izvoze se podaci grafikona (CSV/XLSX) i izveštaji (PDF sa tabelama).
- Zakazivanje izveštaja i slanje e-mailom (spec. §10.7, opciono) planirano je za Fazu 5 (zakazani izveštaji).
- Posebna stranica „Poređenje diskova” (spec. §10.6) je u Fazi 5. Poređenje više diskova na jednom grafikonu postoji u Statistici.
- Procena „puno za” je linearna, iz izabranog perioda, i za kratke periode nije pouzdana (navedeno u UI-ju). Prediktivni trendovi dolaze u Fazi 5.
- CSV koristi `;` i BOM zbog Excel-a sa srpskim podešavanjima. Drugi programi mogu tražiti izbor separatora.

## Napomena o sertifikatu

Kaspersky je tokom faze počeo da blokira aplikaciju zbog samopotpisanog sertifikata. Lokalni CA je instaliran u Windows (*Trusted Root Certification Authorities*) i aplikacija se otvara bez upozorenja. Fajl je u `sertifikat/SmartDisk-CA.crt` (van git-a). Postupak je opisan u [instalacija.md](instalacija.md#https-sertifikat).
