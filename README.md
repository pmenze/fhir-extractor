# DiPAG FHIR Konverter

PDF-Arztrechnung → gematik `dipag-rechnungsbundle` via Claude AI

---

## Übersicht

Die App besteht aus zwei Teilen:

- **`demo_app.html`** – Browser-Frontend: PDF hochladen, FHIR Bundle extrahieren und anzeigen
- **`proxy-spring/`** – Spring Boot 4 / Java 25 Backend: hält den API-Key serverseitig, leitet Anfragen an die Claude API weiter

```
Browser (demo_app.html)
        │
        │  GET  /prompt          → lädt System-Prompt
        │  POST /v1/messages     → leitet Claude-Anfrage weiter
        ▼
Spring Boot Proxy (:8787)
        │
        │  POST https://api.anthropic.com/v1/messages
        ▼
Claude API (claude-opus-4-5)
        │
        ▼
FHIR R4 Bundle (collection)
  ├── Invoice (dipag-rechnung)
  ├── Patient (dipag-patient)
  ├── Practitioner (dipag-person)
  ├── Organization (dipag-institution)
  └── ChargeItem × n (dipag-rechnungsposition)
```

---

## Voraussetzungen

- Java 25
- Maven
- `ANTHROPIC_API_KEY` als Umgebungsvariable

---

## Starten

```bash
cd proxy-spring
ANTHROPIC_API_KEY="sk-ant-..." mvn spring-boot:run
```

Dann `demo_app.html` im Browser öffnen – kein weiterer Server nötig.

---

## Projektstruktur

```
fhir-extractor/
├── demo_app.html               # Browser-Frontend
├── prompts/
│   ├── system_prompt.txt       # DiPAG-Konvertierungsanweisung für Claude
│   └── example_bundle.json     # Few-Shot-Beispiel (wird in Prompt eingebettet)
└── proxy-spring/               # Spring Boot Backend
    └── src/main/java/com/example/fhirproxy/
        ├── ProxyApplication.java   # Einstiegspunkt
        ├── ProxyController.java    # GET /prompt, POST /**
        └── WebConfig.java          # CORS-Konfiguration
```

---

## Endpunkte (Proxy)

| Methode | Pfad | Beschreibung |
|---------|------|--------------|
| `GET` | `/prompt` | Lädt `prompts/system_prompt.txt` mit eingebettetem `example_bundle.json` |
| `POST` | `/**` | Leitet den Request-Body an `https://api.anthropic.com/v1/messages` weiter, streamt die Antwort zurück |

---

## Extrahierte FHIR-Felder

| Ressource | Felder |
|-----------|--------|
| **Invoice** | Rechnungsnummer, Datum, Abrechnungsart (GOÄ/GOZ), Behandlungsart (AMB/IMP), Fachrichtung, Behandlungszeitraum, Zahlungsziel, totalNet, totalGross |
| **Patient** | Name, Geburtsdatum, Geschlecht, Adresse, KVID |
| **Practitioner** | Name (mit Titel), Adresse, Fachrichtung |
| **Organization** | Praxisname, Adresse |
| **ChargeItem** | GOÄ/GOZ-Ziffer, Beschreibung, Steigerungsfaktor, Behandlungsdatum, Anzahl |

---

## Prompt anpassen

`prompts/system_prompt.txt` und `prompts/example_bundle.json` können direkt bearbeitet werden.
Der Proxy lädt den Prompt bei jedem Aufruf von `GET /prompt` neu von der Festplatte –
Änderungen wirken sofort ohne Neustart.
