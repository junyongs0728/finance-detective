"""Small English lexical retrieval baseline; no LLM or semantic search."""
from pathlib import Path
import json
import re
import math
import hashlib
from functools import lru_cache
from collections import Counter
from datetime import datetime, timezone
from pypdf import PdfReader
from finance_detective.collectors.sec import ROOT

PDF_URL = "https://s206.q4cdn.com/919117365/files/doc_financials/2026/ar/Coupang-Inc-_10-K_2026_V3_PWO-65955-FINAL.pdf"
INDEX = ROOT / "data/processed/cpng-evidence.json"
PRESETS = {
    "cash_flow": "operating cash flow decrease operating assets liabilities receivable",
    "revenue": "net revenues growth product commerce developing offerings",
    "margin": "operating income expenses margin cost sales",
}
STOP = {"the", "and", "of", "to", "in", "a", "is", "our", "for", "by", "with", "was", "we", "as"}


def tokens(text):
    return [w for w in re.findall(r"[a-z]+", text.lower()) if w not in STOP]


def build():
    source = ROOT / "data/raw/cpng-2025-10k.pdf"
    pages = PdfReader(source).pages
    chunks = []
    for page_no, page in enumerate(pages, 1):
        text = " ".join((page.extract_text() or "").split())
        words = text.split()
        # Bounded overlapping windows never cross PDF page boundaries.
        for offset in range(0, len(words), 180):
            part = " ".join(words[offset:offset + 240])
            if len(part) < 80:
                continue
            chunks.append({"id": f"p{page_no}-w{offset}", "page": page_no,
                           "text": part, "source_url": f"{PDF_URL}#page={page_no}"})
    result = {"document": "Coupang 2025 Form 10-K — issuer PDF", "source_url": PDF_URL,
              "indexed_at": datetime.now(timezone.utc).isoformat(),
              "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "page_count": len(pages), "chunks": chunks}
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    temp = INDEX.with_suffix(".tmp")
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2)); temp.replace(INDEX)
    return result


class LexicalIndex:
    """Compute corpus statistics once; score queries without reparsing documents."""
    def __init__(self, chunks):
        self.chunks = chunks
        self.counts = [Counter(tokens(c["text"])) for c in chunks]
        self.lengths = [sum(c.values()) for c in self.counts]
        self.average_length = sum(self.lengths) / len(chunks) if chunks else 1
        self.average_length = self.average_length or 1
        self.document_frequency = Counter(t for count in self.counts for t in count)

    def rank(self, query, limit=5):
        terms = set(tokens(query))
        if not terms or not self.chunks or limit <= 0:
            return []
        idfs = {t: math.log(1 + (len(self.chunks) - self.document_frequency[t] + .5) /
                           (self.document_frequency[t] + .5)) for t in terms}
        results = []
        for chunk, count, length in zip(self.chunks, self.counts, self.lengths):
            score = 0.0
            for term in terms:
                freq = count[term]
                score += idfs[term] * (freq * 2.5) / (freq + 1.5 * (.25 + .75 * length / self.average_length))
            if score > 0:
                results.append({**chunk, "score": round(score, 4)})
        return sorted(results, key=lambda x: (-x["score"], x["id"]))[:limit]


def rank(chunks, query, limit=5):
    # Compatibility helper for isolated tests and evaluation; serving uses cached index.
    return LexicalIndex(chunks).rank(query, limit)


@lru_cache(maxsize=2)
def _load_index(path, modified_ns, size):
    # mtime/size key invalidates on ordinary file replacement; one cache per worker.
    data = json.loads(Path(path).read_text())
    return data, LexicalIndex(data["chunks"])


def search(query, topic=None):
    stat = INDEX.stat()
    data, index = _load_index(str(INDEX), stat.st_mtime_ns, stat.st_size)
    effective = PRESETS.get(topic, query)
    return {"method": "BM25 lexical baseline", "effective_query": effective,
            "scope": data["document"], "results": index.rank(effective),
            "answerability": "not_assessed",
            "notice": "검색 결과는 답변 가능 여부를 보장하지 않습니다. 검색 점수는 신뢰도가 아니며 AI 답변이 아닙니다."}


if __name__ == "__main__":
    data = build()
    print(f"Indexed {data['page_count']} PDF pages / {len(data['chunks'])} chunks")
