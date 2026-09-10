#!/usr/bin/env bash
# Local KernelCI instance init: generate the runtime config that `./run.sh
# setup` deliberately leaves out. Idempotent; safe to re-run.
#
#   bash scripts/local-instance-init.sh [--force] [--quiet] [--skip-token]
#
# What it does (each step reports "using existing" vs "generated"):
#   1. kernelci-api/.env  <- from kernelci-api/env.sample
#   2. SSH keypair        <- kernelci-pipeline/data/ssh/id_rsa_tarball (private)
#                            + kernelci-api/docker/ssh/user-data/authorized_keys (public)
#   3. KCI_API_TOKEN in kernelci-pipeline/.env <- HTTP login (POST /latest/user/login),
#      falling back to in-container minting when the login route is absent; + verify
#
# Flags:
#   --force       regenerate the SSH keys AND overwrite kernelci-api/.env
#                 (a new SECRET_KEY invalidates every existing JWT)
#   --quiet       suppress the per-step narration, keep errors
#   --skip-token  skip the API-token step (offline / test runs)
#
# Secrets never land in git-tracked files: kernelci-api/ and
# kernelci-pipeline/ are gitignored in this repo.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
API_DIR="$ROOT/kernelci-api"
PIPE_DIR="$ROOT/kernelci-pipeline"
# Overridable deployment identity, matching scripts/run-local-stack.sh: the
# compose project decides which containers and data volumes this deployment
# owns, so a second isolated stack on the same machine keeps its own database.
PROJECT="${KCI_COMPOSE_PROJECT:-kcirv}"
API_PORT="${KCI_API_PORT:-8001}"
API_URL="${KCI_API_URL:-http://127.0.0.1:$API_PORT}"
export API_HOST_PORT="$API_PORT"

API_ENV="$API_DIR/.env"
PIPE_ENV="$PIPE_DIR/.env"
PRIV_KEY="$PIPE_DIR/data/ssh/id_rsa_tarball"
PUB_KEY="$API_DIR/docker/ssh/user-data/authorized_keys"

FORCE=0
QUIET=0
SKIP_TOKEN=0

die()  { echo "X $*" >&2; exit 1; }
ok()   { echo "OK $*"; }
info() { [ "$QUIET" -eq 1 ] || echo "-> $*"; }

usage() {
  sed -n '2,21p' "$0"
  exit 0
}

while [ $# -gt 0 ]; do
  case "$1" in
    --force)      FORCE=1 ;;
    --quiet)      QUIET=1 ;;
    --skip-token) SKIP_TOKEN=1 ;;
    -h|--help)    usage ;;
    *) die "unknown argument: $1" ;;
  esac
  shift
done

# set_env <file> <key> <value>  Replace an existing KEY= line, or append one.
# Values used here are restricted to [A-Za-z0-9@._/:+-] so sed is safe.
set_env() {
  local file="$1" key="$2" val="$3"
  if [ -f "$file" ] && grep -q "^${key}=" "$file"; then
    sed -i "s|^${key}=.*|${key}=${val}|" "$file"
  else
    printf '%s=%s\n' "$key" "$val" >> "$file"
  fi
}

# api_up  True (exit 0) when the API answers on /latest/ (any HTTP status
# means the server is up; matches scripts/run-local-stack.sh's readiness probe).
api_up() { curl -s -m 3 -o /dev/null "$API_URL/latest/"; }

