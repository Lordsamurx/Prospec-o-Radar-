/* Radar · comportamento da interface. Sem build: JS puro + HTMX.
   Nada aqui envia mensagem a lead: os botões são "Copiar" e "Marquei como enviado". */
(function () {
  "use strict";
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* modo privado */ } },
  };

  /* ---------- HTMX: trocar também respostas 400/422 (mensagens de erro em fragmento) ---------- */
  if (window.htmx) {
    htmx.config.responseHandling = [
      { code: "204", swap: false },
      { code: "[23]..", swap: true },
      { code: "400", swap: true }, { code: "422", swap: true },
      { code: "[45]..", swap: false, error: true },
    ];
    htmx.config.defaultSettleDelay = 0;
  }

  /* ---------- avisos ---------- */
  function toast(message, kind) {
    const box = $("#toasts");
    if (!box || !message) return;
    const el = document.createElement("div");
    el.className = "toast" + (kind === "error" ? " error" : "");
    el.textContent = message;
    if (kind === "error") el.setAttribute("role", "alert");
    box.appendChild(el);
    setTimeout(() => el.remove(), kind === "error" ? 7000 : 3600);
  }
  const detailValue = (e) => (e.detail && e.detail.value !== undefined ? e.detail.value : e.detail);
  document.body.addEventListener("toast", (e) => toast(String(detailValue(e))));
  document.body.addEventListener("toast-error", (e) => toast(String(detailValue(e)), "error"));
  document.body.addEventListener("htmx:sendError", () => toast("Sem conexão com a app. Ela ainda está aberta?", "error"));
  document.body.addEventListener("htmx:responseError", (e) => {
    const xhr = e.detail.xhr;
    if (xhr.getResponseHeader("HX-Trigger")) return; // o servidor já mandou o aviso
    let msg = "Não deu certo (erro " + xhr.status + ").";
    try { const d = JSON.parse(xhr.responseText).detail; if (typeof d === "string") msg = d; } catch (err) { /* não era JSON */ }
    toast(msg, "error");
  });

  /* ---------- tema ---------- */
  document.addEventListener("click", (e) => {
    if (!e.target.closest("[data-theme-toggle]")) return;
    const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
    document.documentElement.dataset.theme = next;
    store.set("radar-theme", next);
    toast(next === "light" ? "Tema claro" : "Tema escuro");
  });

  /* ---------- copiar ---------- */
  async function copyText(text) {
    try { await navigator.clipboard.writeText(text); }
    catch (e) {
      const ta = document.createElement("textarea");
      ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
      document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); } finally { ta.remove(); }
    }
    toast("Copiado");
  }
  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-copy]");
    if (!btn) return;
    const src = $(btn.dataset.copy);
    if (src) copyText("value" in src ? src.value : src.textContent.trim());
  });

  /* ---------- diálogos ---------- */
  document.addEventListener("click", (e) => {
    const close = e.target.closest("[data-dialog-close]");
    if (close) close.closest("dialog").close("cancel");
    const open = e.target.closest("[data-dialog-open]");
    if (open) { const d = $(open.dataset.dialogOpen); if (d) d.showModal(); }
  });
  $$("dialog").forEach((d) => d.addEventListener("click", (e) => { if (e.target === d) d.close("cancel"); }));

  /* ---------- drawer do lead ---------- */
  const drawer = $("#drawer"), overlay = $("#overlay"), drawerBody = $("#drawer-body");
  let lastFocus = null, openId = null;
  const focusables = () => $$('a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])', drawer)
    .filter((el) => el.offsetParent !== null);
  function openLead(id) {
    if (!drawer || !window.htmx) return;
    if (!drawer.classList.contains("on")) lastFocus = document.activeElement;
    openId = String(id);
    drawerBody.setAttribute("aria-busy", "true");
    htmx.ajax("GET", "/leads/" + id, { target: "#drawer-body", swap: "innerHTML" }).then(() => {
      drawerBody.removeAttribute("aria-busy");
      drawerBody.scrollTop = 0;
      drawer.classList.add("on"); overlay.classList.add("on");
      document.body.style.overflow = "hidden";
      const first = $("[data-drawer-close]", drawer) || drawer;
      const focusIn = () => first.focus({ preventScroll: true });
      focusIn();
      // com "reduzir movimento" o painel leva um instante para ficar visível: tenta de novo
      setTimeout(() => { if (!drawer.contains(document.activeElement)) focusIn(); }, 80);
      markActive(openId);
    });
  }
  function closeDrawer() {
    if (!drawer || !drawer.classList.contains("on")) return;
    drawer.classList.remove("on"); overlay.classList.remove("on");
    document.body.style.overflow = "";
    const was = openId;
    openId = null;
    // devolve o foco para onde estava; se abriu pelo teclado (J/K + Enter), para o botão do lead na lista
    const back = lastFocus && lastFocus !== document.body && document.contains(lastFocus) ? lastFocus
      : document.querySelector('[data-open-lead="' + was + '"]');
    if (back) back.focus({ preventScroll: true });
    else if (drawer.contains(document.activeElement)) document.activeElement.blur();
  }
  window.Radar = { openLead, closeDrawer, toast };
  document.addEventListener("click", (e) => {
    const opener = e.target.closest("[data-open-lead]");
    if (opener) { e.preventDefault(); openLead(opener.dataset.openLead); return; }
    if (e.target.closest("[data-drawer-close]")) closeDrawer();
  });
  document.body.addEventListener("drawer-close", closeDrawer);
  document.body.addEventListener("open-lead", (e) => openLead(detailValue(e)));
  if (drawer) drawer.addEventListener("keydown", (e) => {
    if (e.key !== "Tab") return;
    const f = focusables();
    if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (e.shiftKey && (document.activeElement === first || document.activeElement === drawer)) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  });
  if (document.body.dataset.openLeadNow) window.addEventListener("load", () => openLead(document.body.dataset.openLeadNow));

  /* ---------- mudar etapa (pergunta motivo ou valor quando precisa) ---------- */
  const stageDialog = $("#stage-dialog"), stageForm = $("#stage-form");
  const NEEDS_DIALOG = ["PERDIDO", "FECHADO"];
  function sendStatus(id, status, extra, view) {
    return htmx.ajax("PATCH", "/leads/" + id + "/status?view=" + (view || "none"),
      { values: Object.assign({ status: status }, extra || {}), swap: view === "drawer" ? "innerHTML" : "none",
        target: view === "drawer" ? "#drawer-body" : "body" });
  }
  function changeStage(id, status, label, view) {
    if (!NEEDS_DIALOG.includes(status) || !stageDialog) return sendStatus(id, status, null, view);
    $$("[data-for]", stageForm).forEach((el) => { el.hidden = !el.dataset.for.split(" ").includes(status); });
    stageForm.reset();
    $("#stage-text").textContent = (label || "Lead") + " vai para " + (status === "PERDIDO" ? "Perdido" : "Fechado") + ".";
    stageDialog.returnValue = "";
    stageDialog.showModal();
    return new Promise((resolve) => {
      stageDialog.addEventListener("close", function done() {
        stageDialog.removeEventListener("close", done);
        if (stageDialog.returnValue !== "ok") {
          if (openId) openLead(openId); else document.body.dispatchEvent(new CustomEvent("funnel-changed"));
          return resolve(false);
        }
        const data = {};
        new FormData(stageForm).forEach((v, k) => { if (v !== "" && !$("[name='" + k + "']", stageForm).closest("[hidden]")) data[k] = v; });
        resolve(sendStatus(id, status, data, view));
      });
    });
  }
  document.addEventListener("change", (e) => {
    const sel = e.target.closest("select[data-stage-select]");
    if (!sel) return;
    changeStage(sel.dataset.stageSelect, sel.value, sel.dataset.name, sel.dataset.view);
  });

  /* ---------- lista: teclado e seleção em lote ---------- */
  const rows = () => $$(".lead-row");
  let activeIndex = -1;
  function markActive(id) {
    rows().forEach((r, i) => { const on = r.dataset.id === String(id); r.classList.toggle("is-active", on); if (on) activeIndex = i; });
  }
  function moveActive(delta) {
    const list = rows();
    if (!list.length) return;
    activeIndex = Math.max(0, Math.min(list.length - 1, activeIndex + delta));
    list.forEach((r, i) => r.classList.toggle("is-active", i === activeIndex));
    list[activeIndex].scrollIntoView({ block: "nearest", behavior: reduced() ? "auto" : "smooth" });
  }
  function currentLeadId() {
    if (openId) return openId;
    const r = rows()[activeIndex];
    return r ? r.dataset.id : null;
  }
  function setScore(value) {
    const id = currentLeadId();
    if (!id) return toast("Marque um lead com J ou K, ou abra um.");
    htmx.ajax("PATCH", "/leads/" + id + "/score" + (openId ? "" : "?view=none"),
      { values: { score: value }, target: openId ? "#drawer-body" : "body", swap: openId ? "innerHTML" : "none" });
  }
  function updateBulk() {
    const bar = $("#bulk");
    if (!bar) return;
    const n = $$(".pick input:checked").length;
    bar.hidden = n === 0;
    const out = $("#bulk-count"); if (out) out.textContent = n + (n === 1 ? " lead marcado" : " leads marcados");
    const all = $("#pick-all"); if (all) { const total = $$(".pick input").length; all.checked = n > 0 && n === total; all.indeterminate = n > 0 && n < total; }
  }
  document.addEventListener("change", (e) => {
    if (e.target.id === "pick-all") { $$(".pick input").forEach((c) => { c.checked = e.target.checked; }); updateBulk(); }
    else if (e.target.closest(".pick")) updateBulk();
    if (e.target.id === "bulk-action") {
      const v = e.target.value;
      $$("[data-bulk-for]").forEach((el) => { el.hidden = el.dataset.bulkFor !== v; });
    }
  });
  document.addEventListener("click", (e) => {
    if (!e.target.closest("[data-bulk-csv]")) return;
    const f = document.createElement("form");
    f.method = "post"; f.action = "/leads/bulk"; f.hidden = true;
    const add = (k, v) => { const i = document.createElement("input"); i.type = "hidden"; i.name = k; i.value = v; f.appendChild(i); };
    add("action", "csv");
    $$(".pick input:checked").forEach((c) => add("ids", c.value));
    document.body.appendChild(f); f.submit(); f.remove();
  });
  document.body.addEventListener("bulk-done", () => { $$(".pick input:checked").forEach((c) => { c.checked = false; }); updateBulk(); });

  /* ---------- paleta de comandos (Ctrl+K) ---------- */
  const palette = $("#palette"), pInput = $("#palette-input"), pList = $("#palette-list");
  const COMMANDS = [
    { label: "Hoje", href: "/", hint: "tela" }, { label: "Leads", href: "/leads", hint: "tela" },
    { label: "Leads no mapa", href: "/leads?view=mapa", hint: "tela" },
    { label: "Buscas: procurar negócios", href: "/buscas", hint: "tela" }, { label: "Funil", href: "/funil", hint: "tela" },
    { label: "Serviços por categoria", href: "/servicos", hint: "tela" }, { label: "Métricas", href: "/metricas", hint: "tela" },
    { label: "Configurações", href: "/config", hint: "tela" }, { label: "Ajuda", href: "/ajuda", hint: "tela" },
    { label: "Começar sessão de prospecção", href: "/sessao", hint: "ação" },
    { label: "Leads nota A sem site", href: "/leads?score=A&site=sem", hint: "filtro" },
    { label: "Leads com ação vencida", href: "/leads?overdue=1", hint: "filtro" },
    { label: "Nunca abordados", href: "/leads?never_contacted=1", hint: "filtro" },
    { label: "Exportar leads em CSV", href: "/export.csv", hint: "ação" },
    { label: "Fazer backup agora", href: "/config#backup", hint: "ação" },
    { label: "Trocar tema claro e escuro", run: () => $("[data-theme-toggle]").click(), hint: "ação" },
    { label: "Ver atalhos do teclado", run: () => $("#keys-dialog").showModal(), hint: "ajuda" },
  ];
  let pItems = [], pIndex = 0, pTimer = null, pSeq = 0;
  const fold = (s) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  function renderPalette() {
    pList.innerHTML = "";
    pItems.forEach((it, i) => {
      const li = document.createElement("li");
      li.id = "pal-" + i; li.setAttribute("role", "option"); li.setAttribute("aria-selected", i === pIndex ? "true" : "false");
      const a = document.createElement("span"); a.textContent = it.label; a.className = "truncate";
      const b = document.createElement("span"); b.textContent = it.hint || ""; b.className = "sub";
      li.append(a, b);
      li.addEventListener("click", () => runPalette(i));
      pList.appendChild(li);
    });
    if (!pItems.length) { const li = document.createElement("li"); li.className = "group muted"; li.textContent = "Nada encontrado."; pList.appendChild(li); }
    pInput.setAttribute("aria-activedescendant", pItems.length ? "pal-" + pIndex : "");
    const sel = $("#pal-" + pIndex); if (sel) sel.scrollIntoView({ block: "nearest" });
  }
  function searchPalette() {
    const q = fold(pInput.value.trim());
    const base = COMMANDS.filter((c) => !q || fold(c.label).includes(q));
    pItems = base; pIndex = 0; renderPalette();
    clearTimeout(pTimer);
    if (q.length < 2) return;
    const seq = ++pSeq;
    pTimer = setTimeout(() => {
      fetch("/api/command?q=" + encodeURIComponent(pInput.value.trim()) + (location.search.includes("show_mock=1") ? "&show_mock=1" : ""),
        { headers: { Accept: "application/json" } })
        .then((r) => (r.ok ? r.json() : { leads: [] }))
        .then((d) => {
          if (seq !== pSeq) return;
          pItems = d.leads.map((l) => ({ label: l.name, hint: l.sub || "lead", lead: l.id })).concat(base);
          pIndex = 0; renderPalette();
        }).catch(() => {});
    }, 160);
  }
  function runPalette(i) {
    const it = pItems[i];
    if (!it) return;
    palette.close();
    if (it.lead) { if ($("#drawer")) openLead(it.lead); else location.href = "/leads/" + it.lead; }
    else if (it.run) it.run();
    else location.href = it.href;
  }
  function openPalette() { if (!palette || palette.open) return; pInput.value = ""; palette.showModal(); searchPalette(); pInput.focus(); }
  if (palette) {
    pInput.addEventListener("input", searchPalette);
    pInput.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") { e.preventDefault(); pIndex = Math.min(pItems.length - 1, pIndex + 1); renderPalette(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); pIndex = Math.max(0, pIndex - 1); renderPalette(); }
      else if (e.key === "Enter") { e.preventDefault(); runPalette(pIndex); }
    });
    document.addEventListener("click", (e) => { if (e.target.closest("[data-palette-open]")) openPalette(); });
  }

  /* ---------- atalhos ---------- */
  document.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); openPalette(); return; }
    if (e.key === "Escape") {
      if ($("dialog[open]")) return; // o próprio diálogo fecha
      if (drawer && drawer.classList.contains("on")) { e.preventDefault(); closeDrawer(); }
      return;
    }
    const t = e.target;
    if (e.ctrlKey || e.metaKey || e.altKey || $("dialog[open]")) return;
    if (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)) return;
    const k = e.key;
    if (k === "?") { e.preventDefault(); $("#keys-dialog").showModal(); }
    else if (k === "/") { const s = $("#q") || $("#search-niche"); if (s) { e.preventDefault(); s.focus(); } }
    else if (k === "j" || k === "J") { if (rows().length && !openId) { e.preventDefault(); moveActive(1); } }
    else if (k === "k" || k === "K") { if (rows().length && !openId) { e.preventDefault(); moveActive(-1); } }
    else if (k === "Enter" && !openId && rows()[activeIndex] && !t.closest("button, a, summary")) { e.preventDefault(); openLead(rows()[activeIndex].dataset.id); }
    else if (/^[abcABC]$/.test(k) && (openId || rows().length)) { e.preventDefault(); setScore(k.toUpperCase()); }
    else if (k === "e" || k === "E") {
      const id = currentLeadId();
      if (!id) return;
      e.preventDefault();
      const focusStage = () => { const s = $("#dw-stage"); if (s) { s.scrollIntoView({ block: "center" }); s.focus(); } };
      if (openId) focusStage(); else { openLead(id); setTimeout(focusStage, 450); }
    }
  });

  /* ---------- kanban ---------- */
  function applyCollapsed() {
    $$(".kcol").forEach((col) => {
      const saved = store.get("radar-kcol-" + col.dataset.status, col.dataset.default);
      const on = saved === "1";
      col.classList.toggle("collapsed", on);
      const btn = $("[data-kcol-toggle]", col);
      if (btn) { btn.setAttribute("aria-expanded", on ? "false" : "true"); btn.setAttribute("aria-label", (on ? "Abrir" : "Recolher") + " a coluna " + col.dataset.label); }
    });
  }
  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-kcol-toggle]");
    if (!btn) return;
    const col = btn.closest(".kcol");
    store.set("radar-kcol-" + col.dataset.status, col.classList.contains("collapsed") ? "0" : "1");
    applyCollapsed();
  });
  let dragId = null;
  document.addEventListener("dragstart", (e) => {
    const card = e.target.closest && e.target.closest(".kcard");
    if (!card) return;
    dragId = card.dataset.id; card.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", dragId);
  });
  document.addEventListener("dragend", () => { $$(".kcard.dragging").forEach((c) => c.classList.remove("dragging")); $$(".kcol.over").forEach((c) => c.classList.remove("over")); dragId = null; });
  document.addEventListener("dragover", (e) => {
    const col = e.target.closest && e.target.closest(".kcol");
    if (!col || !dragId) return;
    e.preventDefault(); $$(".kcol.over").forEach((c) => { if (c !== col) c.classList.remove("over"); }); col.classList.add("over");
  });
  document.addEventListener("drop", (e) => {
    const col = e.target.closest && e.target.closest(".kcol");
    if (!col || !dragId) return;
    e.preventDefault();
    const card = $('.kcard[data-id="' + dragId + '"]');
    if (card && card.dataset.status !== col.dataset.status) changeStage(dragId, col.dataset.status, card.dataset.name);
  });

  /* ---------- números que contam ---------- */
  function countUp(root) {
    $$("[data-count]", root).forEach((el) => {
      const end = Number(el.dataset.count);
      if (el.dataset.done || !isFinite(end)) return;
      el.dataset.done = "1";
      if (reduced() || end === 0) { el.textContent = end.toLocaleString("pt-BR"); return; }
      const t0 = performance.now(), dur = 600;
      (function tick(now) {
        const p = Math.min(1, (now - t0) / dur);
        el.textContent = Math.round(end * (1 - Math.pow(1 - p, 3))).toLocaleString("pt-BR");
        if (p < 1) requestAnimationFrame(tick);
      })(t0);
    });
  }

  /* ---------- mapas (Leaflet só existe nas telas com mapa) ---------- */
  const TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
  const ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>';
  let leadMap = null;
  function initLeadMap() {
    const el = $("#lead-map"), dataEl = $("#map-data");
    if (!el || !dataEl || !window.L) return;
    if (dataEl.dataset.done) return;
    dataEl.dataset.done = "1";
    if (leadMap) { leadMap.remove(); leadMap = null; }
    const data = JSON.parse(dataEl.textContent);
    leadMap = L.map(el, { scrollWheelZoom: true }).setView(data.center, 12);
    leadMap.attributionControl.setPrefix(false);
    L.tileLayer(TILES, { maxZoom: 19, attribution: ATTR }).addTo(leadMap);
    const group = L.markerClusterGroup ? L.markerClusterGroup({ showCoverageOnHover: false, maxClusterRadius: 44 }) : L.layerGroup();
    data.leads.forEach((l) => {
      const icon = L.divIcon({ className: "", html: '<span class="pin ' + l.score + '"><b>' + (l.score === "DESCARTE" ? "D" : l.score || "–") + "</b></span>", iconSize: [28, 28], iconAnchor: [14, 28] });
      const m = L.marker([l.lat, l.lng], { icon: icon, title: l.name, alt: l.name + ", nota " + (l.score || "sem nota"), keyboard: true });
      const box = document.createElement("div");
      const b = document.createElement("strong"); b.textContent = l.name;
      const p = document.createElement("div"); p.className = "muted"; p.textContent = l.sub;
      const btn = document.createElement("button"); btn.type = "button"; btn.className = "btn sm primary"; btn.style.marginTop = "8px"; btn.textContent = "Abrir lead";
      btn.addEventListener("click", () => openLead(l.id));
      box.append(b, p, btn);
      m.bindPopup(box);
      group.addLayer(m);
    });
    leadMap.addLayer(group);
    if (data.leads.length) leadMap.fitBounds(L.latLngBounds(data.leads.map((l) => [l.lat, l.lng])).pad(0.12), { maxZoom: 15 });
  }
  function initSearchMap() {
    const el = $("#search-map");
    if (!el || !window.L || el.dataset.ready) return;
    el.dataset.ready = "1";
    const center = JSON.parse(el.dataset.center);
    const map = L.map(el).setView(center, 12);
    map.attributionControl.setPrefix(false);
    L.tileLayer(TILES, { maxZoom: 19, attribution: ATTR }).addTo(map);
    const pins = [];
    const latI = $("#search-lat"), lngI = $("#search-lng"), pinsI = $("#batch-pins"), radiusI = $("#search-radius"), info = $("#pin-info");
    const radiusM = () => Math.max(100, Math.min(50000, (parseFloat(String(radiusI && radiusI.value || "1.5").replace(",", ".")) || 1.5) * 1000));
    function sync() {
      const last = pins[pins.length - 1];
      if (latI) latI.value = last ? last.lat.toFixed(6) : "";
      if (lngI) lngI.value = last ? last.lng.toFixed(6) : "";
      if (pinsI) pinsI.value = JSON.stringify(pins.map((p) => ({ lat: p.lat, lng: p.lng, radius_m: radiusM() })));
      if (info) info.textContent = pins.length ? pins.length + (pins.length === 1 ? " pino no mapa. A busca usa este ponto." : " pinos no mapa. A busca simples usa o último; a busca em lote usa todos.") : "Nenhum pino. Clique no mapa para marcar o centro da busca.";
      pins.forEach((p) => p.circle.setRadius(radiusM()));
    }
    map.on("click", (e) => {
      const p = { lat: e.latlng.lat, lng: e.latlng.lng };
      p.marker = L.marker(e.latlng, { title: "Pino da busca. Clique para tirar.", alt: "Pino da busca" }).addTo(map);
      p.circle = L.circle(e.latlng, { radius: radiusM(), color: "#4ade9a", weight: 1.5, fillOpacity: .12 }).addTo(map);
      p.marker.on("click", () => { map.removeLayer(p.marker); map.removeLayer(p.circle); pins.splice(pins.indexOf(p), 1); sync(); });
      pins.push(p); sync();
    });
    if (radiusI) radiusI.addEventListener("input", sync);
    const clear = $("#pins-clear");
    if (clear) clear.addEventListener("click", () => { pins.splice(0).forEach((p) => { map.removeLayer(p.marker); map.removeLayer(p.circle); }); sync(); });
    sync();
  }

  /* ---------- depois de cada troca do HTMX ---------- */
  function refresh(root) {
    countUp(root || document);
    applyCollapsed();
    updateBulk();
    initLeadMap();
    initSearchMap();
    if (openId) markActive(openId);
  }
  document.body.addEventListener("htmx:afterSwap", (e) => refresh(e.detail.target));
  document.addEventListener("DOMContentLoaded", () => refresh(document));
  if (document.readyState !== "loading") refresh(document);
})();
