# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "tokenizers>=0.15",
#     "fasttext-predict>=0.9",
#     "wordfreq>=3.1",
# ]
# ///
import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

import fasttext
from tokenizers import BertWordPieceTokenizer
from wordfreq import zipf_frequency

SUBWORD_THRESHOLD = 5
UNK = "[UNK]"
VOCAB_URL = "https://huggingface.co/bert-base-uncased/resolve/main/vocab.txt"
LID_URL = "https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.ftz"
FOREIGN_CONFIDENT = 0.7
ENGLISH_CONFIDENT = 0.5
ENGLISH_ZIPF = 3.0
ENGLISH_WORD_FRACTION = 0.6

NON_LATIN_RE = re.compile("[^\u0020-\u024f\u1e00-\u1eff\u2000-\u206f\u20a0-\u20cf]")
SEARCH_OPERATOR_RE = re.compile(
    r"\b(?:site|inurl|intitle|intext|filetype|cache|link|allinurl|allintitle|allintext):\S+",
    re.IGNORECASE,
)
QUOTE_CHARS = "\"'`‘’“”«»"
HAS_QUOTE_RE = re.compile(f"[{re.escape(QUOTE_CHARS)}]")
PUNCT_RE = re.compile(r"[^\w\s]")
VIN_CANDIDATE_RE = re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b", re.IGNORECASE)
HEX_HASH_RE = re.compile(r"\b[0-9a-fA-F]{24,}\b")
HEX_ETH_ADDRESS_RE = re.compile(r"\b0[xX][0-9a-fA-F]{40}\b")
CRYPTO_BASE58_RE = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b")
URLISH_RE = re.compile(r"https?://|www\.|\.(com|org|net|io|de|fr|ru|jp)(\b|/)", re.I)


def _contains_vin(query: str) -> bool:
    for match in VIN_CANDIDATE_RE.finditer(query):
        token = match.group(0)
        if any(c.isalpha() for c in token) and any(c.isdigit() for c in token):
            return True
    return False


def _contains_hex_hash(query: str) -> bool:
    for match in HEX_HASH_RE.finditer(query):
        if any(c in "abcdefABCDEF" for c in match.group(0)):
            return True
    if HEX_ETH_ADDRESS_RE.search(query):
        return True
    return False


def _contains_crypto_address(query: str) -> bool:
    for match in CRYPTO_BASE58_RE.finditer(query):
        token = match.group(0)
        if (
            any(c.isdigit() for c in token)
            and any(c.isupper() for c in token)
            and any(c.islower() for c in token)
        ):
            return True
    return False


def is_eligible(query: str) -> bool:
    if NON_LATIN_RE.search(query):
        return False
    if SEARCH_OPERATOR_RE.search(query):
        return False
    if HAS_QUOTE_RE.search(query):
        return False
    if _contains_vin(query):
        return False
    if _contains_hex_hash(query):
        return False
    if _contains_crypto_address(query):
        return False
    return True


def words_for(query: str) -> list[str]:
    cleaned = PUNCT_RE.sub(" ", query.lower())
    return [w for w in cleaned.split() if w]


def hard_words_for(query: str, tokenize) -> list[dict]:
    out = []
    for w in words_for(query):
        pieces = tokenize(w)
        if not pieces:
            continue
        if UNK in pieces or len(pieces) >= SUBWORD_THRESHOLD:
            out.append({"word": w, "subwords": list(pieces)})
    return out


def load_lid(model_path: str | None):
    if model_path is None:
        cached = Path.home() / ".cache" / "lid.176.ftz"
        if not cached.exists():
            cached.parent.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(LID_URL, cached)
        model_path = str(cached)
    model = fasttext.load_model(model_path)

    def lid(text: str) -> tuple[str, float]:
        labels, probs = model.predict(text.lower().replace("\n", " "), k=1)
        return labels[0].removeprefix("__label__"), probs[0]

    return lid


