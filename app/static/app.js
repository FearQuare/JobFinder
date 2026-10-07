(function () {
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  let polling = null;
  let wasRunning = false;
  const SOURCE_LABELS = { karriere: "karriere.at", linkedin: "LinkedIn", adzuna: "Adzuna" };

  async function post(url, data) {
    const body = new FormData();
    Object.entries(data || {}).forEach(([k, v]) => v != null && body.append(k, v));
    const r = await fetch(url, { method: "POST", body });
    const json = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(json.error || json.message || ("HTTP " + r.status));
    return json;
  }

  function describe(s) {
    if (!s || s.status === "idle") return "";
    const c = s.counters || {};
    if (s.status === "running") {
      if (s.phase === "analysing") return `AI analysis: ${c.analysed}/${c.analyse_total} jobs`;
      if (c.details_total) return `Collecting: ${c.seen} listings, ${c.new_jobs} new · descriptions ${c.details_done}/${c.details_total}`;
      return `Collecting: ${c.seen} listings seen, ${c.new_jobs} new`;
    }
    const verb = { done: "Finished", failed: "Failed", cancelled: "Stopped" }[s.status] || s.status;
    const bits = [];
    if (s.kind === "collect") bits.push(`${c.new_jobs} new jobs`);
    if (c.analysed) bits.push(`${c.analysed} analysed`);
    if (c.errors) bits.push(`${c.errors} warnings`);
    return `${verb}${bits.length ? ": " + bits.join(", ") : ""}`;
  }

  function progressPct(s) {
    const c = s.counters || {};
    if (s.phase === "analysing" && c.analyse_total) return 100 * c.analysed / c.analyse_total;
    if (c.details_total) return 100 * c.details_done / c.details_total;
    return s.status === "running" ? 5 : 100;
  }

  function render(s) {
    const running = s.status === "running";
    const statusEl = $("#run-status");
    if (statusEl) statusEl.textContent = describe(s);
    $$("[data-run]").forEach(b => (b.disabled = running));
    const cancelBtn = $("#run-cancel");
    if (cancelBtn) cancelBtn.hidden = !running;

    const panel = $("#run-panel");
    if (panel) {
      const hasRun = s.status && s.status !== "idle";
      panel.hidden = !hasRun;
      if (hasRun) {
        $("#run-panel-title").textContent = (s.kind === "analyze" ? "AI analysis" : "Collection") + " — " + describe(s);
        const pct = Math.round(progressPct(s));
        $("#run-progress").style.width = pct + "%";
        const bar = $("#run-panel .progress");
        if (bar) bar.setAttribute("aria-valuenow", String(pct));
        const src = s.sources || {};
        const box = $("#run-sources");
        box.replaceChildren(...Object.entries(src).map(([k, v]) => {
          const el = document.createElement("span");
          el.textContent = `${SOURCE_LABELS[k] || k}: ${v}`;
          return el;
        }));
        const log = $("#run-log");
        const atBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 20;
        log.textContent = (s.log || []).join("\n");
        if (atBottom) log.scrollTop = log.scrollHeight;
      }
    }

    if (wasRunning && !running) {
      const note = $("#run-refresh");
      if (note) note.hidden = false;
    }
    wasRunning = running;
    if (running && !polling) polling = setInterval(poll, 1500);
    if (!running && polling) { clearInterval(polling); polling = null; }
  }

  async function poll() {
    try {
      const r = await fetch("/api/runs/current");
      render(await r.json());
    } catch (e) { /* server restarting */ }
  }

  document.addEventListener("click", async (ev) => {
    const btn = ev.target.closest("[data-run]");
    if (btn) {
      ev.preventDefault();
      const kind = btn.dataset.run;
      try {
        const s = await post(kind === "analyze" ? "/api/runs/analyze" : "/api/runs/collect",
                             btn.dataset.searchId ? { search_id: btn.dataset.searchId } : {});
        render(s);
        const panel = $("#run-panel");
        if (panel) panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
      } catch (e) { alertBox(e.message); }
      return;
    }
    if (ev.target.closest("#run-cancel")) {
      ev.preventDefault();
      render(await post("/api/runs/cancel"));
      return;
    }
    const li = ev.target.closest("#linkedin-connect");
    if (li) {
      ev.preventDefault();
      li.disabled = true;
      try {
        const s = await post("/api/linkedin/connect");
        showLinkedIn(s);
        pollLinkedIn();
      } catch (e) { showLinkedIn({ status: "failed", message: e.message }); li.disabled = false; }
    }
  });

  function alertBox(msg) {
    const el = $("#flash");
    if (el) { el.textContent = msg; el.hidden = false; } else { window.alert(msg); }
  }

  function showLinkedIn(state) {
    const el = $("#linkedin-login-state");
    if (!el) return;
    el.hidden = !state || state.status === "idle";
    el.className = "alert " + (state.status === "failed" || state.status === "cancelled" ? "alert-error" : "alert-info");
    el.textContent = state.message || "";
  }

  function pollLinkedIn() {
    const t = setInterval(async () => {
      let info;
      try {
        const r = await fetch("/api/linkedin/status");
        info = await r.json();
      } catch (e) { return; /* server restarting; try again on the next tick */ }
      showLinkedIn(info.login);
      if (info.login.status !== "waiting") {
        clearInterval(t);
        if (info.login.status === "connected") setTimeout(() => location.reload(), 800);
        const b = $("#linkedin-connect"); if (b) b.disabled = false;
      }
    }, 1500);
  }

  // Auto-submit filter selects (jobs, insights).
  $$("form[data-autosubmit] select").forEach(sel => sel.addEventListener("change", () => sel.form.submit()));

  // Selects that jump to another page (earlier learning plans).
  $$("select[data-navigate]").forEach(sel => sel.addEventListener("change", () => {
    location.href = sel.dataset.navigate + encodeURIComponent(sel.value);
  }));

  // Buttons that need a confirmation before their form is submitted.
  document.addEventListener("click", (ev) => {
    const btn = ev.target.closest("[data-confirm]");
    if (btn && !window.confirm(btn.dataset.confirm)) ev.preventDefault();
  }, true);

  // Forms whose request takes a while (AI summaries): block double submits and say what's happening.
  document.addEventListener("submit", (ev) => {
    const form = ev.target;
    if (!form.matches("form[data-busy]")) return;
    const btn = ev.submitter || form.querySelector("button[type=submit]");
    if (btn) { btn.disabled = true; btn.textContent = form.dataset.busy; }
  });

  // "Back" links: go back in history when we came from this app, otherwise follow the link.
  document.addEventListener("click", (ev) => {
    const back = ev.target.closest("[data-back]");
    if (!back) return;
    let sameOrigin = false;
    try { sameOrigin = document.referrer && new URL(document.referrer).origin === location.origin; } catch (e) { /* no referrer */ }
    if (sameOrigin && history.length > 1) { ev.preventDefault(); history.back(); }
    else if (back.tagName === "BUTTON") { location.href = "/"; }
  });

  // Mobile navigation drawer.
  const toggle = $(".nav-toggle");
  const nav = $("#main-nav");
  if (toggle && nav) {
    const setOpen = (open) => { nav.classList.toggle("open", open); toggle.setAttribute("aria-expanded", String(open)); };
    toggle.addEventListener("click", () => setOpen(!nav.classList.contains("open")));
    document.addEventListener("keydown", (ev) => { if (ev.key === "Escape" && nav.classList.contains("open")) { setOpen(false); toggle.focus(); } });
    document.addEventListener("click", (ev) => { if (!ev.target.closest(".topbar")) setOpen(false); });
  }

  poll();
})();

// Settings: show the custom-model fields when "Other model…" is picked.
(function () {
  const sel = document.getElementById("planning-model");
  const box = document.getElementById("planning-custom");
  if (sel && box) sel.addEventListener("change", () => { box.hidden = sel.value !== "custom"; });
})();
