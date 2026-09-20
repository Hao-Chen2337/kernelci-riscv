#!/usr/bin/env bash
# Minimal reproduction for the 3 upstream kernelci-api defects.
#
# All three are reproduced against the *stock* image
# (kernelci/staging-kernelci:api) with no help from this repository's code.
# Two of them (1 and 3) need nothing but a running container; (2) needs a
# database with no user in it, which is why the clean-instance recipe below
# uses its own compose project and therefore its own volume.
#
# Usage:  bash deploy/repro-api-bugs.sh            # 1 and 3 (running stack)
#         bash deploy/repro-api-bugs.sh --bug2-clean   # also (2), on a fresh volume
set -uo pipefail

API_URL="${KCI_API_URL:-http://127.0.0.1:8001}"
CONTAINER="${KCI_API_CONTAINER:-kernelci-api}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

pass() { echo "  REPRODUCED  $*"; }
ok()   { echo "  (not reproduced) $*"; }
head_() { echo; echo "=== $* ==="; }

head_ "BUG 1: the versioned app drops the auth router -> no login route"
CODE="$(curl -s -m 10 -o /dev/null -w '%{http_code}' -X POST \
  "$API_URL/latest/user/login" \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  --data-urlencode 'username=admin' --data-urlencode 'password=x')"
echo "  POST /latest/user/login -> HTTP $CODE   (405 = route absent; 200/400/401 = fixed)"
if [ "$CODE" = "405" ]; then pass "login returns 405"; else ok "login returned $CODE"; fi

echo "  -- route table (the empty lists are the bug) --"
docker exec "$CONTAINER" python3 -c "
from api.main import app, versioned_app
f = lambda a: [getattr(r,'path','') for r in a.routes if 'login' in getattr(r,'path','')]
print('     app (built)          :', f(app))
print('     versioned_app (served):', f(versioned_app))
" 2>&1 | tail -2

head_ "BUG 3: passlib 1.7.4 + bcrypt 5.0.0 -> password hashing raises"
OUT="$(docker exec "$CONTAINER" python3 -c "
from api.auth import Authentication
try:
    Authentication.get_password_hash('test-password')
    print('OK')
except Exception as e:
    print('RAISED', type(e).__name__, str(e)[:70])
" 2>&1 | tail -1)"
echo "  Authentication.get_password_hash('test-password') -> $OUT"
case "$OUT" in
  RAISED*) pass "hashing raises (misleading 72-byte error)";;
  *)       ok "hashing worked: $OUT";;
esac
docker exec "$CONTAINER" python3 -c "
import bcrypt
h = bcrypt.hashpw(b'test-password', bcrypt.gensalt())
print('  control: bcrypt', bcrypt.__version__, 'works; hash prefix', h[:7].decode())
" 2>&1 | tail -1

head_ "BUG 2: the served app never bootstraps the first admin"
docker exec "$CONTAINER" python3 -c "
from api.main import versioned_app
names = [getattr(h, '__name__', repr(h)) for h in versioned_app.router.on_startup]
print('  versioned_app.on_startup =', names)
print('  ensure_initial_admin_user registered:', 'ensure_initial_admin_user' in names)
" 2>&1 | tail -2

echo "  -- users actually in this database --"
docker exec "$CONTAINER" python3 -c "
import asyncio
from api.main import initialize_beanie, User
async def m():
    await initialize_beanie()
    print('     users:', len(await User.find_all().to_list()))
asyncio.run(m())" 2>&1 | tail -1
echo "  NOTE: this instance already has an admin (setup created one), so the"
echo "        empty-database case needs the clean-instance run below."

if [ "${1:-}" = "--bug2-clean" ]; then
  head_ "BUG 2 on a genuinely fresh database (own compose project + volume)"
  # kernelci-api's compose file hardcodes container_name (kernelci-api,
  # kernelci-api-db, ...), so a second project can only start if nothing else
  # is using those names.  WITHOUT this guard the failure is silent and the
  # check below then queries the OLD container - producing a confident and
  # completely wrong answer.  (Seen live: "users: 1" on an allegedly fresh DB.)
  if docker ps --format '{{.Names}}' | grep -qx "$CONTAINER"; then
    echo "  SKIP: container '$CONTAINER' is already running."
    echo "        This project cannot coexist with another stack (hardcoded"
    echo "        container names).  Either stop it first:"
    echo "            deploy/stop.sh"
    echo "        or run this mode with the stack down, then restart it with"
    echo "            deploy/stack.sh"
    exit 2
  fi
  PROJ="kcirv-repro$$"
  echo "  project=$PROJ (its own volume, so its own empty database)"
  if ! ( cd "$ROOT/kernelci-api" && docker compose -p "$PROJ" up -d api db ); then
    echo "  FAIL: compose could not start the clean project (see the output above)"
    ( cd "$ROOT/kernelci-api" && docker compose -p "$PROJ" down -v >/dev/null 2>&1 )
    exit 1
  fi
  for _ in $(seq 1 40); do curl -s -m 2 -o /dev/null "$API_URL/latest/" && break; sleep 2; done
  sleep 5   # let the startup handlers finish

  # Prove we are looking at the NEW container, not the old one.
  CID="$(docker inspect -f '{{.Id}}' "$CONTAINER" 2>/dev/null)"
  PROJ_OF="$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' "$CONTAINER" 2>/dev/null)"
  echo "  container project label: ${PROJ_OF:-<none>} (expect $PROJ)"
  VOL="$(docker volume ls --format '{{.Name}}' | grep -x "${PROJ}_mongodata" || true)"
  echo "  fresh volume: ${VOL:-<missing>}"
  if [ "$PROJ_OF" != "$PROJ" ]; then
    echo "  FAIL: '$CONTAINER' does not belong to project $PROJ - refusing to report."
    ( cd "$ROOT/kernelci-api" && docker compose -p "$PROJ" down -v >/dev/null 2>&1 )
    exit 1
  fi

  COUNT="$(docker exec "$CONTAINER" python3 -c "
import asyncio
from api.main import initialize_beanie, User
async def m():
    await initialize_beanie(); print(len(await User.find_all().to_list()))
asyncio.run(m())" 2>/dev/null | tail -1)"
  echo "  users in the fresh database: $COUNT"
  case "$COUNT" in
    0) pass "no admin was bootstrapped although the API came up clean";;
    "") echo "  could not read the user count (container gone?)";;
    *) ok "database has $COUNT user(s): bug not reproduced";;
  esac
  ( cd "$ROOT/kernelci-api" && docker compose -p "$PROJ" down -v >/dev/null 2>&1 )
  echo "  cleaned up (container ${CID:0:12} + volume removed)"
fi
