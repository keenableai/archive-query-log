#!/bin/bash
cd "$(dirname "$0")/../.."
while true; do
  for i in $(seq 1 30); do
    .venv/bin/aql serps parse url-query --size 10000 --config.es.scheme http --config.es.host localhost >/dev/null 2>&1 || true
  done
  integrations/keenbench/publish_query_stream.sh || true
  sleep 300
done
