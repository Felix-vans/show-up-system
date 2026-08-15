# Installatie op je Ubuntu-server

Van je Windows-pc naar je server, via een privé GitHub-repo. Reken op
20 à 30 minuten de eerste keer.

Overal waar `felix` staat: vervang door je eigen Linux-gebruikersnaam op de
server (zie `whoami`).

---

## Deel 1 — Code op GitHub zetten (op je Windows-pc)

### 1.1 Maak een lege privé-repo aan

Ga naar [github.com/new](https://github.com/new):

- Repository name: `show-up-system`
- Zet op **Private** (belangrijk)
- Vink **niets** aan bij "Initialize this repository" (geen README, geen .gitignore)
- Klik **Create repository**

### 1.2 Push je code

Open een terminal in de projectmap
(`C:\claude\Second Brain\03 Projects\Oryn\Tools\show-up-system`) en voer uit:

```bash
git init
git add .
git commit -m "Show-Up System klaar voor server"
git branch -M main
git remote add origin https://github.com/JOUW-GEBRUIKERSNAAM/show-up-system.git
git push -u origin main
```

> **Controleer dit even.** Open je repo op GitHub en kijk of `.env` er **niet**
> tussen staat, en of er geen map `data` is. Staan die er wel? Stop, en laat
> het weten — dan staat je mailwachtwoord online.

---

## Deel 2 — Installeren op de server

Log in op je server (via SSH of rechtstreeks).

### 2.1 Benodigdheden

```bash
sudo apt update
sudo apt install -y python3-venv git
```

### 2.2 Code ophalen

```bash
cd ~
git clone https://github.com/JOUW-GEBRUIKERSNAAM/show-up-system.git
cd show-up-system
```

GitHub vraagt om je gebruikersnaam en een wachtwoord. Dat "wachtwoord" is
**niet** je gewone GitHub-wachtwoord maar een Personal Access Token:
GitHub → Settings → Developer settings → Personal access tokens →
Tokens (classic) → Generate new token → vink `repo` aan → kopieer de token.

### 2.3 Python-omgeving

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### 2.4 Instellingen invullen

```bash
cp .env.example .env
nano .env
```

Vul in:

| Instelling | Waarde |
|---|---|
| `SMTP_ADDRESS` | `vanslegtenhorst.felix@gmail.com` |
| `SMTP_PASSWORD` | je Gmail app-wachtwoord (staat in je lokale `.env`) |
| `FLASK_SECRET` | een willekeurige string, zie hieronder |

Genereer die geheime sleutel met:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Opslaan in nano: `Ctrl+O`, `Enter`, dan `Ctrl+X`.

Beveilig het bestand zodat alleen jij het kan lezen:

```bash
chmod 600 .env
```

### 2.5 Eerste test met de hand

Je Ubuntu Server heeft geen scherm/browser — dat hoeft ook niet. Start de app:

```bash
.venv/bin/gunicorn --bind 0.0.0.0:5000 wsgi:app
```

Open een **tweede terminalvenster naar dezelfde server** (nieuwe SSH-sessie)
en test vanaf daar met curl:

```bash
curl -s http://localhost:5000/login | grep -o 'value="[a-z]*"'
```

Zie je `value="felix"`, `value="anando"` en `value="jules"`? Dan werkt het.

Ga terug naar het eerste venster en stop met `Ctrl+C`.

De écht bruikbare test is vanaf een browser op je eigen pc, via het
Tailscale-adres van de server &mdash; dat komt in Deel 4.

---

## Deel 3 — Automatisch laten draaien (met PM2)

Je gebruikte PM2 al voor je vorige app op deze server — dat gebruiken we
hier ook, in plaats van systemd.

### 3.1 PM2 installeren (indien nog niet aanwezig)

```bash
pm2 --version
```

Geeft dat een foutmelding, dan is Node.js/PM2 nog niet aanwezig:

```bash
curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
sudo apt install -y nodejs
sudo npm install -g pm2
```

### 3.2 Start-script uitvoerbaar maken

```bash
chmod +x start_server.sh
```

Dit scriptje leest je `.env` in en start gunicorn met de juiste poort
(`BIND`) — daardoor moet je de poort maar op één plek aanpassen, niet in
een apart PM2-configbestand.

### 3.3 App starten onder PM2

```bash
pm2 start ./start_server.sh --name oryn-showup
```

### 3.4 Zorgen dat PM2 herstart na een reboot van je server

```bash
pm2 save
pm2 startup
```

Dat laatste commando print een regel die begint met `sudo env PATH=...`
— kopieer en voer die exact uit. Dat is eenmalig; daarna overleeft PM2
zelf een herstart van je server, en PM2 op zijn beurt herstart altijd
`oryn-showup`.

### 3.5 Controleren

```bash
pm2 status
```

Je wil `oryn-showup` zien staan met status `online`.

```bash
pm2 logs oryn-showup --lines 50
```

Om te controleren of de reminders draaien:

```bash
grep "Scheduler started" ~/show-up-system/data/app.log
```

Je hoort **precies één** zo'n regel te zien. Staan er meerdere, laat het weten —
dan zouden prospects dubbele mails kunnen krijgen.

> **Draai je toch liever met systemd?** Er staat ook een kant-en-klaar
> `oryn-showup.service` bestand in de repo. Gebruik dan die in plaats van
> PM2 — niet allebei tegelijk, dat botst op dezelfde poort.

---

## Deel 4 — Toegang voor je collega's via Tailscale

### 4.1 Zoek het Tailscale-adres van je server

```bash
tailscale ip -4
```

Dat geeft iets als `100.101.102.103`.

### 4.2 Deel dit met Anando en Jules

> Open in je browser: `http://100.101.102.103:5000`
> (vervang door het echte adres)
> Klik op je eigen naam om in te loggen.

Zij moeten Tailscale op hun toestel hebben en in jouw tailnet zitten. Handiger
alternatief: gebruik de MagicDNS-naam van je server, dan hoeft niemand een
IP-adres te onthouden:

```bash
tailscale status | head -1
```

Dan wordt het bijvoorbeeld `http://mijn-server:5000`.

---

## Later: updates uitrollen

Wijzig je iets op je Windows-pc? Dan:

```bash
# op Windows
git add .
git commit -m "beschrijf je wijziging"
git push
```

```bash
# op de server
cd ~/show-up-system
git pull
.venv/bin/pip install -r requirements.txt
pm2 restart oryn-showup
```

Je database en je `.env` blijven onaangeroerd bij een update.

---

## Als er iets misloopt

**App start niet / staat op "errored" in PM2**

```bash
pm2 logs oryn-showup --lines 50
```

De laatste regels vertellen meestal precies wat er scheelt (verkeerd pad,
ontbrekend pakket, fout in `.env`, of `start_server.sh` niet uitvoerbaar —
zie stap 3.2).

**Collega's raken niet op de pagina**

- Draait de app? `pm2 status`
- Zit hun toestel in je tailnet? `tailscale status` op de server toont wie verbonden is
- Firewall: `sudo ufw allow 6769/tcp` (jouw poort — enkel nodig als je ufw gebruikt)

**Mails vertrekken niet**

```bash
grep -i "error\|failed" ~/show-up-system/data/app.log | tail -20
```

Meestal is dit een verkeerd app-wachtwoord in `.env`. Let op: het app-wachtwoord
is 16 tekens, en Google toont het met spaties. Beide werken.

**Database terugzetten**

Er wordt elke nacht om 03:15 een kopie gemaakt:

```bash
ls ~/show-up-system/data/backups/
pm2 stop oryn-showup
cp ~/show-up-system/data/backups/meetings-JJJJ-MM-DD.db ~/show-up-system/data/meetings.db
pm2 start oryn-showup
```

---

## Wat er nu aan/uit staat

| Functie | Status |
|---|---|
| 27u-herinnering naar de prospect | **AAN** — volautomatisch |
| Bevestigings- en follow-upmails | **AAN** — bij toevoegen van een lead |
| Nachtelijke back-up (7 dagen) | **AAN** |
| Ochtend-overzicht naar de verkoper | **UIT** — `DIGEST_ENABLED=1` zet het aan |
| 1u-ping naar de verkoper | **UIT** — `OWNER_PINGS_ENABLED=1` zet het aan |

Die laatste twee staan bewust uit zolang jullie één mailbox delen: anders
komen de meldingen van alle drie de verkopers in dezelfde inbox terecht.
De WhatsApp-opvolging doe je in de tussentijd via het dashboard — daar zie je
welke filmpjes nog moeten en welke meetings vandaag zijn, en kan je ze
afvinken zoals nu.

Zodra iedereen een zakelijk adres heeft: vul `notify_email` per persoon in
`users.json` in, zet beide vlaggen op `1`, herstart de service. Klaar.
