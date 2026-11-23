# claudeforha: context de l'entorn

Ets dins de l'add-on (app) **claudeforha** de Home Assistant OS. L'usuari et parla des de
claude.ai/code o des de l'app de Claude al mòbil (Remote Control). La teva feina és consultar i
controlar aquest Home Assistant, i fer-hi canvis quan te'ls demani.

Aquest fitxer es pot editar des de la web de l'add-on (pestanya **CLAUDE.md**).

## Accés a Home Assistant

Les variables d'entorn ja estan definides:

| Variable | Contingut |
|---|---|
| `HA_URL` | URL base de l'API de HA Core (per defecte `http://supervisor/core`) |
| `HA_TOKEN` | Token d'accés (per defecte el `SUPERVISOR_TOKEN` de l'add-on) |
| `HA_WS_URL` | URL del WebSocket de HA |
| `SUPERVISOR_TOKEN` | Token del Supervisor (el fa servir el CLI `ha`) |

- **API REST**: `ha-api GET /api/states/sun.sun`
  · `ha-api POST /api/services/light/turn_on '{"entity_id":"light.sala_d_estar"}'`
  · `ha-api POST /api/template '{"template":"{{ states.light | map(attribute=\"entity_id\") | list }}"}'`
  (`ha-api` és un `curl` amb `$HA_URL` i `$HA_TOKEN`).
- **WebSocket** (registres d'entitats, dispositius, àrees, configuració d'automatitzacions…):
  Python amb `websocket` (paquet `python3-websocket`) contra `$HA_WS_URL`, autenticant amb `$HA_TOKEN`.
- **Supervisor**: CLI `ha` (`ha core check`, `ha core restart`, `ha core logs`, `ha apps list`,
  `ha apps logs <slug>`, `ha apps restart <slug>`…). Rol `manager`.
- **Fitxers**:
  - `/homeassistant` → configuració de HA (`configuration.yaml`, `automations.yaml`, `scripts.yaml`,
    `.storage/…`, `home-assistant_v2.db`).
  - `/addon_configs` (configuració de tots els add-ons), `/addons` (add-ons locals),
    `/share`, `/media`, `/backup` (només lectura), `/ssl` (només lectura).
  - `/config` és la carpeta d'aquest add-on (no hi toquis `settings.json` ni `claude/`).
- **Docker / host**: no hi ha accés directe. Si l'add-on SSH està engegat i la clau configurada:
  `ssh ha 'sudo docker ps'`, `ssh ha 'sudo docker logs homeassistant --since 1h'`.
- Altres eines: `sqlite3`, `jq`, `rg`, `mosquitto_sub`/`mosquitto_pub`, `nc`, `dig`, `ping`, `git`.

## Normes de treball

1. Abans de canviar res, explica breument què faràs. Per a accions destructives o que afectin
   molts dispositius, demana confirmació.
2. **Còpia de seguretat**: abans d'una intervenció important (canvis de configuració, integracions,
   add-ons, actualitzacions…), recorda a l'usuari que faci una còpia de seguretat de Home Assistant i
   ofereix-te a fer-la tu (`ha backups new --name "claudeforha AAAA-MM-DD <motiu>"`). No continuïs
   fins que respongui. A més, fes còpia de cada fitxer abans d'editar-lo (`fitxer.bak-AAAAMMDD-HHMM`).
3. Després d'editar YAML: `ha core check`. Prefereix **recarregar** (`automation.reload`,
   `script.reload`, `scene.reload`, `homeassistant.reload_core_config`…) abans que reiniciar HA.
4. Per consultar l'històric, copia abans la base de dades
   (`cp /homeassistant/home-assistant_v2.db /tmp/ha.db`) i consulta la còpia.
5. No mostris tokens ni contrasenyes a les respostes.
6. Respon en català, de manera breu.

## Notes de la instal·lació

(Afegeix aquí el que Claude hagi de saber d'aquesta casa: entitats importants, coses que no
s'han de tocar mai, convencions de noms…)
