#!/usr/bin/env python3
"""Force Acid web control panel — serves the UI and bridges browser actions
to real MIDI CC sent straight into the "Mockba Acid:In" ALSA sequencer port,
and can start/stop the force-acid engine process itself.

Deliberately stdlib-only (http.server) + mido: no node-gyp / native-module
build step needed on-device. See ../DESIGN.md and
~/.claude/skills/mockbamod-module-creator/references/web-gui.md for why.

Run: LD_LIBRARY_PATH=<path-to>/Python/libjack python3 server.py [--port N]
(the LD_LIBRARY_PATH is only needed because the bundled python-rtmidi wheel
was built with JACK support and won't import without libjack.so.0 resolvable
-- we never actually talk to JACK, we force the ALSA API explicitly below.)
"""
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import mido

WEB_DIR = Path(__file__).resolve().parent
ADDON_DIR = WEB_DIR.parent          # .../AddOns/ForceAcid on a deployed device
STATIC_DIR = WEB_DIR / "static"
PARAMS_PATH = WEB_DIR / "params.json"
ENGINE_BIN = ADDON_DIR / "force-acid"
ENGINE_CONF = ADDON_DIR / "force-acid.conf"

IN_PORT_MATCH = ("Mockba Acid", "In")
OUT_PORT_MATCH = ("Mockba Acid", "Out")

PARAMS = json.loads(PARAMS_PATH.read_text())
PARAM_BY_KEY = {p["key"]: p for g in PARAMS["groups"] for p in g["params"]}
CTRL_CHANNEL0 = PARAMS.get("control_channel", 1) - 1

STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
}

_lock = threading.Lock()
_midi_out = None

FEEDBACK_CHANNEL0 = 15    # v0.2: matches host_shim.cpp's FEEDBACK_CHANNEL (MIDI ch 16)
CC_TO_KEY = {p["cc"]: p["key"] for p in PARAM_BY_KEY.values() if p["kind"] != "momentary"}
_state_lock = threading.Lock()
_state = {}               # key -> last-seen wire value (0-127), from engine feedback


def _find_port(names, needles):
    for n in names:
        if all(x in n for x in needles):
            return n
    return None


def _ensure_out():
    """(Re)open the output port to Mockba Acid:In. Returns the mido port or None."""
    global _midi_out
    with _lock:
        if _midi_out is not None:
            try:
                names = mido.get_output_names()
            except Exception:
                names = []
            if _midi_out.name in names:
                return _midi_out
            try:
                _midi_out.close()
            except Exception:
                pass
            _midi_out = None

        try:
            names = mido.get_output_names()
        except Exception:
            names = []
        target = _find_port(names, IN_PORT_MATCH)
        if not target:
            return None
        try:
            _midi_out = mido.open_output(target, api="LINUX_ALSA")
        except Exception as e:
            print(f"[acid-web] failed to open {target}: {e}", file=sys.stderr)
            _midi_out = None
        return _midi_out


def _feedback_listener():
    """v0.2: background thread -- keeps an input connection to Mockba
    Acid:Out, watches for the engine's own feedback CCs (channel 16, same CC
    numbers as input -- see host_shim.cpp's send_all_feedback/apply_cc) and
    updates _state. Runs for the life of the process; reconnects whenever
    the port disappears (engine not running yet / restarted)."""
    port = None
    while True:
        if port is None:
            try:
                names = mido.get_input_names()
            except Exception:
                names = []
            target = _find_port(names, OUT_PORT_MATCH)
            if target:
                try:
                    port = mido.open_input(target, api="LINUX_ALSA")
                except Exception:
                    port = None
            if port is None:
                time.sleep(1.0)
                continue
        try:
            for msg in port.iter_pending():
                if msg.type == "control_change" and msg.channel == FEEDBACK_CHANNEL0:
                    key = CC_TO_KEY.get(msg.control)
                    if key:
                        with _state_lock:
                            _state[key] = msg.value
        except Exception:
            try:
                port.close()
            except Exception:
                pass
            port = None
            continue
        time.sleep(0.02)


