"""Analyzers de qualidade para TEXTO — detectores registrados com método, versão e threshold.

Regra do plano: score não é decisão; humano decide (keep/review/quarantine).
"""
import hashlib
import math
import re
from typing import Any

DETECTOR_VERSION = "1"


def _infer_language(text: str) -> str:
    """Very rough language detection: checks for common words in English vs Portuguese/Spanish."""
    words = set(re.findall(r"\b[a-zA-Z]+\b", text.lower()))
    en_words = {"the", "and", "is", "of", "to", "in", "a", "it", "that", "with", "for"}
    pt_words = {"o", "a", "e", "de", "que", "se", "para", "com", "não", "uma", "em"}
    es_words = {"el", "la", "de", "que", "y", "en", "un", "una", "los", "las"}
    en_count = len(words & en_words)
    pt_count = len(words & pt_words)
    es_count = len(words & es_words)
    if en_count >= pt_count and en_count >= es_count:
        return "en"
    if pt_count >= es_count:
        return "pt"
    return "es"


def _compute_stats(text: str) -> dict[str, Any]:
    """Compute text statistics."""
    lines = text.splitlines()
    line_lengths = [len(l) for l in lines] if lines else [0]
    return {
        "char_count": len(text),
        "word_count": len(text.split()),
        "line_count": len(lines),
        "max_line_length": max(line_lengths) if line_lengths else 0,
        "min_line_length": min(line_lengths) if line_lengths else 0,
        "has_html": "<" in text and ">" in text,
        "language": _infer_language(text),
    }


def repetition_score(text: str) -> float:
    """0.0-1.0: fraction of repeated n-grams (5-grams)."""
    if not text:
        return 0.0
    words = text.split()
    if len(words) < 5:
        return 0.0
    grams = [tuple(words[i:i + 5]) for i in range(len(words) - 4)]
    if not grams:
        return 0.0
    unique = len(set(grams))
    return 1.0 - (unique / len(grams))


def spam_score(text: str) -> float:
    """0.0-1.0: heuristic spam indicators (repeated punctuation, excessive caps)."""
    if not text:
        return 0.0
    punct = sum(1 for c in text if c in "!@#$%^&*()")
    caps = sum(1 for c in text if c.isupper())
    total = max(1, len(text))
    score = min(1.0, (punct / total) * 5 + (caps / total) * 2)
    return score


def code_ratio(text: str) -> float:
    """0.0-1.0: fraction of text that looks like code (backticks, indentation)."""
    if not text:
        return 0.0
    lines = text.splitlines()
    if not lines:
        return 0.0
    code_lines = 0
    for line in lines:
        stripped = line.strip()
        if stripped and (stripped.startswith(("def ", "import ", "class ", "from ", "return ",
                                                "if ", "for ", "while ", "print(", "const ",
                                                "let ", "var ", "function "))) or \
           stripped.endswith((":", "(", "{")):
            code_lines += 1
    return code_lines / len(lines)


def toxicity_score(text: str) -> float:
    """0.0-1.0: heuristic toxicity (offensive word list)."""
    if not text:
        return 0.0
    offensive = {"fuck", "shit", "ass", "bitch", "dick", "cunt", "bastard",
                 "slut", "whore", "nigger", "retard", "fag", "spic", "chink"}
    words = set(re.findall(r"\b[a-zA-Z]+\b", text.lower()))
    hits = len(words & offensive)
    return min(1.0, hits / max(1, len(words)))


def pii_score(text: str) -> float:
    """0.0-1.0: heuristic PII (email, phone, SSN, credit card patterns)."""
    if not text:
        return 0.0
    patterns = [
        r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b",  # email
        r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b",  # phone
        r"\b\d{3}-\d{2}-\d{4}\b",  # SSN
        r"\b(?:\d[ -]*?){13,16}\b",  # credit card
        r"\b(?:\d{4}[ -]?){3}\d{4}\b",
    ]
    hits = sum(1 for p in patterns if re.search(p, text))
    return min(1.0, hits / len(patterns))


