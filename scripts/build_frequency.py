"""Build a frequency dictionary from English PDF/TXT/EPUB source documents.

Pipeline:
  1. Read every new file directly under books/ (files already processed live
     in books/done/ and are skipped).
  2. Extract raw text, lemmatize with spaCy (verbs/nouns/adjectives collapse
     to their base form), and count (lemma, POS) pairs per document.
  3. Save one per-document stats CSV under output/per_document/.
  4. Move the source file into books/done/ so re-running the script never
     double-counts it.
  5. Re-aggregate every per-document CSV into overall_stats.csv (full stats,
     including stopwords and proper nouns tagged for filtering) and
     wordlist_overall.csv (stopwords/proper nouns removed - the base list to
     use for building vocabulary lists in other languages).

Usage:
    .venv\\Scripts\\python.exe scripts\\build_frequency.py
"""
import csv
import shutil
import sys
from collections import Counter
from pathlib import Path

import spacy

from extract_text import extract_text

ROOT = Path(__file__).resolve().parent.parent
BOOKS_DIR = ROOT / "books"
DONE_DIR = BOOKS_DIR / "done"
OUTPUT_DIR = ROOT / "output"
PER_DOC_DIR = OUTPUT_DIR / "per_document"
OVERALL_STATS_PATH = OUTPUT_DIR / "overall_stats.csv"
WORDLIST_PATH = OUTPUT_DIR / "wordlist_overall.csv"

SUPPORTED_SUFFIXES = {".txt", ".pdf", ".epub"}
CHUNK_SIZE = 100_000  # characters; keeps spaCy memory usage predictable


def load_nlp():
    nlp = spacy.load("en_core_web_sm", disable=["parser", "ner"])
    nlp.max_length = 20_000_000
    return nlp


def iter_chunks(text: str, size: int = CHUNK_SIZE):
    """Yield chunks split on whitespace boundaries so words are never cut."""
    start = 0
    length = len(text)
    while start < length:
        end = min(start + size, length)
        if end < length:
            split = text.rfind(" ", start, end)
            if split > start:
                end = split
        yield text[start:end]
        start = end


def count_tokens(nlp, text: str):
    """Return (counts, stopword_flags) keyed by (lemma, pos).

    is_stop is tracked with OR-aggregation because spaCy's stopword lookup
    can occasionally disagree between two occurrences of the same
    lemma+POS (e.g. casing-dependent lookups); keying counts by
    (lemma, pos) only avoids splitting a single word into duplicate rows.
    """
    counts = Counter()
    stop_flags = {}
    for doc in nlp.pipe(iter_chunks(text), batch_size=1):
        for token in doc:
            if not token.is_alpha:
                continue
            pos = token.pos_
            lemma = token.lemma_ if pos == "PROPN" else token.lemma_.lower()
            key = (lemma, pos)
            counts[key] += 1
            stop_flags[key] = stop_flags.get(key, False) or token.is_stop
    return counts, stop_flags


def process_new_documents(nlp) -> int:
    PER_DOC_DIR.mkdir(parents=True, exist_ok=True)
    DONE_DIR.mkdir(parents=True, exist_ok=True)

    new_files = sorted(
        p for p in BOOKS_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES
    )
    if not new_files:
        print("No new documents to process in books/.")
        return 0

    processed = 0
    for path in new_files:
        print(f"Processing {path.name} ...")
        try:
            text = extract_text(path)
        except Exception as exc:  # keep going even if one file fails
            print(f"  ! Failed to extract text: {exc}")
            continue

        if not text.strip():
            print("  ! No extractable text, skipping (not moved to done).")
            continue

        counts, stop_flags = count_tokens(nlp, text)
        doc_csv = PER_DOC_DIR / f"{path.stem}.csv"
        with doc_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["lemma", "pos", "count", "is_stopword", "is_proper_noun"])
            for (lemma, pos), count in sorted(counts.items(), key=lambda kv: -kv[1]):
                writer.writerow([lemma, pos, count, int(stop_flags[(lemma, pos)]), int(pos == "PROPN")])

        shutil.move(str(path), str(DONE_DIR / path.name))
        print(f"  -> {doc_csv.relative_to(ROOT)} written; moved source to books/done/")
        processed += 1

    return processed


