#!/usr/bin/env python3
"""
DiPAG FHIR Extractor – CLI & Verwendungsbeispiele
==================================================
Verwendung:
    python extract_bundle.py rechnung.pdf
    python extract_bundle.py rechnung.pdf --output ergebnis.json
    python extract_bundle.py rechnung.pdf --model claude-sonnet-4-5
"""

import sys
import os
import json
import argparse
from pathlib import Path

# Extractor importieren
sys.path.insert(0, str(Path(__file__).parent))
from fhir_extractor import DiPAGExtractor


# ---------------------------------------------------------------------------
# Beispiel 1: Einfache Extraktion
# ---------------------------------------------------------------------------
def beispiel_einfach(pdf_pfad: str):
    """Minimal-Beispiel: PDF → Bundle dict."""
    extractor = DiPAGExtractor()  # nutzt ANTHROPIC_API_KEY aus Umgebung
    bundle = extractor.extract(pdf_pfad)

    # Zusammenfassung ausgeben
    entries = bundle.get("entry", [])
    print(f"\n✓ Bundle erstellt mit {len(entries)} Ressourcen:")
    for entry in entries:
        res = entry.get("resource", {})
        rt = res.get("resourceType", "?")
        if rt == "ChargeItem":
            code = res.get("code", {}).get("coding", [{}])[0].get("code", "?")
            text = res.get("code", {}).get("text", "?")
            print(f"  └ {rt}: GOÄ {code} – {text}")
        elif rt == "Invoice":
            total = res.get("totalGross", {}).get("value", 0)
            rn = res.get("identifier", [{}])[0].get("value", "?")
            print(f"  └ {rt}: Nr. {rn}, Gesamt: {total:.2f} EUR")
        else:
            name = (res.get("name") if rt == "Organization"
                    else res.get("name", [{}])[0].get("text", "?") if isinstance(res.get("name"), list)
                    else "?")
            print(f"  └ {rt}: {name}")

    return bundle


# ---------------------------------------------------------------------------
# Beispiel 2: Mit Datei-Ausgabe
# ---------------------------------------------------------------------------
def beispiel_mit_ausgabe(pdf_pfad: str, output: str = None):
    """Extrahiert und speichert als JSON-Datei."""
    extractor = DiPAGExtractor()
    output_pfad = extractor.extract_to_file(pdf_pfad, output)
    print(f"\n✓ Bundle gespeichert unter: {output_pfad}")
    return output_pfad


# ---------------------------------------------------------------------------
# Beispiel 3: Batch-Verarbeitung
# ---------------------------------------------------------------------------
def beispiel_batch(pdf_verzeichnis: str, output_verzeichnis: str):
    """
    Verarbeitet alle PDFs in einem Verzeichnis.
    Geeignet für größere Mengen mit Fehler-Toleranz.
    """
    import glob

    extractor = DiPAGExtractor()
    Path(output_verzeichnis).mkdir(exist_ok=True)

    pdfs = glob.glob(f"{pdf_verzeichnis}/*.pdf")
    print(f"Verarbeite {len(pdfs)} PDFs...\n")

    ergebnisse = {"erfolg": [], "fehler": []}

    for pdf in pdfs:
        stem = Path(pdf).stem
        output = f"{output_verzeichnis}/{stem}_bundle.json"
        print(f"  ▸ {Path(pdf).name}...", end=" ", flush=True)
        try:
            extractor.extract_to_file(pdf, output)
            print("✓")
            ergebnisse["erfolg"].append(pdf)
        except Exception as e:
            print(f"✗ {e}")
            ergebnisse["fehler"].append({"datei": pdf, "fehler": str(e)})

    print(f"\n{'─'*40}")
    print(f"Erfolg: {len(ergebnisse['erfolg'])} / {len(pdfs)}")
    if ergebnisse["fehler"]:
        print(f"Fehler: {len(ergebnisse['fehler'])}")
        for f in ergebnisse["fehler"]:
            print(f"  - {Path(f['datei']).name}: {f['fehler']}")

    return ergebnisse


