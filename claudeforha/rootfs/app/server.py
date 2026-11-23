#!/usr/bin/env python3
"""claudeforha: configuration web UI + Claude Code Remote Control manager.

All persistent state lives in /config (the add-on's addon_config folder):
  settings.json   web password, Remote Control options, HA, SSH, variables, language
  claude/         CLAUDE_CONFIG_DIR (claude.ai login)
  home/           HOME (includes .ssh)
  workspace/      Claude's working folder (CLAUDE.md)
Outside /config (not in the config backup nor in HA backups):
  /data/claude-code   Claude Code, downloaded with the official installer on first start
                      (the published image does not bundle it) and updated from the web UI
"""
import base64
import collections
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.request
from functools import wraps

import pexpect
from flask import (Flask, abort, copy_current_request_context, flash, g, has_request_context,
                   jsonify, redirect, render_template, request, send_file, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

CONFIG = os.environ.get("CFHA_CONFIG", "/config")
SETTINGS_FILE = f"{CONFIG}/settings.json"
CLAUDE_DIR = f"{CONFIG}/claude"
HOME = f"{CONFIG}/home"
SSH_DIR = f"{HOME}/.ssh"
SSH_KEY = f"{SSH_DIR}/id_ed25519"
WORKSPACE = f"{CONFIG}/workspace"
CLAUDE_MD = f"{WORKSPACE}/CLAUDE.md"
PORT = int(os.environ.get("CFHA_PORT", "34017"))
DEFAULT_PASSWORD = "admin"
APP_DIR = os.path.dirname(os.path.abspath(__file__))

# Variables that make Claude Code skip the claude.ai login or disable Remote Control.
# They are never passed to Claude processes.
BLOCKED_ENV = {
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN",
    "ANTHROPIC_BASE_URL", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY", "DISABLE_GROWTHBOOK",
    "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
}
ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ANSI_RE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]|\x1b[@-Z\\-_]")
URL_RE = re.compile(r"https://[^\s\x07\x1b\"'<>]+")

DEFAULTS = {
    "password_hash": None,          # None -> initial password "admin"
    "must_change_password": True,
    "secret_key": None,
    "lang": "",                     # "" = browser language; otherwise a code from i18n/
    "rc": {
        "autostart": True,
        "session_name": "claudeforha",
        "spawn_mode": "same-dir",   # same-dir | worktree | session
        "permission_mode": "",      # "" | default | acceptEdits | plan | bypassPermissions
        "capacity": "",
        "verbose": False,
    },
    "ha": {"url": "", "token": ""},  # empty -> SUPERVISOR_TOKEN + http://supervisor/core
    "ssh": {"host": "a0d7b954-ssh", "port": 22, "user": "hassio", "verified": False, "dismissed": False,
            "auto_hostkey": True},  # always accept the SSH server key (if it changes, do not fail)
    "env": {},
}


def log(msg):
    print(f"[claudeforha] {msg}", flush=True)


def strip_ansi(text):
    return ANSI_RE.sub("", text)


# ---------------------------------------------------------------- translations
# One JSON file per language in i18n/ (en.json, ca.json…). Keys starting with "js." are also
# sent to the browser (window.T). Keys ending in "_html" contain markup.
I18N_DIR = os.path.join(APP_DIR, "i18n")
FALLBACK_LANG = "en"


def _load_i18n():
    out = {}
    for fn in sorted(os.listdir(I18N_DIR)):
        if fn.endswith(".json"):
            with open(os.path.join(I18N_DIR, fn), encoding="utf-8") as f:
                out[fn[:-5]] = json.load(f)
    return out


I18N = _load_i18n()
LANGS = sorted(I18N)


def current_lang():
    pref = (settings or {}).get("lang") or ""
    if pref in I18N:
        return pref
    if has_request_context():
        if "lang" not in g:
            g.lang = request.accept_languages.best_match(LANGS) or FALLBACK_LANG
        return g.lang
    return FALLBACK_LANG


def t(key, _lang=None, **kw):
    lang = _lang or current_lang()
    s = I18N.get(lang, {}).get(key) or I18N[FALLBACK_LANG].get(key) or key
    return s.format(**kw) if kw else s


# ---------------------------------------------------------------- settings
_settings_lock = threading.Lock()


def _merge(defaults, data):
    out = {}
    for k, v in defaults.items():
        if isinstance(v, dict) and k != "env":
            out[k] = _merge(v, data.get(k) or {})
        else:
            out[k] = data.get(k, v)
    return out


def load_settings():
    data = {}
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:  # corrupted file: do not overwrite it silently
            log(f"ERROR reading {SETTINGS_FILE}: {e}")
            os.replace(SETTINGS_FILE, SETTINGS_FILE + f".broken-{int(time.time())}")
            data = {}
    s = _merge(DEFAULTS, data)
    if not s["secret_key"]:
        s["secret_key"] = secrets.token_hex(32)
        save_settings(s)
    return s


def save_settings(s):
    with _settings_lock:
        tmp = SETTINGS_FILE + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=2, ensure_ascii=False)
        os.replace(tmp, SETTINGS_FILE)


settings = None  # loaded in main()


# ---------------------------------------------------------------- Claude's environment
def ha_endpoints():
    sup = os.environ.get("SUPERVISOR_TOKEN", "")
    url = (settings["ha"]["url"] or "").rstrip("/")
    token = settings["ha"]["token"] or ""
    if not url:
        url = "http://supervisor/core" if sup else ""
    if not token:
        token = sup
    if url.endswith("/core") and "supervisor" in url:
        ws = url.replace("http://", "ws://", 1) + "/websocket"
    else:
        ws = re.sub(r"^http", "ws", url) + "/api/websocket" if url else ""
    return url, token, ws


def child_env():
    env = {k: v for k, v in os.environ.items() if k not in BLOCKED_ENV}
    url, token, ws = ha_endpoints()
    env.update(
        HOME=HOME,
        CLAUDE_CONFIG_DIR=CLAUDE_DIR,
        DISABLE_AUTOUPDATER="1",
        IS_SANDBOX="1",
        TERM="xterm-256color",
        HA_URL=url,
        HA_TOKEN=token,
        HA_WS_URL=ws,
    )
    for k, v in (settings.get("env") or {}).items():
        if ENV_KEY_RE.match(k) and k not in BLOCKED_ENV:
            env[k] = v
    return env


