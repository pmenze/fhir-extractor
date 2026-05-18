"""
DiPAG FHIR Bundle Extractor
============================
Konvertiert Arzt-Rechnungen (PDF) in valide DiPAG FHIR R4 Bundles
via Claude's Vision/Document API.
"""

import anthropic
import base64
import json
import uuid
import re
from pathlib import Path
from datetime import datetime
from typing import Optional

# ---------------------------------------------------------------------------
# Prompt-Konstanten
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """Du bist ein spezialisierter FHIR R4 Konverter für das DiPAG-Profil (Digitale Patientenakte Gematik).
Deine Aufgabe: Extrahiere alle Rechnungsdaten aus dem PDF und erzeuge ein valides FHIR R4 Bundle.

## Ausgabe-Format
Antworte NUR mit einem einzigen validen JSON-Objekt. Kein Markdown, keine Backticks, keine Erklärungen.

## Bundle-Struktur (DiPAG dipag-rechnungsbundle)
Das Bundle hat type="collection" und enthält folgende Ressourcen in dieser Reihenfolge:
1. Invoice (dipag-rechnung)
2. Patient (dipag-patient)
3. Practitioner (dipag-person) – der behandelnde Arzt
4. Organization (dipag-institution) – die Praxis
5. ChargeItem (dipag-rechnungsposition) – eine pro Rechnungszeile

## Pflichtfelder und Constraints

### Bundle
- resourceType: "Bundle"
- meta.profile: ["https://gematik.de/fhir/dipag/StructureDefinition/dipag-rechnungsbundle"]
- type: "collection"
- timestamp: ISO 8601 mit Zeitzone
- entry[].fullUrl: "urn:uuid:{uuid}" (neue UUID für jede Ressource)

### Invoice
- meta.profile: ["https://gematik.de/fhir/dipag/StructureDefinition/dipag-rechnung"]
- identifier[0].type.coding[0].system: "https://gematik.de/fhir/dipag/CodeSystem/dipag-rechnung-identifier-type-cs"
- identifier[0].type.coding[0].code: "invoice"
- identifier[0].system: Praxis-eigene System-URL (z.B. "https://{praxisname}/fhir/sid/rechnungsnummer")
- identifier[0].value: Rechnungsnummer
- status: "issued"
- type.coding[0].system: "https://gematik.de/fhir/dipag/CodeSystem/dipag-rechnung-abrechnungsart-cs"
- type.coding[0].code: "GOÄ" (oder "GOZ" bei Zahnarzt)
- extension Behandlungsart: url="https://gematik.de/fhir/dipag/StructureDefinition/dipag-behandlungsart"
  valueCoding.system="http://terminology.hl7.org/CodeSystem/v3-ActCode", code="AMB" (ambulant) oder "IMP" (stationär)
- extension Fachrichtung: url="https://gematik.de/fhir/dipag/StructureDefinition/dipag-fachrichtung"
  valueCoding.system="http://ihe-d.de/CodeSystems/AerztlicheFachrichtungen"
- extension Behandlungszeitraum: url="http://hl7.org/fhir/5.0/StructureDefinition/extension-Invoice.period[x]"
  valuePeriod.start + valuePeriod.end (aus den ChargeItem-Daten ableiten)
- extension Diagnosen: url="https://gematik.de/fhir/dipag/StructureDefinition/DiPagAbrechnungsDiagnoseProzedurFreitext"
  valueString: alle Diagnosen als Freitext
- participant[leistungserbringer].actor.reference: "Practitioner/{uuid}"
- participant[forderungsinhaber].actor.reference: "Organization/{uuid}"
- subject.reference: "Patient/{uuid}"
- issuer.reference: "Organization/{uuid}"
- recipient.reference: "Patient/{uuid}"
- recipient.identifier: GKV-KVID falls vorhanden (system: "http://fhir.de/sid/gkv/kvid-10")
- date: Rechnungsdatum (YYYY-MM-DD)
- lineItem[]: je ChargeItem eine Zeile:
  - sequence: 1, 2, 3, ...
  - chargeItemReference.reference: "ChargeItem/{uuid}"
  - priceComponent[0].type: "base"
  - priceComponent[0].amount.value: Betrag
  - priceComponent[0].amount.currency: "EUR"
- totalNet.value + totalNet.currency: "EUR"
- totalGross.value + totalGross.currency: "EUR"
- paymentTerms: Zahlungsziel als Text
- _paymentTerms.extension[0].url: "https://gematik.de/fhir/dipag/StructureDefinition/dipag-zahlungsziel"
  valueDate: Zahlungsziel als Datum (YYYY-MM-DD)
- note[0].text: Notiztext falls vorhanden

### Patient
- meta.profile: ["https://gematik.de/fhir/dipag/StructureDefinition/dipag-patient"]
- name[0].use: "official", text, family, given
- birthDate: YYYY-MM-DD
- gender: "male" / "female" / "other" / "unknown"
- address[0].type: "both", line, city, postalCode, country: "DE"
- address[0]._line[0].extension: iso21090-ADXP-streetName + iso21090-ADXP-houseNumber
- identifier[0] für GKV: type.coding[0].code="KVZ10", system="http://fhir.de/CodeSystem/identifier-type-de-basis"
  value: KVID, system: "http://fhir.de/sid/gkv/kvid-10"

### Practitioner
- meta.profile: ["https://gematik.de/fhir/dipag/StructureDefinition/dipag-person"]
- name[0]: prefix (mit AC-qualifier-Extension), family, given, use: "official"
- qualification[0].code.coding[0]: Fachrichtung (gleicher Code wie in Invoice-Extension)
- address: wie Patient

### Organization
- meta.profile: ["https://gematik.de/fhir/dipag/StructureDefinition/dipag-institution"]
- name: Praxisname
- address: Praxisadresse

### ChargeItem (pro Rechnungszeile)
- meta.profile: ["https://gematik.de/fhir/dipag/StructureDefinition/dipag-rechnungsposition"]
- status: "billable"
- extension[0] Typ: url="https://gematik.de/fhir/dipag/StructureDefinition/dipag-rechnungsposition-type"
  valueCoding.code="GOÄ", valueCoding.system="https://gematik.de/fhir/dipag/CodeSystem/dipag-chargeitem-type-cs"
- extension[1] GO-Angaben: url="https://gematik.de/fhir/dipag/StructureDefinition/dipag-rechnungsposition-go-angaben"
  sub-extension "Faktor" > sub-extension "Value" > valueDecimal: Steigerungsfaktor
- extension[2] Behandlungsdatum: url="https://gematik.de/fhir/dipag/StructureDefinition/DiPagRechnungspositionBehandlungsdatum"
  valueDate: Datum der Leistung (YYYY-MM-DD)
- code.coding[0].system: "http://fhir.de/CodeSystem/bäk/goä"
- code.coding[0].code: GOÄ-Ziffer (String, z.B. "1", "5", "3501")
- code.text: Leistungsbeschreibung
- quantity.value: Anzahl (meist 1), quantity.unit: "Anzahl", quantity.system: "http://unitsofmeasure.org", quantity.code: "{count}"
- subject.reference: "Patient/{uuid}"
- performer[0].actor.reference: "Practitioner/{uuid}"
- occurrencePeriod.start + occurrencePeriod.end: Behandlungsdatum (start = end = Datum der Leistung)

## Fachrichtungs-Codes (Auswahl)
ALLG=Allgemeinmedizin, INNE=Innere Medizin, CHIR=Chirurgie, DERM=Dermatologie,
GYNA=Gynäkologie, NEUR=Neurologie, ORTH=Orthopädie, PSYC=Psychiatrie,
RADI=Radiologie, UROL=Urologie, OPHTH=Augenheilkunde, HNO=HNO, PAED=Pädiatrie

## Fehlende Daten
- Fehlende optionale Felder: weglassen (nicht null)
- Fehlende Pflichtfelder: sinnvollen Default oder leeren String verwenden
- Unbekannte GOÄ-Ziffer: Code aus dem PDF übernehmen, text aus dem PDF

## Beispiel-Bundle (zur Orientierung der Struktur):
{EXAMPLE_BUNDLE}
"""

