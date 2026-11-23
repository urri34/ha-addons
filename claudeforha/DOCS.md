# Claude Code Remote (unofficial)

Runs [Claude Code](https://claude.com/product/claude-code) inside Home Assistant in **Remote Control**
mode: you talk to it from [claude.ai/code](https://claude.ai/code) or from the Claude mobile app, and it
queries and controls this Home Assistant (REST/WebSocket API, `ha` CLI, configuration files and,
optionally, Docker through SSH).

> **Unofficial project.** This add-on is not made, endorsed or supported by Anthropic. "Claude" and
> "Claude Code" are trademarks of Anthropic PBC. Claude Code is downloaded from Anthropic on first start
> and its use is subject to [Anthropic's terms](https://www.anthropic.com/legal).

## Requirements

- A **claude.ai account with Claude Code access** (Pro, Max, Team or Enterprise). An API key does **not**
  work: Remote Control needs a full claude.ai login.
- Home Assistant OS or Supervised, on `amd64` or `aarch64` (e.g. Raspberry Pi 4/5).
- About 400 MB of free disk space (Claude Code is ~300 MB).

## First start

1. Install the add-on and start it. On first start it downloads Claude Code with Anthropic's official
   installer (a few minutes; the Dashboard shows the progress).
2. Open the web UI: **Open web UI** button, or **Claude Code** in the sidebar.
3. Log in with the password `admin`. You will be asked to change it.
4. **Dashboard → Start**: open the link, authorize with your claude.ai account, copy the code and paste it
   in the web UI.
5. Remote Control starts by itself. The session **claudeforha** appears in claude.ai/code and in the app.

You do not need to create a Home Assistant token: the add-on uses the Supervisor's internal token.

The web UI is available in English and Catalan (automatic, or chosen in **Settings → Language**).

## Web UI tabs

| Tab | What is there |
|---|---|
| Dashboard | Remote Control status, start/stop/restart, live output |
| Claude | claude.ai login, Remote Control options (name, permissions…), Claude Code updates |
| CLAUDE.md | Instructions Claude reads at every session (tell it about your home) |
| Home Assistant | HA connection (own URL/token, optional), SSH, environment variables |
| Settings | Language, password, download/restore a backup, reset everything |

## What Claude can access — read this

This add-on gives Claude **a lot of power** over your Home Assistant:

- `/homeassistant` (read/write), `/addon_configs`, `/addons`, `/share`, `/media` (read/write),
  `/backup` and `/ssl` (read-only).
- The HA Core API, and the Supervisor API with the `manager` role (it can install, start, stop and
  configure add-ons, make backups, restart HA…).
- Optionally, the host's Docker through the SSH add-on.

With the default permission mode, Claude asks for your permission (on your phone or the web) before running
commands or editing files. **Always make a Home Assistant backup before asking for important changes**
(Settings → System → Backups, or ask Claude to run `ha backups new`). Avoid `bypassPermissions` unless you
know what you are doing.

## Direct access (optional)

By default the web UI is only reachable through Home Assistant (Ingress). To open it directly at
`http://HA_IP:34017`, set the port in the add-on's **Network** section. Direct access is protected by the
add-on's own password; do not expose it to the Internet.

## SSH (optional)

Gives Claude access to the containers (`sudo docker …`) through the
**Advanced SSH & Web Terminal** add-on:

1. Install the SSH add-on if you do not have it (the Dashboard links to it).
2. Press **Connect automatically** (on the Dashboard or in Home Assistant → SSH). This add-on's key is added
   to the SSH add-on, which is started or restarted (open terminal sessions are closed).
3. For `docker`, disable the SSH add-on's **Protection mode**. Claude uses it with `ssh ha '…'`.

Commands to do it by hand from the SSH add-on terminal are also shown.

## Where the configuration is stored

Everything is in `/addon_configs/<repository>_claudeforha` (`/config` inside the add-on):
`settings.json`, `claude/` (login), `home/` (`.ssh`), `workspace/` (CLAUDE.md).

- It is kept when the add-on is **updated** or **rebuilt**.
- It is included in Home Assistant backups (Claude Code itself is excluded; it is downloaded again).
- When uninstalling, do not tick the option to delete data if you want to keep it.
  Just in case: Settings → **Download the backup**.

## Troubleshooting

- **"Installing Claude Code" for a long time**: check the add-on log. The download is retried every
  5 minutes if it fails (e.g. no Internet access).
- **"No claude.ai account"**: log in from the Dashboard or the Claude tab. The login expires from time to
  time.
- **Forgotten web password**: stop the add-on, edit `settings.json` in the add-on's config folder and set
  `"password_hash": null` and `"must_change_password": true`. After starting it again, the password is `admin`.
- **Start from scratch**: Settings → **Reset everything** (logs out of claude.ai and deletes all the configuration).
- **Update Claude Code**: Claude tab → **Update Claude Code**. Remote Control is restarted.

## Support

Issues and suggestions: <https://github.com/urri34/ha-addons/issues>
