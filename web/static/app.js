(() => {
  "use strict";

  const groupsEl = document.getElementById("groups");
  const ledEl = document.getElementById("led");
  const statusTextEl = document.getElementById("statusText");
  const engineBtn = document.getElementById("engineBtn");
  const transposeEl = document.getElementById("transpose");
  const transposeValEl = document.getElementById("transposeVal");

  let engineRunning = false;

  // ---- v0.2 sync: registry of live controls + local-interaction gating --
  //
  // The engine echoes its true current value back as CC on channel 16 (see
  // host_shim.cpp's send_all_feedback/apply_cc); the server exposes that as
  // GET /state (key -> wire 0-127). We poll it and push updates into
  // whichever control owns that key -- except for a control the user is
  // *currently* touching (or just released), so a slow round-trip echo
  // doesn't visibly fight/snap back a live drag.

  const controls = {};       // key -> { syncFromServer(wire) }
  const lastLocalTs = {};    // key -> Date.now() of last local interaction
  const LOCAL_SUPPRESS_MS = 900;

  function markLocal(key) {
    lastLocalTs[key] = Date.now();
  }

  // ---- server calls, all fire-and-forget-ish with a small throttle ------

  function postJSON(path, body) {
    return fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    }).catch(() => {});
  }

  const sendCcThrottled = (() => {
    const timers = new Map();
    return (key, value) => {
      markLocal(key);
      if (timers.has(key)) clearTimeout(timers.get(key));
      timers.set(key, setTimeout(() => {
        timers.delete(key);
        postJSON("/cc", { key, value });
      }, 30));
    };
  })();

  function sendCcImmediate(key, value) {
    markLocal(key);
    postJSON("/cc", { key, value });
  }

  // ---- knob widget --------------------------------------------------

  function wireToAngle(wire) {
    // 0..127 -> -135deg..+135deg
    return -135 + (wire / 127) * 270;
  }

  function displayValue(spec, wire) {
    if (spec.kind === "int" || spec.kind === "float") {
      const v = spec.lo + (spec.hi - spec.lo) * (wire / 127);
      if (spec.fmt === "pct") return Math.round(v * 100) + "%";
      if (spec.fmt === "int" || spec.kind === "int") return Math.round(v).toString();
      return v.toFixed(2);
    }
    return "";
  }

  function makeKnob(spec) {
    const wrap = document.createElement("div");
    wrap.className = "control";

    const knob = document.createElement("div");
    knob.className = "knob";
    let wire = 64;
    knob.style.setProperty("--angle", wireToAngle(wire) + "deg");

    const label = document.createElement("div");
    label.className = "control-label";
    label.textContent = spec.label;

    const valueEl = document.createElement("div");
    valueEl.className = "control-value";
    valueEl.textContent = displayValue(spec, wire);

    function setWire(newWire, send) {
      wire = Math.max(0, Math.min(127, Math.round(newWire)));
      knob.style.setProperty("--angle", wireToAngle(wire) + "deg");
      valueEl.textContent = displayValue(spec, wire);
      if (send) sendCcThrottled(spec.key, wire);
    }

    let dragging = false, startY = 0, startWire = 64;
    const SENSITIVITY = 150; // px for full 0..127 sweep

    knob.addEventListener("pointerdown", (e) => {
      dragging = true;
      startY = e.clientY;
      startWire = wire;
      markLocal(spec.key);
      knob.setPointerCapture(e.pointerId);
    });
    knob.addEventListener("pointermove", (e) => {
      if (!dragging) return;
      const delta = (startY - e.clientY) * (127 / SENSITIVITY);
      setWire(startWire + delta, true);
    });
    function endDrag(e) {
      if (!dragging) return;
      dragging = false;
      sendCcImmediate(spec.key, wire);
    }
    knob.addEventListener("pointerup", endDrag);
    knob.addEventListener("pointercancel", endDrag);

    wrap.append(knob, label, valueEl);
    controls[spec.key] = { syncFromServer: (w) => setWire(w, false) };
    return wrap;
  }

  function makeMomentary(spec) {
    const wrap = document.createElement("div");
    wrap.className = "control";

    const pad = document.createElement("div");
    pad.className = "btn-pad";
    pad.textContent = spec.label;

    function press() {
      pad.classList.add("active");
      sendCcImmediate(spec.key, 127);
    }
    function release() {
      if (!pad.classList.contains("active")) return;
      pad.classList.remove("active");
      sendCcImmediate(spec.key, 0);
    }

    pad.addEventListener("pointerdown", (e) => { pad.setPointerCapture(e.pointerId); press(); });
    pad.addEventListener("pointerup", release);
    pad.addEventListener("pointercancel", release);
    pad.addEventListener("pointerleave", release);

    const spacer = document.createElement("div");
    spacer.className = "control-value";
    spacer.innerHTML = "&nbsp;";

    wrap.append(pad, spacer);
    // Momentary controls have no persistent value -- the server never
    // reports them in /state (see server.py's CC_TO_KEY filter) -- so
    // there's nothing to register for sync.
    return wrap;
  }

  function makeToggle(spec) {
    // A persistent on/off button (unlike makeMomentary's press-and-release
    // pad) -- click flips state, sends 127 (on) or 0 (off) once, and stays
    // lit/unlit reflecting that state. Syncs from server like a knob, so an
    // external change (another controller, engine restart) is reflected.
    const wrap = document.createElement("div");
    wrap.className = "control";

    const pad = document.createElement("div");
    pad.className = "btn-pad btn-toggle";
    pad.textContent = spec.label;

    let on = false;
    function setOn(newOn, send) {
      on = newOn;
      pad.classList.toggle("active", on);
      if (send) sendCcImmediate(spec.key, on ? 127 : 0);
    }

    pad.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      markLocal(spec.key);
      setOn(!on, true);
    });

    const spacer = document.createElement("div");
    spacer.className = "control-value";
    spacer.innerHTML = "&nbsp;";

    wrap.append(pad, spacer);
    controls[spec.key] = { syncFromServer: (wire) => setOn(wire >= 64, false) };
    return wrap;
  }

  function makeEnum(spec) {
    const wrap = document.createElement("div");
    wrap.className = "control control-enum";

    const label = document.createElement("div");
    label.className = "control-label";
    label.textContent = spec.label;

    const select = document.createElement("select");
    select.className = "enum-select";
    spec.options.forEach((text, idx) => {
      const opt = document.createElement("option");
      opt.value = String(idx);
      opt.textContent = text;
      select.appendChild(opt);
    });

    function wireToIdx(wire) {
      const n = spec.options.length;
      return Math.max(0, Math.min(n - 1, Math.round((wire / 127) * (n - 1))));
    }

    select.addEventListener("pointerdown", () => markLocal(spec.key));
    select.addEventListener("change", () => {
      const idx = parseInt(select.value, 10);
      const n = spec.options.length;
      const wire = Math.round((idx / (n - 1)) * 127);
      sendCcImmediate(spec.key, wire);
    });

    wrap.append(label, select);
    controls[spec.key] = {
      syncFromServer: (wire) => { select.value = String(wireToIdx(wire)); },
    };
    return wrap;
  }

  function makeSpacer() {
    // Empty grid cell -- used to force a row break in params.json's fixed
    // 4-column layout when a row has fewer than 4 controls (e.g. the
    // Generate/Mutate/Regen top row).
    const wrap = document.createElement("div");
    wrap.className = "control control-spacer";
    return wrap;
  }

  function buildControl(spec) {
    if (spec.kind === "spacer") return makeSpacer();
    if (spec.kind === "momentary") return makeMomentary(spec);
    if (spec.kind === "toggle") return makeToggle(spec);
    if (spec.kind === "enum") return makeEnum(spec);
    return makeKnob(spec);
  }

  // ---- layout ---------------------------------------------------------

  fetch("/params.json").then(r => r.json()).then((data) => {
    data.groups.forEach((group) => {
      const panel = document.createElement("section");
      panel.className = "panel";

      const title = document.createElement("h2");
      title.className = "panel-title";
      title.textContent = group.title;

      const grid = document.createElement("div");
      grid.className = "panel-grid";

      group.params.forEach((spec) => grid.appendChild(buildControl(spec)));

      panel.append(title, grid);
      groupsEl.appendChild(panel);
    });
  }).catch((e) => {
    groupsEl.innerHTML = '<p style="color:#900">Failed to load params.json: ' + e + '</p>';
  });

  // ---- v0.2: poll engine state and sync into controls --------------------

  function pollState() {
    fetch("/state").then(r => r.json()).then((state) => {
      const now = Date.now();
      for (const [key, wire] of Object.entries(state)) {
        if (now - (lastLocalTs[key] || 0) < LOCAL_SUPPRESS_MS) continue; // don't fight an active/recent drag
        const ctrl = controls[key];
        if (ctrl) ctrl.syncFromServer(wire);
      }
    }).catch(() => {});
  }

  // ---- transpose --------------------------------------------------------

  transposeEl.addEventListener("input", () => {
    transposeValEl.textContent = transposeEl.value;
  });
  transposeEl.addEventListener("change", () => {
    postJSON("/transpose", { semitones: parseInt(transposeEl.value, 10) });
  });

  // ---- engine status / control -----------------------------------------

  function setEngineUI(running) {
    engineRunning = running;
    ledEl.classList.toggle("led-on", running);
    ledEl.classList.toggle("led-off", !running);
    statusTextEl.textContent = running ? "ONLINE" : "OFFLINE";
    engineBtn.classList.toggle("on", !running); // red = "press to start" when off
    engineBtn.textContent = running ? "STOP" : "START";
  }

  function pollStatus() {
    fetch("/status").then(r => r.json()).then((s) => setEngineUI(!!s.engine_running))
      .catch(() => setEngineUI(false));
  }

  engineBtn.addEventListener("click", () => {
    postJSON("/engine", { action: engineRunning ? "stop" : "start" });
    setTimeout(pollStatus, 400);
  });

  setEngineUI(false);
  pollStatus();
  setInterval(pollStatus, 2000);
  setInterval(pollState, 400);
})();
