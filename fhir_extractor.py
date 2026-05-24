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
# Prompt laden
# ---------------------------------------------------------------------------

def _load_system_prompt() -> str:
    """Lädt den Prompt aus system_prompt.txt + example_bundle.json (relativ zur Skript-Datei)."""
    base = Path(__file__).parent / "prompts"
    prompt_file = base / "system_prompt.txt"
    bundle_file = base / "example_bundle.json"
    template = prompt_file.read_text(encoding="utf-8")
    example = bundle_file.read_text(encoding="utf-8").strip()
    return template.replace("{EXAMPLE_BUNDLE}", example)


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
        self._system_prompt = _load_system_prompt()

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
