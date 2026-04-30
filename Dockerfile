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
#   docker build --build-arg BLENDER_VERSION=4.2.4 \
#                --build-arg BLENDER_SHA256=<sha256 from blender.org> ...
ARG BLENDER_VERSION=4.2.3
# SHA256 of blender-${BLENDER_VERSION}-linux-x64.tar.xz.
# To populate / update:
#   curl -fsSL https://download.blender.org/release/Blender4.2/blender-4.2.3-linux-x64.tar.xz.sha256
# (copy the 64-char hex hash, drop the filename suffix)
ARG BLENDER_SHA256=3a64efd1982465395abab4259b4091d5c8c56054c7267e9633e4f702a71ea3f4

# System packages:
#   python3.11 + venv — harness runtime; venv is needed to create an isolated
#                       Python environment (Ubuntu's system Python has EXTERNALLY-
#                       MANAGED restrictions that break plain pip installs into
#                       the system site-packages at runtime).
#   wget / xz-utils   — Blender archive download
#   xvfb + Mesa + X11 — headless OpenGL for BLENDER_WORKBENCH renders
#   x11-utils         — provides xdpyinfo for the entrypoint readiness probe
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.11 \
        python3.11-dev \
        python3.11-venv \
        wget \
        xz-utils \
        xvfb \
        x11-utils \
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

# Download Blender portable binary, verify SHA256, and symlink to /usr/local/bin/blender.
# Checksum guards against tampered downloads (supply-chain attack on the mirror).
# If you bump BLENDER_VERSION you MUST also pass BLENDER_SHA256.
RUN wget -q \
        "https://download.blender.org/release/Blender4.2/blender-${BLENDER_VERSION}-linux-x64.tar.xz" \
        -O /tmp/blender.tar.xz \
    && echo "${BLENDER_SHA256}  /tmp/blender.tar.xz" | sha256sum -c - \
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

# Drop root.  UID 1000 matches the typical default user on Linux desktops;
# Docker Desktop on macOS handles UID translation for bind mounts transparently.
# If your host user has a different UID (run `id -u`), override at build time:
#   docker build --build-arg APP_UID=$(id -u) ...
ARG APP_UID=1000
RUN useradd --create-home --shell /bin/bash --uid "${APP_UID}" appuser \
    && chown -R appuser:appuser /app /opt/venv
USER appuser

ENTRYPOINT ["/entrypoint.sh"]
CMD []