def repetition_stats(text: str) -> dict[str, Any]:
    """Detailed repetition analysis for the inspector."""
    if not text:
        return {"repetition_score": 0.0, "unique_grams": 0, "total_grams": 0}
    words = text.split()
    if len(words) < 5:
        return {"repetition_score": 0.0, "unique_grams": 0, "total_grams": 0}
    grams = [tuple(words[i:i + 5]) for i in range(len(words) - 4)]
    unique = len(set(grams))
    return {
        "repetition_score": round(1.0 - unique / len(grams), 3),
        "unique_grams": unique,
        "total_grams": len(grams),
    }


def sha256_file(path) -> str:
    """SHA-256 of a file (used by ingest for exact dedup)."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

# ---------------------------------------------------------------------------
# Normalização de texto (Unicode, HTML, whitespace, boilerplate)
# ---------------------------------------------------------------------------
import html as _html
import re as _re
import unicodedata as _unicodedata

_TAG_RE = _re.compile(r"<[^>\n]{1,2000}>")
_WS_RUN_RE = _re.compile(r"[ \t\x0b\f\u00a0\u200b\u200c\u200d\u2060\ufeff]+")
_MANY_NL_RE = _re.compile(r"\n{3,}")
_CTRL_RE = _re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_BOILER_RES = (
    _re.compile(r"^\s*\[?edit\]?\s*$", _re.I),
    _re.compile(r"^\s*(cookie|advertis|advertisement|subscribe|sign ?up|"
               r"log ?in|share this|follow us|click here|all rights reserved|"
               r"copyright ©|skip to (main )?content|jump to comments)", _re.I),
    _re.compile(r"^\s*(?:https?://\S+\s*)+$"),
    _re.compile(r"^\s*\|[\s:|-]{3,}\|?\s*$"),
    _re.compile(r"^(?:[-*_]\s*){3,}$"),
    _re.compile(r"^\s*(?:\d+\s*[.)]\s*){1,3}\s*$"),
)


def strip_html(text: str) -> str:
    """Remove tags HTML e converte entities (&amp; etc.)."""
    out = _html.unescape(text)
    out = _TAG_RE.sub(" ", out)
    return out


def normalize_unicode(text: str) -> str:
    """NFKC + remove caracteres de controle; Zero-width e NBSP ficam pro whitespace."""
    out = _unicodedata.normalize("NFKC", text)
    return _CTRL_RE.sub("", out)


def collapse_whitespace(text: str) -> str:
    """CRLF→LF, NBSP/zero-width→espaço, runs de espaços→1, 3+ newlines→2, trim."""
    out = text.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    out = _WS_RUN_RE.sub(" ", out)
    out = "\n".join(ln.rstrip() for ln in out.split("\n"))
    out = _MANY_NL_RE.sub("\n\n", out)
    return out.strip()


def remove_boilerplate(text: str) -> str:
    """Dropa linhas de boilerplate (nav/cookies/links soltos) e repetições
    consecutivas idênticas (mantém a primeira ocorrência)."""
    kept: list[str] = []
    prev: str | None = None
    for ln in text.split("\n"):
        if any(rx.match(ln) for rx in _BOILER_RES):
            continue
        if ln.strip() and ln == prev:  # linha repetida em sequência
            continue
        kept.append(ln)
        prev = ln
    return "\n".join(kept).strip()


def normalize_text(text: str) -> tuple[str, dict[str, bool]]:
    """Pipeline completo de normalização. Retorna (texto, report) — report diz
    quais transformações mudaram o conteúdo."""
    report: dict[str, bool] = {}
    steps = (
        ("html", strip_html),
        ("unicode", normalize_unicode),
        ("whitespace", collapse_whitespace),
        ("boilerplate", remove_boilerplate),
    )
    out = text
    for name, fn in steps:
        new = fn(out)
        report[name] = new != out
        out = new
    return out, report
