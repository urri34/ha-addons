# Claude Code Remote for Home Assistant (unofficial)

![Supports amd64](https://img.shields.io/badge/amd64-yes-green.svg)
![Supports aarch64](https://img.shields.io/badge/aarch64-yes-green.svg)

Runs [Claude Code](https://claude.com/product/claude-code) inside Home Assistant in **Remote Control**
mode, so you can ask Claude — from [claude.ai/code](https://claude.ai/code) or the Claude mobile app — to
check and change your Home Assistant: entities, automations, YAML files, add-ons, logs…

- Web UI inside Home Assistant (sidebar) to log in with claude.ai and configure everything. No YAML options.
- Uses the Supervisor token: no Home Assistant token needed.
- Editable `CLAUDE.md` with safe working rules (backups first, `ha core check`, reload before restart…).
- Optional SSH access to the containers through *Advanced SSH & Web Terminal*, set up with one click.
- English and Catalan.

Claude Code is **not** bundled: it is downloaded from Anthropic on first start. You need a claude.ai
Pro, Max, Team or Enterprise account.

See the [documentation](DOCS.md) — and read the section about what Claude can access before installing.

> Unofficial project, not affiliated with or endorsed by Anthropic. "Claude" and "Claude Code" are
> trademarks of Anthropic PBC.

## Development

The image is built by GitHub Actions (`.github/workflows/build.yaml`) when `version` in `config.yaml`
changes. To test changes as a local add-on, copy the `claudeforha` folder to `/addons/claudeforha` on your
Home Assistant (e.g. with the Samba or SSH add-on), delete the `image:` line from its `config.yaml` so the
Supervisor builds the image locally, then reload the add-on store and install *Local add-ons → Claude Code
Remote (unofficial)*. Don't run it alongside the store version: both use port 34017 and the same Remote
Control session name.

Translations live in `rootfs/app/i18n/<lang>.json` (keys starting with `js.` are also used by the browser)
and `rootfs/app/CLAUDE.default.<lang>.md`. Adding a language is adding those two files, plus
`translations/<lang>.yaml`.
