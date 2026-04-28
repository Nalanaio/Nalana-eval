#!/usr/bin/env bash
# Entrypoint for the nalana-eval Docker container.
#
# Configuration is entirely via environment variables — no file edits needed:
#   MODELS   comma-separated model IDs to evaluate  (default: mock)
#   CASES    number of cases to run, 0 = all        (default: 0)
#   SUITE    path to fixture suite dir or JSON       (default: fixtures/starter_v3)
#
# Any extra arguments passed to the container are forwarded to the CLI,
# allowing one-off flag overrides without rebuilding.
set -e

source /opt/venv/bin/activate

# Start virtual framebuffer so Blender's OpenGL renderer has a display context.
Xvfb :99 -screen 0 1920x1080x24 -ac +extension GLX +render -noreset &
export DISPLAY=:99
sleep 1
trap "kill $! 2>/dev/null || true" EXIT

exec python -m nalana_eval.cli benchmark \
    --models     "${MODELS:-mock}" \
    --cases      "${CASES:-0}" \
    --suite      "${SUITE:-fixtures/starter_v3}" \
    --simple-mode \
    --output-dir /app/artifacts \
    "$@"
