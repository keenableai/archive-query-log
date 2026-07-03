#!/bin/bash
set -e
cd "$(dirname "$0")/../.."
ROUNDS=${1:-10}
for i in $(seq 1 "$ROUNDS"); do
  .venv/bin/aql serps parse url-query --size 10000 --config.es.scheme http --config.es.host localhost
done
.venv/bin/aql serps export --sample-size 100000 --output-path exported_serps.jsonl --config.es.scheme http --config.es.host localhost
wc -l exported_serps.jsonl
