"""Lexical overlap only; this deliberately does not certify semantic cleanliness."""
import re
import unicodedata


def normalize(text):
    text = unicodedata.normalize("NFKC", text).lower()
    text = re.sub(r"<[^>]*>", " ", text)
    return "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in text).split()


def shingles(text, size):
    words = normalize(text)
    return {tuple(words[i:i + size]) for i in range(len(words) - size + 1)}


def filter_rows(rows, benchmark_texts, *, text_field="text", shingle_size=13, overlap_threshold=0.5):
    if shingle_size < 1 or not 0 < overlap_threshold <= 1:
        raise ValueError("Invalid overlap parameters")
    targets = [shingles(text, shingle_size) for text in benchmark_texts]
    uncovered = sum(not target for target in targets)
    kept, removed = [], 0
    for row in rows:
        source = shingles(str(row.get(text_field, "")), shingle_size)
        if any(target and len(source & target) / len(target) >= overlap_threshold for target in targets):
            removed += 1
        else:
            kept.append(row)
    return {"rows": kept, "removed_count": removed, "uncovered_items": uncovered,
            "semantic_contamination_free": False}
