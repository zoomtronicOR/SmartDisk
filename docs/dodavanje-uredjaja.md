# Dodavanje uređaja i SSH pristup

Aplikacija se na uređaj prijavljuje **namenskim nalogom samo za nadzor** (`diskmonitor`), isključivo SSH ključem. Nalog sme da izvrši samo tačno određene read-only komande (spec. §5.3). Profili u ovom dokumentu su provereni na Proxmox VE 9.2, TrueNAS CORE 13.0 i TrueNAS SCALE 27.0. Synology DSM još nije proveren na stvarnom uređaju (videti [izveštaj o Fazi 2](faza-2-izvestaj.md)).

Tačan spisak komandi i gotov sudoers fajl za svaku platformu prikazuje i sama aplikacija: stranica uređaja → **Profil privilegija za nalog na uređaju** (dugme *Kopiraj*). Spisak se pravi iz istih šablona po kojima aplikacija izvršava komande.

## Redosled koraka

1. Na uređaju napraviti nalog `diskmonitor` i sudo profil (odeljci ispod, po platformi).
2. U aplikaciji: *Uređaji → Dodaj uređaj*: naziv, platforma, IP adresa, port, korisnik `diskmonitor`. Novi uređaj je **isključen**.
3. **Korak 1 - SSH ključ:** *Generiši ključ* napravi ed25519 par. Javni ključ (*Kopiraj*) dodati nalogu na uređaju (odeljci ispod). Preporuka je da ključ važi samo za adresu SmartDisk kontejnera:
   ```text
   from="192.168.88.246",no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty ssh-ed25519 AAAA… smartdisk-<id>
   ```
4. **Korak 2 - host ključ:** *Preuzmi otisak host ključa*, pa ga uporediti sa otiskom na samom uređaju (konzola ili već pouzdana SSH sesija). Tek ako se poklapaju: *Otisak se poklapa - potvrđujem*.

   | Platforma | Komanda na uređaju |
   |---|---|
   | Proxmox VE, TrueNAS SCALE, Synology | `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` |
   | TrueNAS CORE | `ssh-keygen -lf /usr/local/etc/ssh/ssh_host_ed25519_key.pub` |

5. **Korak 3:** *Test konekcije* (prepoznaje sistem i alate), zatim *Uključi nadzor* i po želji *Prikupi sada*. U istoriji prikupljanja se vide broj diskova, broj skladišta i eventualne greške pojedinih koraka.

## Proxmox VE

Kao root na hostu:

```bash
apt install sudo                                   # na Proxmoxu nije instaliran podrazumevano
useradd -m -s /bin/bash -c "SmartDisk nadzor (read-only)" diskmonitor
passwd -l diskmonitor                              # bez lozinke, prijava samo ključem
install -d -m 700 -o diskmonitor -g diskmonitor /home/diskmonitor/.ssh
# javni ključ iz aplikacije (sa from=… opcijama) upisati u /home/diskmonitor/.ssh/authorized_keys
chown diskmonitor:diskmonitor /home/diskmonitor/.ssh/authorized_keys && chmod 600 /home/diskmonitor/.ssh/authorized_keys
```

Sudo profil iz aplikacije sačuvati kao `/etc/sudoers.d/smartdisk`, pa ga proveriti:

```bash
visudo -cf /tmp/smartdisk.sudoers && install -m 0440 -o root -g root /tmp/smartdisk.sudoers /etc/sudoers.d/smartdisk
visudo -c
```

Profil dozvoljava, bez lozinke i samo kao root:

- `smartctl -j --scan-open`
- `smartctl -j -a -n standby -d <sat|scsi|ata|auto> /dev/sd[a-z]` (i `sd[a-z][a-z]`)
- `smartctl -j -a -n standby -d nvme /dev/nvme[0-9]` (i `nvme[0-9][0-9]`)
- `lvs …` i `vgs …` sa fiksnim JSON parametrima
- `pvesm status`

`lsblk`, `zpool list/status` i `/proc/mdstat` rade bez sudo-a.

Provereno je da profil **odbija** sve ostalo, na primer:

```text
sudo -n smartctl -j -a -n standby -d sat /dev/sda -t short   → sudo: a password is required
sudo -n smartctl -t short /dev/sda                           → sudo: a password is required
sudo -n /bin/sh -c id                                        → sudo: a password is required
```

## TrueNAS CORE

TrueNAS sam generiše `/usr/local/etc/sudoers` iz svoje baze i ručne izmene prepisuje. Zato se nalog i sudo komande podešavaju **kroz middleware** (ili web interfejs, *Accounts → Users*):

- korisničko ime `diskmonitor`, *Disable Password*, shell `/bin/sh`;
- home direktorijum **na pool-u**, npr. `/mnt/DataPool/diskmonitor`. TrueNAS ne dozvoljava da SSH ključ stoji uz `/nonexistent`, a ne prihvata ni sam koren pool-a;
- **Permit Sudo** uključen, **Allow all sudo commands** isključen, a u spisak sudo komandi (bez lozinke) uneti komande iz aplikacije, svaku posebno. **Spisak nikad ne ostavljati prazan:** prazan spisak u TrueNAS-u znači „sve komande”;
- javni ključ iz aplikacije u polje *SSH Public Key*.

Isto preko konzole (`midclt`), kako je urađeno na 192.168.88.93:

```bash
midclt call user.get_next_uid                       # npr. 1002
midclt call user.create '{"username":"diskmonitor","uid":1002,"full_name":"SmartDisk nadzor (read-only)",
  "group_create":true,"password_disabled":true,"home":"/mnt/DataPool/diskmonitor","shell":"/bin/sh",
  "sudo":true,"sudo_nopasswd":true,"sudo_commands":["/usr/local/sbin/smartctl -j --scan-open", "…"]}'
midclt call user.update <id> '{"sshpubkey":"from=\"192.168.88.246\",no-pty,… ssh-ed25519 AAAA… smartdisk-3"}'
```

