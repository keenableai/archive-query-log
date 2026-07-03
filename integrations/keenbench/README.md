# Keenbench query stream

Runs the AQL crawling pipeline on a single machine against the live Wayback
Machine CDX API to produce a continuous stream of real user queries. No
access to the gated AQL-22 corpus is needed; the queries are re-mined from
public CDX data.

The output artifact is `aql/queries.jsonl` in the Hugging Face dataset
`keenable-ai/keenbench-results`: one line per unique query with metadata
(`query`, `providers`, `first_seen`, `last_seen`, `n_serps`, `sample_url`).
Downstream filtering (rare-entity selection, language filtering) lives in
the keenbench repo and consumes that artifact.

## Setup

```
docker run -d --name aql-es -p 9200:9200 \
  -e discovery.type=single-node -e xpack.security.enabled=false \
  -e "ES_JAVA_OPTS=-Xms1g -Xmx1g" \
  docker.elastic.co/elasticsearch/elasticsearch:7.17.28

uv venv --python 3.13 .venv
uv pip install -e .
integrations/keenbench/apply_patches.sh
```

The patches fix two upstream dependency bugs that break local crawling:

- `web-archive-api` fails to parse the CDX `showNumPages` probe when
  `output=json` is set, silently falling back to fetching the entire capture
  list as one unbounded response.
- `elasticsearch-pydantic` leaks `_score` from search hits into bulk update
  actions, which Elasticsearch rejects.

## Crawl

```
export ES_SCHEME=http
.venv/bin/aql init --config.es.scheme http
.venv/bin/python integrations/keenbench/bootstrap_local.py
.venv/bin/aql sources build --no-skip-archives --no-skip-providers --config.es.scheme http
.venv/bin/aql captures fetch --size 9 --config.es.scheme http
```

`bootstrap_local.py` registers the Wayback Machine plus nine major engines as
providers. It indexes the providers with the exact provider UUIDs that the
hardcoded parsers in `archive_query_log/parsers/url_query.py` expect, because
`aql providers add`/`import` assign random UUIDs that never match any parser
on a fresh deployment. Only query-dense SERP prefixes (`/search?` and
similar) are used; `/?` prefixes are avoided because CDX canonicalizes them
to whole-domain scans dominated by homepage captures.

`captures fetch` streams captures indefinitely for large engines; stop it
whenever enough captures have accumulated and rerun it later to continue.

## Query stream artifact

```
integrations/keenbench/parse_and_export.sh 10
integrations/keenbench/publish_query_stream.sh
```

`parse_and_export.sh` parses queries from capture URLs into the serps
index. `publish_query_stream.sh` aggregates the serps index into
`aql_queries.jsonl` (one line per unique query, case-insensitive dedup,
provider/timestamp/serp-count metadata) and uploads it to
`aql/queries.jsonl` in the `keenable-ai/keenbench-results` dataset
(override with `HF_DATASET`). Rerunning after more crawling refreshes the
artifact in place.
