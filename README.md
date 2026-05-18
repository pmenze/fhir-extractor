# DiPAG FHIR Bundle Extractor

PDF-Arztrechnung → gematik `dipag-rechnungsbundle` via Claude AI

---

## Übersicht

```
PDF (Rechnung)
     │
     ▼
┌────────────────────────────────────────────┐
│  DiPAGExtractor                            │
│  ├── PDF → Base64                          │
│  ├── Claude API (Vision/Document)          │
│  │   ├── System-Prompt mit DiPAG-Schema   │
│  │   └── Few-Shot Beispiel-Bundle         │
│  ├── JSON-Parser + Cleanup                │
│  └── Struktur-Validierung                 │
└────────────────────────────────────────────┘
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

## Installation

```bash
pip install anthropic
export ANTHROPIC_API_KEY="sk-ant-..."
```

---

## Verwendung

### Python-API

```python
from fhir_extractor import DiPAGExtractor

extractor = DiPAGExtractor()

# Als dict
bundle = extractor.extract("rechnung.pdf")

# Direkt als Datei speichern
extractor.extract_to_file("rechnung.pdf", "output.json")
```

### CLI

```bash
# Einfache Extraktion + Konsolenausgabe
python extract_bundle.py rechnung.pdf

# Mit JSON-Ausgabe
python extract_bundle.py rechnung.pdf --output bundle.json

# Mit Validierung
python extract_bundle.py rechnung.pdf --validate

# Batch-Verarbeitung
python extract_bundle.py --batch ./rechnungen/ --output ./bundles/
```

### Demo-App (Browser)

`demo_app.html` direkt im Browser öffnen – kein Server nötig.  
API-Key im UI eingeben, PDF hochladen, Bundle extrahieren.

---

## Extrahierte Felder

| Ressource | Felder |
|-----------|--------|
| **Invoice** | Rechnungsnummer, Datum, Abrechnungsart (GOÄ/GOZ), Behandlungsart (AMB/IMP), Fachrichtung, Behandlungszeitraum, Diagnosen, Zahlungsziel, totalNet, totalGross, Notizen |
| **Patient** | Name, Geburtsdatum, Geschlecht, Adresse (mit iso21090-Extensions), KVID |
| **Practitioner** | Name (mit Titel/AC-qualifier), Adresse, Fachrichtung |
| **Organization** | Praxisname, Adresse |
| **ChargeItem** | GOÄ-Ziffer + Beschreibung, Steigerungsfaktor, Behandlungsdatum, Anzahl |

---

## Architektur-Entscheidungen

### Warum Document-API statt Text-Extraktion?
Claude versteht PDFs nativ – Tabellen, Layouts und Formatierungen bleiben erhalten.
Kein Vorverarbeitungsschritt (pdfplumber, pypdf etc.) nötig.

### Warum Few-Shot im System-Prompt?
Das Beispiel-Bundle zeigt die exakte Struktur der DiPAG-Extensions
(insbesondere die verschachtelte `go-angaben > Faktor > Value`-Struktur),
die ohne Beispiel häufig falsch generiert wird.

### Warum Retry-Mechanismus?
Bei sehr komplexen Rechnungen (~20+ Positionen) kann Claude gelegentlich
kein vollständig valides JSON liefern. 2 Retries decken >99% der Fälle ab.

### Prompt-Caching (Empfehlung für Produktion)
Bei Batch-Verarbeitung: System-Prompt mit `cache_control: {"type": "ephemeral"}`
markieren. Spart ~90% der Input-Token-Kosten für wiederholte Anfragen.

```python
# Prompt-Caching aktivieren
response = client.messages.create(
    model="claude-opus-4-5",
    system=[{
        "type": "text",
        "text": SYSTEM_PROMPT,
        "cache_control": {"type": "ephemeral"}  # <-- Caching
    }],
    ...
)
```

---

## Validierung (nach Extraktion)

Für Produktionsumgebungen empfohlen:

```bash
# HAPI FHIR Validator (benötigt Java)
java -jar validator_cli.jar bundle.json \
  -version 4.0.1 \
  -ig https://gematik.de/fhir/dipag

# Oder: fhir.resources (Python, Basis-Validierung)
pip install fhir.resources
```

```python
from fhir.resources.bundle import Bundle
bundle_obj = Bundle.model_validate(bundle_dict)
```

---

## Bekannte Limitierungen

- **Handschriftliche Rechnungen**: Funktioniert, aber schlechtere Qualität
- **Sehr lange Rechnungen** (>30 Positionen): max_tokens ggf. auf 12000 erhöhen
- **GOÄ-Ziffern mit Buchstaben** (z.B. `3597.H1`): werden als String übernommen
- **Privatärztliche Zusatzziffern**: werden ins `code.text`-Feld extrahiert
