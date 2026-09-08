#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR/frontend"
npm ci
npm run build

# Vercel serves public/ from its CDN. Keep dist/ for Flask's index/SPA fallback
# and leave Render's build.sh and Procfile unchanged.
mkdir -p "$PROJECT_DIR/public"
cp -R "$PROJECT_DIR/frontend/dist/." "$PROJECT_DIR/public/"