def run(cmd, timeout=30, **kw):
    try:
        r = subprocess.run(cmd, env=child_env(), cwd=WORKSPACE, capture_output=True,
                           text=True, timeout=timeout, **kw)
        return r.returncode, strip_ansi((r.stdout or "") + (r.stderr or "")).strip()
    except subprocess.TimeoutExpired:
        return 124, t("common.timeout")
    except FileNotFoundError as e:
        return 127, str(e)


_auth_cache = {"t": 0, "ok": False, "text": ""}


def claude_auth(force=False):
    if not claude_installed():
        return False, ""
    if force or time.time() - _auth_cache["t"] > 20:
        code, out = run(["claude", "auth", "status"], timeout=30)
        _auth_cache.update(t=time.time(), ok=(code == 0), text=out)
    return _auth_cache["ok"], _auth_cache["text"]


_claude_version = None


def claude_version():
    global _claude_version
    if not claude_installed():
        return "–"
    if _claude_version is None:
        _claude_version = run(["claude", "--version"])[1] or "?"
    return _claude_version


# ---------------------------------------------------------------- Installing / updating Claude Code
# The published image does NOT include Claude Code (it is proprietary software): on first start it is
# downloaded with Anthropic's official installer into CC_HOME (outside /config). A locally built image
# may still have one in /usr/local/bin: the newer of the two is used.
CC_HOME = os.environ.get("CFHA_CC_HOME", "/data/claude-code")
CC_BIN_DIR = f"{CC_HOME}/.local/bin"
CC_BIN = f"{CC_BIN_DIR}/claude"
IMAGE_CLAUDE = "/usr/local/bin/claude"
CC_CHANNEL = os.environ.get("CFHA_CLAUDE_VERSION", "latest")
_cc_lock = threading.Lock()
_cc_install = {"state": "idle", "message": "", "t": 0}   # idle | installing | done | error


def claude_installed():
    return shutil.which("claude") is not None


def _bin_version(path):
    try:
        out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return None
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", out or "")
    return tuple(int(x) for x in m.groups()) if m else None


def select_claude():
    """Put CC_BIN_DIR first in PATH if the downloaded copy is newer than the image's (or there is
    none in the image); otherwise delete the download."""
    global _claude_version
    path = [p for p in os.environ.get("PATH", "").split(":") if p and p != CC_BIN_DIR]
    use = False
    if os.path.exists(CC_BIN):
        vi, vp = _bin_version(IMAGE_CLAUDE), _bin_version(CC_BIN)
        if vp and (not vi or vp > vi):
            use = True
        else:
            log(f"Downloaded Claude Code {vp} is not usable or older than the image's {vi}: deleting it")
            shutil.rmtree(CC_HOME, ignore_errors=True)
    os.environ["PATH"] = ":".join(([CC_BIN_DIR] if use else []) + path)
    _claude_version = None
    return use


def claude_updated():
    return CC_BIN_DIR in os.environ.get("PATH", "").split(":")


def _cleanup_cc_versions():
    """Keep only the version the link points to (each one is ~300 MB)."""
    vdir = f"{CC_HOME}/.local/share/claude/versions"
    if os.path.islink(CC_BIN) and os.path.isdir(vdir):
        keep = os.path.basename(os.path.realpath(CC_BIN))
        for v in os.listdir(vdir):
            if v != keep:
                p = os.path.join(vdir, v)
                shutil.rmtree(p, ignore_errors=True) if os.path.isdir(p) else os.remove(p)
    shutil.rmtree(f"{CC_HOME}/.cache", ignore_errors=True)


def claude_bootstrap():
    """First start: download Claude Code with the official installer (claude.ai/install.sh)."""
    if not _cc_lock.acquire(blocking=False):
        return
    try:
        _cc_install.update(state="installing", message="")
        log(f"Claude Code not found: downloading it with the official installer ({CC_CHANNEL})")
        os.makedirs(CC_HOME, exist_ok=True)
        env = {**os.environ, "HOME": CC_HOME, "DISABLE_AUTOUPDATER": "1"}
        r = subprocess.run(["bash", "-c", 'curl -fsSL https://claude.ai/install.sh | bash -s "$1"', "_", CC_CHANNEL],
                           env=env, cwd=CC_HOME, capture_output=True, text=True, timeout=900)
        out = strip_ansi((r.stdout or "") + (r.stderr or "")).strip()
        _cleanup_cc_versions()
        select_claude()
        if claude_installed():
            _cc_install.update(state="done", message="")
            _auth_cache["t"] = 0
            log(f"Claude Code installed: {claude_version()}")
        else:
            _cc_install.update(state="error", message=out[-300:] or f"exit code {r.returncode}")
            log(f"Claude Code download failed (exit code {r.returncode}): {out[-800:]}")
    except Exception as e:
        _cc_install.update(state="error", message=str(e))
        log(f"Claude Code download failed: {e}")
    finally:
        _cc_install["t"] = time.time()
        _cc_lock.release()


def ensure_claude():
    """Called by the watchdog: start the download if Claude Code is missing (retry every 5 min)."""
    if claude_installed() or _cc_install["state"] == "installing":
        return
    if _cc_install["state"] == "error" and time.time() - _cc_install["t"] < 300:
        return
    _cc_install["state"] = "installing"
    threading.Thread(target=claude_bootstrap, daemon=True).start()


def cc_state_text():
    if _cc_install["state"] == "error":
        return t("cc.state_error", err=_cc_install["message"])
    return t("cc.state_installing")


def claude_install_latest():
    """Download the latest version with the native installer (claude install) into CC_HOME."""
    os.makedirs(CC_HOME, exist_ok=True)
    env = child_env()
    env["HOME"] = CC_HOME
    try:
        r = subprocess.run(["claude", "install", "latest"], env=env, cwd=CC_HOME,
                           capture_output=True, text=True, timeout=600)
        code, out = r.returncode, strip_ansi((r.stdout or "") + (r.stderr or "")).strip()
    except subprocess.TimeoutExpired:
        return 124, t("common.timeout")
    if code == 0:
        _cleanup_cc_versions()
    return code, out


