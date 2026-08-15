# Oryn Show-Up System

> **Op de server zetten?** Volg [DEPLOY.md](DEPLOY.md) — stap voor stap,
> van GitHub tot Tailscale-toegang voor je collega's.

Tool om leads uit de AI Consultatie cold-call strategie op te volgen: van
eerste gesprek tot geboekte meeting, met automatische bevestigings- en
follow-upmails en een dagelijks ochtend-overzicht van wat je zelf nog moet
versturen (WhatsApp-tekst + intro-filmpje).

## Wat het doet

Elke cold call wordt een **lead** in het dashboard, met twee mogelijke paden:

1. **Meeting nu boeken** &mdash; je vult naam, bedrijf, email, tijdstip in.
   Afhankelijk van of je het **persoonlijke nummer** of enkel het
   **onthaalnummer** hebt, gaat automatisch de juiste bevestigingsmail (mail 1
   of 2 uit het rapport) + calendar invite uit.
2. **Nog niet overtuigd** &mdash; geen meeting, maar wel interesse. Er gaat
   automatisch de juiste follow-upmail (mail 3 of 4) uit, met het verzoek om
   terug te mailen zodra ze een moment willen prikken. Zodra ze reageren klik
   je **"boek nu"** in de tabel om er alsnog een meeting van te maken.

Daarnaast, volledig automatisch:

- **27 uur voor de meeting:** reminder-email naar de prospect.
- **Elke ochtend (~07:30):** één verzamel-mail naar jezelf met exact wat je
  die dag manueel moet versturen &mdash; WhatsApp-herinneringen (met tijdstip
  en kant-en-klare tekst), intro-filmpjes die nog moeten uit voor leads waar
  net een persoonlijk nummer is binnengekomen, en een seintje bij
  "niet overtuigd"-leads die al een tijdje geen reactie gaven.
- **Laatste-moment fallback:** als een meeting binnen het uur is en er nog
  geen ping was (bv. omdat hij pas na de ochtend-digest geboekt werd), krijg
  je alsnog meteen een losse melding.

Het versturen van het WhatsApp-tekstbericht en het persoonlijke intro-filmpje
blijft **manueel** &mdash; dat is bewust: het filmpje moet sowieso door jezelf
opgenomen worden, en de digest-mail zorgt dat je nooit hoeft te onthouden wat
er nog moet gebeuren.

## Setup (eenmalig)

### 1. Installeer Python 3.11 of hoger

Download van https://www.python.org/downloads/ &mdash; vink tijdens installatie **"Add Python to PATH"** aan.

Check:
```
python --version
```

### 2. Installeer dependencies

Open een terminal in deze folder (`Tools/show-up-system/`):
```
pip install -r requirements.txt
```

### 3. Gmail configureren

1. Zet 2FA aan op je Gmail account: https://myaccount.google.com/security
2. Maak een App Password aan: https://myaccount.google.com/apppasswords
3. Kopieer `.env.example` naar `.env` en vul `SMTP_ADDRESS` +
   `SMTP_PASSWORD` in. Dat is de mailbox waaruit alle verkopers versturen.
4. De gebruikers zelf (Felix, Anando, Jules) staan in `users.json` &mdash;
   enkel namen en kleuren, geen wachtwoorden. Dat bestand is veilig om te
   delen; `.env` niet.

Krijgt later iedereen een eigen zakelijk adres? Voeg dan `smtp_address` en
`smtp_password` toe bij die persoon in `users.json` &mdash; dat wint dan van
de gedeelde mailbox. Geen code-aanpassing nodig.

### 4. Start de app

```
python run.py
```

Open in browser: http://localhost:5000

## Gebruik

**Tijdens/na een cold call:**
1. Open http://localhost:5000
2. Vul de lead in: naam, bedrijf, email, niche, telefoon (indien gekregen),
   welk soort nummer (persoonlijk/onthaal)
3. Kies: **meeting nu boeken** (datum + tijd) of **nog niet overtuigd**
4. Klik toevoegen &mdash; de juiste mail (1 van de 4) gaat meteen uit

**Als een "niet overtuigd"-lead reageert:** klik **"boek nu"** op die rij,
vul het moment in &mdash; de bevestigingsmail + calendar invite gaan dan
alsnog uit.

**Zodra je een persoonlijk nummer krijgt** (bv. na een onthaal-only lead die
terugbelt): klik **"nummer toevoegen"** op die rij. Het intro-filmpje
verschijnt dan in je volgende ochtend-digest.

**Na de meeting:** markeer **fit** of **geen fit** op de rij &mdash; dit
bouwt de basis voor latere conversieratio-analyse op.

