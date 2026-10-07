(function () {
  const root = document.getElementById("profile-root");
  if (!root) return;
  let state = JSON.parse(document.getElementById("profile-data").textContent);
  const opts = JSON.parse(document.getElementById("profile-options").textContent);
  let dirty = false;

  const esc = (v) => String(v == null ? "" : v).replace(/[&<>"']/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
  const skillLevelOpts = Object.entries(opts.skill_levels).map(([k, v]) => [Number(k), v]);
  const langLevelOpts = [["", "Not sure"]].concat(opts.language_levels.map(l => [l, l === "native" ? "Native" : l]));
  const eduStatusOpts = [["completed", "Completed"], ["in_progress", "In progress"], ["planned", "Planned / accepted"]];

  // Field definitions for repeatable sections.
  const LISTS = {
    skills: {
      title: "Skills", noun: "skill", layout: "row", hint: "Technical skills, tools and methods. Be honest about the level: the plan builds on it.",
      blank: () => ({ name: "", level: 2, years: null }),
      fields: [
        { k: "name", label: "Skill", placeholder: "e.g. C#, SQL, Docker" },
        { k: "level", label: "Level", type: "select", options: skillLevelOpts, num: true },
        { k: "years", label: "Years", type: "number", step: "0.5" },
      ],
    },
    languages: {
      title: "Languages", noun: "language", layout: "row", hint: "CEFR level, from A1 (beginner) to C2 (mastery). Your German level matters a lot in Austria.",
      blank: () => ({ language: "", level: "" }),
      fields: [
        { k: "language", label: "Language", placeholder: "e.g. German" },
        { k: "level", label: "Level", type: "select", options: langLevelOpts },
      ],
    },
    experience: {
      title: "Work experience", noun: "job", layout: "entry", hint: "Jobs and internships, most recent first.",
      blank: () => ({ title: "", company: "", start: "", end: "", current: false, technologies: [], description: "" }),
      fields: [
        { k: "title", label: "Job title" }, { k: "company", label: "Company" },
        { k: "start", label: "Start", placeholder: "2024-07" }, { k: "end", label: "End", placeholder: "2025-06" },
        { k: "current", label: "I work here now", type: "checkbox" },
        { k: "technologies", label: "Technologies (comma-separated)", type: "list", full: true },
        { k: "description", label: "What you did", type: "textarea", full: true },
      ],
    },
    education: {
      title: "Education", noun: "education", layout: "entry", hint: "",
      blank: () => ({ degree: "", field: "", institution: "", start: "", end: "", status: "completed" }),
      fields: [
        { k: "degree", label: "Degree", placeholder: "BSc, MSc…" }, { k: "field", label: "Field", placeholder: "Software Engineering" },
        { k: "institution", label: "Institution" }, { k: "status", label: "Status", type: "select", options: eduStatusOpts },
        { k: "start", label: "Start", placeholder: "2020" }, { k: "end", label: "End", placeholder: "2024" },
      ],
    },
    certifications: {
      title: "Certifications", noun: "certificate", layout: "row", hint: "",
      blank: () => ({ name: "", issuer: "", year: "" }),
      fields: [{ k: "name", label: "Certificate" }, { k: "issuer", label: "Issuer" }, { k: "year", label: "Year" }],
    },
    projects: {
      title: "Projects", noun: "project", layout: "entry", hint: "Side projects, your thesis, open source: anything that shows your skills.",
      blank: () => ({ name: "", technologies: [], url: "", description: "" }),
      fields: [
        { k: "name", label: "Project" }, { k: "url", label: "Link" },
        { k: "technologies", label: "Technologies (comma-separated)", type: "list", full: true },
        { k: "description", label: "Description", type: "textarea", full: true },
      ],
    },
  };

  function input(path, f, value) {
    const common = `data-path="${path}" ${f.num ? 'data-num="1"' : ""} ${f.type === "list" ? 'data-list="1"' : ""} aria-label="${esc(f.label)}"`;
    if (f.type === "select") {
      return `<select ${common}>${f.options.map(([v, t]) => `<option value="${esc(v)}" ${String(v) === String(value ?? "") ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>`;
    }
    if (f.type === "textarea") return `<textarea rows="3" ${common}>${esc(value)}</textarea>`;
    if (f.type === "checkbox") return `<label class="check"><input type="checkbox" ${common} ${value ? "checked" : ""}> ${esc(f.label)}</label>`;
    if (f.type === "number") return `<input type="number" min="0" step="${f.step || 1}" ${common} value="${value == null ? "" : esc(value)}" data-numnull="1">`;
    const v = f.type === "list" ? (value || []).join(", ") : value;
    return `<input type="text" ${common} value="${esc(v)}" placeholder="${esc(f.placeholder || "")}">`;
  }

  function listSection(key) {
    const def = LISTS[key];
    const items = state[key] || [];
    let body;
    if (def.layout === "row") {
      const head = `<div class="row row-${key} row-head">${def.fields.map(f => `<span>${esc(f.label)}</span>`).join("")}<span></span></div>`;
      body = head + items.map((it, i) => `<div class="row row-${key}">${def.fields.map(f => input(`${key}.${i}.${f.k}`, f, it[f.k])).join("")}
          ${removeBtn(key, i, it)}</div>`).join("");
      if (!items.length) body = `<p class="hint">None yet.</p>`;
    } else {
      body = items.map((it, i) => `<div class="entry">${def.fields.map(f => f.type === "checkbox"
          ? `<div class="field" style="align-self:end">${input(`${key}.${i}.${f.k}`, f, it[f.k])}</div>`
          : `<label class="field ${f.full ? "full" : ""}"><span>${esc(f.label)}</span>${input(`${key}.${i}.${f.k}`, f, it[f.k])}</label>`).join("")}
          ${removeBtn(key, i, it, "remove")}</div>`).join("") || `<p class="hint">None yet.</p>`;
    }
    const quick = key === "skills" ? `<div class="form-inline" style="margin-top:16px"><input type="text" id="quick-skills" aria-label="Add several skills" placeholder="Add several: Docker, Git, Python" style="flex:1"><button type="button" class="btn-small btn-secondary" data-quick>Add all</button></div>` : "";
    return `<section class="card"><div class="section-head"><h2>${def.title}</h2><button type="button" class="btn-small btn-secondary" data-add="${key}">Add ${def.noun}</button></div>
      ${def.hint ? `<p class="card-note">${def.hint}</p>` : ""}<div class="rows">${body}</div>${quick}</section>`;
  }

  function removeBtn(key, i, item, extra) {
    const name = item.name || item.language || item.title || item.degree || "";
    return `<button type="button" class="btn-icon ${extra || ""}" data-remove="${key}.${i}" aria-label="Remove ${esc(name || LISTS[key].noun)}" title="Remove">
      <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><path d="M2 2l8 8M10 2l-8 8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg></button>`;
  }

  function picks(name, options, selected, exclude) {
    return `<div class="pick">${Object.entries(options).filter(([k]) => !(exclude || []).includes(k)).map(([k, v]) =>
      `<label><input type="checkbox" data-pick="${name}" value="${k}" ${selected.includes(k) ? "checked" : ""}>${esc(v)}</label>`).join("")}</div>`;
  }

  function render() {
    const s = state;
    root.innerHTML = `
      <section class="card">
        <h2>About you</h2>
        <div class="grid grid-3" style="gap:16px">
          <label class="field"><span>Name</span>${input("name", {}, s.name)}</label>
          <label class="field"><span>Headline</span>${input("headline", { placeholder: "Junior Software Engineer (.NET)" }, s.headline)}</label>
          <label class="field"><span>Location</span>${input("location", { placeholder: "Vienna" }, s.location)}</label>
          <label class="field"><span>GitHub</span>${input("links.github", {}, s.links.github)}</label>
          <label class="field"><span>LinkedIn</span>${input("links.linkedin", {}, s.links.linkedin)}</label>
          <label class="field"><span>Portfolio</span>${input("links.portfolio", {}, s.links.portfolio)}</label>
        </div>
        <label class="field" style="margin-top:16px"><span>Career goal or summary</span>${input("summary", { type: "textarea" }, s.summary)}</label>
      </section>
      <section class="card">
        <h2>What you're looking for</h2>
        <div class="form-row" role="group" aria-label="Target roles"><span class="field-label">Target roles</span>${picks("target_categories", opts.categories, s.target_categories, ["other"])}</div>
        <div class="form-row" role="group" aria-label="Target level"><span class="field-label">Target level</span>${picks("target_seniorities", opts.seniorities, s.target_seniorities, ["unspecified"])}</div>
        <div class="form-row" role="group" aria-label="Contract type"><span class="field-label">Contract type</span>${picks("target_job_types", opts.job_types, s.target_job_types, ["unspecified"])}</div>
        <div class="grid grid-3" style="gap:16px">
          <label class="field"><span>Preferred locations</span>${input("preferred_locations", { placeholder: "Vienna, remote" }, s.preferred_locations)}</label>
          <label class="field"><span>Hours per week for learning</span>${input("weekly_hours", { type: "number", num: true }, s.weekly_hours)}</label>
          <label class="field"><span>Want a job within (months)</span>${input("timeline_months", { type: "number", num: true }, s.timeline_months)}</label>
        </div>
      </section>
      <div class="grid grid-2" style="align-items:start">${listSection("skills")}${listSection("languages")}</div>
      ${listSection("experience")}${listSection("education")}
      <div class="grid grid-2" style="align-items:start">${listSection("certifications")}${listSection("projects")}</div>`;
  }

  function setPath(path, value) {
    const parts = path.split(".");
    let obj = state;
    for (let i = 0; i < parts.length - 1; i++) obj = obj[/^\d+$/.test(parts[i]) ? Number(parts[i]) : parts[i]];
    obj[parts[parts.length - 1]] = value;
  }

  function markDirty() {
    dirty = true;
    document.getElementById("save-status").textContent = "Unsaved changes";
  }

  root.addEventListener("input", (e) => {
    const el = e.target;
    if (el.dataset.path) {
      let v = el.type === "checkbox" ? el.checked : el.value;
      if (el.dataset.list) v = v.split(",").map(x => x.trim()).filter(Boolean);
      else if (el.dataset.numnull) v = v === "" ? null : Number(v);
      else if (el.dataset.num) v = Number(v);
      setPath(el.dataset.path, v);
      markDirty();
    } else if (el.dataset.pick) {
      state[el.dataset.pick] = Array.from(root.querySelectorAll(`[data-pick="${el.dataset.pick}"]:checked`)).map(x => x.value);
      markDirty();
    }
  });
  root.addEventListener("change", (e) => { if (e.target.tagName === "SELECT" || e.target.type === "checkbox") e.target.dispatchEvent(new Event("input", { bubbles: true })); });

  root.addEventListener("click", (e) => {
    const add = e.target.closest("[data-add]");
    const rem = e.target.closest("[data-remove]");
    if (add) {
      const key = add.dataset.add;
      state[key] = (state[key] || []).concat([LISTS[key].blank()]);
      markDirty(); render();
      const rows = root.querySelectorAll(`[data-path^="${key}.${state[key].length - 1}."]`);
      if (rows[0]) rows[0].focus();
    } else if (rem) {
      const [key, idx] = rem.dataset.remove.split(".");
      state[key].splice(Number(idx), 1);
      markDirty(); render();
    } else if (e.target.closest("[data-quick]")) {
      const box = document.getElementById("quick-skills");
      const have = new Set(state.skills.map(s => s.name.toLowerCase()));
      box.value.split(",").map(x => x.trim()).filter(Boolean).forEach(n => {
        if (!have.has(n.toLowerCase())) { state.skills.push({ name: n, level: 2, years: null }); have.add(n.toLowerCase()); }
      });
      markDirty(); render();
    }
  });

  async function save() {
    const btn = document.getElementById("profile-save");
    btn.disabled = true;
    try {
      const r = await fetch("/api/profile", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(state) });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || "Save failed");
      state = j.profile; dirty = false; render();
      document.getElementById("save-status").textContent = "Profile saved.";
    } catch (e) {
      document.getElementById("save-status").textContent = "Couldn't save: " + e.message;
    } finally { btn.disabled = false; }
  }
  document.getElementById("profile-save").addEventListener("click", save);

  const importBtn = document.getElementById("cv-import");
  importBtn.addEventListener("click", async () => {
    const file = document.getElementById("cv-file").files[0];
    const status = document.getElementById("cv-status");
    if (!file) { status.textContent = "Choose your CV file first."; return; }
    const fd = new FormData(); fd.append("file", file);
    importBtn.disabled = true;
    const spin = document.createElement("span");
    spin.className = "spinner";
    status.replaceChildren(spin, " Reading your CV with AI. This takes 20–60 seconds.");
    try {
      const r = await fetch("/api/profile/cv", { method: "POST", body: fd });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || "Import failed");
      state = j.profile; render(); markDirty();
      const f = j.found;
      status.textContent = `Found ${f.experience} jobs, ${f.education} degrees, ${f.skills} skills, ${f.languages} languages, ${f.certifications} certificates, ${f.projects} projects. Check everything below, especially skill levels, then save your profile.`;
    } catch (e) {
      status.textContent = e.message;
    } finally { importBtn.disabled = false; }
  });

  window.addEventListener("beforeunload", (e) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } });
  render();
})();
