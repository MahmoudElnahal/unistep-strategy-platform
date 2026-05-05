#!/bin/bash
# UNISTEP Platform v9 — Run script
set -e

cd "$(dirname "$0")"

if [ -z "$OPENAI_API_KEY" ]; then
    if [ -f .env ]; then
        echo "📋 Loading .env..."
        export $(grep -v '^#' .env | xargs)
    else
        echo "⚠️  OPENAI_API_KEY not set!"
        echo "   اعمل: export OPENAI_API_KEY=sk-..."
        echo "   أو حط الـ key في ملف .env"
        exit 1
    fi
fi

echo "🚀 Starting UNISTEP Platform v9..."
echo "   Browser: http://localhost:8000"
echo "   Wizard:  http://localhost:8000/wizard"
echo "   API:     http://localhost:8000/docs"
echo ""

PYTHONPATH=. uvicorn api.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --reload \
    --reload-dir core \
    --reload-dir steps \
    --reload-dir api
