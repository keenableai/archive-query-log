#!/bin/bash
set -e
cd "$(dirname "$0")/../.."
SITE_PACKAGES=$(.venv/bin/python -c "import sysconfig; print(sysconfig.get_paths()['purelib'])")
for p in integrations/keenbench/patches/*.patch; do
  patch -p1 -d "$SITE_PACKAGES" --forward < "$p" || true
done