def is_english(query: str, context_words: list[str], lid) -> bool:
    lang_full, p_full = lid(query)
    context = " ".join(context_words)
    lang_ctx, p_ctx = lid(context) if context else (lang_full, p_full)
    if lang_full != "en" and p_full >= FOREIGN_CONFIDENT:
        return False
    if lang_ctx != "en" and p_ctx >= FOREIGN_CONFIDENT:
        return False
    if lang_ctx == "en" and p_ctx >= ENGLISH_CONFIDENT:
        return True
    letter_words = [w for w in context_words if w.isalpha()]
    if not letter_words:
        return True
    common = sum(zipf_frequency(w, "en") >= ENGLISH_ZIPF for w in letter_words)
    return common / len(letter_words) >= ENGLISH_WORD_FRACTION


def length_bucket(n_words: int) -> str:
    if n_words <= 2:
        return "short"
    if n_words <= 5:
        return "medium"
    return "long"


def load_tokenizer(vocab_path: str | None):
    if vocab_path is None:
        cached = Path.home() / ".cache" / "bert_base_uncased_vocab.txt"
        if not cached.exists():
            cached.parent.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(VOCAB_URL, cached)
        vocab_path = str(cached)
    tokenizer = BertWordPieceTokenizer(vocab_path, lowercase=True)
    return lambda text: list(tokenizer.encode(text, add_special_tokens=False).tokens)


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
    parser.add_argument("--vocab", default=None, help="bert-base-uncased vocab.txt (downloaded and cached if omitted)")
    parser.add_argument("--lid-model", default=None, help="fasttext lid.176 model (downloaded and cached if omitted)")
    parser.add_argument("--any-language", action="store_true")
    parser.add_argument("--min-words", type=int, default=3)
    parser.add_argument("--max-query-len", type=int, default=200)
    parser.add_argument("--per-bucket", type=int, default=0, help="cap output per length bucket (0 = no cap)")
    args = parser.parse_args()

    tokenize = load_tokenizer(args.vocab)
    lid = None if args.any_language else load_lid(args.lid_model)
    queries = iter_queries(args.serps)
    print(f"unique queries: {len(queries)}", file=sys.stderr)

    stats: dict[str, int] = {}
    buckets: dict[str, list[dict]] = {"medium": [], "long": [], "short": []}
    for q in queries.values():
        query = q["query"]
        if len(query) > args.max_query_len:
            stats["too_long"] = stats.get("too_long", 0) + 1
            continue
        if URLISH_RE.search(query):
            stats["urlish"] = stats.get("urlish", 0) + 1
            continue
        words = words_for(query)
        if len(words) < args.min_words:
            stats["too_few_words"] = stats.get("too_few_words", 0) + 1
            continue
        if not is_eligible(query):
            stats["ineligible"] = stats.get("ineligible", 0) + 1
            continue
        hard = hard_words_for(query, tokenize)
        if not hard:
            stats["no_rare_word"] = stats.get("no_rare_word", 0) + 1
            continue
        if lid is not None:
            hard_set = {h["word"] for h in hard}
            context_words = [w for w in words if w not in hard_set]
            if not is_english(query, context_words, lid):
                stats["non_english"] = stats.get("non_english", 0) + 1
                continue
        bucket = length_bucket(len(words))
        buckets[bucket].append(
            {
                **q,
                "length_bucket": bucket,
                "n_words": len(words),
                "hard_words": hard,
                "max_pieces": max(
                    len(h["subwords"]) if UNK not in h["subwords"] else 99 for h in hard
                ),
            }
        )

    print(f"filtered: {stats}", file=sys.stderr)
    for bucket in ("medium", "long", "short"):
        rows = sorted(buckets[bucket], key=lambda c: -c["max_pieces"])
        if args.per_bucket:
            rows = rows[: args.per_bucket]
        print(f"{bucket}: {len(buckets[bucket])} candidates, emitting {len(rows)}", file=sys.stderr)
        for c in rows:
            print(json.dumps(c, ensure_ascii=False))


if __name__ == "__main__":
    main()