# ---------------------------------------------------------------- Remote Control
class RemoteControl:
    def __init__(self):
        self.lock = threading.RLock()
        self.proc = None
        self.want = False
        self.state = "stopped"
        self.started_at = None
        self.next_try = 0
        self.backoff = 10
        self.last_exit = None
        self.session_url = None
        self.lines = collections.deque(maxlen=3000)

    def _add(self, line):
        if self.lines and self.lines[-1][1] == line:
            return
        self.lines.append((time.time(), line))
        print(f"[rc] {line}", flush=True)
        m = re.search(r"https://claude\.ai/code\S*", line)
        if m:
            self.session_url = m.group(0)

    def args(self):
        rc = settings["rc"]
        a = ["--spawn", rc["spawn_mode"] or "same-dir"]
        if rc["session_name"]:
            a += ["--name", rc["session_name"]]
        if rc["permission_mode"]:
            a += ["--permission-mode", rc["permission_mode"]]
        if str(rc["capacity"]).strip() and rc["spawn_mode"] != "session":
            a += ["--capacity", str(rc["capacity"]).strip()]
        if rc["verbose"]:
            a.append("--verbose")
        return a

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def _spawn(self):
        args = self.args()
        self._add(f"--- Starting: claude remote-control {' '.join(args)}")
        self.session_url = None
        self.proc = subprocess.Popen(
            ["/usr/local/bin/run-remote-control.exp", *args],
            cwd=WORKSPACE, env=child_env(), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.started_at = time.time()
        self.state = "running"
        threading.Thread(target=self._reader, args=(self.proc,), daemon=True).start()

    def _reader(self, p):
        partial = ""
        while True:
            chunk = p.stdout.read1(4096) if hasattr(p.stdout, "read1") else p.stdout.read(4096)
            if not chunk:
                break
            text = partial + strip_ansi(chunk.decode("utf-8", errors="replace"))
            parts = text.split("\n")
            partial = parts.pop()
            for line in parts:
                line = line.rstrip("\r").split("\r")[-1].strip()
                if line:
                    self._add(line)
        if partial.strip():
            self._add(partial.strip())
        code = p.wait()
        with self.lock:
            if p is not self.proc:
                return
            uptime = time.time() - (self.started_at or time.time())
            self.last_exit = code
            self._add(f"--- Remote Control exited (code {code}, {int(uptime)} s)")
            self.backoff = 10 if uptime > 300 else min(self.backoff * 2, 300)
            self.next_try = time.time() + self.backoff
            self.state = "restarting" if self.want else "stopped"

    def start(self):
        with self.lock:
            self.want = True
            self.next_try = 0
            self.backoff = 10
        self.tick()

    def stop(self):
        with self.lock:
            self.want = False
            p = self.proc
        if p and p.poll() is None:
            self._add("--- Stopping Remote Control")
            p.send_signal(signal.SIGTERM)
            try:
                p.wait(25)
            except subprocess.TimeoutExpired:
                p.kill()
                subprocess.run(["pkill", "-f", "claude remote-control"])
        with self.lock:
            self.state = "stopped"

    def restart(self):
        self.stop()
        self.start()

    def tick(self):
        with self.lock:
            if not self.want or self.running() or time.time() < self.next_try:
                return
            if not claude_installed():
                self.state = "waiting_install"
                self.next_try = time.time() + 10
                return
            ok, _ = claude_auth(force=True)
            if not ok:
                self.state = "waiting_login"
                self.next_try = time.time() + 30
                return
            self._spawn()

    def status(self):
        with self.lock:
            return {
                "state": "running" if self.running() else ("stopped" if self.state == "running" else self.state),
                "running": self.running(),
                "want": self.want,
                "pid": self.proc.pid if self.running() else None,
                "uptime": int(time.time() - self.started_at) if self.running() and self.started_at else None,
                "last_exit": self.last_exit,
                "session_url": self.session_url,
                "next_try_in": max(0, int(self.next_try - time.time())) if self.state in ("restarting", "waiting_login") else None,
            }

    def tail(self, n=200):
        return [line for _, line in list(self.lines)[-n:]]


rc = RemoteControl()


def watchdog():
    while True:
        time.sleep(5)
        try:
            ensure_claude()
            rc.tick()
        except Exception as e:
            log(f"watchdog: {e}")


# ---------------------------------------------------------------- Claude login
class ClaudeLogin:
    def __init__(self):
        self.lock = threading.Lock()
        self.child = None
        self.state = "idle"   # idle | starting | waiting_code | checking | done | error
        self.url = None
        self.output = ""
        self.message = ""     # i18n key, translated in status()
        self.started = 0

    def start(self):
        self.cancel()
        with self.lock:
            self.state, self.url, self.output, self.message = "starting", None, "", ""
            self.started = time.time()
            self.child = pexpect.spawn(
                "claude", ["auth", "login", "--claudeai"], env=child_env(), cwd=WORKSPACE,
                encoding="utf-8", codec_errors="replace", dimensions=(50, 4000), timeout=None)
            threading.Thread(target=self._reader, args=(self.child,), daemon=True).start()

    def _reader(self, child):
        raw = ""
        while True:
            try:
                data = child.read_nonblocking(4096, timeout=1)
                raw += data
                self.output = strip_ansi(raw)[-6000:]
                if not self.url:
                    for u in URL_RE.findall(raw) + URL_RE.findall(self.output):
                        if "oauth" in u or "authorize" in u:
                            self.url = u
                            self.state = "waiting_code"
                            break
            except pexpect.TIMEOUT:
                if time.time() - self.started > 900:
                    child.terminate(force=True)
                    self.state, self.message = "error", "login.timeout15"
                    return
                continue
            except pexpect.EOF:
                break
        child.close()
        if child is not self.child:
            return
        self.state = "checking"
        ok, text = claude_auth(force=True)
        if ok:
            self.state, self.message = "done", "login.ok"
            log("claude.ai login successful")
            if settings["rc"]["autostart"] or rc.want:
                threading.Thread(target=rc.restart, daemon=True).start()
        else:
            self.state, self.message = "error", "login.incomplete"

    def submit_code(self, code):
        with self.lock:
            if not self.child or not self.child.isalive():
                return False
            self.child.send(code.strip())
            time.sleep(1)
            self.child.send("\r")
            self.state = "checking"
            return True

    def cancel(self):
        with self.lock:
            if self.child and self.child.isalive():
                self.child.terminate(force=True)
            self.child = None
            self.state = "idle"

    def status(self):
        return {"state": self.state, "url": self.url, "output": self.output[-3000:],
                "message": t(self.message) if self.message else ""}


login_flow = ClaudeLogin()


# ---------------------------------------------------------------- SSH
def write_ssh_config():
    s = settings["ssh"]
    os.makedirs(SSH_DIR, mode=0o700, exist_ok=True)
    cfg = (
        "# Generated by claudeforha (Home Assistant tab > SSH). Do not edit by hand.\n"
        "Host ha\n"
        f"  HostName {s['host']}\n"
        f"  Port {int(s['port'] or 22)}\n"
        f"  User {s['user']}\n"
        f"  IdentityFile {SSH_KEY}\n"
        "  IdentitiesOnly yes\n"
        "  ConnectTimeout 10\n"
    )
    if s.get("auto_hostkey", True):
        # HA internal network: if the SSH add-on is reinstalled and its key changes, accept the new one
        cfg += "  StrictHostKeyChecking no\n  UserKnownHostsFile /dev/null\n  LogLevel ERROR\n"
    else:
        cfg += "  StrictHostKeyChecking accept-new\n"
    with open(f"{SSH_DIR}/config", "w") as f:
        f.write(cfg)
    os.chmod(f"{SSH_DIR}/config", 0o600)


def generate_ssh_key():
    for p in (SSH_KEY, SSH_KEY + ".pub"):
        if os.path.exists(p):
            os.remove(p)
    r = subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "claudeforha", "-f", SSH_KEY],
                       capture_output=True, text=True)
    if settings is not None:
        settings["ssh"]["verified"] = False
        save_settings(settings)
    return r.returncode, (r.stdout + r.stderr).strip()


