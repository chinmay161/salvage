# Salvage: offline legacy-format recovery. No network is used at build time.
# Base image pinned by digest (tag: python:3.12-slim).
FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

COPY salvage/ /app/salvage/
COPY vendor/ /app/vendor/
COPY docker/salvage /salvage
COPY docker/entrypoint.sh /usr/local/bin/salvage-entrypoint
RUN chmod 755 /salvage /usr/local/bin/salvage-entrypoint \
    && python3 -m compileall -q /app

# Runs as root on purpose: an output folder that Docker creates for a bind
# mount on a Linux host is owned by root, and a non-root user could not
# write to it. Pass --user "$(id -u):$(id -g)" for host-owned output files.
WORKDIR /work
ENTRYPOINT ["/usr/local/bin/salvage-entrypoint"]
