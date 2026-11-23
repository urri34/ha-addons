# claudeforha add-on: Claude Code (Remote Control) + configuration web UI
#
# Claude Code itself is NOT included in the image (it is proprietary software that cannot be
# redistributed): the add-on downloads it on first start with Anthropic's official installer
# (https://claude.ai/install.sh) into /data/claude-code.
FROM debian:bookworm-slim

# Set by the Supervisor / CI (amd64, aarch64)
ARG BUILD_ARCH=amd64

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git openssh-client expect tini jq ripgrep \
        procps less nano tzdata sqlite3 iputils-ping netcat-openbsd dnsutils \
        mosquitto-clients \
        python3 python3-flask python3-waitress python3-pexpect python3-yaml python3-websocket \
    && rm -rf /var/lib/apt/lists/*

# Supervisor "ha" CLI (uses SUPERVISOR_TOKEN)
RUN curl -fsSL -o /usr/local/bin/ha \
        "https://github.com/home-assistant/cli/releases/latest/download/ha_${BUILD_ARCH}" \
    && chmod 755 /usr/local/bin/ha \
    || echo "WARNING: could not download the ha CLI"

COPY rootfs/ /

# Strip possible Windows line endings (CRLF) and make the scripts executable
RUN find /app /usr/local/bin/run-remote-control.exp /usr/local/bin/ha-api /run.sh -type f \
        -exec sed -i 's/\r$//' {} + \
    && chmod 755 /run.sh /usr/local/bin/run-remote-control.exp /usr/local/bin/ha-api

ARG BUILD_VERSION=dev
# "latest", "stable" or a specific version (e.g. 2.1.310) for the first download
ENV CFHA_VERSION=${BUILD_VERSION} \
    CFHA_CLAUDE_VERSION=latest \
    HOME=/config/home \
    CLAUDE_CONFIG_DIR=/config/claude \
    DISABLE_AUTOUPDATER=1 \
    IS_SANDBOX=1

LABEL io.hass.type="addon" \
      io.hass.arch="${BUILD_ARCH}" \
      io.hass.version="${BUILD_VERSION}" \
      org.opencontainers.image.title="Claude Code Remote for Home Assistant (unofficial)" \
      org.opencontainers.image.source="https://github.com/urri34/ha-addons" \
      org.opencontainers.image.licenses="MIT"

WORKDIR /config/workspace
ENTRYPOINT ["/usr/bin/tini", "--", "/run.sh"]
