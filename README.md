# frequency-dictionary
Make frequency dictionary from documents.

## What it does
Extracts every word from English `.pdf`, `.txt`, and `.epub` source documents in
`books/`, lemmatizes verbs/nouns/adjectives to their base form (e.g. `going` /
`went` → `go`, `dogs` → `dog`, `better` → `good`), and counts occurrences.
Articles/prepositions (stopwords) and proper nouns are **kept** in the full
statistics but tagged so they can be filtered out when building a vocabulary
list for another language.

## Setup
```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python -m spacy download en_core_web_sm
```

## Usage
1. Drop `.pdf` / `.txt` / `.epub` files into `books/`.
2. Run:
   ```powershell
   .\.venv\Scripts\python scripts\build_frequency.py
   ```
3. Processed source files are moved to `books/done/` (so re-running only
   picks up newly added files).

## Outputs
- `output/per_document/<book>.csv` — per-document word counts
  (`lemma, pos, count, is_stopword, is_proper_noun`).
- `output/overall_stats.csv` — full corpus-wide statistics, one row per
  `(lemma, pos)` pair exactly as spaCy tagged it (all words, including
  stopwords/proper nouns, tagged for filtering). Useful for auditing/
  debugging, since it shows every POS variant a word was seen as.
- `output/wordlist_overall.csv` — the base word list for building vocabulary
  lists in other languages: stopwords and proper nouns removed, and
  **merged across POS/case so each word family is a single row**
  (`lemma, pos_variants, total_count, doc_frequency`), ranked by frequency.

### Why merging is needed (and its limits)
spaCy lemmatizes per-token based on its own POS guess, so the same word can
end up on two different rows in `overall_stats.csv` — e.g. `walk` tagged
`NOUN` in "a long walk" vs `VERB` in "they walk". Gerunds are worse: a
gerund used nominally (e.g. "The **talking** stopped.") is correctly tagged
`NOUN` by spaCy, and NOUN lemmatization only handles plurals, not "-ing"
stripping, so `talking` stays `talking` instead of collapsing to `talk`.
`wordlist_overall.csv` fixes this by:
1. Merging rows for the same lemma across all POS tags (case-insensitive).
2. For any `NOUN` lemma ending in `-ing`, checking whether stripping the
   gerund suffix (handling doubled consonants like `running`→`run` and
   silent-e like `writing`→`write`) yields a verb root that is
   independently attested as a `VERB` lemma elsewhere in the corpus — if so,
   it merges into that verb (`talking`→`talk`, `understanding`→`understand`).
   This avoids misfiring on genuine standalone nouns like `morning` or
   `ceiling`, whose stripped roots (`morn`, `ceil`) aren't real verbs.

**Known remaining limitations** (left as-is, no general fix without a
hand-curated dictionary):
- Rare cases where spaCy's own lemmatizer fails to reduce an inflected form
  (e.g. an isolated `worlds` that doesn't collapse to `world`) stay
  ungrouped — typically a handful of occurrences, negligible for ranking.
- Nouns that are spelled identically to an unrelated verb's irregular past
  tense (e.g. `thought` the noun vs. `think`→`thought`→`think`) are **not**
  merged, since there's no general rule to tell "inflected form of an
  irregular verb" apart from "genuinely distinct noun" without a curated
  irregular-verb lookup table.

## Architecture

```
books/*.pdf,.txt,.epub
        │
        ▼
scripts/extract_text.py        (pdfplumber / ebooklib+BeautifulSoup / plain read)
        │  raw text
        ▼
scripts/build_frequency.py
        │  1) split into whitespace-safe chunks
        │  2) nlp.pipe(chunks)  ──► spaCy pipeline (en_core_web_sm)
        │        tagger + lemmatizer only (parser/ner disabled for speed)
        │  3) count (lemma, pos) pairs, tag is_stopword / is_proper_noun
        ▼
output/per_document/<book>.csv          (one row per lemma+pos, per book)
        │  aggregate across all per-document CSVs
        ▼
output/overall_stats.csv                (full stats, tags kept for filtering)
output/wordlist_overall.csv             (stopwords/proper nouns removed)

books/<processed file>  ──moved──►  books/done/
```

**Key points:**
- **Everything runs locally, offline.** spaCy is a library, not an API — there
  is no network call at processing time. `nlp = spacy.load("en_core_web_sm")`
  loads model weights already downloaded to disk (`.venv/Lib/site-packages/`),
  and `nlp(text)` runs the tagger/lemmatizer as local CPU computation. No
  document content ever leaves the machine.
- **Internet is only needed once**, to `pip install` dependencies and
  `spacy download en_core_web_sm` (fetches the model package from PyPI).
- **Idempotent/incremental by design**: only files sitting directly in
  `books/` are processed; each run moves what it just processed into
  `books/done/`, and `output/overall_stats.csv` /
  `output/wordlist_overall.csv` are fully regenerated from *all*
  `output/per_document/*.csv` files every run — so adding new books later
  and re-running merges them into the existing statistics without
  double-counting.

## POS (Part-of-Speech) tags

spaCy tags every word with a [Universal POS tag](https://universaldependencies.org/u/pos/).
These are the values you'll see in the `pos` column of the CSV outputs:

| Tag | Meaning | Example |
|---|---|---|
| `NOUN` | 일반명사 (common noun) | word, elephant, house |
| `PROPN` | 고유명사 (proper noun) — excluded from `wordlist_overall.csv` | Winston, London, Orwell |
| `VERB` | 동사 (verb) | use, think, shoot |
| `AUX` | 조동사 (auxiliary verb) — treated as stopword | be, have, do, will |
| `ADJ` | 형용사 (adjective) | good, bad, little |
| `ADV` | 부사 (adverb) | away, often, quickly |
| `DET` | 한정사/관사 (determiner) — treated as stopword | the, a, this |
| `ADP` | 전치사/후치사 (adposition) — treated as stopword | in, of, with, like |
| `PRON` | 대명사 (pronoun) — treated as stopword | he, it, this |
| `CCONJ` | 등위접속사 (coordinating conjunction) — treated as stopword | and, but, or |
| `SCONJ` | 종속접속사 (subordinating conjunction) — treated as stopword | that, because, if |
| `PART` | 불변화사 (particle) — treated as stopword | to (infinitive marker), not |
| `NUM` | 숫자 (numeral) | one, two, 2024 |
| `INTJ` | 감탄사 (interjection) | oh, well |

Rows where `is_stopword=1` or `is_proper_noun=1` are removed when building
`output/wordlist_overall.csv`. `is_stopword` reflects spaCy's built-in
stopword list (mostly `DET`/`ADP`/`PRON`/`AUX`/`CCONJ`/`SCONJ`/`PART`), and
`is_proper_noun` is simply `pos == "PROPN"`.
