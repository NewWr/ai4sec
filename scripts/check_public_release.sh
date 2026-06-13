#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

warn() {
  echo "WARN: $*" >&2
}

echo "Checking working tree tracked files..."

tracked_private="$(
  git ls-files \
    '.env' '.env.*' '**/.env' '**/.env.*' \
    'docker-data/**' '.local-dev-data/**' 'backend/data/**' 'dify-rag/**' \
    'ai4sec-dify-sync/.env' 'ai4sec-dify-sync/state/*.db' 'ai4sec-dify-sync/state/*.db-*' \
    'ai4sec-dify-sync/state/*.pid' 'ai4sec-dify-sync/logs/**' \
    '*.db' '*.sqlite' '*.sqlite3' '*.pdf' '*.zip' '*.pem' '*.key' '*.p12' '*.pfx' '*.crt' '*.cer' \
    ':!:*.env.example' ':!:**/*.env.example' 2>/dev/null || true
)"
if [[ -n "$tracked_private" ]]; then
  echo "$tracked_private" >&2
  fail "private/runtime files are tracked by Git"
fi

echo "Checking untracked private files are ignored..."
for path in .env docker-data/app.db .local-dev-data/app.db backend/data/app.db dify-rag/docker/.env ai4sec-dify-sync/.env ai4sec-dify-sync/state/dify_syncs.db ai4sec-dify-sync/logs/sync.log; do
  if [[ -e "$path" ]] && ! git check-ignore -q "$path"; then
    fail "$path exists but is not ignored"
  fi
done

echo "Scanning tracked text for high-risk secret literals..."
if git grep -n -I -E \
  '(sk-[A-Za-z0-9_-]{20,}|Bearer[[:space:]]+[A-Za-z0-9._~+/=-]{20,}|(api[_-]?key|secret|token|password)[[:space:]]*[:=][[:space:]]*["'\''][A-Za-z0-9._~+/=-]{20,}["'\''])' \
  -- \
  ':!*.lock' \
  ':!frontend/package-lock.json' \
  ':!.env.example' \
  ':!docs/PUBLIC_RELEASE.md' \
  ':!scripts/check_public_release.sh'; then
  fail "possible secret literal found in tracked source"
fi

echo "Checking known private deployment examples..."
if git grep -n -I -E 'DIFY_API_BASE=http://([0-9]+\.[0-9]+\.[0-9]+\.[0-9]+)' -- \
  ':!.env.example' \
  ':!docs/PUBLIC_RELEASE.md' \
  | rg -v 'DIFY_API_BASE=http://(127\.|0\.0\.0\.0|localhost)' ; then
  fail "private deployment address found"
fi
if git grep -n -I -E 'DIFY_DEFAULT_DATASET_ID=[0-9a-fA-F-]{36}' -- \
  ':!.env.example' \
  ':!docs/PUBLIC_RELEASE.md'; then
  fail "private dataset id found"
fi

echo "Checking Git history for previously committed private artifacts..."
history_hits="$(
  git log --all --name-only --pretty=format: \
    | sort -u \
    | rg '(^|/)(\.env($|\.)|docker-data|\.local-dev-data|backend/data|ai4sec-dify-sync/state|ai4sec-dify-sync/logs|app\.db|rank_cache\.(sqlite3|sqlite|db)|original\.pdf)|\.(pdf|sqlite|sqlite3|db|pem|key|p12|pfx|crt|cer)$|(^|/)paper_search/\.env$|(^|/)papersdownload/\.env$' \
    | rg -v '(^|/)\.env\.(example|template)$' \
    || true
)"
if [[ -n "$history_hits" ]]; then
  total="$(printf "%s\n" "$history_hits" | sed '/^$/d' | wc -l | tr -d ' ')"
  printf "%s\n" "$history_hits" | sed -n '1,80p' >&2
  if [[ "$total" -gt 80 ]]; then
    echo "... ${total} total history path hit(s); showing first 80." >&2
  fi
  fail "Git history contains private artifacts; publish from a clean-history export or rewrite history first"
fi

echo "Checking current large tracked files..."
large_tracked="$(
  git ls-files -z | xargs -0 -r du -k 2>/dev/null | awk '$1 > 2048 {print $2 " (" $1 " KiB)"}'
)"
if [[ -n "$large_tracked" ]]; then
  warn "large tracked files:"
  echo "$large_tracked" >&2
fi

echo "Public release check passed."