SSH_SETUP_TEMPLATE = r"""KEY='@KEY@'
# 1) Right now, without restarting the SSH add-on
echo "$KEY" | sudo tee -a /etc/ssh/authorized_keys >/dev/null
# 2) So it survives restarts of the SSH add-on (stored in its options)
T=$(sudo cat /run/s6/container_environment/SUPERVISOR_TOKEN)
curl -s -H "Authorization: Bearer $T" http://supervisor/addons/self/info \
  | jq --arg k "$KEY" '{options: (.data.options | .ssh.authorized_keys = (((.ssh.authorized_keys // []) + [$k]) | unique))}' \
  | curl -s -X POST -H "Authorization: Bearer $T" -H 'Content-Type: application/json' -d @- http://supervisor/addons/self/options
echo"""


def ssh_setup_commands():
    """Commands to authorize the key in the SSH & Web Terminal add-on (from its terminal)."""
    return SSH_SETUP_TEMPLATE.replace("@KEY@", ssh_public_key())


def ssh_public_key():
    if os.path.exists(SSH_KEY + ".pub"):
        with open(SSH_KEY + ".pub") as f:
            return f.read().strip()
    return ""


# --- "Advanced SSH & Web Terminal" add-on, managed through the Supervisor API (manager role)
SSH_ADDON = "a0d7b954_ssh"
SSH_ADDON_URL = ("https://my.home-assistant.io/redirect/supervisor_addon/?addon=a0d7b954_ssh"
                 "&repository_url=https%3A%2F%2Fgithub.com%2Fhassio-addons%2Frepository")


def supervisor(path, method="GET", data=None, timeout=15):
    tok = os.environ.get("SUPERVISOR_TOKEN")
    if not tok:
        raise RuntimeError("no Supervisor access")
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request("http://supervisor" + path, data=body, method=method,
                                 headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.load(r)
    except urllib.error.HTTPError as e:
        try:
            d = json.load(e)
        except Exception:
            raise RuntimeError(f"HTTP {e.code}")
    if d.get("result") != "ok":
        raise RuntimeError(d.get("message") or "Supervisor error")
    return d.get("data") or {}


def _key_id(line):
    """Type + key, without the comment: to compare public keys."""
    return " ".join((line or "").split()[:2])


def ssh_addon_managed():
    """We only manage the add-on if SSH points to the default server (Advanced SSH & Web Terminal)."""
    return settings["ssh"]["host"] == DEFAULTS["ssh"]["host"]


_ssh_addon_cache = {"t": 0, "v": None}


def ssh_addon_status(force=False):
    """{installed, state, protected, has_key}, or None if unknown (or not managed)."""
    if not ssh_addon_managed():
        return None
    if not force and time.time() - _ssh_addon_cache["t"] < 15:
        return _ssh_addon_cache["v"]
    try:
        addons = supervisor("/addons").get("addons") or []
        # "Terminal & SSH" (the official one) has no Docker access: only detected to explain it
        core_ssh = any(a.get("slug") == "core_ssh" for a in addons)
        if not any(a.get("slug") == SSH_ADDON for a in addons):
            v = {"installed": False, "state": None, "protected": None, "has_key": False, "core_ssh": core_ssh}
        else:
            info = supervisor(f"/addons/{SSH_ADDON}/info")
            keys = ((info.get("options") or {}).get("ssh") or {}).get("authorized_keys") or []
            mine = _key_id(ssh_public_key())
            v = {"installed": True, "state": info.get("state"), "protected": info.get("protected"),
                 "has_key": bool(mine) and any(_key_id(k) == mine for k in keys)}
    except Exception as e:
        log(f"Could not query the SSH add-on: {e}")
        v = None
    _ssh_addon_cache.update(t=time.time(), v=v)
    return v


def ssh_addon_set_key(add=None, remove=None):
    """Add and/or remove a key from the SSH add-on's authorized_keys. Returns True if anything changed.
    The SSH add-on only applies it when restarted."""
    opts = supervisor(f"/addons/{SSH_ADDON}/info").get("options") or {}
    ssh = opts.setdefault("ssh", {})
    keys = list(ssh.get("authorized_keys") or [])
    new = [k for k in keys if not (remove and _key_id(k) == _key_id(remove))]
    if add and not any(_key_id(k) == _key_id(add) for k in new):
        new.append(add)
    _ssh_addon_cache["t"] = 0
    if new == keys:
        return False
    ssh["authorized_keys"] = new
    supervisor(f"/addons/{SSH_ADDON}/options", "POST", {"options": opts})
    return True


def ssh_addon_connect():
    """Put our key in the SSH add-on, start or restart it if needed and test the connection."""
    pub = ssh_public_key()
    if not pub:
        return False, t("ssh.err_no_key")
    st = ssh_addon_status(force=True)
    if not st or not st["installed"]:
        return False, t("ssh.err_not_installed")
    changed = ssh_addon_set_key(add=pub)
    if st["state"] != "started":
        supervisor(f"/addons/{SSH_ADDON}/start", "POST", timeout=180)
    elif changed or not ssh_check(timeout=15)[0]:
        supervisor(f"/addons/{SSH_ADDON}/restart", "POST", timeout=180)
    ok, out = False, ""
    for _ in range(8):  # SSH takes a few seconds to accept connections after starting
        ok, out = ssh_check(timeout=15)
        if ok:
            break
        time.sleep(3)
    settings["ssh"]["verified"] = ok
    save_settings(settings)
    _ssh_addon_cache["t"] = 0
    return ok, out


def ssh_addon_replace_key(old_pub):
    """After changing the key pair: in the SSH add-on, replace the old key with the new one."""
    try:
        st = ssh_addon_status(force=True)
        if not (st and st["installed"] and old_pub):
            return ""
        keys = ((supervisor(f"/addons/{SSH_ADDON}/info").get("options") or {}).get("ssh") or {}).get("authorized_keys") or []
        if any(_key_id(k) == _key_id(old_pub) for k in keys):  # only if we had put it there
            ssh_addon_set_key(add=ssh_public_key(), remove=old_pub)
            settings["ssh"]["verified"] = False
            save_settings(settings)
            return t("ssh.replaced_suffix")
    except Exception as e:
        log(f"Could not update the key in the SSH add-on: {e}")
    return ""


# ---------------------------------------------------------------- CLAUDE.md
# One default per language: CLAUDE.default.<lang>.md. While the user has not edited it, CLAUDE.md
# follows the interface language and is upgraded when the default text changes.
def default_claude_md(lang=None):
    lang = lang or current_lang()
    path = os.path.join(APP_DIR, f"CLAUDE.default.{lang}.md")
    if not os.path.exists(path):
        path = os.path.join(APP_DIR, f"CLAUDE.default.{FALLBACK_LANG}.md")
    with open(path, encoding="utf-8") as f:
        return f.read()


# Fingerprints of default CLAUDE.md texts from earlier versions (to upgrade them if untouched)
OLD_DEFAULT_CLAUDE_MD = {
    "30393276c3dbe0e68493f0c90318c726c35ac29b222bef0be38c0562a14461ca",  # 0.1.0 - 0.1.4
    "7736b2f391c0a87ab5b6db5c5ffe99de7198b100f4dd35a0eff37bd3a568e5b0",  # 0.2.0 (ca)
}


def _sha256(data):
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path):
    with open(path, "rb") as f:
        return _sha256(f.read())


