# =============================================================
# Sovereign Workbench — Python Sandbox Image
# =============================================================
# Hardened execution environment for untrusted Python code.
#
# Security properties
# -------------------
# - Runs as non-root user (sandboxuser, uid=1000)
# - No additional pip packages — stdlib only
# - No EXPOSE / no network (--network=none enforced at runtime)
# - Container filesystem is read-only (--read-only at runtime)
# - /tmp writable via --tmpfs (no exec allowed)
# - Container auto-removed (--rm at runtime)
#
# Build
# -----
#   docker build -t sovereign-sandbox-python -f sandbox/python/Dockerfile .
#
# Run (managed by DockerRunner — do not invoke manually in production)
#   docker run --rm --network=none --memory=128m --cpus=0.5 \
#     --read-only --tmpfs /tmp:size=32m \
#     --security-opt no-new-privileges \
#     --pids-limit 64 \
#     -v /path/to/workspace:/sandbox:ro \
#     sovereign-sandbox-python
# =============================================================

FROM python:3.11-slim

LABEL maintainer="Sovereign Workbench" \
      description="Isolated Python sandbox for untrusted code execution"

# Create a non-root sandboxuser (uid/gid 1000)
RUN groupadd --gid 1000 sandboxuser && \
    useradd  --uid 1000 --gid 1000 \
             --no-create-home \
             --shell /bin/false \
             sandboxuser

# No pip installs — only Python stdlib is available inside the sandbox.
# This is intentional: the sandbox is a computation environment,
# not a general-purpose Python runtime.

# Switch to non-root user
USER sandboxuser

# Working dir (code is mounted at /sandbox at runtime — not copied in)
WORKDIR /sandbox

# Default entrypoint: run the mounted main.py
CMD ["python", "/sandbox/main.py"]
