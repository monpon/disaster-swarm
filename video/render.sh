#!/usr/bin/env bash
# Incremental render; see render.mjs. Only parts whose inputs changed are re-rendered.
set -euo pipefail
cd "$(dirname "$0")"
exec node render.mjs "$@"