def claude_md_is_default():
    """True if CLAUDE.md is missing or still has an (old or current) default text, in any language."""
    if not os.path.exists(CLAUDE_MD):
        return True
    h = _sha256_file(CLAUDE_MD)
    return h in OLD_DEFAULT_CLAUDE_MD or any(
        h == _sha256(default_claude_md(lang).encode("utf-8")) for lang in LANGS)


def sync_claude_md(lang=None):
    """Write the default CLAUDE.md in the given language if the user has not edited it."""
    if claude_md_is_default():
        text = default_claude_md(lang)
        if not os.path.exists(CLAUDE_MD) or _sha256_file(CLAUDE_MD) != _sha256(text.encode("utf-8")):
            with open(CLAUDE_MD, "w", encoding="utf-8") as f:
                f.write(text)


def ensure_workspace():
    for d in (HOME, SSH_DIR, CLAUDE_DIR, WORKSPACE):
        os.makedirs(d, exist_ok=True)
    if not os.path.exists(SSH_KEY):
        generate_ssh_key()
    if not os.path.exists(CLAUDE_MD) or _sha256_file(CLAUDE_MD) in OLD_DEFAULT_CLAUDE_MD:
        sync_claude_md()
    write_ssh_config()


# ---------------------------------------------------------------- Flask
class IngressMiddleware:
    """With Ingress, HA passes the prefix in X-Ingress-Path: this way url_for() builds correct paths."""

    def __init__(self, wsgi):
        self.wsgi = wsgi

    def __call__(self, environ, start_response):
        prefix = environ.get("HTTP_X_INGRESS_PATH")
        if prefix:
            environ["SCRIPT_NAME"] = prefix.rstrip("/")
        return self.wsgi(environ, start_response)


app = Flask(__name__, template_folder=os.path.join(APP_DIR, "templates"),
            static_folder=os.path.join(APP_DIR, "static"))
app.wsgi_app = IngressMiddleware(app.wsgi_app)
app.config.update(SESSION_COOKIE_NAME="cfha_session", SESSION_COOKIE_SAMESITE="Lax",
                  SESSION_COOKIE_HTTPONLY=True, PERMANENT_SESSION_LIFETIME=30 * 24 * 3600,
                  MAX_CONTENT_LENGTH=20 * 1024 * 1024)

_fails = {}  # ip -> [attempts, blocked_until]


def client_ip():
    return request.headers.get("X-Forwarded-For", request.remote_addr or "?").split(",")[0].strip()


def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get("auth"):
            if request.path.startswith("/api/"):
                return jsonify(error="unauthorized"), 401
            return redirect(url_for("login"))
        if settings["must_change_password"] and request.endpoint not in ("password", "logout"):
            if request.path.startswith("/api/"):
                return jsonify(error="must_change_password"), 403
            return redirect(url_for("password"))
        return fn(*a, **kw)
    return wrapper


@app.before_request
def csrf_protect():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    if request.method == "POST":
        token = request.form.get("csrf") or request.headers.get("X-CSRF")
        if token != session.get("csrf"):
            abort(400, t("common.csrf"))


@app.context_processor
def inject():
    lang = current_lang()
    strings = I18N.get(lang, {})
    js = {k: v for k, v in I18N[FALLBACK_LANG].items() if k.startswith("js.")}
    js.update({k: v for k, v in strings.items() if k.startswith("js.")})
    return {"csrf": session.get("csrf", ""), "settings": settings, "version": os.environ.get("CFHA_VERSION", ""),
            "ingress": bool(request.headers.get("X-Ingress-Path")), "t": t, "lang": lang, "js_strings": js,
            "languages": [(code, I18N[code].get("_name", code)) for code in LANGS]}


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        ip = client_ip()
        n, until = _fails.get(ip, [0, 0])
        if time.time() < until:
            flash(t("auth.too_many", n=int(until - time.time())), "error")
            return render_template("login.html"), 429
        pw = request.form.get("password", "")
        h = settings["password_hash"]
        ok = check_password_hash(h, pw) if h else secrets.compare_digest(pw, DEFAULT_PASSWORD)
        if ok:
            _fails.pop(ip, None)
            session.clear()
            session.permanent = True
            session["auth"] = True
            session["csrf"] = secrets.token_hex(16)
            return redirect(url_for("index"))
        n += 1
        _fails[ip] = [n, time.time() + 300 if n >= 5 else 0]
        if n >= 5:
            _fails[ip][0] = 0
        flash(t("auth.wrong"), "error")
    return render_template("login.html", first=settings["password_hash"] is None)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/password", methods=["GET", "POST"])
