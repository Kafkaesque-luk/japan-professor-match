#!/usr/bin/env bash
# Restore the bundled professor vectors into Qdrant via the seed one-shot.
# Equivalent to: docker compose run --rm seed
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose run --rm seed
