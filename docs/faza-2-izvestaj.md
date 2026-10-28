# Izveštaj – Faza 2: Prikupljanje podataka

**Datum:** 28.10.2026.
**Verzija:** 0.1.0 + migracija `0002`
**Okruženje:** LXC `Smart-Disk`, `https://192.168.88.246`

## Isporučeno (spec. §22, Faza 2)

| Stavka | Stanje | Gde |
|---|---|---|
| Proxmox adapter | ✓ provereno na 2 hosta (PVE 9.2.21) | `adapters/platforms.py: collect_linux` |
| TrueNAS CORE adapter | ✓ provereno (TrueNAS-13.0-U6.8) | `collect_truenas_core` |
| TrueNAS SCALE adapter | napisan, **nije proveren** (uređaj je u resilver-u) | `collect_linux` |
| Synology adapter | napisan, **nije proveren** (nema uređaja); JSON i tekstualni smartctl | `collect_synology` |
| Inventar diskova | ✓ stabilan identitet (WWN/EUI/serijski broj), praćenje putanje, nestali diskovi, diskovi koje smartctl ne vidi | `persist.py`, tabela `disks` |
| SMART (SATA/SAS) | ✓ overall-health, ključni brojači, svi atributi (value/worst/thresh/raw), log grešaka, self-testovi | `adapters/smart.py` |
| NVMe | ✓ critical warning, spare i prag, percentage used, data units, komande, busy time, unsafe shutdowns, media greške, log grešaka, vreme iznad temperaturnih pragova | isto |
| ZFS | ✓ stanje, vdev stablo, R/W/CKSUM po članu, scrub/resilver (stanje, napredak, greške), kapacitet, fragmentacija, redundansa, greške podataka | `adapters/storage.py` |
| LVM / LVM-thin | ✓ VG (dodeljeno/slobodno, partial), thin pool (data/meta %, stanje iz `lv_attr`) | isto |
| Proxmox storage | ✓ `pvesm status` (dir, lvmthin, pbs…) | isto |
| mdadm / Synology RAID | parser sa testom; na stvarnom nizu nije proveren | isto |
| Istorijsko čuvanje | ✓ uzorak po disku i pool-u u svakom ciklusu; podesiv period (podrazumevano 365 dana), noćno brisanje | `disk_samples`, `pool_samples`, `scheduler._cleanup_samples` |
| Profili privilegija (spec. §5.3) | ✓ tačni sudoers profili iz istih šablona kao komande; prikaz u UI-ju | `adapters/privileges.py`, [dodavanje-uredjaja.md](dodavanje-uredjaja.md) |
| UI | ✓ Diskovi, detalj diska, Skladište, diskovi i pool-ovi na stranici uređaja, brojači i „Zahteva pažnju” na pregledu, period čuvanja u podešavanjima | `frontend/src/pages`, `components/storage.tsx` |

Status ciklusa sada može biti i **Delimično**: veza je uspela, ali neki korak nije (npr. nedostaje sudo za `lvs`). Ono što jeste prikupljeno se čuva, a greške su navedene u istoriji.

## Nalozi na uređajima

Na svakom uređaju je napravljen namenski nalog `diskmonitor` (bez lozinke, samo ključ sa `from="192.168.88.246"`):

| Uređaj | Adresa | Platforma | Sudo |
|---|---|---|---|
| Proxmox i5 | 192.168.88.233 | Proxmox VE 9.2.21 | instaliran paket `sudo`, `/etc/sudoers.d/smartdisk` (0440, `visudo -c` OK) |
| Proxmox i3 | 192.168.88.10 | Proxmox VE 9.2.21 | isto |
| TrueNAS CORE | 192.168.88.93 | TrueNAS-13.0-U6.8 | kroz middleware (`sudo_commands`), home `/mnt/DataPool/diskmonitor` |

Za podešavanje je korišćen privremeni root ključ `claude-smartdisk-setup`. **Treba ga ukloniti** sa sva tri uređaja (videti kraj izveštaja).

## Testiranje

**Automatski testovi** (`backend/tests`, 13 testova, svi prolaze): parseri na stvarnim izlazima snimljenim sa Proxmox i TrueNAS CORE uređaja (`tests/fixtures`), uz sintetičke slučajeve koji na uređajima ne postoje: degradiran ZFS mirror sa resilver-om, CKSUM greškama, UNAVAIL i spare diskom; degradiran mdadm RAID5 sa oporavkom; disk u standby-ju; disk bez SMART-a; FAILED status; tekstualni izlaz smartctl 6.5; zlonamerna imena uređaja iz izlaza (`/dev/sda; rm -rf /`, `-d "sat -t long"`), koja se odbacuju. Jedan test vodi ceo Proxmox adapter kroz simulirani uređaj i proverava da li se sudo koristi tačno tamo gde treba.

**Sudo profili na uređajima:** dozvoljene komande prolaze kao `diskmonitor`. Odbijene su `smartctl … -t short`, `smartctl -t short /dev/sda` i `/bin/sh -c id`. Na Proxmoxu i CORE-u `zpool`, `lsblk`, `glabel` i `/proc/mdstat` rade bez sudo-a.

