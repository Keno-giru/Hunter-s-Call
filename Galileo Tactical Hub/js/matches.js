// Galileo hub - match picker and match info.
//
// Picker: every match in datasets/catalog.json as a card (teams, competition, date, length, source, footage).
// Opening one reloads the hub on that pack, with its footage (shown picture-in-picture over 3D/2D).
// Match info: teams, competition, date, the match clock at the clip's first frame, score then, goals with
// their clock; saved next to the pack as match_info.json through tools/serve.py (local only), so the HUD shows
// the real match clock and the score at every moment of the review.

const CATALOG = "datasets/catalog.json";

function el(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k === "style") e.style.cssText = v;
    else if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2), v);
    else if (k === "value") e.value = v;
    else e.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of kids.flat()) if (c != null && c !== false) e.append(c instanceof Node ? c : String(c));
  return e;
}
const fmtLen = (s) => (s >= 3600 ? `${Math.floor(s / 3600)} h ${Math.round((s % 3600) / 60)} min` : s >= 60 ? `${Math.round(s / 60)} min` : `${Math.round(s)} s`);
const fmtDate = (iso) => {
  if (!iso) return "";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? String(iso) : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
};
const CLOCK_RX = /^\s*\d+(\+\d+)?:\d{1,2}\s*$/;

