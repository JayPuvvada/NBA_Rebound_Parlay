#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

python3 -m pip install --disable-pip-version-check -r "$PROJECT_DIR/requirements.txt"

cd "$PROJECT_DIR/frontend"
npm ci
npm run build