**End-to-end** kroz UI u Chrome-u i API (admin nalog):

| Scenario | Rezultat |
|---|---|
| Dodavanje uređaja, generisanje ključa, potvrda host ključa | otisci u aplikaciji se poklapaju sa `ssh-keygen -lf` na sva tri uređaja |
| Test konekcije | uspešno (96–858 ms), prepoznati PVE 9.2.21 i TrueNAS-13.0-U6.8 |
| Prikupljanje – Proxmox i5 | uspešno, 3,1 s: 2 diska (Seagate HDD 1 TB, Kingston NVMe 1 TB), 7 skladišta |
| Prikupljanje – Proxmox i3 | uspešno, 1,6 s: 1 disk (Lexar SSD 1 TB), 5 skladišta |
| Prikupljanje – TrueNAS CORE | uspešno, 2,6 s: 10 diskova (9 HDD + NVMe boot), 3 ZFS pool-a; `ses0` (kućište) pravilno preskočen |
| Planirano prikupljanje | izvršava se automatski; greške u logu servisa: 0 |
| Pregled | 3 uređaja, 13 diskova, 15 skladišta, najviša temperatura 49 °C |
| Skladište | DataPool raidz2 (7 diskova, članovi povezani sa ada0…ada8), **MediaPool bez redundanse** (stripe, 2 diska) prikazan sa upozorenjem, boot-pool single, scrub: datum i 0 grešaka |
| Detalj diska | 24 SMART atributa, self-test log (npr. „Aborted by host” na Seagate disku), maskiran serijski broj, izvorni JSON |
| Konzola pregledača | bez grešaka |

Zapažanja na stvarnim uređajima (nisu greške aplikacije):

- **MediaPool na TrueNAS CORE nema redundansu**: dva diska (8 TB IronWolf + 4 TB SkyHawk) u stripe-u. Kvar bilo kog od njih znači gubitak celog pool-a (7,4 TB podataka). Aplikacija to prikazuje kao upozorenje.
- Seagate disk na Proxmox i5 ima 2 UDMA CRC greške (kabl/konektor) i jedan prekinut kratki self-test. Ništa kritično.
- Pool-ovi na TrueNAS-u nemaju uključene sve ZFS funkcije (`zpool upgrade` poruka). To je informativna poruka sistema.

Posle testa nisu brisani podaci: uređaji su stvarni i ostaju u nadzoru.

## Poznata ograničenja i odluke

- **TrueNAS SCALE i Synology nisu provereni na stvarnom uređaju.** SCALE dodati kada se završi resilver. Synology adapter je napisan po dokumentovanom formatu (`smartctl` 6.x tekst, `/proc/mdstat`, `df`).
- Disk koji spava se ne budi (`smartctl -n standby`), pa za takav disk u tom ciklusu nema SMART očitavanja (stanje „Standby”). To je namerno.
- Na Proxmoxu se LVM volume grupa ne povezuje sa fizičkim diskom (kolona „Pool” je prazna). Za to bi bio potreban `pvs`, koji se može dodati u profil.
- Diskovi iza hardverskog RAID kontrolera (`-d megaraid,N`, `-d cciss,N`) nisu podržani: spec. §6.4 traži poseban profil, a na postojećim uređajima ih nema.
- Atributi SMART-a se čuvaju u svakom uzorku (JSONB, ~4 KB po očitavanju). Za 13 diskova na 15 minuta to je oko 5 MB dnevno, odnosno ~1,8 GB za 12 meseci. Ako bude potrebno, atributi se mogu čuvati samo kada se promene.
- Dnevni agregati za podatke starije od perioda čuvanja (spec. §9.2) i grafikoni od–do dolaze u Fazi 3. Do tada se starija merenja brišu tek posle 365 dana.
- Stanje diska u Fazi 2 je gruba procena (kritično / upozorenje / bez upozorenja / nema podataka). Ocena „Zdravlje diska”, trendovi i pragovi dolaze u Fazi 4.
- TrueNAS CORE ima `/usr/local/etc/sudoers` sa pravima 0644 (`visudo -c` upozorava). Tako ga podešava sam TrueNAS, a mi ga ne menjamo.

## Otvoreno

1. **Ukloniti privremeni root ključ** `claude-smartdisk-setup`:
   - Proxmox (oba): obrisati red sa `claude-smartdisk-setup` iz `/root/.ssh/authorized_keys`;
   - TrueNAS CORE: *Accounts → Users → root → SSH Public Key*, obrisati ključ.
2. TrueNAS SCALE: posle resilver-a dodati ključ za podešavanje (ili napraviti nalog po [uputstvu](dodavanje-uredjaja.md#truenas-scale)), proveriti adapter i snimiti fixtures.
3. Za Fazu 4: pragovi degradacije za konkretne diskove (spec. §23, tačka 9) i da li se koristi postojeći MQTT broker u Home Assistant-u (tačka 6).