def ing_root_candidates(lemma_lower: str):
    """Candidate verb roots for a NOUN lemma ending in '-ing' (gerund).

    English gerund formation reverses one of: doubled final consonant
    (running -> run), silent-e drop (writing -> write), or plain suffixing
    (talking -> talk). We generate all plausible roots; the caller only
    accepts one if it is independently attested as a VERB lemma elsewhere
    in the corpus, so unrelated nouns like "morning" or "ceiling" (whose
    stripped roots are not real verbs) are left untouched.
    """
    base = lemma_lower[:-3]
    candidates = [base, base + "e"]
    if len(base) >= 3 and base[-1] == base[-2] and base[-1] not in "aeiou":
        candidates.append(base[:-1])
    return candidates


def normalize_for_wordlist(lemma: str, pos: str, verb_lemma_set: set) -> str:
    norm = lemma.lower()
    if pos == "NOUN" and norm.endswith("ing") and len(norm) > 6:
        for candidate in ing_root_candidates(norm):
            if candidate in verb_lemma_set:
                return candidate
    return norm


def aggregate_outputs():
    doc_files = sorted(PER_DOC_DIR.glob("*.csv"))
    if not doc_files:
        print("No per-document stats found yet; nothing to aggregate.")
        return

    per_doc_rows = []
    for doc_file in doc_files:
        with doc_file.open(newline="", encoding="utf-8") as f:
            per_doc_rows.append(list(csv.DictReader(f)))

    total_counts = Counter()
    doc_frequency = Counter()
    flags = {}  # (lemma, pos) -> (is_stopword, is_proper_noun)

    for rows in per_doc_rows:
        for row in rows:
            key = (row["lemma"], row["pos"])
            count = int(row["count"])
            total_counts[key] += count
            doc_frequency[key] += 1
            flags[key] = (int(row["is_stopword"]), int(row["is_proper_noun"]))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with OVERALL_STATS_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["rank", "lemma", "pos", "total_count", "doc_frequency", "is_stopword", "is_proper_noun"])
        for rank, (key, count) in enumerate(total_counts.most_common(), start=1):
            lemma, pos = key
            is_stop, is_propn = flags[key]
            writer.writerow([rank, lemma, pos, count, doc_frequency[key], is_stop, is_propn])

    # Build the vocabulary wordlist: merge case + POS variants of the same
    # word (e.g. walk/NOUN + walk/VERB, or talking/NOUN -> talk once it is
    # confirmed as a gerund of the attested verb "talk") into a single row,
    # since a language learner only needs one entry per word family.
    verb_lemma_set = {lemma for (lemma, pos) in total_counts if pos == "VERB"}

    merged_total = Counter()
    merged_doc_freq = Counter()
    merged_pos_variants = {}

    for rows in per_doc_rows:
        doc_lemmas_seen = set()
        for row in rows:
            if int(row["is_stopword"]) or int(row["is_proper_noun"]):
                continue
            pos = row["pos"]
            norm = normalize_for_wordlist(row["lemma"], pos, verb_lemma_set)
            count = int(row["count"])
            merged_total[norm] += count
            merged_pos_variants.setdefault(norm, set()).add(pos)
            doc_lemmas_seen.add(norm)
        for norm in doc_lemmas_seen:
            merged_doc_freq[norm] += 1

    with WORDLIST_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["rank", "lemma", "pos_variants", "total_count", "doc_frequency"])
        for rank, (lemma, count) in enumerate(merged_total.most_common(), start=1):
            pos_variants = ";".join(sorted(merged_pos_variants[lemma]))
            writer.writerow([rank, lemma, pos_variants, count, merged_doc_freq[lemma]])

    print(f"Aggregated {len(doc_files)} document(s) -> {OVERALL_STATS_PATH.relative_to(ROOT)}, {WORDLIST_PATH.relative_to(ROOT)}")


def main():
    nlp = load_nlp()
    process_new_documents(nlp)
    aggregate_outputs()


if __name__ == "__main__":
    sys.exit(main())