# ---------------------------------------------------------------------------
# Beispiel 4: Benutzerdefinierte Validierung
# ---------------------------------------------------------------------------
def beispiel_mit_validierung(pdf_pfad: str):
    """
    Extraktion mit erweiterter Validierung der GOÄ-Positionen.
    Prüft ob alle ChargeItems eine gültige GOÄ-Ziffer haben.
    """
    extractor = DiPAGExtractor()
    bundle = extractor.extract(pdf_pfad)

    fehler = []
    charge_items = [
        e["resource"] for e in bundle.get("entry", [])
        if e.get("resource", {}).get("resourceType") == "ChargeItem"
    ]

    for ci in charge_items:
        ci_id = ci.get("id", "?")[:8]

        # GOÄ-Ziffer vorhanden?
        codings = ci.get("code", {}).get("coding", [])
        if not codings or not codings[0].get("code"):
            fehler.append(f"ChargeItem {ci_id}: keine GOÄ-Ziffer")

        # Steigerungsfaktor vorhanden?
        faktor = None
        for ext in ci.get("extension", []):
            if "go-angaben" in ext.get("url", ""):
                for sub in ext.get("extension", []):
                    if sub.get("url") == "Faktor":
                        for sub2 in sub.get("extension", []):
                            if sub2.get("url") == "Value":
                                faktor = sub2.get("valueDecimal")
        if faktor is None:
            fehler.append(f"ChargeItem {ci_id}: kein Steigerungsfaktor")

        # Behandlungsdatum vorhanden?
        bdat = next(
            (e.get("valueDate") for e in ci.get("extension", [])
             if "Behandlungsdatum" in e.get("url", "")),
            None
        )
        if not bdat:
            fehler.append(f"ChargeItem {ci_id}: kein Behandlungsdatum")

    if fehler:
        print(f"\n⚠ Validierungswarnungen ({len(fehler)}):")
        for f in fehler:
            print(f"  - {f}")
    else:
        print(f"\n✓ Alle {len(charge_items)} ChargeItems valide")

    return bundle, fehler


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="DiPAG FHIR Bundle Extractor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Beispiele:
  python extract_bundle.py rechnung.pdf
  python extract_bundle.py rechnung.pdf --output ergebnis.json
  python extract_bundle.py rechnung.pdf --validate
  python extract_bundle.py --batch ./rechnungen/ --output ./bundles/
        """
    )
    parser.add_argument("pdf", nargs="?", help="PDF-Datei")
    parser.add_argument("--output", "-o", help="Ausgabedatei (.json)")
    parser.add_argument("--model", default="claude-sonnett-4-6",
                        choices=["claude-opus-4-7", "claude-sonnet-4-6"],
                        help="Claude-Modell")
    parser.add_argument("--validate", action="store_true",
                        help="Erweiterte Validierung nach Extraktion")
    parser.add_argument("--batch", metavar="VERZEICHNIS",
                        help="Batch-Modus: alle PDFs im Verzeichnis verarbeiten")

    args = parser.parse_args()

    # API Key prüfen
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("✗ ANTHROPIC_API_KEY nicht gesetzt.")
        print("  export ANTHROPIC_API_KEY='sk-ant-...'")
        sys.exit(1)

    if args.batch:
        output_dir = args.output or "./fhir_bundles"
        beispiel_batch(args.batch, output_dir)
    elif args.pdf:
        if not Path(args.pdf).exists():
            print(f"✗ Datei nicht gefunden: {args.pdf}")
            sys.exit(1)

        if args.validate:
            bundle, _ = beispiel_mit_validierung(args.pdf)
        else:
            bundle = beispiel_einfach(args.pdf)

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(bundle, f, indent=2, ensure_ascii=False)
            print(f"\nBundle gespeichert: {args.output}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