Napomene iz prakse (13.0-U6):

- `user.create` bez `uid` pada sa `KeyError: 'uid'`, a ostavlja već napravljenu grupu. `uid` uzeti iz `user.get_next_uid`.
- Direktorijum za home ne praviti unapred. Middleware ga pravi sam, a ako već postoji, prijavljuje grešku.

Profil dozvoljava `smartctl` za `/dev/ada*`, `/dev/da*` i `/dev/nvme*` sa tipovima `atacam`, `ata`, `sat`, `scsi`, `auto` i `nvme`. `zpool`, `glabel` i `sysctl kern.disks` rade bez sudo-a.

## TrueNAS SCALE

Provereno na TrueNAS SCALE 27.0.0-RC.1 (192.168.88.47). Kao i na CORE-u, TrueNAS sam generiše sudoers i nalog, pa se sve podešava **kroz middleware** ili web interfejs (*Credentials → Users*), ne ručnom izmenom fajlova. Na novijim verzijama root nalog je zaključan, pa se komande pokreću kao administrator (`admin` ili `truenas_admin`) uz `sudo`.

Razlike u odnosu na CORE:

- sudo komande bez lozinke idu u polje `sudo_commands_nopasswd` (polja `sudo` i `sudo_nopasswd` ne postoje);
- nalog bez lozinke mora imati isključen SMB (`"smb": false`), inače ga TrueNAS odbija;
- `home` je pool (npr. `/mnt/datapool`), a uz `"home_create": true` TrueNAS sam pravi `/mnt/datapool/diskmonitor`. Bez home direktorijuma na pool-u (podrazumevano `/var/empty`) SSH ključ ne može da se sačuva;
- shell `/usr/bin/bash`; `uid` nije potreban.

Naziv pool-a: `zpool list -Ho name` (ne `boot-pool`). Zatim, uz pravi naziv pool-a i javni ključ iz aplikacije:

```bash
POOL=datapool
sudo midclt call user.create '{"username":"diskmonitor","full_name":"SmartDisk nadzor (read-only)",
  "group_create":true,"password_disabled":true,"smb":false,"ssh_password_enabled":false,
  "home":"/mnt/'"$POOL"'","home_create":true,"shell":"/usr/bin/bash",
  "sudo_commands_nopasswd":["/usr/sbin/smartctl -j --scan-open", "…"],
  "sshpubkey":"from=\"192.168.88.246\",no-pty,no-port-forwarding,no-agent-forwarding,no-X11-forwarding ssh-ed25519 AAAA… smartdisk-4"}'
```

Spisak `sudo_commands_nopasswd` je tačno spisak koji aplikacija prikazuje za SCALE (11 `smartctl` komandi za `/dev/sd*` i `/dev/nvme*`). `zpool` i `lsblk` rade bez sudo-a. Komanda vraća ceo zapis novog naloga; proveriti `home`, `smb: false` i spisak komandi. Provera da nalog postoji: `sudo midclt call user.query '[["username","=","diskmonitor"]]'`.

Napomene iz prakse (27.0.0-RC.1):

- javni ključ se ne lepi u terminal (to je samo tekst, ne komanda), nego u polje naloga ili u `sshpubkey`;
- `/etc/version` na SCALE 27 nema završni prelom reda. Aplikacija od verzije 0.6.7 to podnosi; starije verzije su prijavljivale „smartctl nije pronađen”.

## Synology DSM

Netestirano (nema uređaja). Adapter postoji:

- DSM 7 ima `smartctl` 6.x bez JSON izlaza, pa aplikacija tada parsira tekstualni izlaz;
- diskovi su `/dev/sata*` (DSM 7.2+) ili `/dev/sd*`;
- RAID/SHR stanje dolazi iz `/proc/mdstat` (`md0` je sistem, `md1` swap), a zauzeće iz `df` za `/volumeN`.

Nalog: *Control Panel → User & Group*, SSH uključiti u *Terminal & SNMP*. Sudo profil iz aplikacije upisati u `/etc/sudoers.d/smartdisk`. **DSM nadogradnja može da ukloni taj fajl**, pa ga posle svake nadogradnje proveriti. Putanju `smartctl`-a proveriti sa `command -v smartctl`.

## Rešavanje problema

| Poruka | Uzrok i rešenje |
|---|---|
| Konekcija je odbijena | SSH servis ne radi ili je na drugom portu |
| Isteklo je vreme za povezivanje | uređaj nije dostupan sa kontejnera (mreža, firewall) |
| DNS ime ne može da se razreši | koristiti IP adresu ili ispraviti DNS |
| SSH prijava je odbijena | javni ključ nije u `authorized_keys`, `from=` ne odgovara adresi kontejnera, pogrešan korisnik ili loša prava na `~/.ssh` (700) i `authorized_keys` (600) |
| Host ključ se ne poklapa | ključ servera je promenjen. Proveriti uređaj, pa ponovo preuzeti i potvrditi ključ |
| „Komanda zahteva sudo, a sudo nije podešen…” | sudo nije instaliran, profil nije upisan ili komanda nije u profilu. Uporediti sa profilom iz aplikacije. Ciklus je tada **Delimično** uspešan |
| Disk „SMART nedostupan” | kontroler ili USB adapter ne prosleđuje SMART. Disk ostaje u inventaru |
| Disk „Standby” | disk spava. Aplikacija ga namerno ne budi (`-n standby`) |
| Alat „…” nije pronađen | alat nije instaliran ili nije dostupan korisniku. Funkcija je nedostupna |
| Prepoznat je drugi sistem | proveriti izabranu platformu uređaja |
