# DiPAG FHIR Konverter

PDF-Arztrechnung → gematik `dipag-rechnungsbundle` via KI-Modell

---

## Übersicht

Die App besteht aus zwei Teilen:

- **`demo_app.html`** – Browser-Frontend: PDF hochladen, FHIR Bundle extrahieren, validieren und anzeigen
- **`proxy-spring/`** – Spring Boot 4 / Java 25 Backend: hält API-Keys serverseitig, leitet Anfragen weiter, validiert FHIR-Bundles

```
Browser (demo_app.html)
        │
        │  GET  /prompt          → lädt System-Prompt
        │  POST /v1/messages     → Extraktion via Claude oder Gemma 4
        │  POST /validate        → FHIR-Validierung gegen DiPAG-Profile
        ▼
Spring Boot Proxy (:8787)
        │
        ├─ Claude-Modell  → POST https://api.anthropic.com/v1/messages
        │
        └─ Gemma 4        → PDF → PNG-Seiten (PDFBox) → POST https://api.infomaniak.com/2/ai/.../openai/v1/chat/completions
                ↓
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
- `ANTHROPIC_API_KEY` als Umgebungsvariable (für Claude-Modelle)
- `INFOMANIAK_API_KEY` + `INFOMANIAK_PRODUCT_ID` (für Gemma 4 via Infomaniak, optional)

---

## Starten

```bash
cd proxy-spring

# Nur Claude
ANTHROPIC_API_KEY="sk-ant-..." mvn spring-boot:run

# Claude + Infomaniak (Gemma 4)
ANTHROPIC_API_KEY="sk-ant-..." \
INFOMANIAK_API_KEY="..." \
INFOMANIAK_PRODUCT_ID="12345" \
mvn spring-boot:run
```

Dann `demo_app.html` im Browser öffnen – kein weiterer Server nötig.

---

## Modelle

| Modell | Anbieter | Besonderheit |
|--------|----------|--------------|
| `claude-opus-4-7` | Anthropic | Empfohlen – beste Extraktionsqualität |
| `claude-sonnet-4-6` | Anthropic | Günstiger |
| `google/gemma-4-31B-it` | Infomaniak | Open-Source, vision-fähig; PDF wird serverseitig zu PNG-Seiten gerendert |

---

## FHIR-Validierung

Nach jeder Extraktion validiert der Proxy das Bundle automatisch gegen die geladenen DiPAG-Profile.
Das Ergebnis erscheint im Tab **Validierung** der Ergebnisansicht:

- **Grüner Haken** an jedem Ressource-Chip → keine Fehler für diesen Typ
- **Rotes Ausrufezeichen** → mindestens ein Validierungsfehler
- Tab zeigt Zusammenfassung (Fehler / Warnungen / Hinweise) und Details mit Pfadangabe

### Profile einbinden

FHIR-Profildateien (StructureDefinition, CodeSystem, ValueSet als `.json`) in den Ordner `proxy-spring/fhir-profiles/` legen.
Der Server lädt sie beim Start. Fehlt der Ordner, wird nur gegen Basis-R4 validiert.

```bash
# Beispiel: DiPAG-Paket von Simplifier installieren
npm --registry https://packages.simplifier.net install de.gematik.dipag@1.0.7
# Enthaltene .json-Dateien nach proxy-spring/fhir-profiles/ kopieren
```

---

## Endpunkte (Proxy)

| Methode | Pfad | Beschreibung |
|---------|------|--------------|
| `GET` | `/prompt` | Lädt `prompts/system_prompt.txt` mit eingebettetem `example_bundle.json` |
| `POST` | `/**` | Leitet an Anthropic oder Infomaniak weiter (Routing nach Modellname) |
| `POST` | `/validate` | Validiert ein FHIR-Bundle, gibt `OperationOutcome` als JSON zurück |

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

`proxy-spring/prompts/system_prompt.txt` und `proxy-spring/prompts/example_bundle.json` können direkt bearbeitet werden.
Der Proxy lädt den Prompt bei jedem Aufruf von `GET /prompt` neu von der Festplatte –
Änderungen wirken sofort ohne Neustart.