def engine_present():
    try:
        names = mido.get_output_names()
    except Exception:
        return False
    return _find_port(names, IN_PORT_MATCH) is not None and \
        _find_port(mido.get_input_names(), OUT_PORT_MATCH) is not None


def engine_start():
    if engine_present():
        return True, "already running"
    if not ENGINE_BIN.exists():
        return False, f"binary not found: {ENGINE_BIN}"
    args = [str(ENGINE_BIN)]
    if ENGINE_CONF.exists():
        args += ["--config", str(ENGINE_CONF)]
    try:
        proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 stdin=subprocess.DEVNULL, start_new_session=True)
    except Exception as e:
        return False, str(e)
    # Reap it whenever it exits (killall from /engine stop, a crash, or the
    # process outliving this server) -- otherwise it zombies forever, since
    # nothing else waits on it.
    threading.Thread(target=proc.wait, daemon=True).start()
    for _ in range(20):  # up to ~2s for the port to register
        time.sleep(0.1)
        if engine_present():
            return True, "started"
    return False, "launched but ports did not register in time"


def engine_stop():
    subprocess.run(["killall", "force-acid"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    global _midi_out
    with _lock:
        if _midi_out is not None:
            try:
                _midi_out.close()
            except Exception:
                pass
            _midi_out = None
    return True, "stopped"


def send_cc(cc, value):
    port = _ensure_out()
    if port is None:
        return False, "engine not running / port not found"
    value = max(0, min(127, int(round(value))))
    port.send(mido.Message('control_change', channel=CTRL_CHANNEL0, control=cc, value=value))
    return True, None


def send_transpose(semitones):
    port = _ensure_out()
    if port is None:
        return False, "engine not running / port not found"
    note = max(0, min(127, 60 + int(semitones)))
    port.send(mido.Message('note_on', channel=CTRL_CHANNEL0, note=note, velocity=100))

    def _off():
        time.sleep(0.08)
        try:
            port.send(mido.Message('note_off', channel=CTRL_CHANNEL0, note=note, velocity=0))
        except Exception:
            pass
    threading.Thread(target=_off, daemon=True).start()
    return True, None


class Handler(BaseHTTPRequestHandler):
    server_version = "ForceAcidWeb/0.1"

    def log_message(self, fmt, *args):
        sys.stderr.write("[acid-web] " + (fmt % args) + "\n")

    def _json(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, relpath, content_type):
        path = STATIC_DIR / relpath
        try:
            data = path.read_bytes()
        except OSError:
            self.send_error(404, "not found")
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if relpath != "index.html":
            self.send_header("Cache-Control", "public, max-age=60")
        else:
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in STATIC_FILES:
            relpath, ctype = STATIC_FILES[path]
            self._file(relpath, ctype)
        elif path == "/params.json":
            self._json(200, PARAMS)
        elif path == "/status":
            self._json(200, {"engine_running": engine_present()})
        elif path == "/state":
            with _state_lock:
                self._json(200, dict(_state))
        else:
            self.send_error(404, "not found")

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            self._json(400, {"ok": False, "error": "bad json"})
            return

        if path == "/cc":
            key = body.get("key")
            value = body.get("value")
            spec = PARAM_BY_KEY.get(key)
            if spec is None or value is None:
                self._json(400, {"ok": False, "error": "unknown key or missing value"})
                return
            ok, err = send_cc(spec["cc"], value)
            self._json(200 if ok else 503, {"ok": ok, "error": err})

        elif path == "/transpose":
            semis = body.get("semitones", 0)
            ok, err = send_transpose(semis)
            self._json(200 if ok else 503, {"ok": ok, "error": err})

        elif path == "/engine":
            action = body.get("action")
            if action == "start":
                ok, msg = engine_start()
            elif action == "stop":
                ok, msg = engine_stop()
            else:
                self._json(400, {"ok": False, "error": "action must be start|stop"})
                return
            self._json(200 if ok else 503, {"ok": ok, "message": msg})

        else:
            self.send_error(404, "not found")


def main():
    port = 8303
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    threading.Thread(target=_feedback_listener, daemon=True).start()
    srv = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"[acid-web] serving on http://0.0.0.0:{port}  (engine dir: {ADDON_DIR})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
