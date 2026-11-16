// Galileo hub - right-click menu. Only inside the hub (#hub) while it runs; text fields keep the browser's
// own menu, and a right-button drag (the 3D camera pans with it) never opens the menu.
//
// On a player (hovered on the 3D pitch, 2D board or video, or a roster row): select, add/remove, join as
// line, select their team's back line / midfield / attack.
// Anywhere else: view, team units, drawing tools and colour, board tools, footage display and sync,
// clip in/out, clear selection, help.

const DRAG_PX = 6;

function el(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k === "style") e.style.cssText = v;
    else if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? "" : String(v));
  }
  for (const c of kids.flat()) if (c != null && c !== false) e.append(c instanceof Node ? c : String(c));
  return e;
}
const isTyping = (t) => !!t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));

export function init(ctx) {
  const { store, mounts } = ctx;
  const root = mounts.root || document.getElementById("hub");
  const svc = {};
  for (const name of ["shell", "drawing", "board2d", "footage", "timeline"]) ctx.need(name).then((s) => { svc[name] = s; }, () => {});

  let menus = [], downAt = null, returnFocus = null;

  // ------------------------------------------------------------ open / close
  root.addEventListener("pointerdown", (e) => { if (e.button === 2) downAt = [e.clientX, e.clientY]; }, true);
  root.addEventListener("contextmenu", (e) => {
    if (isTyping(e.target)) return;                                   // native menu in text fields
    e.preventDefault();
    const moved = downAt && Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) > DRAG_PX;
    downAt = null;
    if (moved) return;                                                // that was a right-drag (camera pan)
    const row = e.target.closest?.("[data-idx]");
    const hov = store.get("hover");
    const idx = row && root.contains(row) ? +row.dataset.idx : Number.isInteger(hov) ? hov : null;
    open(build(idx), e.clientX, e.clientY);
  });
  document.addEventListener("pointerdown", (e) => { if (menus.length && !menus.some((m) => m.contains(e.target))) closeAll(); }, true);
  window.addEventListener("blur", () => closeAll());
  window.addEventListener("resize", () => closeAll());
  document.addEventListener("keydown", (e) => {
    if (!menus.length) return;
    const m = menus.find((x) => x.contains(document.activeElement)) || menus[menus.length - 1];
    const focusables = [...m.querySelectorAll(".cm-item:not(:disabled), .cm-chip")];
    const i = focusables.indexOf(document.activeElement);
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); if (menus.length > 1 && m !== menus[0]) closeFrom(menus.indexOf(m)); else closeAll(true); }
    else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      const n = focusables.length; if (!n) return;
      focusables[(i + (e.key === "ArrowDown" ? 1 : -1) + n) % n].focus();
    } else if (e.key === "ArrowRight" && document.activeElement?._sub) { e.preventDefault(); openSub(document.activeElement, true); }
    else if (e.key === "ArrowLeft" && m !== menus[0]) { e.preventDefault(); const owner = m._owner; closeFrom(menus.indexOf(m)); owner?.focus(); }
    else return;
  }, true);

  function closeFrom(k) { for (const m of menus.splice(k)) { m._owner?.classList.remove("is-open"); m.remove(); } }
  function closeAll(restore) {
    closeFrom(0);
    if (restore && returnFocus && document.contains(returnFocus)) returnFocus.focus?.();
    returnFocus = null;
  }
  function place(m, x, y, alt) {
    document.body.append(m);
    const r = m.getBoundingClientRect(), W = innerWidth, H = innerHeight;
    if (x + r.width > W - 4) x = alt != null ? alt - r.width : W - r.width - 4;
    if (y + r.height > H - 4) y = Math.max(4, H - r.height - 4);
    m.style.left = `${Math.max(4, x)}px`; m.style.top = `${Math.max(4, y)}px`;
  }
  function open(items, x, y) {
    closeAll();
    returnFocus = document.activeElement;
    const m = render(items);
    menus.push(m);
    place(m, x, y);
    m.querySelector(".cm-item:not(:disabled), .cm-chip")?.focus({ preventScroll: true });
  }
  function openSub(item, focus) {
    const k = menus.findIndex((m) => m.contains(item));
    closeFrom(k + 1);
    for (const o of menus[k].querySelectorAll(".cm-item.is-open")) o.classList.remove("is-open");
    item.classList.add("is-open");
    const m = render(item._sub());
    m._owner = item;
    menus.push(m);
    const r = item.getBoundingClientRect();
    place(m, r.right + 2, r.top - 4, r.left - 2);
    if (focus) m.querySelector(".cm-item:not(:disabled), .cm-chip")?.focus({ preventScroll: true });
  }

  // ------------------------------------------------------------ rendering
  function act(fn, keep) {
    return (e) => {
      e.stopPropagation();
      try { const r = fn(); if (r && typeof r.catch === "function") r.catch((err) => console.error("[contextmenu]", err)); }
      catch (err) { console.error("[contextmenu]", err); svc.shell?.toast?.(String(err.message || err)); }
      if (keep) refresh(); else closeAll();
    };
  }
  function refresh() {                                                // re-render the menus that stay open (chip rows)
    for (const m of menus) if (m._items) { const fresh = m._items(); const n = render(fresh); n._items = m._items; n._owner = m._owner; m.replaceChildren(...n.childNodes); }
  }
  function render(items) {
    const m = el("div", { class: "cm", role: "menu", "aria-orientation": "vertical" });
    const list = typeof items === "function" ? items() : items;
    if (typeof items === "function") m._items = items;
    for (const it of list) {
      if (!it) continue;
      if (it.sep) { m.append(el("div", { class: "cm-sep", role: "separator" })); continue; }
      if (it.head) { m.append(el("div", { class: "cm-head" }, ...(it.head))); continue; }
      if (it.row) {
        m.append(el("div", { class: "cm-row", role: "group", "aria-label": it.label || "" }, it.row.map((c) =>
          el("button", { type: "button", class: `cm-chip ${c.cls || ""}`, role: "menuitemradio", "aria-pressed": c.pressed == null ? null : String(!!c.pressed),
            "aria-checked": c.pressed == null ? null : String(!!c.pressed), title: c.title || c.label, "aria-label": c.title || c.label,
            style: c.style, onclick: act(c.run, c.keep) }, c.text ?? c.label))));
        continue;
      }
      const b = el("button", { type: "button", class: "cm-item", role: it.checked != null ? "menuitemcheckbox" : "menuitem",
        "aria-checked": it.checked == null ? null : String(!!it.checked), disabled: it.disabled || null, "aria-haspopup": it.sub ? "menu" : null },
        el("span", null, it.label), it.sub ? el("span", { class: "cm-arrow", "aria-hidden": "true" }, "▸") : it.key ? el("span", { class: "cm-key" }, it.key) : null);
      if (it.sub) {
        b._sub = it.sub;
        let t = 0;
        b.addEventListener("pointerenter", () => { clearTimeout(t); t = setTimeout(() => openSub(b, false), 90); });
        b.addEventListener("pointerleave", () => clearTimeout(t));
        b.addEventListener("click", (e) => { e.stopPropagation(); openSub(b, true); });
      } else if (it.run) {
        b.addEventListener("click", act(it.run, it.keep));
        b.addEventListener("pointerenter", () => { const k = menus.findIndex((x) => x.contains(b)); if (k >= 0) closeFrom(k + 1); });
      }
      m.append(b);
    }
    return m;
  }

  // ------------------------------------------------------------ menu contents
  const R = () => store.get("replay");
  const sel = () => store.get("selection") || [];
  const short = (team) => R()?.meta?.[team]?.short ?? team;

  function unitItems(team) {
    const sh = svc.shell;
    return (sh?.units || [["DEF", "Back line"], ["MID", "Midfield"], ["FWD", "Attack"]]).map(([key, label]) => ({
      label: `${short(team)} ${label.toLowerCase()}`, run: () => sh?.quickUnit?.(team, key, label, false),
    }));
  }

  function playerItems(i) {
    const r = R(), p = r?.players?.[i];
    if (!p) return [];
    const sh = svc.shell, on = sel().includes(i);
    const f = ctx.state.frameI ?? Math.round(store.get("frame") || 0);
    const d = r.det[f * r.nP + i];
    const state = d === 1 ? "seen" : d === 0 ? "estimated" : "off pitch";
    const kit = r.meta?.[p.team]?.color || "#888";
    return [
      { head: [el("span", { class: "sh-kit sh-kit-sm", style: `--kit:${kit}` }), `${p.short || p.name}${p.role ? " · " + p.role : ""}`, el("small", null, state)] },
      { label: "Select only this player", run: () => store.set("selection", [i]) },
      { label: on ? "Remove from selection" : "Add to selection", key: "Shift+click", run: () => sh?.selectPlayer?.(i, true) },
      { label: "Join selection as line", disabled: (on ? sel().length : sel().length + 1) < 2, run: () => { if (!on) store.set("selection", [...sel(), i]); return sh?.joinSelection?.(); } },
      { sep: true },
      ...unitItems(p.team),
    ];
  }

  function viewRow() {
    const v = store.get("view");
    return { row: [["3d", "3D"], ["2d", "2D"], ["split", "Split"], ["video", "Video"]].map(([k, l]) => ({
      label: l, pressed: v === k, title: `${l} view`, run: () => svc.shell?.setView?.(k) })), label: "View" };
  }

  function drawItems() {
    const d = svc.drawing;
    if (!d) return [{ label: "Drawing tools not loaded", disabled: true }];
    return () => [
      ...(d.toolLabels || d.tools.map((id) => ({ id, label: id }))).map((t) => ({
        label: t.label, key: t.key ? t.key.toUpperCase() : null, checked: d.tool === t.id, run: () => d.setTool(t.id) })),
      { sep: true },
      { row: d.colors.map((c, k) => ({ label: "", title: `Colour ${k + 1}`, cls: "cm-swatch", style: `background:${c}`, pressed: d.color === c, keep: true, run: () => d.setColor(c) })), label: "Colour" },
      { row: [{ label: "Solid", pressed: !d.dash, keep: true, run: () => d.setDash(false) }, { label: "Dashed", pressed: !!d.dash, keep: true, run: () => d.setDash(true) }], label: "Stroke" },
      { sep: true },
      { label: "Undo", key: "Ctrl+Z", run: () => d.undo() },
      { label: "Show all pinned shapes", checked: !!d.showAll, run: () => d.setShowAll(!d.showAll) },
      { label: "Clear all drawings", run: () => d.clear() },
    ];
  }

  function boardItems() {
    const b = svc.board2d;
    if (!b) return [{ label: "2D board not loaded", disabled: true }];
    const to2d = () => { const v = store.get("view"); if (v !== "2d" && v !== "split") svc.shell?.setView?.("2d"); };
    return [
      { label: "Tactics-board mode (drag players)", checked: !!b.board, run: () => { to2d(); b.setBoard(!b.board); } },
      { label: "Lasso select", checked: !!b.lasso, run: () => { to2d(); b.setLasso(!b.lasso); } },
      { label: "Rotate 90°", run: () => { to2d(); b.rotate(); } },
      { label: "Flip ends", run: () => { to2d(); b.flip(); } },
      { label: "Fit (reset zoom)", run: () => { to2d(); b.resetView(); } },
      { label: "Reset dragged positions", run: () => b.resetPositions() },
    ];
  }

  function footageItems() {
    const f = svc.footage;
    const has = !!(f && f.video && (f.video.currentSrc || f.video.src));
    if (!has) return [{ label: "No footage open (Footage panel)", disabled: true }];
    const mode = f.getMode?.();
    return () => [
      { row: [["off", "Off"], ["pip", "PiP"], ["full", "Full"]].map(([k, l]) => ({ label: l, pressed: f.getMode?.() === k, keep: true, run: () => f.setMode(k) })), label: "Display" },
      { row: [-1, -0.1, 0.1, 1].map((s) => ({ label: `${s > 0 ? "+" : "−"}${Math.abs(s)}`, title: `Nudge offset ${s > 0 ? "+" : ""}${s} s`, keep: true, run: () => f.nudge(s) })), label: "Nudge" },
      { label: "Sync here", run: () => f.syncHere() },
      { label: "Mark camera cut here", run: () => f.cuts?.mark?.() },
      { label: `Mute`, checked: !!f.video.muted, disabled: mode === "off", run: () => { f.video.muted = !f.video.muted; } },
    ];
  }

  function clipItems() {
    const t = svc.timeline;
    if (!t) return [{ label: "Timeline not loaded", disabled: true }];
    const lp = t.getLoop?.() || {};
    return [
      { label: "Mark in", key: "I", run: () => t.markIn() },
      { label: "Mark out", key: "O", run: () => t.markOut() },
      { label: "Save clip", disabled: lp.in == null || lp.out == null, run: () => t.saveClip() },
      { label: "Loop in → out", checked: !!lp.loop, disabled: lp.in == null || lp.out == null, run: () => t.setLoop(!lp.loop) },
      { label: "Clear in/out", disabled: lp.in == null && lp.out == null, run: () => t.clearMarks() },
    ];
  }

  function stageItems() {
    const n = sel().length;
    return [
      viewRow(),
      { sep: true },
      { label: "Select a unit", sub: () => [...unitItems("home"), { sep: true }, ...unitItems("away")] },
      { label: "Draw", sub: drawItems },
      { label: "Board", sub: boardItems },
      { label: "Footage", sub: footageItems },
      { label: "Clip", sub: clipItems },
      { sep: true },
      { label: `Join selection as line${n ? ` (${n})` : ""}`, disabled: n < 2, run: () => svc.shell?.joinSelection?.() },
      { label: "Clear selection", disabled: !n, key: "", run: () => store.set("selection", []) },
      { label: "Change match…", run: () => svc.shell?.run?.("matches") },
      { label: "Match info (teams, clock, goals)…", run: () => svc.shell?.run?.("matchinfo") },
      { sep: true },
      { label: "Commands and shortcuts", key: "?", run: () => svc.shell?.openHelp?.() },
    ];
  }

  function build(idx) {
    if (idx == null || !R()?.players?.[idx]) return stageItems();
    return [...playerItems(idx), { sep: true }, { label: "More", sub: stageItems }];
  }

  ctx.provide?.("contextmenu", { open: (x, y, idx = null) => open(build(idx), x, y), close: () => closeAll() });
}
