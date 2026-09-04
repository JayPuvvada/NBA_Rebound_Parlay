#!/usr/bin/env bash
# Exit on error
set -o errexit

# 1. Install Python dependencies
# Temporarily clear proxy variables so pip can reach PyPI without a 407 authentication error
HTTP_PROXY="" HTTPS_PROXY="" http_proxy="" https_proxy="" pip3 install -r requirements.txt

# 2. Build the React Frontend
cd frontend
npm install
npm run build
cd ..
