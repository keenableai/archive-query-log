# Keenbench query stream

Runs the AQL crawling pipeline on a single machine against the live Wayback
Machine CDX API to produce a continuous stream of real user queries, then
samples queries containing rare named entities from it. No access to the
gated AQL-22 corpus is needed; the queries are re-mined from public CDX data.

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

## Query stream

```
integrations/keenbench/parse_and_export.sh 10
```

Parses queries from capture URLs and exports a random sample to
`exported_serps.jsonl` (one SERP per line, query in `url_query`).

## Rare-entity sampling

```
uv run integrations/keenbench/sample_rare_entities.py exported_serps.jsonl \
  --max-zipf 3.0 --top 1000 > rare_entity_queries.jsonl
```

Dedups queries, drops URL-like/operator-syntax/non-Latin/filename queries,
extracts entities with spaCy (with a title-cased retry for lowercase
queries), and keeps queries whose rarest entity token has a wordfreq zipf
frequency below the threshold, ranked rarest first. Residual noise (typos,
non-English Latin-script queries) is expected to be filtered downstream by
an LLM judge or a knowledge-base existence check.
