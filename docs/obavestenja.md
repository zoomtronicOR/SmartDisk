# Obaveštenja: e-pošta, MQTT / Home Assistant, Web Push

Alarmi se šalju kroz tri nezavisna kanala. Svaki kanal se uključuje posebno, a svaki pokušaj slanja (uspešan ili ne) vidi se u *Podešavanja → Evidencija obaveštenja* i na stranici alarma.

Obaveštenje se šalje kada se alarm otvori, kada se pogorša (eskalacija), kao podsetnik za nepotvrđen alarm koji traje (podrazumevano posle 24 h) i, ako je to uključeno, kada se reši. Pre svega podesite *Podešavanja → Opšte za obaveštenja → Adresa aplikacije* (npr. `https://192.168.88.246`), da linkovi u porukama vode na alarm.

## E-pošta (SMTP)

*Podešavanja → E-pošta (SMTP)*:

| Polje | Primer |
|---|---|
| SMTP server / port / bezbednost | `smtp.gmail.com`, 587, STARTTLS (ili 465 + SSL/TLS) |
| Korisničko ime / lozinka | nalog za slanje; za Gmail se koristi *App password*, a ne obična lozinka |
| Pošiljalac | adresa sa koje poruke stižu |
| Primaoci | jedna ili više adresa, razdvojene zarezom |
| Najniži nivo | podrazumevano „Visoko i više”, da e-pošta ne bude zatrpana |

Dugme **Pošalji probnu poruku** šalje poruku sa trenutno unetim vrednostima, i pre čuvanja. Greške su opisne („server je odbio korisničko ime ili lozinku”, „server nije dostupan”, „TLS greška – proverite port”). Lozinka se čuva šifrovano i nikad se ne prikazuje.

## MQTT i Home Assistant

Preduslov je Mosquitto broker u Home Assistant-u (add-on *Mosquitto broker*) i MQTT integracija u HA.

1. U Home Assistant-u napraviti posebnog korisnika za SmartDisk (*Settings → People → Users*, ili `logins` u konfiguraciji Mosquitto add-on-a).
2. U SmartDisk-u, *Podešavanja → MQTT i Home Assistant*: adresa HA (npr. `192.168.88.x`), port 1883 (ili 8883 sa TLS), korisnik i lozinka. Zatim **Testiraj vezu**, pa **Sačuvaj** sa uključenim „Objavljuj stanje i alarme”.
3. Sa uključenim *Home Assistant MQTT Discovery*, entiteti se u HA pojavljuju sami: jedan uređaj „SmartDisk” sa sažetkom i po jedan uređaj „SmartDisk – <naziv>” za svaki nadzirani sistem (temperatura, SMART, zdravlje, sati rada, NVMe istrošenost diskova; status i greške pool-ova; status uređaja). Svaka vrsta entiteta se može isključiti.

Teme (prefiks se podešava, podrazumevano `diskmonitor`):

| Tema | Sadržaj | Retain |
|---|---|---|
| `diskmonitor/availability` | `online` / `offline` (LWT) | da |
| `diskmonitor/summary` | broj uređaja, diskova, diskova sa upozorenjem, alarma po nivou, poslednje/sledeće prikupljanje | da |
| `diskmonitor/devices/<id>/state` | status uređaja, poslednji uspeh, greška, sledeći ciklus | da |
| `diskmonitor/disks/<id>/state` | temperatura, SMART, zdravlje i razlozi, sati rada, NVMe istrošenost, kvalitet podatka, vreme očitavanja | da |
| `diskmonitor/pools/<id>/state` | status, ispravnost, READ/WRITE/CKSUM, zauzeće, scrub | da |
| `diskmonitor/events` | svaki alarm: otvoren, pogoršan, podsetnik, rešen (QoS 1) | ne |

Nedostupna vrednost je `null`, nikad 0. Serijski brojevi i SSH podaci se ne objavljuju. SmartDisk ne prima komande preko MQTT-a.

Primer automatizacije u HA (obaveštenje na telefon za kritične alarme):

