# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "spacy>=3.7",
#     "click>=8.0",
#     "wordfreq>=3.1",
#     "en-core-web-sm @ https://github.com/explosion/spacy-models/releases/download/en_core_web_sm-3.8.0/en_core_web_sm-3.8.0-py3-none-any.whl",
# ]
# ///
import argparse
import json
import re
import sys
from collections import Counter

import spacy
from wordfreq import zipf_frequency

ENTITY_LABELS = {"PERSON", "ORG", "GPE", "LOC", "FAC", "PRODUCT", "WORK_OF_ART", "EVENT"}
URLISH = re.compile(r"https?://|www\.|\.(com|org|net|de|fr|ru|jp)(\b|/)", re.I)
OPERATORISH = re.compile(r"(^|\s)[#@-]\w|\w:(\"|\w)|[+&|]\w|\"")
HAS_ALPHA = re.compile(r"[A-Za-z]")
TOKEN = re.compile(r"[A-Za-z][A-Za-z'\-]+")


def latin_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(c.isascii() for c in letters) / len(letters)


def entity_rarity(entity: str) -> float | None:
    tokens = TOKEN.findall(entity)
    if not tokens:
        return None
    return min(zipf_frequency(t.lower(), "en") for t in tokens)


def iter_queries(paths: list[str]) -> dict[str, dict]:
    queries: dict[str, dict] = {}
    for path in paths:
        with open(path) as f:
            for line in f:
                doc = json.loads(line)
                query = (doc.get("url_query") or "").strip()
                key = query.lower()
                if not query or key in queries:
                    continue
                provider = doc.get("provider")
                if isinstance(provider, dict):
                    provider = provider.get("domain") or provider.get("id")
                capture = doc.get("capture")
                timestamp = capture.get("timestamp") if isinstance(capture, dict) else doc.get("timestamp")
                queries[key] = {"query": query, "provider": provider, "timestamp": timestamp}
    return queries


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("serps", nargs="+", help="serps JSONL exported by `aql serps export`")
    parser.add_argument("--max-zipf", type=float, default=3.0, help="rarest token of the entity must be below this zipf frequency")
    parser.add_argument("--min-query-len", type=int, default=6)
    parser.add_argument("--max-query-len", type=int, default=120)
    parser.add_argument("--top", type=int, default=100)
    args = parser.parse_args()

    queries = iter_queries(args.serps)
    print(f"unique queries: {len(queries)}", file=sys.stderr)

    nlp = spacy.load("en_core_web_sm", disable=["lemmatizer"])

    candidates = []
    stats = Counter()
    texts = []
    for q in queries.values():
        query = q["query"]
        if not (args.min_query_len <= len(query) <= args.max_query_len):
            stats["len"] += 1
            continue
        if URLISH.search(query) or not HAS_ALPHA.search(query):
            stats["urlish_or_no_alpha"] += 1
            continue
        if OPERATORISH.search(query):
            stats["operator_syntax"] += 1
            continue
        if latin_ratio(query) < 0.9:
            stats["non_latin"] += 1
            continue
        texts.append(q)

    raw_docs = nlp.pipe([t["query"] for t in texts], batch_size=256)
    titled_docs = nlp.pipe([t["query"].title() for t in texts], batch_size=256)
    for q, doc, titled in zip(texts, raw_docs, titled_docs):
        ents = [e for e in doc.ents if e.label_ in ENTITY_LABELS]
        if not ents:
            ents = [e for e in titled.ents if e.label_ in ENTITY_LABELS]
        if not ents:
            stats["no_entity"] += 1
            continue
        scored = [(e.text, e.label_, entity_rarity(e.text)) for e in ents]
        scored = [
            (t, l, r)
            for t, l, r in scored
            if r is not None and not re.search(r"\d|\w\.\w|[/_=]", t)
        ]
        if not scored:
            stats["no_scorable_entity"] += 1
            continue
        text, label, rarity = min(scored, key=lambda x: x[2])
        if rarity >= args.max_zipf:
            stats["common_entity"] += 1
            continue
        candidates.append({**q, "entity": text, "entity_label": label, "rarity_zipf": rarity})

    print(f"filtered: {dict(stats)}", file=sys.stderr)
    print(f"rare-entity candidates: {len(candidates)}", file=sys.stderr)
    candidates.sort(key=lambda c: c["rarity_zipf"])
    for c in candidates[: args.top]:
        print(json.dumps(c, ensure_ascii=False))


if __name__ == "__main__":
    main()