@login_required
def password():
    if request.method == "POST":
        cur, new, rep = (request.form.get(k, "") for k in ("current", "new", "repeat"))
        h = settings["password_hash"]
        # With the initial password (none saved yet) the current one is not asked for
        if h and not check_password_hash(h, cur):
            flash(t("auth.cur_wrong"), "error")
        elif len(new) < 8:
            flash(t("auth.min8"), "error")
        elif new != rep:
            flash(t("auth.mismatch"), "error")
        elif new == DEFAULT_PASSWORD:
            flash(t("auth.not_admin"), "error")
        else:
            settings["password_hash"] = generate_password_hash(new)
            settings["must_change_password"] = False
            save_settings(settings)
            flash(t("auth.changed"), "ok")
            return redirect(url_for("index"))
    return render_template("password.html")


@app.route("/")
@login_required
def index():
    sync_claude_md()  # CLAUDE.md follows the interface language while untouched
    return render_template("index.html", auth_ok=claude_auth()[0], ssh_cmds=ssh_setup_commands(),
                           ssh_addon=ssh_addon_status(), ssh_addon_url=SSH_ADDON_URL)


@app.route("/api/status")
@login_required
def api_status():
    ok, text = claude_auth()
    ssh = {k: settings["ssh"][k] for k in ("verified", "dismissed")}
    cc = {"installed": claude_installed(), "state": _cc_install["state"], "message": _cc_install["message"]}
    return jsonify(rc=rc.status(), auth={"ok": ok, "text": text}, log=rc.tail(int(request.args.get("n", 150))), ssh=ssh,
                   claude_version=claude_version(), cc=cc)


@app.route("/rc/<action>", methods=["POST"])
@login_required
def rc_action(action):
    fn = {"start": rc.start, "stop": rc.stop, "restart": rc.restart}.get(action)
    if not fn:
        abort(404)
    threading.Thread(target=fn, daemon=True).start()
    if request.headers.get("X-CSRF"):
        return jsonify(ok=True)
    flash(t(f"rc.flash_{action}"), "ok")
    return redirect(url_for("index"))


@app.route("/logs")
@login_required
def logs():
    body = "\n".join(time.strftime("%Y-%m-%d %H:%M:%S ", time.localtime(ts)) + l for ts, l in rc.lines)
    return app.response_class(body, mimetype="text/plain; charset=utf-8")


# --- Claude
@app.route("/claude")
@login_required
def claude_page():
    ok, text = claude_auth(force=True)
    image_v = _bin_version(IMAGE_CLAUDE) if os.path.exists(IMAGE_CLAUDE) else None
    return render_template("claude.html", auth_ok=ok, auth_text=text, cv=claude_version(),
                           cc_updated=claude_updated(), cc_installed=claude_installed(),
                           cc_state_text=cc_state_text(),
                           cc_image=".".join(map(str, image_v)) if image_v else None)


@app.route("/claude/update", methods=["POST"])
@login_required
def claude_update():
    if not claude_installed() or not _cc_lock.acquire(blocking=False):
        flash(t("cc.busy"), "error")
        return redirect(url_for("claude_page") + "#cc")
    try:
        before = claude_version()
        code, out = claude_install_latest()
        select_claude()
        after = claude_version()
        if code != 0:
            flash(t("cc.update_failed", err=out[-500:] or code), "error")
        elif after == before:
            flash(t("cc.already_latest", v=after), "ok")
        else:
            msg = t("cc.updated", before=before, after=after)
            if rc.running():
                rc.restart()
                msg += t("cc.rc_restarted")
            flash(msg, "ok")
    finally:
        _cc_lock.release()
    return redirect(url_for("claude_page") + "#cc")


@app.route("/claude/update/undo", methods=["POST"])
@login_required
def claude_update_undo():
    if not os.path.exists(IMAGE_CLAUDE):  # nothing to go back to: the image has no Claude Code
        return redirect(url_for("claude_page") + "#cc")
    with _cc_lock:
        shutil.rmtree(CC_HOME, ignore_errors=True)
        select_claude()
    msg = t("cc.undone", v=claude_version())
    if rc.running():
        rc.restart()
        msg += t("cc.rc_restarted")
    flash(msg, "ok")
    return redirect(url_for("claude_page") + "#cc")


@app.route("/api/login", methods=["GET"])
@login_required
def api_login():
    return jsonify(login_flow.status())


@app.route("/api/login/start", methods=["POST"])
@login_required
def api_login_start():
    if not claude_installed():
        return jsonify(ok=False, error=cc_state_text()), 409
    login_flow.start()
    return jsonify(ok=True)


@app.route("/api/login/code", methods=["POST"])
@login_required
def api_login_code():
    code = (request.get_json(silent=True) or {}).get("code", "")
    if not code.strip():
        return jsonify(ok=False, error=t("login.empty_code")), 400
    return jsonify(ok=login_flow.submit_code(code))


@app.route("/api/login/cancel", methods=["POST"])
@login_required
def api_login_cancel():
    login_flow.cancel()
    return jsonify(ok=True)


@app.route("/claude/logout", methods=["POST"])
@login_required
def claude_logout():
    rc.stop()
    code, out = run(["claude", "auth", "logout"])
    claude_auth(force=True)
    flash(t("claude.logout_flash", out=out or code), "ok" if code == 0 else "error")
    return redirect(url_for("claude_page"))


# --- Settings
@app.route("/settings")
@login_required
def settings_page():
    url, token, ws = ha_endpoints()
    env_text = "\n".join(f"{k}={v}" for k, v in (settings["env"] or {}).items())
    # HA and SSH status, in parallel so the page loads fast
    res = {}
    checks = [threading.Thread(target=copy_current_request_context(lambda: res.update(ha=ha_check(timeout=5))))]
    if os.path.exists(SSH_KEY):
        checks.append(threading.Thread(target=copy_current_request_context(lambda: res.update(ssh=ssh_check(timeout=10)))))
    for th in checks:
        th.start()
    for th in checks:
        th.join()
    ha_ok, ha_msg = res.get("ha", (False, t("ha.could_not_check")))
    ssh_ok, ssh_msg = res.get("ssh", (False, t("ssh.no_key_yet")))
    if settings["ssh"]["verified"] != ssh_ok:
        settings["ssh"]["verified"] = ssh_ok
        save_settings(settings)
    return render_template("settings.html", ha_url_eff=url, ha_ws_eff=ws,
                           ha_ok=ha_ok, ha_msg=ha_msg, ssh_ok=ssh_ok, ssh_msg=ssh_msg,
                           ssh_hostkey_changed=ssh_msg == t("ssh.hostkey_changed_short"), ssh_cmds=ssh_setup_commands(),
                           ssh_addon=ssh_addon_status(force=True), ssh_addon_url=SSH_ADDON_URL,
                           ha_token_src=(t("ha.token_own") if settings["ha"]["token"] else
                                         "SUPERVISOR_TOKEN" if os.environ.get("SUPERVISOR_TOKEN") else t("ha.token_none")),
                           pubkey=ssh_public_key(), has_key=os.path.exists(SSH_KEY), env_text=env_text)


