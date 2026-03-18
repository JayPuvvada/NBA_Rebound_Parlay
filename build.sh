#!/usr/bin/env bash
# Exit on error
set -o errexit

# 1. Install Python dependencies
pip3 install -r requirements.txt

# 2. Build the React Frontend
cd frontend
npm install
npm run build
cd ..
