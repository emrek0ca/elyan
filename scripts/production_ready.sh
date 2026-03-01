#!/bin/bash
# scripts/production_ready.sh
# ─────────────────────────────────────────────────────────────────────────────
# Elyan Production Readiness Check
# ─────────────────────────────────────────────────────────────────────────────

echo "🚀 Elyan Production Readiness Check starting..."

# 1. Environment Check
echo "🔍 Checking Environment..."
if [ ! -f ".env" ]; then
    echo "❌ Error: .env file missing!"
    exit 1
fi

# 2. Dependency Check
echo "🔍 Checking Dependencies..."
python3 -c "import aiohttp, rich, click, httpx" 2>/dev/null
if [ $? -ne 0 ]; then
    echo "❌ Error: Missing core dependencies. Run: pip install -r requirements.txt"
    exit 1
fi

# 3. Model Provider Check
echo "🔍 Checking API Keys..."
grep -E "OPENAI_API_KEY|ANTHROPIC_API_KEY|GOOGLE_API_KEY" .env > /dev/null
if [ $? -ne 0 ]; then
    echo "⚠️  Warning: No major cloud provider API keys found in .env"
fi

# 4. Local Service Check
echo "🔍 Checking Ollama..."
curl -s http://localhost:11434/api/tags > /dev/null
if [ $? -ne 0 ]; then
    echo "⚠️  Ollama is not running. Local-only tasks will fail."
else
    echo "✅ Ollama is ONLINE"
fi

# 5. Run Regression Suite
echo "🔍 Running E2E Regression Checks..."
python3 tests/regression_runner.py
if [ $? -ne 0 ]; then
    echo "❌ Error: Regression tests failed!"
    exit 1
fi

echo "✅ Elyan is READY for production deployment."