@app.route("/settings/rc", methods=["POST"])
@login_required
def settings_rc():
    f = request.form
    r = settings["rc"]
    r["session_name"] = f.get("session_name", "").strip() or "claudeforha"
    r["spawn_mode"] = f.get("spawn_mode") if f.get("spawn_mode") in ("same-dir", "worktree", "session") else "same-dir"
    pm = f.get("permission_mode", "")
    r["permission_mode"] = pm if pm in ("", "default", "acceptEdits", "plan", "bypassPermissions") else ""
    cap = f.get("capacity", "").strip()
    r["capacity"] = cap if cap.isdigit() else ""
    r["autostart"] = f.get("autostart") == "on"
    r["verbose"] = f.get("verbose") == "on"
    save_settings(settings)
    flash(t("common.saved_restart") if rc.running() else t("common.saved"), "ok")
    return redirect(url_for("claude_page") + "#rc")


@app.route("/settings/lang", methods=["POST"])
@login_required
def settings_lang():
    lang = request.form.get("lang", "")
    settings["lang"] = lang if lang in I18N else ""
    save_settings(settings)
    g.pop("lang", None)
    sync_claude_md()
    flash(t("lang.saved"), "ok")
    return redirect(url_for("backup"))


@app.route("/settings/ha", methods=["POST"])
@login_required
def settings_ha():
    settings["ha"]["url"] = request.form.get("url", "").strip().rstrip("/")
    tok = request.form.get("token", "").strip()
    if request.form.get("clear_token") == "on":
        settings["ha"]["token"] = ""
    elif tok:
        settings["ha"]["token"] = tok
    save_settings(settings)
    flash(t("ha.saved"), "ok")
    return redirect(url_for("settings_page") + "#ha")


@app.route("/settings/ha/test", methods=["POST"])
@login_required
def settings_ha_test():
    ok, msg = ha_check()
    flash(t("ha.test_ok", msg=msg) if ok else msg, "ok" if ok else "error")
    return redirect(url_for("settings_page") + "#ha")


def ha_check(timeout=10):
    url, token, _ = ha_endpoints()
    if not url or not token:
        return False, t("ha.check_missing")
    try:
        req = urllib.request.Request(url + "/api/config", headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.load(r)
        return True, f"Home Assistant {d.get('version')} ({d.get('location_name')})"
    except urllib.error.HTTPError as e:
        return False, t("ha.check_http", code=e.code, url=url)
    except Exception as e:
        return False, t("ha.check_fail", url=url, err=e)


def ssh_check(timeout=25):
    write_ssh_config()
    code, out = run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", "ha",
                     "echo OK: $(whoami)@$(hostname)"], timeout=timeout)
    if code == 0:
        return True, out
    if "IDENTIFICATION HAS CHANGED" in out or "Host key verification failed" in out:
        return False, t("ssh.hostkey_changed_short")
    return False, t("ssh.check_fail", code=code, out=out[-500:])


@app.route("/settings/ssh/forget", methods=["POST"])
@login_required
def settings_ssh_forget():
    s = settings["ssh"]
    port = int(s["port"] or 22)
    names = [s["host"]] if port == 22 else [f"[{s['host']}]:{port}"]
    known = f"{SSH_DIR}/known_hosts"
    if os.path.exists(known):
        for name in names:
            run(["ssh-keygen", "-R", name, "-f", known])
    flash(t("ssh.forgotten"), "ok")
    return redirect(url_for("settings_page") + "#ssh")


@app.route("/settings/ssh", methods=["POST"])
@login_required
def settings_ssh():
    s = settings["ssh"]
    s["host"] = request.form.get("host", "").strip() or DEFAULTS["ssh"]["host"]
    port = request.form.get("port", "22").strip()
    s["port"] = int(port) if port.isdigit() else 22
    s["user"] = request.form.get("user", "").strip() or "hassio"
    s["auto_hostkey"] = request.form.get("auto_hostkey") == "on"
    save_settings(settings)
    write_ssh_config()
    flash(t("common.saved"), "ok")
    return redirect(url_for("settings_page") + "#ssh")


@app.route("/settings/ssh/generate", methods=["POST"])
@login_required
def settings_ssh_generate():
    old = ssh_public_key()
    code, out = generate_ssh_key()
    if code == 0:
        flash(t("ssh.generated") + ssh_addon_replace_key(old), "ok")
    else:
        flash(t("common.error", err=out), "error")
    return redirect(url_for("settings_page") + "#ssh")


@app.route("/settings/ssh/import", methods=["POST"])
@login_required
def settings_ssh_import():
    key = request.form.get("private_key", "").strip().replace("\r", "")
    if key and not key.startswith("-----BEGIN"):
        try:  # also accepts the key as one-line base64
            key = base64.b64decode(key).decode().strip()
        except Exception:
            pass
    if not key.startswith("-----BEGIN"):
        flash(t("ssh.not_privkey"), "error")
        return redirect(url_for("settings_page") + "#ssh")
    tmp = SSH_KEY + ".new"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(key + "\n")
    code, pub = run(["ssh-keygen", "-y", "-f", tmp])
    if code != 0:
        os.remove(tmp)
        flash(t("ssh.invalid_key", err=pub), "error")
    else:
        old = ssh_public_key()
        os.replace(tmp, SSH_KEY)
        with open(SSH_KEY + ".pub", "w") as f:
            f.write(pub.strip() + "\n")
        flash(t("ssh.imported") + ssh_addon_replace_key(old), "ok")
    return redirect(url_for("settings_page") + "#ssh")