**Meeting/lead annuleren:** klik `annuleer` &mdash; er worden geen reminders
meer verstuurd. Per ongeluk geklikt? Klik `herstel` op diezelfde rij.

**Het overzicht nu al testen:** onderaan de pagina staat *"Stuur mij het
overzicht nu (test)"*. Die stuurt de ochtend-digest meteen naar jezelf zonder
iets als verstuurd te markeren &mdash; testen kan dus nooit een echte
herinnering onderdrukken.

### Sneller werken

- **Snelknoppen** onder datum en tijd (`morgen`, `+2d`, `14:00`, ...) &mdash;
  scheelt klikken in de datumpicker terwijl je aan de telefoon zit.
- **Niche wordt onthouden** tussen leads door, want je belt meestal één
  sector per sessie.
- **Filtertabs** bovenaan de tabel: Alles / Meetings / Niet overtuigd /
  Actie nodig / Afgesloten.
- **Tellers** bovenaan tonen in één blik: meetings vandaag, meetings gepland,
  niet-overtuigde leads, en hoeveel rijen actie van jou vragen.
- Meetings van **vandaag** worden geel gemarkeerd en staan bovenaan.

## Belangrijk

- **App moet open blijven** voor reminders + de ochtend-digest te werken.
  Als je pc slaapt of je sluit de terminal → geen mails.
- Overweeg om in Windows Power Settings de slaap-modus uit te zetten tijdens
  werkuren.
- Alle tijden zijn in **Europe/Brussels** (zomertijd/wintertijd automatisch).
- Draait vandaag **lokaal** op je eigen pc. De code is bewust zo opgezet
  (env-config, per-gebruiker credentials in JSON, geen hardcoded paden) dat
  een latere verhuizing naar een eigen server een deploy-stap is, geen
  herbouw.
- **Koppeling met het CRM van je baas** is bewust nog niet gebouwd &mdash;
  dit systeem werkt nu volledig op zichzelf. De data zit in een simpele
  SQLite-tabel (`leads` in `data/meetings.db`) die later relatief eenvoudig
  te exporteren of te syncen is zodra jullie kiezen hoe die koppeling eruit
  moet zien.

## Edge cases die al ingebouwd zijn

- Meeting < 27u van nu → 27u-reminder wordt overgeslagen (alleen bevestiging)
- Meeting < 1u van nu → automatische ping wordt overgeslagen (alleen bevestiging)
- Meeting in het verleden → geblokkeerd
- Ongeldig emailadres → geblokkeerd
- Duplicaat (zelfde email met actieve meeting) → geblokkeerd
- Scheduler crash of restart → pending reminders + digest worden bij
  volgende poll/dag opnieuw geëvalueerd
- Mail versturen faalt → lead staat toch opgeslagen, foutmelding verschijnt in UI
- Lege ochtend (niets te doen) → geen digest-mail, geen ruis in je inbox

## Files

```
show-up-system/
├── run.py              # Start alles
├── app.py              # Flask routes: lead toevoegen, boeken, contact/video/outcome updates
├── scheduler.py        # 27u-reminder, laatste-moment fallback, ochtend-digest
├── email_sender.py     # SMTP + template rendering + ICS calendar invite
├── db.py                # SQLite helpers (tabel: leads)
├── utils.py             # Tijd + Nederlandse datumformattering
├── templates/
│   ├── index.html
│   ├── login.html
│   ├── email_confirm_personal.html    # mail 1: meeting vast + persoonlijk nummer
│   ├── email_confirm_reception.html   # mail 2: meeting vast + enkel onthaal
│   ├── email_followup_personal.html   # mail 3: niet overtuigd + persoonlijk nummer
│   ├── email_followup_reception.html  # mail 4: niet overtuigd + enkel onthaal
│   └── email_reminder.html            # 27u-reminder naar prospect
├── data/                # SQLite DB (tabel: leads) + logs (auto-generated)
├── .env                  # Server-config (NIET committen)
└── requirements.txt
```

## Volgende iteraties (later)

- Koppeling met het CRM van je baas (export of live sync — vorm nog te bepalen)
- Zelf-boek pagina / Calendly voor "niet overtuigd"-leads (nu: manueel via "boek nu")
- WhatsApp Business API voor automatische tekstherinneringen (nu: manueel via de ochtend-digest)
- Kwalificatie-form met multiple-choice vragen
- Deploy naar eigen server (code is er al klaar voor, zie hierboven)
- Conversieratio-dashboard op basis van de fit/geen-fit outcomes