```yaml
trigger:
  - platform: mqtt
    topic: diskmonitor/events
condition:
  - "{{ trigger.payload_json.severity == 'critical' and trigger.payload_json.kind in ['opened', 'escalated'] }}"
action:
  - service: notify.mobile_app_telefon
    data:
      title: "SmartDisk"
      message: "{{ trigger.payload_json.title }}"
```

## Web Push (obaveštenja u pregledaču)

Preduslov je HTTPS sa pouzdanim sertifikatom, tj. instaliran lokalni CA ([instalacija.md](instalacija.md#https-sertifikat)).

1. *Moj nalog → Obaveštenja u ovom pregledaču*: izabrati najniži nivo i (po želji) uređaje, pa **Uključi obaveštenja**.
2. Pregledač traži dozvolu, i treba je odobriti.
3. **Pošalji probu** proverava da obaveštenja stižu.

Obaveštenja stižu i kada aplikacija nije otvorena, dok god je pregledač pokrenut. Klik na obaveštenje otvara alarm. **Utišaj 8 h** privremeno zaustavlja obaveštenja za taj pregledač. Svaki pregledač ili uređaj ima svoju pretplatu. Ako je dozvola u pregledaču blokirana, menja se u podešavanjima sajta (ikona katanca u adresnoj traci).

## Telegram, Pushover, webhook

*Podešavanja → Dodatni kanali obaveštenja*. Svaki kanal se posebno uključuje, ima najniži nivo i dugme **Pošalji probu**.

- **Telegram**: napraviti bota preko `@BotFather` (dobija se token) i poslati mu bilo koju poruku. Chat ID se dobija npr. od `@userinfobot` (za grupu: dodati bota u grupu).
- **Pushover**: API token aplikacije (*Create an Application*) i korisnički ključ sa pushover.net. Kritični alarmi idu sa visokim prioritetom.
- **Webhook**: POST sa JSON telom događaja na zadati URL. Uz tajnu se šalje zaglavlje `X-SmartDisk-Signature: sha256=<HMAC-SHA256 tela>`. Za Home Assistant: automatizacija sa okidačem *Webhook* (`http://<HA>:8123/api/webhook/<id>`), npr. za *persistent notification*.

## Režim održavanja

*Podešavanja → Režim održavanja*: za zadati broj sati šalju se samo kritična obaveštenja (npr. dok se menja disk ili traje scrub). Alarmi se i dalje beleže, a MQTT telemetrija radi. Preskočena obaveštenja se vide u evidenciji.

## Zakazani izveštaji

*Podešavanja → Zakazani izveštaji*: dnevni, nedeljni ili mesečni izveštaji (stanje uređaja, diskovi sa upozorenjima, SMART promene…) stižu kao PDF, XLSX ili CSV prilog e-pošte. Potreban je podešen SMTP. **Pošalji sada** služi za proveru.

## Alarmi: nivoi i ponašanje

| Nivo | Značenje | Primer |
|---|---|---|
| Informativno | promena, još nije problem | nove CRC greške, temperatura blizu praga, stabilni realocirani sektori |
| Upozorenje | prvi znak degradacije | pending sektori, temperatura iznad praga, NVMe istrošenost ≥ 80 % |
| Visoko | ubrzano pogoršanje | ≥ 5 novih realociranih sektora u 24 h, rast NVMe media grešaka, ponovljeno pregrevanje, nestao disk |
| Kritično | neposredan rizik | SMART FAILED, NVMe critical warning, rezerva ispod praga, rast neispravljivih sektora, disk sa problemom u degradiranom pool-u |

- **Potvrda** znači „video sam”. Alarm ostaje aktivan dok uslov traje, a ako se problem pogorša, ponovo postaje otvoren.
- Alarm se **sam rešava** kada uslov prestane. Za temperaturu važi histereza (podrazumevano 2 °C).
- **Ručno zatvoren** alarm se ponovo otvara ako uslov i dalje postoji. U roku cooldown-a (60 min) to je isti alarm, bez novog obaveštenja.
- Pragovi i ponašanje se menjaju u *Podešavanja → Pragovi alarma* (dugme **Vrati preporučene** vraća podrazumevane vrednosti).
- Aplikacija nikad sama ne menja skladište (nema `zpool replace/offline`, SMART testova ni sličnog). Zamena diska je uvek ručna.