@app.route("/settings/ssh/test", methods=["POST"])
@login_required
def settings_ssh_test():
    ok, out = ssh_check()
    settings["ssh"]["verified"] = ok
    save_settings(settings)
    flash(t("ssh.test_ok", out=out) if ok else t("ssh.test_fail", out=out), "ok" if ok else "error")
    if request.form.get("next") == "index":
        return redirect(url_for("index"))
    return redirect(url_for("settings_page") + "#ssh")


@app.route("/ssh/connect", methods=["POST"])
@login_required
def ssh_connect():
    try:
        ok, out = ssh_addon_connect()
    except Exception as e:
        ok, out = False, str(e)
    flash(t("ssh.connected", out=out) if ok else t("ssh.connect_fail", out=out), "ok" if ok else "error")
    if request.form.get("next") == "index":
        return redirect(url_for("index"))
    return redirect(url_for("settings_page") + "#ssh")


@app.route("/ssh/dismiss", methods=["POST"])
@login_required
def ssh_dismiss():
    settings["ssh"]["dismissed"] = True
    save_settings(settings)
    flash(t("ssh.dismissed"), "ok")
    return redirect(url_for("index"))


@app.route("/settings/env", methods=["POST"])
@login_required
def settings_env():
    env, bad = {}, []
    for line in request.form.get("env", "").replace("\r", "").split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        k, sep, v = line.partition("=")
        k = k.strip()
        if not sep or not ENV_KEY_RE.match(k) or k in BLOCKED_ENV:
            bad.append(k or line)
            continue
        env[k] = v
    settings["env"] = env
    save_settings(settings)
    flash(t("env.saved", ignored=t("env.ignored", list=", ".join(bad)) if bad else ""), "error" if bad else "ok")
    return redirect(url_for("settings_page") + "#env")


# --- CLAUDE.md
@app.route("/claudemd", methods=["GET", "POST"])
@login_required
def claudemd():
    if request.method == "POST":
        text = request.form.get("text", "").replace("\r\n", "\n")
        with open(CLAUDE_MD, "w", encoding="utf-8") as f:
            f.write(text)
        flash(t("claudemd.saved"), "ok")
        return redirect(url_for("claudemd"))
    sync_claude_md()
    with open(CLAUDE_MD, encoding="utf-8") as f:
        text = f.read()
    return render_template("claudemd.html", text=text)


@app.route("/claudemd/reset", methods=["POST"])
@login_required
def claudemd_reset():
    with open(CLAUDE_MD, "w", encoding="utf-8") as f:
        f.write(default_claude_md())
    flash(t("claudemd.restored"), "ok")
    return redirect(url_for("claudemd"))


# --- Backup
BACKUP_ITEMS = ["settings.json", "claude", "home", "workspace/CLAUDE.md"]


@app.route("/backup")
@login_required
def backup():
    return render_template("backup.html", reset_word=t("backup.reset_word"))


@app.route("/backup/download")
@login_required
def backup_download():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for item in BACKUP_ITEMS:
            p = os.path.join(CONFIG, item)
            if os.path.exists(p):
                tar.add(p, arcname=item)
    buf.seek(0)
    name = time.strftime("claudeforha-%Y%m%d-%H%M%S.tar.gz")
    return send_file(buf, mimetype="application/gzip", as_attachment=True, download_name=name)


@app.route("/backup/restore", methods=["POST"])
@login_required
def backup_restore():
    global settings
    f = request.files.get("file")
    if not f:
        flash(t("backup.no_file"), "error")
        return redirect(url_for("backup"))
    try:
        with tarfile.open(fileobj=io.BytesIO(f.read()), mode="r:gz") as tar:
            members = []
            for m in tar.getmembers():
                n = os.path.normpath(m.name)
                if n.startswith(("/", "..")) or not (m.isfile() or m.isdir()) or \
                        not any(n == i or n.startswith(i + "/") for i in BACKUP_ITEMS):
                    continue
                members.append(m)
            rc.stop()
            for m in members:
                tar.extract(m, CONFIG)
    except Exception as e:
        flash(t("backup.restore_fail", err=e), "error")
        return redirect(url_for("backup"))
    settings = load_settings()
    ensure_workspace()
    claude_auth(force=True)
    if settings["rc"]["autostart"]:
        rc.start()
    session.clear()
    flash(t("backup.restored", n=len(members)), "ok")
    return redirect(url_for("login"))


@app.route("/reset", methods=["POST"])
@login_required
def factory_reset():
    """Return the add-on to its initial state: log out of claude.ai and delete all of /config."""
    global settings
    words = {I18N[lang].get("backup.reset_word", "").upper() for lang in LANGS} - {""}
    if request.form.get("confirm", "").strip().upper() not in words:
        flash(t("backup.reset_need_word", word=t("backup.reset_word")), "error")
        return redirect(url_for("backup"))
    rc.stop()
    login_flow.cancel()
    code, out = run(["claude", "auth", "logout"])
    log(f"Full reset. claude.ai logout: {out or code}")
    lang = current_lang()
    for name in os.listdir(CONFIG):
        p = os.path.join(CONFIG, name)
        if os.path.isdir(p) and not os.path.islink(p):
            shutil.rmtree(p, ignore_errors=True)
        else:
            os.remove(p)
    settings = load_settings()
    app.secret_key = settings["secret_key"]  # invalidates every web session
    ensure_workspace()
    _auth_cache["t"] = 0
    rc.want = bool(settings["rc"]["autostart"])
    session.clear()
    flash(t("backup.reset_done", _lang=lang), "ok")
    return redirect(url_for("login"))


@app.errorhandler(400)
def bad_request(e):
    return f"<p>{e.description}</p><p><a href='javascript:history.back()'>{t('common.back')}</a></p>", 400


# ---------------------------------------------------------------- main
def shutdown(signum, frame):
    log("Stopping…")
    try:
        rc.stop()
    finally:
        os._exit(0)


def main():
    global settings
    os.makedirs(CONFIG, exist_ok=True)
    settings = load_settings()
    app.secret_key = settings["secret_key"]
    ensure_workspace()
    if select_claude():
        log(f"Using the downloaded Claude Code: {claude_version()}")
    if not claude_installed():
        ensure_claude()
    if settings["password_hash"] is None:
        log("First access: web password = 'admin' (you will be asked to change it).")
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    if settings["rc"]["autostart"]:
        rc.want = True
    threading.Thread(target=watchdog, daemon=True).start()
    log(f"Web UI on http://0.0.0.0:{PORT} (and via Ingress)")
    from waitress import serve
    serve(app, host="0.0.0.0", port=PORT, threads=8, ident="claudeforha")


if __name__ == "__main__":
    main()