EXAMPLE_BUNDLE = """{
  "resourceType": "Bundle",
  "meta": {"profile": ["https://gematik.de/fhir/dipag/StructureDefinition/dipag-rechnungsbundle"]},
  "type": "collection",
  "timestamp": "2018-10-24T12:00:00+01:00",
  "entry": [
    {
      "fullUrl": "urn:uuid:INVOICE-UUID",
      "resource": {
        "resourceType": "Invoice",
        "meta": {"profile": ["https://gematik.de/fhir/dipag/StructureDefinition/dipag-rechnung"]},
        "status": "issued",
        "type": {"coding": [{"system": "https://gematik.de/fhir/dipag/CodeSystem/dipag-rechnung-abrechnungsart-cs","code": "GOÄ","display": "Gebührenordnung für Ärzte"}]},
        "identifier": [{"type": {"coding": [{"code": "invoice","system": "https://gematik.de/fhir/dipag/CodeSystem/dipag-rechnung-identifier-type-cs"}]},"system": "https://praxis-beispiel.de/fhir/sid/rechnungsnummer","value": "1234"}],
        "extension": [
          {"url": "https://gematik.de/fhir/dipag/StructureDefinition/dipag-behandlungsart","valueCoding": {"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode","code": "AMB","display": "ambulatory"}},
          {"url": "https://gematik.de/fhir/dipag/StructureDefinition/dipag-fachrichtung","valueCoding": {"system": "http://ihe-d.de/CodeSystems/AerztlicheFachrichtungen","code": "INNE","display": "Innere Medizin"}},
          {"url": "http://hl7.org/fhir/5.0/StructureDefinition/extension-Invoice.period[x]","valuePeriod": {"start": "2018-10-04","end": "2018-10-19"}},
          {"url": "https://gematik.de/fhir/dipag/StructureDefinition/DiPagAbrechnungsDiagnoseProzedurFreitext","valueString": "Grippaler Infekt"}
        ],
        "participant": [
          {"role": {"coding": [{"code": "leistungserbringer","system": "https://gematik.de/fhir/dipag/CodeSystem/dipag-participant-role-cs"}]},"actor": {"reference": "Practitioner/PRACTITIONER-UUID"}},
          {"role": {"coding": [{"code": "forderungsinhaber","system": "https://gematik.de/fhir/dipag/CodeSystem/dipag-participant-role-cs"}]},"actor": {"reference": "Organization/ORG-UUID"}}
        ],
        "subject": {"reference": "Patient/PATIENT-UUID"},
        "recipient": {"reference": "Patient/PATIENT-UUID"},
        "issuer": {"reference": "Organization/ORG-UUID"},
        "date": "2018-10-24",
        "lineItem": [{"sequence": 1,"chargeItemReference": {"reference": "ChargeItem/CHARGEITEM-UUID"},"priceComponent": [{"type": "base","amount": {"value": 10.72,"currency": "EUR"}}]}],
        "totalNet": {"value": 54.95,"currency": "EUR"},
        "totalGross": {"value": 54.95,"currency": "EUR"},
        "paymentTerms": "Zahlbar bis 14.11.2018",
        "_paymentTerms": {"extension": [{"url": "https://gematik.de/fhir/dipag/StructureDefinition/dipag-zahlungsziel","valueDate": "2018-11-14"}]}
      }
    }
  ]
}"""


