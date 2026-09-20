#!/usr/bin/env bash
set -euo pipefail
DEPLOY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_DIR="$DEPLOY_ROOT/code/deploy"
ENV_FILE="$COMPOSE_DIR/.env"
SVC="${1:-}"
if [ -z "$SVC" ]; then
  echo "用法: bash logs.sh <backend|worker|web-renderer|frontend|postgres|redis>"
  docker compose -f "$COMPOSE_DIR/docker-compose.yml" --env-file "$ENV_FILE" ps
  exit 0
fi
docker compose -f "$COMPOSE_DIR/docker-compose.yml" --env-file "$ENV_FILE" logs -f --tail 200 "$SVC"