export function init(ctx) {
  const { store, bus } = ctx;
  let shell = null, overlay = null, returnFocus = null;
  ctx.need("shell").then((s) => {
    shell = s;
    s.registerCommand({ name: "matches", help: "Pick another match (gallery of every match in the dataset folder)", run: () => openPicker() });
    s.registerCommand({ name: "matchinfo", help: "Edit match info: teams, clock at the clip start, score, goals", run: () => openInfo() });
  });
  const toast = (t) => (shell ? shell.toast(t) : bus.emit("toast", { text: t }));
  const packPath = () => window.__hubPackPath || null;

  // ------------------------------------------------------------ overlay
  function close() {
    if (!overlay) return;
    overlay.remove(); overlay = null;
    document.removeEventListener("keydown", onKey, true);
    if (returnFocus && document.contains(returnFocus)) returnFocus.focus?.();
  }
  function onKey(e) { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); } }
  function show(title, body, wide) {
    close();
    returnFocus = document.activeElement;
    const x = el("button", { type: "button", class: "sh-btn sh-close", "aria-label": "Close", onclick: close }, "Esc");
    overlay = el("div", { class: "mx-scrim", onclick: (e) => { if (e.target === overlay) close(); } },
      el("div", { class: `mx-dialog${wide ? " mx-wide" : ""}`, role: "dialog", "aria-modal": "true", "aria-label": title },
        el("header", { class: "mx-head" }, el("h2", null, title), x), body));
    document.body.append(overlay);
    document.addEventListener("keydown", onKey, true);
    (overlay.querySelector("input, button.mx-card") || x).focus();
  }

  // ------------------------------------------------------------ picker
  async function openPicker() {
    let cat;
    try {
      const r = await fetch(CATALOG, { cache: "no-store" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      cat = await r.json();
    } catch (e) {
      toast(`No match catalog (${CATALOG}): ${e.message}. Build it with tools/galileo.py, or open a pack by URL.`);
      return;
    }
    const cur = packPath();
    const items = (cat.matches || []).map((m) => {
      const info = m.info || {};
      const home = info.home?.name || m.teams?.home || "Home", away = info.away?.name || m.teams?.away || "Away";
      const secs = m.frames && m.fps ? m.frames / m.fps : 0;
      const clip = (m.clips || [])[0] || null;
      const pack = `datasets/${m.dir}/${m.files?.pack || "pack.ghp.json"}`;
      const kind = String(m.source || "").startsWith("video") ? "video tracking" : m.source || "";
      return { m, info, home, away, secs, clip, pack, kind, current: cur && cur.replace(/^\.\//, "") === pack,
        text: `${home} ${away} ${info.competition || ""} ${m.source || ""} ${m.match_id}`.toLowerCase() };
    });
    const search = el("input", { type: "search", class: "mx-search", placeholder: "Search teams, competition, source…", "aria-label": "Search matches" });
    const grid = el("div", { class: "mx-grid", role: "list" });
    const render = () => {
      const q = search.value.trim().toLowerCase();
      const list = items.filter((it) => !q || q.split(/\s+/).every((w) => it.text.includes(w)));
      grid.replaceChildren(...(list.length ? list.map(card) : [el("p", { class: "sh-empty" }, "No match matches that search.")]));
    };
    const card = (it) => {
      const sc = it.info.score_final || it.m.score;
      return el("button", { type: "button", class: `mx-card${it.current ? " is-current" : ""}`, role: "listitem",
        title: `${it.home} v ${it.away}${it.clip ? " · opens with its footage" : ""}`, onclick: () => openMatch(it) },
        el("span", { class: "mx-thumb", "aria-hidden": "true" },
          it.clip?.thumb ? el("img", { src: `datasets/${it.clip.dir}/${it.clip.thumb}`, alt: "", loading: "lazy" }) : (it.clip ? "▶" : "◎"),
          el("span", { class: "mx-len" }, it.secs ? fmtLen(it.secs) : "")),
        el("span", { class: "mx-title" }, el("b", null, it.home), el("span", { class: "mx-v" }, sc ? ` ${sc[0]}–${sc[1]} ` : " v "), el("b", null, it.away)),
        el("span", { class: "mx-meta" }, [it.info.competition, fmtDate(it.info.date || it.m.date)].filter(Boolean).join(" · ") || it.m.match_id),
        el("span", { class: "mx-chips" },
          it.kind ? el("span", { class: "mx-chip" }, it.kind) : null,
          it.clip ? el("span", { class: "mx-chip mx-chip-on" }, `footage${(it.m.clips || []).length > 1 ? " ×" + it.m.clips.length : ""}`) : el("span", { class: "mx-chip" }, "no footage"),
          it.info.home ? el("span", { class: "mx-chip mx-chip-on" }, "match info") : null,
          it.current ? el("span", { class: "mx-chip mx-chip-cur" }, "open now") : null));
    };
    search.addEventListener("input", render);
    render();
    show(`Matches (${items.length})`, el("div", { class: "mx-body" }, search, grid,
      el("p", { class: "mx-note" }, "Matches come from datasets/ (convert, ingest + track, or the SoccerTrack import). Opening one reloads the hub; footage opens picture-in-picture over the 3D and 2D views.")), true);
  }
  function openMatch(it) {
    const q = new URLSearchParams({ pack: it.pack });
    if (it.clip) q.set("footage", `datasets/${it.clip.dir}/${it.clip.file}`);
    const v = store.get("view");
    if (v && v !== "video") q.set("view", v);
    location.assign(`index.html?${q.toString()}`);
  }

  // ------------------------------------------------------------ match info editor
  function openInfo() {
    const r = store.get("replay");
    if (!r) return;
    const pack = packPath();
    const info = JSON.parse(JSON.stringify(r.meta.match_info || {}));
    const m = r.meta || {};
    const inp = (v, attrs = {}) => el("input", { type: "text", value: v ?? "", ...attrs });
    const f = {
      hn: inp(info.home?.name ?? (m.home?.name !== "Home (video)" ? m.home?.name : ""), { placeholder: "Home team", "aria-label": "Home team name" }),
      hs: inp(info.home?.short ?? "", { placeholder: "HOM", maxlength: 4, class: "mx-short", "aria-label": "Home short name" }),
      an: inp(info.away?.name ?? (m.away?.name !== "Away (video)" ? m.away?.name : ""), { placeholder: "Away team", "aria-label": "Away team name" }),
      as: inp(info.away?.short ?? "", { placeholder: "AWY", maxlength: 4, class: "mx-short", "aria-label": "Away short name" }),
      comp: inp(info.competition ?? m.competition ?? "", { placeholder: "Competition, season", "aria-label": "Competition" }),
      date: el("input", { type: "date", value: (info.date || m.date || "").slice(0, 10), "aria-label": "Match date" }),
      venue: inp(info.venue ?? m.stadium ?? "", { placeholder: "Stadium", "aria-label": "Venue" }),
      per: el("select", { "aria-label": "Period at the first frame" }, [1, 2, 3, 4].map((p) => el("option", { value: p }, ["1st half", "2nd half", "ET 1", "ET 2"][p - 1]))),
      clock: inp(info.clock?.clock ?? "", { placeholder: "mm:ss, e.g. 48:17", class: "mx-clock", "aria-label": "Match clock at the first frame" }),
      s0h: el("input", { type: "number", min: 0, value: info.score_start?.[0] ?? 0, class: "mx-num", "aria-label": "Home goals at the clip start" }),
      s0a: el("input", { type: "number", min: 0, value: info.score_start?.[1] ?? 0, class: "mx-num", "aria-label": "Away goals at the clip start" }),
      sfh: el("input", { type: "number", min: 0, value: info.score_final?.[0] ?? "", class: "mx-num", "aria-label": "Final home goals" }),
      sfa: el("input", { type: "number", min: 0, value: info.score_final?.[1] ?? "", class: "mx-num", "aria-label": "Final away goals" }),
      notes: el("textarea", { rows: 2, placeholder: "Notes (optional)", "aria-label": "Notes" }),
    };
    f.per.value = String(info.clock?.period ?? 1);
    f.notes.value = info.notes ?? "";
    const goals = el("div", { class: "mx-goals" });
    const goalRow = (g = {}) => {
      const team = el("select", { "aria-label": "Team" }, el("option", { value: "home" }, "Home"), el("option", { value: "away" }, "Away"));
      team.value = g.team === "away" ? "away" : "home";
      const per = el("select", { "aria-label": "Period" }, [1, 2, 3, 4].map((p) => el("option", { value: p }, ["1H", "2H", "ET1", "ET2"][p - 1])));
      per.value = String(g.period ?? 1);
      const clock = inp(g.clock ?? "", { placeholder: "67:30", class: "mx-clock", "aria-label": "Goal clock" });
      const who = inp(g.scorer ?? "", { placeholder: "Scorer (optional)", "aria-label": "Scorer" });
      const row = el("div", { class: "mx-goal" }, team, per, clock, who,
        el("button", { type: "button", class: "sh-x", "aria-label": "Remove goal", onclick: () => row.remove() }, "×"));
      row._get = () => ({ team: team.value, period: +per.value, clock: clock.value.trim(), ...(who.value.trim() ? { scorer: who.value.trim() } : {}) });
      return row;
    };
    for (const g of info.goals || []) goals.append(goalRow(g));
    const err = el("p", { class: "mx-err", role: "alert" });
    const collect = () => {
      const num = (x) => (x.value === "" ? null : Math.max(0, Math.round(+x.value)));
      const out = {
        home: { name: f.hn.value.trim(), short: f.hs.value.trim().toUpperCase() },
        away: { name: f.an.value.trim(), short: f.as.value.trim().toUpperCase() },
        competition: f.comp.value.trim(), date: f.date.value, venue: f.venue.value.trim(),
        clock: f.clock.value.trim() ? { period: +f.per.value, clock: f.clock.value.trim() } : null,
        score_start: [num(f.s0h) ?? 0, num(f.s0a) ?? 0],
        goals: [...goals.children].map((r) => r._get()).filter((g) => g.clock),
        score_final: num(f.sfh) != null && num(f.sfa) != null ? [num(f.sfh), num(f.sfa)] : null,
        notes: f.notes.value.trim(),
      };
      const bad = [];
      if (out.clock && !CLOCK_RX.test(out.clock.clock)) bad.push("clip start clock must look like 48:17");
      out.goals.forEach((g, i) => { if (!CLOCK_RX.test(g.clock)) bad.push(`goal ${i + 1}: clock must look like 67:30`); });
      for (const k of Object.keys(out)) if (out[k] == null || out[k] === "") delete out[k];
      return { out, bad };
    };
    async function save() {
      const { out, bad } = collect();
      if (bad.length) { err.textContent = bad.join(" · "); return; }
      err.textContent = "";
      if (!pack) { download(out); return; }
      try {
        const res = await fetch("/api/match-info", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pack, info: out }) });
        const j = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(j.error || `HTTP ${res.status}`);
        r.meta.match_info = out;
        store.set("matchinfo", Date.now());
        toast(`Match info saved (${j.file})`);
        close();
      } catch (e) {
        err.textContent = `Could not save through the hub server (${e.message}). Restart tools/serve.py, or download the file and put it next to the pack.`;
      }
    }
    function download(out) {
      const a = el("a", { href: URL.createObjectURL(new Blob([JSON.stringify(out, null, 1)], { type: "application/json" })), download: "match_info.json" });
      document.body.append(a); a.click(); a.remove();
      toast("match_info.json downloaded: save it next to pack.ghp.json");
    }
    const row = (label, ...kids) => el("label", { class: "mx-row" }, el("span", null, label), el("span", { class: "mx-fields" }, ...kids));
    const body = el("form", { class: "mx-body mx-form", onsubmit: (e) => { e.preventDefault(); save(); } },
      el("p", { class: "mx-note" }, pack ? `Saved next to ${pack} as match_info.json (stays on this PC; datasets/ is never pushed).` : "This hub was opened without a pack path: saving downloads match_info.json."),
      row("Home", f.hn, f.hs), row("Away", f.an, f.as), row("Competition", f.comp), row("Date · venue", f.date, f.venue),
      el("h3", null, "Clock and score"),
      row("First frame at", f.per, f.clock),
      el("p", { class: "mx-note" }, "The match clock on the broadcast at the clip's first frame (the 2nd half starts at 45:00). The HUD then shows the real clock and the score at every moment."),
      row("Score at that moment", f.s0h, el("span", null, "–"), f.s0a),
      el("h3", null, "Goals"), goals,
      el("button", { type: "button", class: "sh-btn", onclick: () => goals.append(goalRow({ period: +f.per.value })) }, "+ Add goal"),
      row("Final score (optional)", f.sfh, el("span", null, "–"), f.sfa),
      f.notes, err,
      el("div", { class: "mx-actions" },
        el("button", { type: "button", class: "sh-btn", onclick: () => download(collect().out) }, "Download"),
        el("button", { type: "submit", class: "sh-btn mx-primary" }, "Save")));
    show("Match info", body);
  }

  ctx.provide("matches", { openPicker, openInfo });
}