# ---------------------------------------------------------------------------
# Haupt-Extraktor
# ---------------------------------------------------------------------------

class DiPAGExtractor:
    """
    Extrahiert DiPAG FHIR R4 Bundles aus Arzt-Rechnungen (PDF).

    Beispiel:
        extractor = DiPAGExtractor()
        bundle = extractor.extract("rechnung.pdf")
        print(json.dumps(bundle, indent=2, ensure_ascii=False))
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-sonnet-4-6"):
        self.client = anthropic.Anthropic(api_key=api_key)  # nutzt ANTHROPIC_API_KEY wenn None
        self.model = model
        self._system_prompt = SYSTEM_PROMPT.replace("{EXAMPLE_BUNDLE}", EXAMPLE_BUNDLE)

    # ------------------------------------------------------------------
    # Öffentliche API
    # ------------------------------------------------------------------

    def extract(self, pdf_path: str, max_retries: int = 2) -> dict:
        """
        Liest ein PDF und gibt ein DiPAG FHIR Bundle als dict zurück.

        Args:
            pdf_path:    Pfad zur PDF-Datei
            max_retries: Anzahl Wiederholungen bei JSON-Fehler

        Returns:
            dict mit validem FHIR Bundle

        Raises:
            FileNotFoundError: PDF existiert nicht
            ValueError:        Extraktion fehlgeschlagen nach allen Retries
        """
        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF nicht gefunden: {pdf_path}")

        pdf_b64 = base64.standard_b64encode(path.read_bytes()).decode("utf-8")

        last_error = None
        for attempt in range(max_retries + 1):
            try:
                raw_json = self._call_claude(pdf_b64, attempt)
                bundle = self._parse_and_fix(raw_json)
                self._validate_structure(bundle)
                return bundle
            except (json.JSONDecodeError, ValueError) as e:
                last_error = e
                if attempt < max_retries:
                    print(f"  Versuch {attempt + 1} fehlgeschlagen ({e}), wiederhole...")

        raise ValueError(f"Extraktion fehlgeschlagen nach {max_retries + 1} Versuchen: {last_error}")

    def extract_to_file(self, pdf_path: str, output_path: Optional[str] = None) -> str:
        """
        Extrahiert und speichert das Bundle als JSON-Datei.

        Returns:
            Pfad zur erstellten JSON-Datei
        """
        bundle = self.extract(pdf_path)

        if output_path is None:
            stem = Path(pdf_path).stem
            output_path = f"{stem}_fhir_bundle.json"

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(bundle, f, indent=2, ensure_ascii=False)

        print(f"Bundle gespeichert: {output_path}")
        return output_path

    # ------------------------------------------------------------------
    # Interne Methoden
    # ------------------------------------------------------------------

    def _call_claude(self, pdf_b64: str, attempt: int) -> str:
        """Sendet das PDF an Claude und gibt den Roh-Text zurück."""

        user_text = "Extrahiere alle Rechnungsdaten aus dieser PDF-Rechnung und erzeuge das DiPAG FHIR Bundle."
        if attempt > 0:
            user_text += (
                "\n\nWICHTIG: Deine vorherige Antwort war kein valides JSON. "
                "Antworte diesmal NUR mit rohem JSON, ohne jegliche Umrahmung oder Text davor/danach."
            )

        response = self.client.messages.create(
            model=self.model,
            max_tokens=8192,
            system=self._system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": "application/pdf",
                                "data": pdf_b64,
                            },
                        },
                        {"type": "text", "text": user_text},
                    ],
                }
            ],
        )
        return response.content[0].text

    def _parse_and_fix(self, raw: str) -> dict:
        """Bereinigt die Antwort und parst JSON."""
        # Backtick-Blöcke entfernen
        clean = re.sub(r"```(?:json)?\s*", "", raw).strip()
        # Führenden/folgenden Nicht-JSON-Text entfernen
        start = clean.find("{")
        end = clean.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError("Kein JSON-Objekt in der Antwort gefunden")
        return json.loads(clean[start:end])

    def _validate_structure(self, bundle: dict) -> None:
        """Prüft Mindeststruktur und ergänzt fehlende Pflichtfelder."""
        if bundle.get("resourceType") != "Bundle":
            raise ValueError("Kein FHIR Bundle (resourceType != 'Bundle')")
        if bundle.get("type") != "collection":
            raise ValueError("Bundle type muss 'collection' sein")
        if not bundle.get("entry"):
            raise ValueError("Bundle enthält keine Entries")

        # Timestamp sicherstellen
        if not bundle.get("timestamp"):
            bundle["timestamp"] = datetime.now().astimezone().isoformat()

        # UUIDs prüfen und ggf. ergänzen
        self._ensure_uuids(bundle)

        # Ressourcentypen zählen
        types = [e.get("resource", {}).get("resourceType") for e in bundle.get("entry", [])]
        if "Invoice" not in types:
            raise ValueError("Bundle enthält keine Invoice-Ressource")
        if "Patient" not in types:
            raise ValueError("Bundle enthält keinen Patient")

    def _ensure_uuids(self, bundle: dict) -> None:
        """
        Stellt sicher, dass alle fullUrl-Felder korrekte urn:uuid-URLs haben
        und interne Referenzen konsistent sind.
        """
        id_map: dict[str, str] = {}  # alte ID → neue UUID

        for entry in bundle.get("entry", []):
            resource = entry.get("resource", {})
            res_type = resource.get("resourceType", "")
            res_id = resource.get("id", "")

            # Neue UUID generieren falls nötig
            if not res_id or len(res_id) < 8:
                new_id = str(uuid.uuid4())
                old_key = f"{res_type}/{res_id}" if res_id else None
                resource["id"] = new_id
                if old_key:
                    id_map[old_key] = new_id
                id_map[f"{res_type}/{new_id}"] = new_id

            full_url = entry.get("fullUrl", "")
            if not full_url.startswith("urn:uuid:"):
                entry["fullUrl"] = f"urn:uuid:{resource['id']}"
