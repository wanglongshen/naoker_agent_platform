#!/usr/bin/env bash
set -euo pipefail
DEPLOY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_DIR="$DEPLOY_ROOT/code/deploy"
ENV_FILE="$COMPOSE_DIR/.env"
docker compose -f "$COMPOSE_DIR/docker-compose.yml" --env-file "$ENV_FILE" ps
echo "---- 内存 ----"
docker stats --no-stream --format "table {{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}" | head -10
echo "---- 健康 ----"
BE_URL=$(grep '^NEXT_PUBLIC_API_BASE_URL=' "$ENV_FILE" | cut -d= -f2)
curl -sf "${BE_URL}/health" && echo "后端 OK" || echo "后端异常"
