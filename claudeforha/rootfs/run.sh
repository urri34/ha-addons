#!/usr/bin/env bash
# Add-on entry point: prepares the persistent folders and starts the web UI,
# which manages the Claude Remote Control process (and downloads Claude Code on first start).
set -euo pipefail

mkdir -p /config/home/.ssh /config/claude /config/workspace
chmod 700 /config/home/.ssh /config/claude
# ssh does not use $HOME but the user's home directory (root): link it to the persistent folder
rm -rf /root/.ssh && ln -s /config/home/.ssh /root/.ssh

echo "claudeforha ${CFHA_VERSION:-dev}"
exec python3 /app/server.py
