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

```bash
.venv/bin/gunicorn --bind 0.0.0.0:5000 wsgi:app
```

Open in een browser op je server: `http://localhost:5000`
Zie je het inlogscherm met Felix, Anando en Jules? Dan werkt het.
Stop met `Ctrl+C`.

---

## Deel 3 — Automatisch laten draaien

### 3.1 Service installeren

Pas eerst de gebruikersnaam en paden aan als die bij jou anders zijn:

```bash
nano oryn-showup.service
```

Installeer daarna:

```bash
sudo cp oryn-showup.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable oryn-showup
sudo systemctl start oryn-showup
```

### 3.2 Controleren

```bash
sudo systemctl status oryn-showup
```

Je wil `active (running)` zien.

Om te controleren of de reminders draaien:

```bash
grep "Scheduler started" ~/show-up-system/data/app.log
```

Je hoort **precies één** zo'n regel te zien. Staan er meerdere, laat het weten —
dan zouden prospects dubbele mails kunnen krijgen.

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
sudo systemctl restart oryn-showup
```

Je database en je `.env` blijven onaangeroerd bij een update.

---

## Als er iets misloopt

**Service start niet**

```bash
sudo journalctl -u oryn-showup -n 50 --no-pager
```

De laatste regels vertellen meestal precies wat er scheelt (verkeerd pad,
ontbrekend pakket, fout in `.env`).

**Collega's raken niet op de pagina**

- Draait de service? `sudo systemctl status oryn-showup`
- Zit hun toestel in je tailnet? `tailscale status` op de server toont wie verbonden is
- Firewall: `sudo ufw allow 5000/tcp` (enkel nodig als je ufw gebruikt)

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
sudo systemctl stop oryn-showup
cp ~/show-up-system/data/backups/meetings-JJJJ-MM-DD.db ~/show-up-system/data/meetings.db
sudo systemctl start oryn-showup
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
