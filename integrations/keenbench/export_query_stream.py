import argparse
import json

from elasticsearch.helpers import scan

from archive_query_log.config import Config


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="aql_queries.jsonl")
    args = parser.parse_args()

    config = Config()
    queries: dict[str, dict] = {}
    hits = scan(
        config.es.client,
        index=config.es.index_serps,
        query={"query": {"match_all": {}}},
        _source=["url_query", "provider.domain", "capture.url", "capture.timestamp"],
    )
    n_serps = 0
    for hit in hits:
        n_serps += 1
        src = hit["_source"]
        query = (src.get("url_query") or "").strip()
        if not query:
            continue
        key = query.lower()
        provider = src.get("provider", {}).get("domain")
        capture = src.get("capture", {})
        timestamp = capture.get("timestamp")
        row = queries.get(key)
        if row is None:
            queries[key] = {
                "query": query,
                "providers": {provider} if provider else set(),
                "first_seen": timestamp,
                "last_seen": timestamp,
                "n_serps": 1,
                "sample_url": capture.get("url"),
            }
            continue
        row["n_serps"] += 1
        if provider:
            row["providers"].add(provider)
        if timestamp:
            if row["first_seen"] is None or timestamp < row["first_seen"]:
                row["first_seen"] = timestamp
            if row["last_seen"] is None or timestamp > row["last_seen"]:
                row["last_seen"] = timestamp

    with open(args.output, "w") as f:
        for row in queries.values():
            row["providers"] = sorted(row["providers"])
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"{n_serps} serps -> {len(queries)} unique queries -> {args.output}")


if __name__ == "__main__":
    main()
