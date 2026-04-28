# ─── Stage 1: unit-tests ────────────────────────────────────────────────────
# Lightweight Python image for pure-Python tests.  No Blender binary needed —
# all Blender calls are either mocked or auto-skipped via the blender_worker mark.
FROM python:3.11-slim AS unit-tests

WORKDIR /app

# Install declared dependencies first so this layer is cached independently
# of source-code changes.
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir pydantic>=2.7 "pytest>=8"

# Copy source, then install the package itself without re-downloading deps.
COPY . .
RUN pip install --no-cache-dir --no-deps .

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

CMD ["pytest", "tests/", "-m", "not blender_worker", "--tb=short"]


# ─── Stage 2: blender ───────────────────────────────────────────────────────
# Full image: Ubuntu 22.04 + Blender portable binary + Xvfb for headless
# OpenGL rendering (the BLENDER_WORKBENCH engine requires a display context).
FROM --platform=linux/amd64 ubuntu:22.04 AS blender

ARG DEBIAN_FRONTEND=noninteractive

# Pin Blender 4.2 LTS.  Override at build time:
#   docker build --build-arg BLENDER_VERSION=4.2.4 ...
ARG BLENDER_VERSION=4.2.3

# System packages:
#   python3.11 + venv — harness runtime; venv is needed to create an isolated
#                       Python environment (Ubuntu's system Python has EXTERNALLY-
#                       MANAGED restrictions that break plain pip installs into
#                       the system site-packages at runtime).
#   wget / xz-utils   — Blender archive download
#   xvfb + Mesa + X11 — headless OpenGL for BLENDER_WORKBENCH renders
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.11 \
        python3.11-dev \
        python3.11-venv \
        wget \
        xz-utils \
        xvfb \
        libgl1-mesa-glx \
        libgl1-mesa-dri \
        libglu1-mesa \
        libxi6 \
        libxrender1 \
        libxfixes3 \
        libxxf86vm1 \
        libxkbcommon0 \
        libxkbcommon-x11-0 \
        libfontconfig1 \
        libfreetype6 \
        libgomp1 \
        libsm6 \
        libice6 \
        libxext6 \
    && rm -rf /var/lib/apt/lists/*

# Create an isolated virtual environment.  This sidesteps Ubuntu's
# EXTERNALLY-MANAGED marker and guarantees that pip, pytest, nalana-eval, and
# all installed packages live in a single well-known location (/opt/venv).
RUN python3.11 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Download Blender portable binary and symlink to /usr/local/bin/blender.
# Verify the expected checksum at: https://download.blender.org/release/Blender4.2/
RUN wget -q \
        "https://download.blender.org/release/Blender4.2/blender-${BLENDER_VERSION}-linux-x64.tar.xz" \
        -O /tmp/blender.tar.xz \
    && tar -xf /tmp/blender.tar.xz -C /opt/ \
    && rm /tmp/blender.tar.xz \
    && ln -s "/opt/blender-${BLENDER_VERSION}-linux-x64/blender" /usr/local/bin/blender

WORKDIR /app

# Install declared dependencies first (cached layer).
# Pillow is added here for make_thumbnail / make_fallback_png in the harness.
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir pydantic>=2.7 "pytest>=8" Pillow "anthropic>=0.28" "openai>=1.30"

# Copy source, then install the package itself without re-downloading deps.
COPY . .
RUN pip install --no-cache-dir --no-deps . \
    && python -c "import nalana_eval; print('nalana_eval import OK')" \
    && python -c "import pydantic; print('pydantic import OK')"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # DISPLAY is set to the Xvfb server started by the entrypoint.
    DISPLAY=:99 \
    # Let single_run.py / worker_loop.py find dispatcher, scene_capture, screenshot.
    NALANA_EVAL_RUNTIME_PATH=/app/nalana_eval \
    BLENDER_BIN=/usr/local/bin/blender

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD []
