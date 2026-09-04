#!/usr/bin/env bash
# atomsh installer:  curl -fsSL https://atomgpt.org/install | bash
#
# Installs the atomsh CLI in an isolated environment and puts the launcher
# on your PATH. Nothing is installed system-wide; no sudo.
#
# Environment:
#   ATOMSH_SOURCE    package spec to install (default: atomsh)
#   ATOMSH_BIN_DIR   where to link the launcher (default: ~/.local/bin)
#   ATOMSH_HOME      venv location for the pip fallback (default: ~/.atomsh)
set -euo pipefail

SOURCE="${ATOMSH_SOURCE:-atomsh}"
BIN_DIR="${ATOMSH_BIN_DIR:-$HOME/.local/bin}"
ATOMSH_HOME="${ATOMSH_HOME:-$HOME/.atomsh}"

say()  { printf '%s\n' "$*"; }
warn() { printf '\033[33m%s\033[0m\n' "$*" >&2; }
die()  { printf '\033[31merror:\033[0m %s\n' "$*" >&2; exit 1; }

have() { command -v "$1" >/dev/null 2>&1; }

# ── strategy 1: uv ───────────────────────────────────────────────────────────
# Preferred: uv manages its own isolated tool environment and will fetch a
# suitable Python if the system one is unusable.
install_with_uv() {
  local log
  log="$(mktemp)"
  say "Installing with uv…"
  # --reinstall matters when SOURCE is a local checkout: without it uv can
  # serve a cached build for an unchanged version number.
  if ! uv tool install --force --reinstall "$SOURCE" >"$log" 2>&1; then
    cat "$log" >&2
    rm -f "$log"
    return 1
  fi
  rm -f "$log"
  have atomsh || [ -x "$HOME/.local/bin/atomsh" ] || return 1
  return 0
}

# ── strategy 2: venv + pip ───────────────────────────────────────────────────
# Works on a normal Python install. Note that `python -m venv` can succeed on
# distributions that ship Python without ensurepip, leaving a venv with no pip
# in it, so the venv is only accepted once pip is confirmed present.
find_python() {
  for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if have "$candidate" && "$candidate" -c \
        'import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)' \
        >/dev/null 2>&1; then
      printf '%s' "$candidate"
      return 0
    fi
  done
  return 1
}

install_with_venv() {
  local python venv
  python="$(find_python)" || return 1
  venv="$ATOMSH_HOME/venv"

  say "Installing with $($python --version)…"
  [ -d "$venv" ] || "$python" -m venv "$venv" >/dev/null 2>&1 || return 1
  [ -x "$venv/bin/pip" ] || return 1   # ensurepip missing; fall through to uv

  "$venv/bin/python" -m pip install --quiet --upgrade pip >/dev/null 2>&1 || true
  "$venv/bin/python" -m pip install --quiet --upgrade "$SOURCE" || return 1

  mkdir -p "$BIN_DIR"
  ln -sf "$venv/bin/atomsh" "$BIN_DIR/atomsh"
  return 0
}

# ── strategy 3: bootstrap uv, then retry ─────────────────────────────────────
bootstrap_uv() {
  have curl || die "curl is required to bootstrap uv."
  say "No usable Python toolchain found. Installing uv (astral.sh)…"
  curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1 || return 1
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  have uv || return 1
  return 0
}

# ── run ──────────────────────────────────────────────────────────────────────
installed=false

if have uv && install_with_uv; then
  installed=true
elif install_with_venv; then
  installed=true
elif bootstrap_uv && install_with_uv; then
  installed=true
fi

$installed || die "could not install atomsh. Install uv (https://astral.sh/uv) and retry."

LAUNCHER="$BIN_DIR/atomsh"
[ -x "$LAUNCHER" ] || LAUNCHER="$(command -v atomsh || true)"
[ -n "$LAUNCHER" ] || die "installed, but the atomsh launcher was not found."

say ""
say "Installed $("$LAUNCHER" --version 2>/dev/null || echo atomsh) → $LAUNCHER"

# Put the launcher on PATH. Printing the instruction and leaving it to the
# reader does not work: the usual outcome is `atomsh: command not found`
# followed by sourcing an rc file that was never edited. Set
# ATOMSH_NO_MODIFY_PATH=1 to be told instead of helped.
add_to_path() {
  local line="export PATH=\"$BIN_DIR:\$PATH\""
  local edited=""

  for rc in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile"; do
    [ -f "$rc" ] || continue
    if grep -qF "$BIN_DIR" "$rc" 2>/dev/null; then
      edited="$edited $rc(already)"
      continue
    fi
    printf '\n# added by the atomsh installer\n%s\n' "$line" >> "$rc" \
      && edited="$edited $rc"
  done

  if [ -z "$edited" ]; then
    # No rc file existed; create the one the login shell will read.
    printf '\n# added by the atomsh installer\n%s\n' "$line" >> "$HOME/.profile"
    edited=" $HOME/.profile"
  fi
  printf '%s' "$edited"
}

case ":$PATH:" in
  *":$BIN_DIR:"*)
    ON_PATH=yes
    ;;
  *)
    ON_PATH=no
    if [ "${ATOMSH_NO_MODIFY_PATH:-0}" = "1" ]; then
      warn ""
      warn "$BIN_DIR is not on your PATH. Add it with:"
      warn "  echo 'export PATH=\"$BIN_DIR:\$PATH\"' >> ~/.bashrc"
    else
      touched="$(add_to_path)"
      say ""
      say "Added $BIN_DIR to your PATH in:$touched"
    fi
    ;;
esac

say ""
say "Next:"
if [ "$ON_PATH" = "no" ]; then
  say "  export PATH=\"$BIN_DIR:\$PATH\"    # this shell only, once"
fi
say "  atomsh login     connect your atomgpt.org account"
say "  atomsh           start coding"
