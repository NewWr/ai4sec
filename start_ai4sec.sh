#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$ROOT_DIR"
DIFY_DIR="$PROJECT_DIR/dify-rag/docker"
SYNC_DIR="$ROOT_DIR/ai4sec-dify-sync"
PATCH_DIR="$ROOT_DIR/.ai4sec-docker-patch"
MAIN_SERVICES=(dify-proxy backend frontend)
SYNC_SERVICES=(ai4sec-dify-sync)
DEV_PORT=3003
NO_CACHE="${AI4SEC_NO_CACHE:-0}"
DIFY_PROFILE_LIST="${AI4SEC_DIFY_PROFILES:-postgresql,weaviate,collaboration}"
DIFY_PUBLIC_URL="${AI4SEC_DIFY_PUBLIC_URL:-http://127.0.0.1:3080}"

cd "$PROJECT_DIR"

if command -v docker-compose >/dev/null 2>&1; then
  BASE_COMPOSE=(docker-compose)
elif docker compose version >/dev/null 2>&1; then
  BASE_COMPOSE=(docker compose)
else
  echo "docker-compose or docker compose is required." >&2
  exit 1
fi

DOCKER=(docker)
COMPOSE=("${BASE_COMPOSE[@]}")
if ! docker ps >/dev/null 2>&1; then
  if sudo -n docker ps >/dev/null 2>&1; then
    DOCKER=(sudo -n docker)
    COMPOSE=(sudo -n "${BASE_COMPOSE[@]}")
  else
    echo "Cannot access Docker. Run with sudo or enable passwordless sudo/docker group access." >&2
    exit 1
  fi
fi
MAIN_COMPOSE=("${COMPOSE[@]}" --profile dify)
DIFY_PROFILE_FLAGS=()
IFS=',' read -ra DIFY_PROFILES <<< "$DIFY_PROFILE_LIST"
for profile in "${DIFY_PROFILES[@]}"; do
  profile="${profile//[[:space:]]/}"
  if [[ -n "$profile" ]]; then
    DIFY_PROFILE_FLAGS+=(--profile "$profile")
  fi
done
DIFY_COMPOSE=("${COMPOSE[@]}" "${DIFY_PROFILE_FLAGS[@]}")

wait_for_http() {
  local url="$1"
  local name="$2"
  local timeout="${3:-120}"
  local start
  start="$(date +%s)"
  while true; do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "$name is ready: $url"
      return 0
    fi
    if (( "$(date +%s)" - start >= timeout )); then
      echo "Timed out waiting for $name: $url" >&2
      return 1
    fi
    sleep 2
  done
}

build_patch_images() {
  echo "Building patch images from existing dependency layers..."
  cd "$PROJECT_DIR/frontend"
  BACKEND_URL="${BACKEND_URL:-http://host.docker.internal:8001}" \
    NEXT_PUBLIC_BACKEND_URL="${NEXT_PUBLIC_BACKEND_URL:-http://localhost:8001}" \
    npm run build

  cd "$PROJECT_DIR"
  "${DOCKER[@]}" build -f backend/Dockerfile.patch -t ai4sec-backend:latest .
  "${DOCKER[@]}" build -f dify-proxy/Dockerfile.patch -t ai4sec-dify-proxy:latest dify-proxy

  rm -rf "$PATCH_DIR/frontend"
  mkdir -p "$PATCH_DIR/frontend/.next"
  cp "$PROJECT_DIR/frontend/Dockerfile.patch" "$PATCH_DIR/frontend/Dockerfile"
  cp -a "$PROJECT_DIR/frontend/.next/standalone" "$PATCH_DIR/frontend/.next/standalone"
  cp -a "$PROJECT_DIR/frontend/.next/static" "$PATCH_DIR/frontend/.next/static"
  cp -a "$PROJECT_DIR/frontend/public" "$PATCH_DIR/frontend/public"
  "${DOCKER[@]}" build -t ai4sec-frontend:latest "$PATCH_DIR/frontend"
}

build_sync_patch_image() {
  echo "Building ai4sec-dify-sync patch image from existing dependency layer..."
  cd "$SYNC_DIR"
  "${DOCKER[@]}" build -f Dockerfile.patch -t ai4sec-dify-sync-ai4sec-dify-sync:latest .
}

