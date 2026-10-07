(function () {
  const gen = document.getElementById("plan-generate");
  const status = document.getElementById("plan-status");
  if (gen) gen.addEventListener("click", async () => {
    gen.disabled = true;
    status.hidden = false;
    status.className = "alert alert-info";
    const label = document.getElementById("planning-model");
    const name = label ? label.options[label.selectedIndex].text.split(" — ")[0].replace(" ★", "") : "the AI";
    const spin = document.createElement("span");
    spin.className = "spinner";
    status.replaceChildren(spin, ` ${name} is comparing your profile with the job market and writing your plan. This can take 1–4 minutes with the smarter models.`);
    try {
      const model = document.getElementById("planning-model");
      const effort = document.getElementById("planning-effort");
      const r = await fetch("/api/plan/generate", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: model ? model.value : "", effort: effort ? effort.value : "" }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || "Failed");
      location.href = "/plan?id=" + j.id;
    } catch (e) {
      status.className = "alert alert-error";
      status.textContent = e.message;
      gen.disabled = false;
    }
  });

  document.addEventListener("change", async (e) => {
    const sel = e.target.closest("select[data-item]");
    if (!sel) return;
    const card = document.getElementById(sel.dataset.item);
    try {
      const r = await fetch(`/api/plan/${sel.dataset.plan}/items/${sel.dataset.item}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: sel.value }),
      });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error);
      card.dataset.status = sel.value;
      card.classList.toggle("done", sel.value === "done");
      document.getElementById("progress-num").textContent = j.progress_pct + "%";
      document.getElementById("progress-bar").style.width = j.progress_pct + "%";
      const bar = document.getElementById("progress-bar").parentElement;
      if (bar) bar.setAttribute("aria-valuenow", String(j.progress_pct));
      applyFilter();
    } catch (err) { status.hidden = false; status.className = "alert alert-error"; status.textContent = "Couldn't save: " + err.message; }
  });

  const filter = document.getElementById("prio-filter");
  function applyFilter() {
    if (!filter) return;
    const show = new Set(Array.from(filter.querySelectorAll("input[value]:checked")).map(x => x.value));
    const hideDone = document.getElementById("hide-done").checked;
    document.querySelectorAll(".item").forEach(it => {
      it.classList.toggle("hide", !show.has(it.dataset.priority) || (hideDone && it.dataset.status === "done"));
    });
  }
  if (filter) filter.addEventListener("change", applyFilter);
})();
