#!/usr/bin/env bash
# Network preflight + proxy handling, shared by run.sh and run-local-stack.sh.
#
# Why this exists: the previous code unconditionally unset http_proxy/
# https_proxy with a comment saying "the local proxy is dead;
# direct access works".  That is one machine's temporary state baked into a
# public repository.  Someone behind a working proxy (a lab, a corporate
# egress proxy, a mirror-only network) would have it silently removed, and
# their downloads would break instead of the author's.
#
# So: probe with the configuration exactly as the user set it, and only fall
# back to a direct connection when the proxy is demonstrably broken - saying
# so out loud, and letting the user force either mode:
#
#   (default)            honour the environment and git proxy configuration
#   KCI_BYPASS_PROXY=1   ignore the proxy configuration for this run
#
# Nothing here changes the environment of the caller's shell: bypassing is
# applied per command, so a run cannot leak a modified environment into the
# next one.
set -uo pipefail

KCI_PROBE_URL="${KCI_PROBE_URL:-https://files.kernelci.org/}"
KCI_PROBE_TIMEOUT="${KCI_PROBE_TIMEOUT:-10}"

kci_bypass_requested() {
  [ "${KCI_BYPASS_PROXY:-0}" = "1" ]
}

_kci_unset_proxy_env() {
  env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY \
    -u all_proxy -u ALL_PROXY "$@"
}

# curl honouring the user's proxy configuration (or the bypass switch).
kci_curl() {
  if kci_bypass_requested; then
    curl --noproxy '*' "$@"
  else
    curl "$@"
  fi
}

# curl over a direct connection, whatever the environment says.
kci_curl_direct() {
  _kci_unset_proxy_env curl --noproxy '*' "$@"
}

# Run a command with the proxy environment removed when a bypass is asked for.
# Used for helpers that read the proxy variables themselves (python-requests,
# tuxrun, git).
kci_run() {
  if kci_bypass_requested; then
    _kci_unset_proxy_env "$@"
  else
    "$@"
  fi
}

# git honouring the bypass switch.  lowSpeedLimit/lowSpeedTime turn "hangs
# forever behind a dead proxy" into "fails after 20s of no progress", which is
# what makes the retry loops below useful.
kci_git() {
  local -a stall=(-c http.lowSpeedLimit=1000 -c http.lowSpeedTime=20)
  if kci_bypass_requested; then
    _kci_unset_proxy_env git -c http.proxy= -c https.proxy= "${stall[@]}" "$@"
  else
    git "${stall[@]}" "$@"
  fi
}

kci_net_ok() {
  kci_curl -s -o /dev/null -m "$KCI_PROBE_TIMEOUT" -I "$KCI_PROBE_URL"
}

kci_net_ok_direct() {
  kci_curl_direct -s -o /dev/null -m "$KCI_PROBE_TIMEOUT" -I "$KCI_PROBE_URL"
}

# Probe one proxy URL with the probe endpoint.  Returns 0 when it can carry the
# request.  Used to name the *failing* entries instead of listing every setting
# a user has: the list used to imply a working proxy was broken and never
# tested git's own proxy - which is the one that actually kills `git clone`
# (it is what `git` uses, regardless of what the http_proxy environment says).
kci_proxy_works() {
  [ -n "${1:-}" ] || return 1
  curl -x "$1" -s -o /dev/null -m "$KCI_PROBE_TIMEOUT" -I "$KCI_PROBE_URL"
}

kci_proxy_is_ssh() {
  case "${1:-}" in
    socks5://*|socks5h://*|socks4://*) return 0 ;;
    *) return 1 ;;
  esac
}

# Where the proxy configuration currently comes from (for error messages).
# Only settings that FAILED the probe are printed as broken; the rest are
# listed as working, because "these are your proxy settings" was read as
# "these are the problem" even when the proxy in question answered fine.
kci_proxy_report() {
  local found=0 name value git_proxy probed
  for name in http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY; do
    value="${!name:-}"
    [ -n "$value" ] || continue
    found=1
    if kci_proxy_is_ssh "$value"; then
      echo "      $name=$value (not probed: socks proxy)"
    elif kci_proxy_works "$value"; then
      echo "      $name=$value (reachable)"
    else
      echo "      $name=$value  <-- BROKEN (did not answer $KCI_PROBE_URL)"
    fi
  done
  git_proxy="$(git config --get http.proxy 2>/dev/null || true)"
  if [ -n "$git_proxy" ]; then
    found=1
    probed="$(git config --get https.proxy 2>/dev/null || true)"
    if kci_proxy_is_ssh "$git_proxy"; then
      echo "      git config http.proxy=$git_proxy (not probed: socks proxy)"
    elif kci_proxy_works "$git_proxy"; then
      echo "      git config http.proxy=$git_proxy (reachable)"
    else
      echo "      git config http.proxy=$git_proxy  <-- BROKEN (this is the one git clone uses)"
    fi
    [ -n "$probed" ] && [ "$probed" != "$git_proxy" ] && \
      echo "      git config https.proxy=$probed"
  fi
  [ "$found" = 0 ] && echo "      (no proxy configured)"
  return 0
}

# Probe and report.  Returns 0 when the network is usable, 1 with actionable
# advice when it is not.  Callers decide whether that is fatal.
kci_net_preflight() {
  local what="${1:-network}"
  if kci_net_ok; then
    if kci_bypass_requested; then
      echo "OK  $what reachable (KCI_BYPASS_PROXY=1: proxy ignored)"
    else
      echo "OK  $what reachable (proxy configuration as-is)"
    fi
    return 0
  fi
  if ! kci_bypass_requested && kci_net_ok_direct; then
    echo "X   $what unreachable through your proxy, but reachable directly."
    echo "    The proxy looks broken.  Either fix/remove the settings below,"
    echo "    or re-run with KCI_BYPASS_PROXY=1 to ignore them:"
    kci_proxy_report
    return 1
  fi
  echo "X   $what unreachable: $KCI_PROBE_URL (${KCI_PROBE_TIMEOUT}s timeout)."
  echo "    Proxy settings in effect:"
  kci_proxy_report
  echo "    If your proxy is the problem, re-run with KCI_BYPASS_PROXY=1."
  return 1
}

# Clone a git URL with retries, falling back to a direct connection when the
# configured proxy is dead.  This is the single most common failure on a fresh
# machine: a stale proxy entry makes `git clone` hang with no output at all.
kci_git_clone() {
  local url="$1" dest="$2" attempt
  for attempt in 1 2 3; do
    if kci_git clone --depth 1 "$url" "$dest"; then
      return 0
    fi
    rm -rf "$dest"
    if [ "$attempt" = 1 ] && ! kci_bypass_requested; then
      echo "  clone failed with the current proxy settings; retrying directly"
      if KCI_BYPASS_PROXY=1 kci_git clone --depth 1 "$url" "$dest"; then
        return 0
      fi
      rm -rf "$dest"
    fi
    if [ "$attempt" -lt 3 ]; then
      echo "  clone attempt $attempt/3 failed; retrying in 3s"
      sleep 3
    fi
  done
  return 1
}