# whoami_code <token>  HTTP status of /latest/whoami with the bearer token.
# 200 = the token authenticates; anything else = invalid/expired/missing.
whoami_code() { curl -s -m 15 -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $1" "$API_URL/latest/whoami"; }

# mint_token_in_container  Print a fresh JWT for the existing admin (from the
# DB) by running the API's own JWT strategy INSIDE the api container, so the
# SECRET_KEY comes from the .env the API itself loaded. Used as a fallback when
# a kernelci-api build has no registered login route. Prints the token on
# stdout; exits non-zero (message on stderr) when there is no user yet or the
# container is unreachable.
mint_token_in_container() {
  (cd "$API_DIR" && docker compose -p "$PROJECT" exec -T api python3 - <<'PY'
import asyncio, sys
from api.main import initialize_beanie, User, auth_backend

async def main():
    await initialize_beanie()
    users = await User.find_all().to_list()
    user = next((u for u in users if getattr(u, "is_superuser", False)), None) \
        or (users[0] if users else None)
    if user is None:
        print("no user in DB yet - the API must finish its first startup "
              "(it creates the initial admin) before a token can be minted",
              file=sys.stderr)
        sys.exit(1)
    print(await auth_backend.get_strategy().write_token(user))

asyncio.run(main())
PY
)
}

# ---------------------------------------------------------------- 1) .env --
if [ ! -d "$API_DIR" ]; then
  echo "  !! skip kernelci-api/.env: kernelci-api/ not cloned yet (run ./run.sh setup)"
elif [ -f "$API_ENV" ] && [ "$FORCE" -ne 1 ]; then
  ok "kernelci-api/.env: using existing (pass --force to regenerate; a new SECRET_KEY invalidates every JWT)"
else
  [ -f "$API_DIR/env.sample" ] || die "missing $API_DIR/env.sample"
  if [ "$FORCE" -eq 1 ] && [ -f "$API_ENV" ]; then
    info "regenerating kernelci-api/.env (--force): a new SECRET_KEY invalidates every existing JWT"
  fi
  cp "$API_DIR/env.sample" "$API_ENV"
  set_env "$API_ENV" SECRET_KEY "$(openssl rand -hex 32)"
  set_env "$API_ENV" MONGO_SERVICE "mongodb://db:27017"
  set_env "$API_ENV" PUBLIC_BASE_URL "$API_URL"
  set_env "$API_ENV" KCI_INITIAL_ADMIN_USERNAME "admin"
  set_env "$API_ENV" KCI_INITIAL_PASSWORD "$(openssl rand -hex 16)"
  set_env "$API_ENV" KCI_INITIAL_ADMIN_EMAIL "admin@kernelci.local"
  chmod 600 "$API_ENV"
  ok "kernelci-api/.env: generated (SECRET_KEY, MONGO_SERVICE, PUBLIC_BASE_URL, initial admin username/password/email)"
fi

# ------------------------------------------------------------- 2) SSH keys --
if [ ! -d "$PIPE_DIR" ] || [ ! -d "$API_DIR" ]; then
  echo "  !! skip SSH keypair: kernelci-pipeline/ or kernelci-api/ not cloned yet (run ./run.sh setup)"
elif [ -f "$PRIV_KEY" ] && [ -f "$PUB_KEY" ] && [ "$FORCE" -ne 1 ]; then
  ok "SSH keypair: using existing ($PRIV_KEY + $PUB_KEY)"
else
  [ "$FORCE" -eq 1 ] && info "regenerating SSH keypair (--force): restart the ssh/storage stack to pick it up"
  TMPDIR_KEY="$(mktemp -d)"
  ssh-keygen -t rsa -b 4096 -N "" -f "$TMPDIR_KEY/id_rsa_tarball" -q -C "kernelci-riscv-local-init" \
    || { rm -rf "$TMPDIR_KEY"; die "ssh-keygen failed"; }
  mkdir -p "$(dirname "$PRIV_KEY")" "$(dirname "$PUB_KEY")"
  cp "$TMPDIR_KEY/id_rsa_tarball" "$PRIV_KEY"     && chmod 600 "$PRIV_KEY"     || die "failed to install private key"
  cp "$TMPDIR_KEY/id_rsa_tarball.pub" "$PUB_KEY"  && chmod 644 "$PUB_KEY"      || die "failed to install public key"
  rm -rf "$TMPDIR_KEY"
  ok "SSH keypair: generated (private 600 -> $PRIV_KEY; public 644 -> $PUB_KEY)"
fi

# ----------------------------------------------------------- 3) API token --
if [ "$SKIP_TOKEN" -eq 1 ]; then
  info "skip API token (--skip-token)"
elif [ ! -d "$API_DIR" ]; then
  echo "  !! skip KCI_API_TOKEN: kernelci-api/ not cloned yet (run ./run.sh setup)"
elif [ ! -f "$API_ENV" ]; then
  echo "  !! skip KCI_API_TOKEN: no kernelci-api/.env (generate it first)"
else
  ADMIN_USER="$(grep '^KCI_INITIAL_ADMIN_USERNAME=' "$API_ENV" | head -1 | cut -d= -f2-)"
  ADMIN_PASSWORD="$(grep '^KCI_INITIAL_PASSWORD=' "$API_ENV" | head -1 | cut -d= -f2-)"
  [ -n "$ADMIN_USER" ] || ADMIN_USER=admin
  [ -n "$ADMIN_PASSWORD" ] || die "no KCI_INITIAL_PASSWORD in $API_ENV"

  if api_up; then
    ok "API already up ($API_URL)"
  else
    info "starting: docker compose -p "$PROJECT" up -d api db redis storage ssh"
    (cd "$API_DIR" && docker compose -p "$PROJECT" up -d api db redis storage ssh >/dev/null) \
      || die "docker compose failed (run it manually from $API_DIR to see the error)"
    ready=0
    for _ in $(seq 1 40); do
      api_up && { ready=1; break; }
      sleep 2
    done
    [ "$ready" -eq 1 ] || die "API not ready at $API_URL after 80s"
    ok "API stack started"
  fi

  # Reuse an already-valid token (idempotent: a re-run must not churn a
  # working token). A placeholder or expired token fails whoami -> replaced.
  TOKEN="$(grep '^KCI_API_TOKEN=' "$PIPE_ENV" 2>/dev/null | head -1 | cut -d= -f2-)"
  if [ -n "$TOKEN" ] && [ "$(whoami_code "$TOKEN")" = "200" ]; then
    ok "KCI_API_TOKEN: using existing (already valid in $PIPE_ENV)"
  else
    [ -n "$TOKEN" ] && info "existing KCI_API_TOKEN is invalid; obtaining a fresh one"
    TOKEN=""

    # Try the official login endpoint first; when this kernelci-api build has no
    # registered login route (upstream versioned-app regression -> 404/405),
    # fall back to minting the token inside the api container with its own
    # JWT strategy.
    LOGIN_BODY="$(mktemp)"
    LOGIN_CODE="$(curl -s -m 20 -o "$LOGIN_BODY" -w '%{http_code}' \
      -X POST "$API_URL/latest/user/login" \
      -H 'Content-Type: application/x-www-form-urlencoded' \
      --data-urlencode "username=$ADMIN_USER" \
      --data-urlencode "password=$ADMIN_PASSWORD")"
    TOKEN="$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("access_token",""))' "$LOGIN_BODY" 2>/dev/null)"
    rm -f "$LOGIN_BODY"

    if [ -z "$TOKEN" ]; then
      if [ "$LOGIN_CODE" = "405" ] || [ "$LOGIN_CODE" = "404" ]; then
        info "login endpoint not registered in this kernelci-api build; minting the token with the API's own JWT strategy instead"
      else
        info "login did not return a token (HTTP $LOGIN_CODE); falling back to in-container minting"
      fi
      if ! MINT_OUT="$(mint_token_in_container)"; then
        die "token minting failed: check the api container is running (docker compose -p $PROJECT ps) and that a user already exists in the DB"
      fi
      # Keep only the JWT-shaped line: docker compose is free to print warnings
      # on stdout, and a polluted token would only surface as a confusing
      # whoami failure further down.
      TOKEN="$(printf '%s\n' "$MINT_OUT" | grep -E '^eyJ[A-Za-z0-9._-]+$' | tail -1)"
      [ -n "$TOKEN" ] || die "minting produced no JWT (docker compose output: $(printf '%s' "$MINT_OUT" | head -c 200))"
    fi
    [ -n "$TOKEN" ] || die "could not obtain a token"

    # Verify the token on an authenticated endpoint before writing it.
    WHO_CODE="$(whoami_code "$TOKEN")"
    [ "$WHO_CODE" = "200" ] || die "token did not authenticate (/latest/whoami returned HTTP $WHO_CODE)"

    mkdir -p "$PIPE_DIR"
    set_env "$PIPE_ENV" KCI_API_TOKEN "$TOKEN"
    ok "KCI_API_TOKEN: written to $PIPE_ENV (verified via /latest/whoami HTTP 200)"
  fi
fi

[ "$QUIET" -eq 1 ] || echo
[ "$QUIET" -eq 1 ] || echo "next step: bash $ROOT/scripts/run-local-stack.sh"
