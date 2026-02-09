// taxonomy/static/taxonomy/js/tree/main.js
/**
 * Página Árbol taxonómico (Tree Page Orchestrator)
 *
 * Responsabilidad:
 *  - Inicializar UI (refs, tooltip, botones).
 *  - Crear renderer D3 (solo render/interaction).
 *  - Crear controller de sampling (solo sampling).
 *  - Cargar dataset (JSON del backend) y entregarlo a renderer + samplingCtl.
 *
 * No debe:
 *  - Construir árbol (eso es backend).
 *  - Normalizar rutas / ranks / keys (eso es backend).
 *  - Hacer búsqueda “inteligente” en frontend (idealmente backend-driven).
 */

import {
  createUIRefs,
  makeTooltip,
  setCrumb,
  toggleFullscreen,
  syncFsIcon,
  showLoadError,
  toTxtList,
  copyToClipboard,
  downloadText,
} from "./ui.js";

import { loadTreeData, apiSearchTree } from "./api.js"; // thin transport: fetch JSON
import { createTreeRenderer } from "../trees/d3_tree.js";
import { createSamplingFiltersController } from "./sampling_filters.js";
(function initTreePage() {
  const endpoint = window.TREE_ENDPOINT;
  // justo después de: const endpoint = window.TREE_ENDPOINT;
  let currentRankCut = null; // null => no enviar parámetro (sin cut). "" => rankCut= (root colapsado). "genus" => cut real.

  async function reloadTreeWithRankCut(nextRankCut, { fit = true } = {}) {
    // normaliza: null | "" | "genus"
    const v = (nextRankCut === null || typeof nextRankCut === "undefined")
      ? null
      : String(nextRankCut).trim().toLowerCase();

    currentRankCut = (v === "" ? "" : v);

    // 1) pedir el árbol ya cortado al backend
    const data = await loadTreeData({
      endpoint,
      rankCut: currentRankCut, // api.js: null => no manda param; "" => rankCut= ; "genus" => rankCut=genus
    });

    // 2) entregar data al sampling + renderer
    samplingCtl.setData(data);
    renderer.render(data);

    if (fit) renderer.fitToView?.();
  }

  // =========================================================================
  // 1) UI base (refs + tooltip)
  // =========================================================================
  const ui = createUIRefs();
  const tooltip = makeTooltip(ui.mount, ui.tt);

  // =========================================================================
  // 2) Helpers locales (NO dependen de ui.js)
  //    - utilidades de rendering HTML
  //    - utilidades de selección y export
  // =========================================================================
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[c]));
  }

  function asArraySelected(mapLike) {
    if (!mapLike) return [];
    if (mapLike instanceof Map) return Array.from(mapLike.values());
    if (Array.isArray(mapLike)) return mapLike;
    try {
      return Array.from(mapLike.values());
    } catch {
      return [];
    }
  }

  // Convierte selección manual del renderer a payload liviano
  // (lo mínimo que el backend necesita para exportar)
  function selectionToPayload(selectedMap) {
    return asArraySelected(selectedMap).map((x) => ({
      id: x.id,
      key: x.key,
      rank: x.rank,
      name: x.name,
    }));
  }

  function getCookie(name) {
    const v = `; ${document.cookie}`;
    const parts = v.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(";").shift();
    return null;
  }

  // POST -> recibe blob (download) desde endpoints de export del backend
  async function postDownload(url, payload, filenameFallback) {
    const csrf = getCookie("csrftoken");
    const res = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrf || "",
      },
      body: JSON.stringify(payload),
    });

    if (!res.ok) {
      const txt = await res.text();
      throw new Error(`Export failed (${res.status}): ${txt}`);
    }

    const blob = await res.blob();
    const cd = res.headers.get("Content-Disposition") || "";
    const m = /filename="([^"]+)"/.exec(cd);
    const filename = (m && m[1]) ? m[1] : (filenameFallback || "download.txt");

    const href = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = href;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(href);
  }

  function setText(id, txt) {
    const el = document.getElementById(id);
    if (el) el.textContent = txt;
  }

  // Badge del modo de selección: Manual vs Sampling
  function setBadgeMode(modeText, isSampling) {
    const badge = document.getElementById("selModeBadge");
    if (!badge) return;

    badge.textContent = modeText || "Manual";
    badge.classList.remove(
      "bg-secondary-lt", "text-secondary",
      "bg-success-lt", "text-success"
    );

    if (isSampling) badge.classList.add("bg-success-lt", "text-success");
    else badge.classList.add("bg-secondary-lt", "text-secondary");
  }

  // =========================================================================
  // 3) Renderer (D3) — solo render + interacción
  // =========================================================================
  const renderer = createTreeRenderer({
    mount: ui.mount,
    tooltip,
    onSelectionChange: () => repaintSelection(),
    onCrumbChange: (txt) => setCrumb(ui.crumb, txt),
  });

  // =========================================================================
  // 4) Vista de selección (panel derecho)
  // =========================================================================
  function renderSelListTbody(rowsHtml, emptyMsg = "Sin selección.") {
    const tbody = document.getElementById("selList");
    if (!tbody) return;
    tbody.innerHTML =
      rowsHtml ||
      `<tr><td class="text-muted small ps-3" colspan="2">${escapeHtml(emptyMsg)}</td></tr>`;
  }

  // Render selección manual (resultado directo de clicks en el árbol)
  function renderSelectionManualTbody(selectedMap) {
    const items = asArraySelected(selectedMap);

    setText("selCount", String(items.length));
    setText("selRanks", "–");
    setText("selTarget", "–");

    const hint = document.getElementById("selHint");
    if (hint) hint.textContent = "";

    if (!items.length) {
      renderSelListTbody("", "No taxa selected.");
      return;
    }

    const sorted = items.slice().sort((a, b) => (
      String(a.rank || "").localeCompare(String(b.rank || "")) ||
      String(a.name || "").localeCompare(String(b.name || ""))
    ));

    const rows = sorted.map((x) => {
      const selId = String(x.id || x.key || "");
      const rank = String(x.rank || "");
      const name = String(x.name || "");
      return `
        <tr>
          <td class="ps-3">
            <span class="small text-muted me-2">${escapeHtml(rank)}</span>
            <span>${escapeHtml(name)}</span>
          </td>
          <td class="text-end pe-3">
            <button type="button"
                    class="btn btn-sm btn-outline-danger"
                    data-sel-remove="${escapeHtml(selId)}"
                    title="Quitar">
              Quitar
            </button>
          </td>
        </tr>
      `;
    }).join("");

    renderSelListTbody(rows);
  }

  // Normaliza respuesta de sampling a filas outgroup+ingroup sin duplicados
  function buildSamplingRows(result) {
    const ing = Array.isArray(result?.ingroup?.picked) ? result.ingroup.picked : [];
    const out = Array.isArray(result?.outgroupPicked) ? result.outgroupPicked : [];

    const norm = (x, group) => ({
      key: x?.key || "",
      name: x?.name || "",
      rank: x?.rank || "",
      group,
    });

    const rows = []
      .concat(out.map((x) => norm(x, "outgroup")))
      .concat(ing.map((x) => norm(x, "ingroup")))
      .filter((x) => x.key);

    // uniq por key
    const seen = new Set();
    const uniq = [];
    for (const r of rows) {
      if (seen.has(r.key)) continue;
      seen.add(r.key);
      uniq.push(r);
    }

    // sort: outgroup primero, luego por rank/name
    uniq.sort((a, b) => {
      if (a.group !== b.group) return a.group === "outgroup" ? -1 : 1;
      const ra = String(a.rank || ""), rb = String(b.rank || "");
      const cmpR = ra.localeCompare(rb);
      if (cmpR) return cmpR;
      return String(a.name || "").localeCompare(String(b.name || ""));
    });

    return uniq;
  }

  // Render selección proveniente del sampling
  function renderSelectionSamplingTbody(result) {
    const rows = buildSamplingRows(result);

    if (!rows.length) {
      setText("selCount", "0");
      renderSelListTbody("", "Sin selección.");
      return;
    }

    const icon = (g) =>
      g === "outgroup"
        ? `<i class="fa-solid fa-circle-dot text-warning me-2" title="Outgroup"></i>`
        : `<i class="fa-solid fa-leaf text-success me-2" title="Ingroup"></i>`;

    const html = rows.map((r) => `
      <tr>
        <td class="ps-3">
          ${icon(r.group)}
          <span class="small text-muted me-2">${escapeHtml(r.rank || "")}</span>
          <span>${escapeHtml(r.name || "")}</span>
        </td>
        <td class="text-end pe-3">
          <button class="btn btn-sm btn-outline-secondary"
                  type="button"
                  data-copy-key="${escapeHtml(r.key)}"
                  title="Copiar key">
            <i class="fa-solid fa-copy"></i>
          </button>
        </td>
      </tr>
    `).join("");

    renderSelListTbody(html);

    const ingN = (result?.ingroup?.picked || []).length;
    const outN = (result?.outgroupPicked || []).length;

    setText("selCount", String(rows.length));
    setText("selRanks", "–");
    setText("selTarget", (result?.targetRank || result?.ingroup?.targetRank || "–"));

    const hint = document.getElementById("selHint");
    if (hint) hint.textContent = `Ingroup: ${ingN} | Outgroup: ${outN}`;
  }

  // Delegación de eventos del tbody de selección:
  //  - Quitar elemento (manual)
  //  - Copiar key (sampling)
  function bindSelListDelegation() {
    const tbody = document.getElementById("selList");
    if (!tbody) return () => { };

    const handler = async (e) => {
      const rmBtn = e.target.closest?.("[data-sel-remove]");
      if (rmBtn) {
        const selId = rmBtn.getAttribute("data-sel-remove");
        if (selId && typeof renderer.removeSelectedBySelId === "function") {
          renderer.removeSelectedBySelId(selId);
          repaintSelection();
        } else {
          console.warn("[selection] removeSelectedBySelId no existe. selId=", selId);
        }
        return;
      }

      const cpBtn = e.target.closest?.("[data-copy-key]");
      if (cpBtn) {
        const key = cpBtn.getAttribute("data-copy-key") || "";
        if (key) await copyToClipboard(key);
      }
    };

    tbody.addEventListener("click", handler);
    return () => tbody.removeEventListener("click", handler);
  }

  const unbindSelList = bindSelListDelegation();

  // =========================================================================
  // 5) Sampling controller (estado + ejecución)
  // =========================================================================
  const samplingCtl = createSamplingFiltersController({ renderer });
  samplingCtl.attachEventHandlers();

  // Estado: si hay resultado de sampling, la “selección” visible proviene de ahí.
  let lastSamplingResult = null;

  function repaintSelection() {
    if (lastSamplingResult) {
      renderSelectionSamplingTbody(lastSamplingResult);
      return;
    }
    renderSelectionManualTbody(renderer.getSelectedSpecies?.());
  }

  // Payload para export: sampling (si existe) o manual (fallback)
  function getExportPayload({ allowManualFallback = true } = {}) {
    if (lastSamplingResult) return lastSamplingResult;
    if (!allowManualFallback) return null;
    return selectionToPayload(renderer.getSelectedSpecies?.());
  }

  // =========================================================================
  // 6) Exports (backend download + clipboard)
  // =========================================================================
  document.getElementById("exportSelJson")?.addEventListener("click", async () => {
    const payload = getExportPayload({ allowManualFallback: true });
    if (!payload) return;
    await postDownload("/taxonomy/sampling/export/json/", payload, "sampling.json");
  });

  document.getElementById("exportSelTxt")?.addEventListener("click", async () => {
    const payload = getExportPayload({ allowManualFallback: true });
    if (!payload) return;
    await postDownload("/taxonomy/sampling/export/txt/", payload, "sampling.txt");
  });

  document.getElementById("exportSelNewick")?.addEventListener("click", async () => {
    const payload = getExportPayload({ allowManualFallback: false });
    if (!payload) return;
    await postDownload("/taxonomy/sampling/export/newick/", payload, "sampling_taxonomic.newick");
  });

  document.getElementById("copySel")?.addEventListener("click", async () => {
    const payload = lastSamplingResult;
    if (!payload) return;

    const ing = payload?.ingroup?.picked || [];
    const out = payload?.outgroupPicked || [];
    const keys = []
      .concat(out.map(x => x?.key))
      .concat(ing.map(x => x?.key))
      .filter(Boolean);

    await copyToClipboard(keys.join("\n") + (keys.length ? "\n" : ""));
  });

  // =========================================================================
  // 7) Resultado final de sampling (evento global)
  // =========================================================================
  window.addEventListener("sampling:final", (ev) => {
    lastSamplingResult = ev.detail || null;
    if (!lastSamplingResult) return;

    setBadgeMode("Sampling", true);

    const sub = document.getElementById("selSubtitle");
    if (sub) sub.textContent = "Taxones seleccionados por sampling (ingroup + outgroup)";

    renderSelectionSamplingTbody(lastSamplingResult);

    const st = document.getElementById("samplingStatus");
    if (st) st.classList.remove("d-none");
  });

  // =========================================================================
  // 8) Botones “vista sampling” (revelar y limpiar)
  // =========================================================================
  document.getElementById("applySamplingView")?.addEventListener("click", () => {
    if (!lastSamplingResult) return;

    const keys = []
      .concat(lastSamplingResult?.ingroup?.picked || [])
      .concat(lastSamplingResult?.outgroupPicked || [])
      .map((x) => x?.key)
      .filter(Boolean);

    if (typeof renderer.revealKeys === "function" && keys.length) {
      renderer.revealKeys(keys, { fit: true });
      return;
    }

    if (typeof renderer.openToRank === "function") {
      renderer.openToRank("species", { fit: true });
      return;
    }

    renderer.setRankCut?.("species");
    renderer.fitToView?.();
  });

  document.getElementById("clearSamplingView")?.addEventListener("click", () => {
    lastSamplingResult = null;

    setBadgeMode("Manual", false);

    const sub = document.getElementById("selSubtitle");
    if (sub) sub.textContent = "Taxones seleccionados para muestreo/exportación";

    const hint = document.getElementById("selHint");
    if (hint) hint.textContent = "";

    const st = document.getElementById("samplingStatus");
    if (st) st.classList.add("d-none");

    renderer.setSamplingMode?.("");
    renderer.setSamplingRootKey?.(null);
    renderer.setRankCut?.(null);
    renderer.fitToView?.();

    if (window.__samplingWizard?.reset) window.__samplingWizard.reset();

    repaintSelection();
  });

  // =========================================================================
  // 9) Expand-to-rank dropdown (solo UI -> renderer)
  // =========================================================================
  document.querySelectorAll(".dropdown-menu [data-rank]").forEach((item) => {
    item.addEventListener("click", (e) => {
      e.preventDefault();
      const rank = item.dataset.rank || "";
      const label = item.textContent.trim();

      renderer.setRankCut?.(rank);

      const lbl = document.getElementById("vizRankLabel");
      if (lbl) lbl.textContent = label;
    });
  });

  // =========================================================================
  // 10) Sampling root dropdown (legacy)
  // =========================================================================
  function onSamplingRootChange() {
    const sel = document.getElementById("samplingRoot");
    if (!sel) return;

    const v = sel.value || "";

    if (v === "") {
      renderer.setSamplingMode?.("");
      renderer.fitToView?.();
      samplingCtl.emitSamplingConfigChanged?.();
      return;
    }

    if (v === "node") {
      renderer.setSamplingMode?.("node");
      samplingCtl.emitSamplingConfigChanged?.();
      return;
    }

    if (v === "tree") {
      renderer.setSamplingMode?.("");
      samplingCtl.emitSamplingConfigChanged?.();
    }
  }
  document.getElementById("samplingRoot")?.addEventListener("change", onSamplingRootChange);

  // =========================================================================
  // 11) Wizard (scope + multi-targets)
  //     - Es una UI opcional; si no existe el HTML, no hace nada.
  // =========================================================================
  function tryGetActiveNodeInfo() {
    // 1) API directa del renderer (preferida)
    if (typeof renderer.getActiveNodeInfo === "function") {
      const a = renderer.getActiveNodeInfo();
      if (a?.key) return a;
    }
    // 2) API alternativa
    if (typeof renderer.getActiveNode === "function") {
      const a = renderer.getActiveNode();
      if (a?.key) return a;
    }
    // 3) fallback global si lo implementaste
    if (window.__activeNodeInfo?.key) return window.__activeNodeInfo;
    return null;
  }

  // Valida descendencia por prefijo: childKey startsWith(ancestorKey + "|")
  // Requiere keys en formato path "rank:name|rank:name|..."
  function isDescendantPath(childKey, ancestorKey) {
    const c = String(childKey || "");
    const a = String(ancestorKey || "");
    if (!a) return true;
    if (!c) return false;
    return c === a || c.startsWith(a + "|");
  }

  function initSamplingWizard() {
    const step1 = document.getElementById("samStep1");
    const step2 = document.getElementById("samStep2");
    const stepLabel = document.getElementById("samStepLabel");
    const prevBtn = document.getElementById("samPrev");
    const nextBtn = document.getElementById("samNext");

    const scopeSel = document.getElementById("samplingScope");
    const scopeBadge = document.getElementById("scopeBadge");
    const scopeSetActive = document.getElementById("scopeSetActive");
    const scopeClear = document.getElementById("scopeClear");

    const targetAddActive = document.getElementById("targetAddActive");
    const targetsClear = document.getElementById("targetsClear");
    const targetsChips = document.getElementById("targetsChips");
    const warnBox = document.getElementById("targetsWarn");
    const warnText = document.getElementById("targetsWarnText");

    // Si no existe el HTML del wizard, no hacemos nada.
    if (!scopeSel || !targetsChips || !targetAddActive) return null;

    const state = {
      step: 1,
      scopeKey: "",
      scopeLabel: "",
      targetKeys: [],
      targetLabels: new Map(),
    };

    function showWarn(msg) {
      if (!warnBox || !warnText) return;
      warnText.textContent = msg || "";
      warnBox.classList.toggle("d-none", !msg);
    }

    function setStep(n) {
      state.step = n;
      if (stepLabel) stepLabel.textContent = `${n}/2`;
      if (prevBtn) prevBtn.disabled = (n === 1);
      if (nextBtn) nextBtn.classList.toggle("d-none", n !== 1);
      if (step1) step1.classList.toggle("d-none", n !== 1);
      if (step2) step2.classList.toggle("d-none", n !== 2);
      showWarn("");
    }

    function setScope(key, label) {
      state.scopeKey = key || "";
      state.scopeLabel = label || "";

      if (scopeBadge) {
        if (!state.scopeKey) {
          scopeBadge.style.display = "none";
          scopeBadge.textContent = "scope=—";
        } else {
          scopeBadge.style.display = "";
          scopeBadge.textContent = `scope=${state.scopeLabel || "active node"}`;
        }
      }

      // Si cambia scope: elimina targets fuera del scope
      if (state.scopeKey && state.targetKeys.length) {
        const kept = [];
        for (const k of state.targetKeys) {
          if (isDescendantPath(k, state.scopeKey)) kept.push(k);
          else state.targetLabels.delete(k);
        }
        if (kept.length !== state.targetKeys.length) {
          state.targetKeys = kept;
          renderTargets();
          showWarn("Some targets were removed because they were outside the selected scope.");
        }
      }
    }

    function renderTargets() {
      if (!targetsChips) return;

      if (!state.targetKeys.length) {
        targetsChips.innerHTML =
          `<span class="text-muted small">No targets selected (sampling will use entire scope).</span>`;
        return;
      }

      targetsChips.innerHTML = state.targetKeys.map((k) => {
        const lbl = state.targetLabels.get(k) || k;
        return `
          <span class="badge bg-azure-lt text-azure d-inline-flex align-items-center gap-1">
            <span class="text-truncate" style="max-width:170px;">${escapeHtml(lbl)}</span>
            <button type="button"
                    class="btn btn-sm btn-link p-0 text-azure"
                    data-target-remove="${escapeHtml(k)}"
                    title="Remove">
              <i class="fa-solid fa-xmark"></i>
            </button>
          </span>
        `;
      }).join("");
    }

    function addTargetFromActive() {
      const a = tryGetActiveNodeInfo();
      if (!a?.key) {
        showWarn("No active node. Click a node in the tree first.");
        return;
      }
      if (!isDescendantPath(a.key, state.scopeKey)) {
        showWarn("Target clade must be inside the selected scope.");
        return;
      }
      if (!state.targetKeys.includes(a.key)) {
        state.targetKeys.push(a.key);
        state.targetLabels.set(a.key, `${a.rank || "node"}: ${a.name || a.key}`);
        renderTargets();
        showWarn("");
      }
    }

    prevBtn?.addEventListener("click", () => setStep(1));
    nextBtn?.addEventListener("click", () => setStep(2));

    scopeSel.addEventListener("change", () => {
      const v = scopeSel.value || "";
      if (v === "") {
        setScope("", "");
        showWarn("");
        return;
      }
      if (v === "node") {
        const a = tryGetActiveNodeInfo();
        if (!a?.key) {
          showWarn("No active node. Click a node in the tree first.");
          scopeSel.value = "";
          setScope("", "");
          return;
        }
        setScope(a.key, `${a.rank || "node"}: ${a.name || a.key}`);
        showWarn("");
      }
    });

    scopeSetActive?.addEventListener("click", () => {
      const a = tryGetActiveNodeInfo();
      if (!a?.key) {
        showWarn("No active node. Click a node in the tree first.");
        return;
      }
      scopeSel.value = "node";
      setScope(a.key, `${a.rank || "node"}: ${a.name || a.key}`);
      showWarn("");
    });

    scopeClear?.addEventListener("click", () => {
      scopeSel.value = "";
      setScope("", "");
      showWarn("");
    });

    targetAddActive.addEventListener("click", addTargetFromActive);

    targetsClear?.addEventListener("click", () => {
      state.targetKeys = [];
      state.targetLabels.clear();
      renderTargets();
      showWarn("");
    });

    targetsChips.addEventListener("click", (e) => {
      const btn = e.target.closest?.("[data-target-remove]");
      if (!btn) return;
      const k = btn.getAttribute("data-target-remove");
      state.targetKeys = state.targetKeys.filter((x) => x !== k);
      state.targetLabels.delete(k);
      renderTargets();
    });

    function reset() {
      try {
        setStep(1);
        if (scopeSel) scopeSel.value = "";
        setScope("", "");
        state.targetKeys = [];
        state.targetLabels.clear();
        renderTargets();
        showWarn("");
      } catch (_) { }
    }

    // Exponer estado para integración con samplingCtl
    window.__samplingWizard = { state, reset, setStep };

    // init
    setStep(1);
    setScope("", "");
    renderTargets();
    showWarn("");

    return window.__samplingWizard;
  }

  initSamplingWizard();

  // =========================================================================
  // 12) Search wiring (backend-driven)
  // =========================================================================
  const searchEndpoint = window.TREE_SEARCH_ENDPOINT;

  // Estado local de navegación de hits
  let searchState = {
    q: "",
    hits: [],
    idx: -1,
    total: 0,
    limit: 50,
    offset: 0,
    include: "species,nodes",
  };

  function setSearchControlsStateFromState() {
    const prevBtn = document.getElementById("taxSearchPrev");
    const nextBtn = document.getElementById("taxSearchNext");
    const clrBtn = document.getElementById("taxSearchClear");

    const count = searchState.hits.length;
    const hasMany = count > 1;
    const hasAny = count > 0;

    if (prevBtn) prevBtn.disabled = !hasMany;
    if (nextBtn) nextBtn.disabled = !hasMany;
    if (clrBtn) clrBtn.disabled = !hasAny;
  }

  // Navega al hit actual (abre el árbol y centra si puede)
  function revealActiveHit({ fit = false } = {}) {
    const hit = searchState.hits[searchState.idx];
    if (!hit?.key) return;

    // 1) abre ruta usando revealKeys si existe
    if (typeof renderer.revealKeys === "function") {
      renderer.revealKeys([hit.key], { fit });
      return;
    }

    // 2) fallback: samplingRootKey + openToRank si tienes API
    if (typeof renderer.setSamplingRootKey === "function") {
      renderer.setSamplingRootKey(hit.key);
    }
    if (typeof renderer.openToRank === "function") {
      renderer.openToRank(hit.rank || "species", { fit });
      return;
    }

    renderer.fitToView?.();
  }

  async function runTaxSearchBackend() {
    const inp = document.getElementById("taxSearch");
    if (!inp) return;

    const q = inp.value.trim();
    if (q.length < 2) return;

    if (!searchEndpoint || typeof searchEndpoint !== "string") {
      console.error("TREE_SEARCH_ENDPOINT is missing");
      return;
    }

    // Config base (puedes exponer limit desde UI si quieres)
    const limit = 50;
    const offset = 0;

    // Reset state antes de buscar
    searchState = {
      q,
      hits: [],
      idx: -1,
      total: 0,
      limit,
      offset,
      include: "species,nodes",
    };

    try {
      const data = await apiSearchTree({
        url: searchEndpoint,
        q,
        limit,
        offset,
        include: searchState.include,
      });

      const hits = Array.isArray(data?.hits) ? data.hits : [];
      searchState.hits = hits;
      searchState.total = Number(data?.total || hits.length || 0);
      searchState.idx = hits.length ? 0 : -1;

      setSearchControlsStateFromState();

      if (searchState.idx >= 0) {
        revealActiveHit({ fit: false });
      }
    } catch (err) {
      console.error(err);
      // dejar botones coherentes aunque falle
      setSearchControlsStateFromState();
    }
  }

  function moveHit(delta) {
    const n = searchState.hits.length;
    if (!n) return;

    // navegación circular como el main original
    let next = searchState.idx + delta;
    if (next < 0) next = n - 1;
    if (next >= n) next = 0;

    searchState.idx = next;
    setSearchControlsStateFromState();
    revealActiveHit({ fit: false });
  }

  function clearTaxSearchBackend({ focus = true } = {}) {
    const inp = document.getElementById("taxSearch");
    if (inp) {
      inp.value = "";
      if (focus) inp.focus();
    }

    searchState = {
      q: "",
      hits: [],
      idx: -1,
      total: 0,
      limit: 50,
      offset: 0,
      include: "species,nodes",
    };

    setSearchControlsStateFromState();
  }


  // Bind UI
  document.getElementById("taxSearchGo")?.addEventListener("click", runTaxSearchBackend);
  document.getElementById("taxSearch")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      runTaxSearchBackend();
    }
  });

  document.getElementById("taxSearchNext")?.addEventListener("click", () => moveHit(-1));
  document.getElementById("taxSearchPrev")?.addEventListener("click", () => moveHit(+1));

  document.getElementById("taxSearchClear")?.addEventListener("click", clearTaxSearchBackend);


  // =========================================================================
  // 13) Carga inicial del dataset (backend -> renderer + samplingCtl)
  // =========================================================================
  async function load() {
    try {
      if (!endpoint || typeof endpoint !== "string" || !endpoint.trim()) {
        throw new Error("TREE_ENDPOINT is empty or undefined. Check your template (window.TREE_ENDPOINT).");
      }

      // 1) fetch JSON (árbol ya construido en backend)
      const data = await loadTreeData(endpoint);

      // 2) entregar data a samplingCtl y renderer
      samplingCtl.setData(data);
      renderer.render(data);

      // 3) reset UI state
      searchState = {
        q: "",
        hits: [],
        idx: -1,
        total: 0,
        limit: 50,
        offset: 0,
        include: "species,nodes",
      };
      clearTaxSearchBackend({ focus: false });
      if (ui.tt) ui.tt.style.zIndex = 20;
      if (ui.fsBtn) ui.fsBtn.style.zIndex = 30;

      setCrumb(ui.crumb, "ROOT");
      tooltip.hide();

      lastSamplingResult = null;
      setBadgeMode("Manual", false);

      const samplingSel = document.getElementById("samplingRoot");
      if (samplingSel) {
        samplingSel.value = "";
        renderer.setSamplingMode?.("");
      }

      samplingCtl.resetDefaults?.();
      samplingCtl.emitSamplingConfigChanged?.();

      if (window.__samplingWizard?.reset) window.__samplingWizard.reset();

      repaintSelection();
    } catch (err) {
      console.error(err);
      showLoadError(ui.mount, `Error loading tree: ${err?.message || err}`);
    }
  }

  // =========================================================================
  // 14) Botones UI (fit, collapse, clear, fullscreen, etc.)
  // =========================================================================
  ui.loadBtn?.addEventListener("click", load);

  ui.fitBtn?.addEventListener("click", () => {
    renderer.fitToView?.();
  });

  ui.collapseAllBtn?.addEventListener("click", () => {
    renderer.collapseAll?.();

    const samplingSel = document.getElementById("samplingRoot");
    if (samplingSel) samplingSel.value = "";

    lastSamplingResult = null;
    setBadgeMode("Manual", false);

    samplingCtl.resetDefaults?.();
    samplingCtl.emitSamplingConfigChanged?.();

    if (window.__samplingWizard?.reset) window.__samplingWizard.reset();

    repaintSelection();
  });

  ui.clearSel?.addEventListener("click", () => {
    renderer.clearSelection?.();

    repaintSelection();

    const st = document.getElementById("samplingStatus");
    if (st && !lastSamplingResult) st.classList.add("d-none");
  });

  // Export local (client-side) — útil para depurar o cuando no quieres pasar por backend.
  // Nota: tus exports oficiales ya están arriba vía postDownload().
  ui.exportSel?.addEventListener("click", () => {
    const payload = selectionToPayload(renderer.getSelectedSpecies?.());
    downloadText("selection.json", JSON.stringify(payload, null, 2), "application/json;charset=utf-8");
  });

  ui.exportSelTxt?.addEventListener?.("click", async () => {
    const payload = selectionToPayload(renderer.getSelectedSpecies?.());
    const txt = toTxtList(payload);
    await copyToClipboard(txt);
  });

  ui.mount?.addEventListener("mouseleave", tooltip.hide);
  ui.mount?.addEventListener("scroll", tooltip.hide);

  ui.fsBtn?.addEventListener("click", async () => {
    await toggleFullscreen(ui.mount);
  });

  document.addEventListener("fullscreenchange", () => {
    syncFsIcon(ui.fsIcon);
    setTimeout(() => renderer.resizeToMount?.(), 80);
  });

  document.addEventListener("webkitfullscreenchange", () => {
    syncFsIcon(ui.fsIcon);
    setTimeout(() => renderer.resizeToMount?.(), 80);
  });

  // =========================================================================
  // 15) Ejecutar sampling (UI -> samplingCtl -> renderer reveal)
  // =========================================================================
  document.getElementById("runSampling")?.addEventListener("click", async () => {
    if (typeof samplingCtl.runSamplingAndBuildResult !== "function") {
      console.warn("[sampling] samplingCtl.runSamplingAndBuildResult no existe.");
      return;
    }

    // Integración wizard: scope/targets -> samplingCtl (si existe)
    const wiz = window.__samplingWizard?.state;
    if (wiz) {
      const scopeKey = wiz.scopeKey || "";
      const targetKeys = Array.isArray(wiz.targetKeys) ? wiz.targetKeys : [];

      if (typeof samplingCtl.setScopeKey === "function") samplingCtl.setScopeKey(scopeKey);
      else samplingCtl.scopeKey = scopeKey;

      if (typeof samplingCtl.setTargetKeys === "function") samplingCtl.setTargetKeys(targetKeys);
      else samplingCtl.targetKeys = targetKeys;

      samplingCtl.emitSamplingConfigChanged?.();
    }

    const result = samplingCtl.runSamplingAndBuildResult();
    console.log("[sampling] result:", result);

    const keys = []
      .concat(result?.ingroup?.picked || [])
      .concat(result?.outgroupPicked || [])
      .map((x) => x?.key)
      .filter(Boolean);

    if (typeof renderer.revealKeys === "function" && keys.length) {
      renderer.revealKeys(keys, { fit: true });
    } else if (typeof renderer.openToRank === "function") {
      renderer.openToRank("species", { fit: true });
    } else {
      renderer.setRankCut?.("species");
      renderer.fitToView?.();
    }
  });

  // =========================================================================
  // 16) Init
  // =========================================================================
  load();

  window.addEventListener("beforeunload", () => {
    try { unbindSelList?.(); } catch (_) { }
  });
})();
