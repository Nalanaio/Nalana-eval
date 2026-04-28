#!/usr/bin/env bash
# Entrypoint for the `blender` Docker stage.
#
# 1. Activates the virtual environment so that nalana-eval, pytest, and all
#    installed packages are unconditionally on PATH regardless of how the
#    container's environment was initialised.
# 2. Starts Xvfb before executing the container command so that Blender's
#    BLENDER_WORKBENCH render engine can open an OpenGL display context.
set -e

# Activate the venv.  This prepends /opt/venv/bin to PATH and sets
# VIRTUAL_ENV, making every installed console script (nalana-eval, pytest…)
# immediately available to exec.
source /opt/venv/bin/activate

# Start Xvfb on display :99.
Xvfb :99 -screen 0 1920x1080x24 -ac +extension GLX +render -noreset &
XVFB_PID=$!
export DISPLAY=:99

# Give Xvfb time to initialise before Blender tries to open a connection.
sleep 1

# Kill Xvfb when the container exits regardless of exit code.
trap "kill ${XVFB_PID} 2>/dev/null || true" EXIT

exec "$@"
