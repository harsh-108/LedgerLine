#!/usr/bin/env bash
cd "$(dirname "$0")/backend" && uvicorn app.main:app --reload --port 8000
