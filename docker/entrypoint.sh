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
# Redirect Xvfb's own stdio to a log file so its harmless startup warnings
# (e.g. `_XSERVTransmkdir: Owner of /tmp/.X11-unix should be set to root` when
# running as the non-root appuser) don't drown out benchmark output.
# The log is dumped on failure to preserve diagnosability.
XVFB_LOG="${XVFB_LOG:-/tmp/xvfb.log}"
Xvfb :99 -screen 0 1920x1080x24 -ac +extension GLX +render -noreset \
    >"${XVFB_LOG}" 2>&1 &
XVFB_PID=$!
export DISPLAY=:99
trap "kill ${XVFB_PID} 2>/dev/null || true" EXIT

_dump_xvfb_log() {
    if [ -s "${XVFB_LOG}" ]; then
        echo "--- Xvfb log (${XVFB_LOG}) ---" >&2
        cat "${XVFB_LOG}" >&2
        echo "--- end Xvfb log ---" >&2
    fi
}

# Wait until the X server is actually responding rather than guessing with sleep.
# Probe with xdpyinfo (from x11-utils); give up after ~6 seconds.
for _ in $(seq 1 30); do
    if xdpyinfo -display :99 >/dev/null 2>&1; then
        break
    fi
    if ! kill -0 "${XVFB_PID}" 2>/dev/null; then
        echo "Xvfb died during startup" >&2
        _dump_xvfb_log
        exit 1
    fi
    sleep 0.2
done

if ! xdpyinfo -display :99 >/dev/null 2>&1; then
    echo "Xvfb did not become ready within 6 seconds" >&2
    _dump_xvfb_log
    exit 1
fi

exec python -m nalana_eval.cli benchmark \
    --models     "${MODELS:-mock}" \
    --cases      "${CASES:-0}" \
    --suite      "${SUITE:-fixtures/starter_v3}" \
    --simple-mode \
    --output-dir /app/artifacts \
    "$@"
