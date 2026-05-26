#!/bin/bash
# OTS-AHA Development Quick Start
# Usage: bash scripts/start.sh

echo "🚀 OTS Approval Helping Agent — Starting services..."

# 1. Start infrastructure
echo ""
echo "📦 Step 1/3: Starting PostgreSQL + MinIO..."
docker-compose -f "$(dirname "$0")/../docker-compose.yml" up -d
sleep 3
echo "   ✅ Infrastructure ready"

# 2. Activate venv & start FastAPI
echo ""
echo "🐍 Step 2/3: Starting FastAPI server..."
source "$(dirname "$0")/../venv/bin/activate"
cd "$(dirname "$0")/.."
PYTHONPATH=. uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 &
UVICORN_PID=$!
sleep 2
echo "   ✅ FastAPI running at http://localhost:8000"
echo "   📖 Swagger UI: http://localhost:8000/docs"

# 3. Seed mock data (optional)
echo ""
echo "📊 Step 3/3: Seeding mock data..."
PYTHONPATH=. python3 scripts/generate_mock_data.py 2>/dev/null && echo "   ✅ Mock data seeded" || echo "   ⏭️  Mock data script not ready yet"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🟢 All services running!"
echo "   API:       http://localhost:8000"
echo "   Swagger:   http://localhost:8000/docs"
echo "   MinIO:     http://localhost:9001 (minioadmin/minioadmin)"
echo "   PostgreSQL: localhost:5432 (ots_user/ots2026/ots)"
echo ""
echo "Press Ctrl+C to stop"
wait $UVICORN_PID
