#!/bin/bash
set -e
cd "$(dirname "$0")/../.."
HF_DATASET=${HF_DATASET:-keenable-ai/keenbench-results}
ES_SCHEME=http .venv/bin/python integrations/keenbench/export_query_stream.py --output aql_queries.jsonl
uvx --from huggingface_hub hf upload "$HF_DATASET" aql_queries.jsonl aql/queries.jsonl \
  --repo-type dataset --commit-message "aql: query stream refresh"
