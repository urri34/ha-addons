# Changelog

## 0.2.0
- **English and Catalan.** The web UI, server messages and the default `CLAUDE.md` are now translated
  (`rootfs/app/i18n/*.json`). The language follows the browser or can be chosen in Settings → Language.
  While untouched, `CLAUDE.md` follows the chosen language.
- **Claude Code is no longer bundled in the image.** It is downloaded on first start with Anthropic's
  official installer into `/data/claude-code` (retried every 5 minutes if it fails). This allows publishing
  pre-built images without redistributing Claude Code.
- Published as a community add-on: renamed to **Claude Code Remote (unofficial)**, new icon and colours,
  English `config.yaml`, `DOCS.md` and translations.
- Direct access on port 34017 is now **disabled by default** (enable it in the Network section if needed).

## 0.1.x (private, Catalan only)
### 0.1.16
- Pestanya Claude: secció **Claude Code** amb la versió i el botó **Actualitza Claude Code**, que baixa
  l'última versió sense refer l'add-on i reinicia Remote Control. **Torna a la versió de l'add-on** ho desfà.
  La baixada es guarda a `/data/claude-code` (fora de la còpia i de les còpies de HA). Si una actualització
  de l'add-on porta una versió més nova, es fa servir aquella i s'esborra la baixada.
- Tauler: l'avís de còpia de seguretat deixa clar que és al menú de Home Assistant, no a la pestanya
  Configuració de l'add-on.

### 0.1.15
- SSH: si hi ha l'add-on oficial **Terminal & SSH** però no l'Advanced, s'explica que no dona accés als
  contenidors i s'enllaça l'Advanced SSH & Web Terminal.

### 0.1.14
- SSH automàtic: l'add-on consulta el Supervisor per saber si *Advanced SSH & Web Terminal* està instal·lat.
  - No instal·lat: enllaç per instal·lar-lo.
  - Instal·lat: botó **Connecta automàticament**, que hi afegeix la clau (sense duplicar-la), l'engega o el
    reinicia (avisa que es tanquen les sessions de terminal) i prova la connexió.
  - Les ordres per fer-ho a mà queden plegades com a alternativa.
- Avís si l'add-on SSH té el **Mode de protecció** activat (sense ell, `docker` no funciona).
- En generar o importar un parell de claus nou, la clau vella se substitueix per la nova a l'add-on SSH.

### 0.1.13
- Tauler: els avisos de còpia de seguretat i de mode de permisos només surten amb el compte de claude.ai connectat.

### 0.1.12
- Claude: la configuració de Remote Control és un desplegable; a la vista queden el nom de la sessió i el mode
  de permisos. S'obre sol si s'hi arriba des de l'avís del Tauler o després de desar.

### 0.1.11
- SSH: nova opció **Actualitza automàticament la clau del servidor SSH** (activada per defecte): si l'add-on SSH
  es reinstal·la i canvia de clau, la connexió continua funcionant. Si es desactiva, la connexió s'atura amb un
  avís i el botó **Oblida la clau del servidor** només surt en aquest mode.
- L'explicació de per a què serveix l'SSH només surt quan no està connectat.

### 0.1.10
- Home Assistant → SSH simplificada: estat, última prova, **Prova la connexió** i, si no connecta, les mateixes
  ordres d'instal·lació que el Tauler. Servidor, port, usuari i claus passen a **Opcions avançades**.
- Botó **Oblida la clau del servidor**, amb avís quan l'add-on SSH ha canviat de clau (p. ex. en reinstal·lar-lo).

### 0.1.9
- Fora el codi de neteja de la prova d'historial amb git. Per desfer canvis: còpies de seguretat oficials de HA.

### 0.1.8
- Pestanyes reordenades i reanomenades: Tauler · Claude · CLAUDE.md · Home Assistant (abans Configuració) ·
  Configuració (abans Seguretat).
- **Surt** demana confirmació.
- Tauler: avís nou per si Claude demana permís massa sovint, amb enllaç al mode de permisos.

### 0.1.7
- Tauler: fora la línia "Sessió: https://claude.ai/code?…" (repetia l'enllaç del missatge d'estat).
- Claude: només es veu l'estat; els detalls del login i el botó de tancar sessió van en un desplegable.
  El bloc de login només surt si no hi ha sessió connectada.
- Configuració: Home Assistant i SSH mostren l'estat (es comprova en obrir la pàgina) i la configuració
  va en un desplegable, obert si no connecta.
- Seguretat: fora "On es guarda la configuració". Restaura i Restableix-ho tot són desplegables, i la
  restauració avisa que es perdrà la configuració actual.

### 0.1.6
- Avís al Tauler: fer una còpia de seguretat de HA abans de demanar intervencions a Claude.
- CLAUDE.md per defecte: Claude recorda (i ofereix fer) una còpia de seguretat abans de canvis importants.
  S'actualitza sol si no l'has modificat.
- Fora l'apartat Git de Configuració.

### 0.1.4
- Login de claude.ai: botó **Copia l'enllaç** per obrir-lo en un altre navegador.
- Tauler: un cop connectat a claude.ai, recomana configurar l'SSH amb les ordres exactes (amb la clau ja posada)
  i un botó per provar-ho. Es pot amagar.
- El parell de claus SSH es genera sol el primer cop.
- La configuració de Remote Control passa de Configuració a la pestanya Claude.

### 0.1.3
- Tauler guiat: explica què passa amb Remote Control i només activa els botons que tenen sentit.
- Sense compte de claude.ai, el bloc de login surt directament al Tauler.
- La sortida de Remote Control queda plegada (desplegable) i amagada mentre no n'hi ha.

### 0.1.2
- Primer canvi de contrasenya: només demana la nova (dues vegades), no l'actual.
- Seguretat → **Restableix-ho tot**: tanca la sessió de claude.ai i esborra tota la configuració.

### 0.1.1
- `ssh` llegeix la configuració i les claus de la carpeta persistent (`/root/.ssh` → `/config/home/.ssh`).

### 0.1.0
- Primera versió: Claude Code amb Remote Control, web de configuració (Ingress + port 34017)
  amb contrasenya pròpia, login de claude.ai des de la web, accés a HA amb el token del
  Supervisor, claus SSH, git, variables d'entorn, editor de CLAUDE.md i còpia de la configuració.
