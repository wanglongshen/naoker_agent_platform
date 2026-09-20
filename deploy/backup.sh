#!/usr/bin/env bash
set -euo pipefail
DEPLOY_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE_DIR="$DEPLOY_ROOT/code/deploy"
ENV_FILE="$COMPOSE_DIR/.env"
STAMP=$(date +%Y%m%d_%H%M%S)
BK="$DEPLOY_ROOT/backups/$STAMP"
mkdir -p "$BK"

echo "== 1/2 数据库导出 =="
docker compose -f "$COMPOSE_DIR/docker-compose.yml" --env-file "$ENV_FILE" up -d postgres
docker exec agent-postgres pg_dump -U agent -Fc -d rbac -f /tmp/rbac.dump
docker cp agent-postgres:/tmp/rbac.dump "$BK/rbac.dump"
docker exec agent-postgres rm -f /tmp/rbac.dump
[ -s "$BK/rbac.dump" ] || { echo "dump 为空"; exit 1; }

echo "== 2/2 文件库打包 =="
FILES_VOL=$(docker volume ls -q | grep 'agent.*files' | head -1 || true)
[ -n "$FILES_VOL" ] || { echo "未找到文件库卷"; exit 1; }
docker run --rm -v "$FILES_VOL":/data -v "$BK":/backup alpine:3.20 tar czf /backup/var.tar.gz -C /data .

echo "备份完成: $BK"
ls -lh "$BK"
