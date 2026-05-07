#!/usr/bin/env bash
# Install repo-local git hooks into .git/hooks/.
#
# Run once after cloning the repo. Hooks are not git-tracked
# (.git/hooks/ lives outside the working tree), so each clone needs
# its own install.
#
# What you get:
#   - pre-commit: refuses direct commits on main / master
#                 (use `git commit --no-verify` to bypass in emergencies)
#
# Idempotent: re-running overwrites with the latest hook source.

set -euo pipefail

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
HOOKS_SRC="$REPO_ROOT/scripts/git-hooks"
HOOKS_DST="$REPO_ROOT/.git/hooks"

if [ ! -d "$HOOKS_DST" ]; then
    echo "ERROR: $HOOKS_DST not found. Are you inside a git repo?" >&2
    exit 1
fi

if [ ! -d "$HOOKS_SRC" ]; then
    echo "ERROR: $HOOKS_SRC not found. Repo layout unexpected." >&2
    exit 1
fi

installed=0
for hook in "$HOOKS_SRC"/*; do
    [ -f "$hook" ] || continue
    name="$(basename "$hook")"
    cp "$hook" "$HOOKS_DST/$name"
    chmod +x "$HOOKS_DST/$name"
    echo "  Installed: $name"
    installed=$((installed + 1))
done

if [ "$installed" -eq 0 ]; then
    echo "ERROR: no hook files found under $HOOKS_SRC" >&2
    exit 1
fi

echo ""
echo "Installed $installed hook(s) into $HOOKS_DST/"
echo "Bypass any hook with: git commit --no-verify"
