#!/usr/bin/env bash
set -euo pipefail
DEPLOY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_DIR="$DEPLOY_ROOT/code/deploy"
ENV_FILE="$COMPOSE_DIR/.env"
SVC="${1:-}"
ARGS=(-f "$COMPOSE_DIR/docker-compose.yml" --env-file "$ENV_FILE")
if [ -n "$SVC" ]; then
  docker compose "${ARGS[@]}" restart "$SVC"
else
  docker compose "${ARGS[@]}" restart
fi
echo "重启完成"
