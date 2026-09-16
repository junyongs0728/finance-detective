"""Optional: reproduce the original Coupang numeric and PDF retrieval baseline."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv
from finance_detective.collectors.sec import collect
from finance_detective.providers.common import fetch
from finance_detective.retrieval.evidence import PDF_URL, build


def main():
    load_dotenv(ROOT / ".env", override=False)
    collect()
    pdf = ROOT / "data/raw/cpng-2025-10k.pdf"
    raw = fetch(PDF_URL)
    if not raw.startswith(b"%PDF-"):
        raise RuntimeError("Issuer response was not a PDF")
    pdf.write_bytes(raw)
    result = build()
    print(f"Prepared Coupang baseline: {result['page_count']} pages, {len(result['chunks'])} chunks")


if __name__ == "__main__":
    main()