stop_local_dev_server() {
  local pids
  pids="$(pgrep -f "next dev .*--port ${DEV_PORT}" || true)"
  if [[ -n "$pids" ]]; then
    echo "Stopping local Next.js dev server on port ${DEV_PORT}: $pids"
    kill $pids || true
    sleep 2
    pids="$(pgrep -f "next dev .*--port ${DEV_PORT}" || true)"
    if [[ -n "$pids" ]]; then
      kill -9 $pids || true
    fi
  fi
}

start_dify_stack() {
  if [[ ! -f "$DIFY_DIR/docker-compose.yaml" ]]; then
    echo "Dify compose file not found: $DIFY_DIR/docker-compose.yaml" >&2
    exit 1
  fi

  echo "Starting Dify knowledge-base stack..."
  echo "  compose:  $DIFY_DIR/docker-compose.yaml"
  echo "  profiles: ${DIFY_PROFILE_LIST}"
  cd "$DIFY_DIR"
  "${DIFY_COMPOSE[@]}" up -d --remove-orphans
}

echo "Stopping test/dev processes..."
stop_local_dev_server

start_dify_stack

echo "Stopping existing AI4Sec compose services..."
cd "$PROJECT_DIR"
"${MAIN_COMPOSE[@]}" down --remove-orphans
"${DOCKER[@]}" rm -f scholar-frontend scholar-backend ai4sec-dify-proxy >/dev/null 2>&1 || true

if [[ -f "$SYNC_DIR/docker-compose.yml" ]]; then
  echo "Stopping existing ai4sec-dify-sync compose service..."
  cd "$SYNC_DIR"
  "${COMPOSE[@]}" down --remove-orphans
  "${DOCKER[@]}" rm -f ai4sec-dify-sync >/dev/null 2>&1 || true
fi

BUILD_FLAGS=()
if [[ "$NO_CACHE" == "1" ]]; then
  BUILD_FLAGS+=(--no-cache)
fi

echo "Building AI4Sec images..."
cd "$PROJECT_DIR"
if ! "${MAIN_COMPOSE[@]}" build "${BUILD_FLAGS[@]}" "${MAIN_SERVICES[@]}"; then
  echo "Build failed. Checking for existing local AI4Sec images before startup fallback..." >&2
  "${DOCKER[@]}" image inspect ai4sec-backend:latest ai4sec-frontend:latest ai4sec-dify-proxy:latest >/dev/null
  build_patch_images
fi

echo "Starting AI4Sec formal services..."
"${MAIN_COMPOSE[@]}" up -d --force-recreate "${MAIN_SERVICES[@]}"

if [[ -f "$SYNC_DIR/docker-compose.yml" ]]; then
  echo "Rebuilding and starting ai4sec-dify-sync..."
  cd "$SYNC_DIR"
  if ! "${COMPOSE[@]}" build "${BUILD_FLAGS[@]}" "${SYNC_SERVICES[@]}"; then
    echo "ai4sec-dify-sync build failed. Checking for existing local image before startup fallback..." >&2
    "${DOCKER[@]}" image inspect ai4sec-dify-sync-ai4sec-dify-sync:latest >/dev/null
    build_sync_patch_image
  fi
  "${COMPOSE[@]}" up -d --force-recreate "${SYNC_SERVICES[@]}"
fi

echo "Waiting for services..."
wait_for_http "${DIFY_PUBLIC_URL%/}/console/api/setup" "dify web/api" 240
wait_for_http "http://127.0.0.1:8001/api/models" "backend" 180
wait_for_http "http://127.0.0.1:3001/" "frontend" 180
wait_for_http "http://127.0.0.1:3002/health" "dify proxy" 120
wait_for_http "http://127.0.0.1:3002/api/datasets" "dify proxy dataset API" 180
wait_for_http "http://127.0.0.1:3001/synthesis" "synthesis page" 180
wait_for_http "http://127.0.0.1:3001/writing" "writing page" 180

echo
echo "Running containers:"
"${DOCKER[@]}" ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' \
  | grep -E '^(NAMES|scholar-|ai4sec-|docker[-_](api|api_websocket|worker|worker_beat|web|nginx|db_postgres|redis|weaviate|sandbox|plugin_daemon|ssrf_proxy))'

echo
echo "AI4Sec formal instance is running:"
echo "  frontend:   http://localhost:3001"
echo "  backend:    http://localhost:8001"
echo "  dify proxy: http://localhost:3002"
echo "  dify web:   ${DIFY_PUBLIC_URL}"
