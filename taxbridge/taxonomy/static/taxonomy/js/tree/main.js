// taxonomy/static/taxonomy/js/tree/main.js
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

import { loadTreeData } from "./api.js";
import { createTreeRenderer } from "./d3_tree.js";
import { createSamplingFiltersController } from "./sampling_filters.js";

(function initTreePage() {
    const endpoint = window.TREE_ENDPOINT;
    const ui = createUIRefs();
    const tooltip = makeTooltip(ui.mount, ui.tt);

    // ---------------- helpers locales (NO dependen de ui.js) ----------------

    function asArraySelected(mapLike) {
        if (!mapLike) return [];
        if (mapLike instanceof Map) return Array.from(mapLike.values());
        // fallback por si el renderer devuelve array
        if (Array.isArray(mapLike)) return mapLike;
        try { return Array.from(mapLike.values()); } catch { return []; }
    }

    function selectionToPayload(selectedMap) {
        return asArraySelected(selectedMap).map((x) => ({
            id: x.id,
            key: x.key,
            rank: x.rank,
            name: x.name
        }));
    }

    function renderSelectionTableLite({ selListEl, selCountEl }, selectedMap) {
        const items = asArraySelected(selectedMap);

        if (selCountEl) selCountEl.textContent = String(items.length);

        if (!selListEl) return;

        // tabla simple y estable (no depende de estilos)
        if (!items.length) {
            selListEl.innerHTML = `
        <div class="p-2 text-muted small">
          (sin selección)
        </div>`;
            return;
        }

        const rows = items
            .slice()
            .sort((a, b) => (String(a.rank || "").localeCompare(String(b.rank || "")) || String(a.name || "").localeCompare(String(b.name || ""))))
            .map((x) => `
        <tr>
          <td class="small">${escapeHtml(String(x.rank || ""))}</td>
          <td class="small">${escapeHtml(String(x.name || ""))}</td>
          <td class="text-end">
            <button type="button" class="btn btn-sm btn-outline-danger" data-sel-remove="${escapeHtml(String(x.id || x.key || ""))}">
              Quitar
            </button>
          </td>
        </tr>
      `).join("");

        selListEl.innerHTML = `
      <div class="table-responsive">
        <table class="table table-sm mb-0">
          <thead>
            <tr>
              <th class="small">Rank</th>
              <th class="small">Name</th>
              <th></th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
      </div>`;
    }

    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, (c) => ({
            "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
        }[c]));
    }

    function bindSelectionRemove(selListEl, onRemove) {
        if (!selListEl) return () => { };
        const handler = (e) => {
            const btn =
                e.target.closest?.("[data-sel-remove]") ||
                e.target.closest?.(".sel-remove");

            if (!btn) return;

            const selId =
                btn.getAttribute("data-sel-remove") ||
                btn.getAttribute("data-sel-id") ||
                btn.dataset?.selId;

            if (selId && typeof onRemove === "function") onRemove(selId);
        };

        selListEl.addEventListener("click", handler);
        return () => selListEl.removeEventListener("click", handler);
    }

    // ---------------- renderer ----------------

    const renderer = createTreeRenderer({
        mount: ui.mount,
        tooltip,
        onSelectionChange: () => repaintSelection(),
        onCrumbChange: (txt) => setCrumb(ui.crumb, txt),
    });

    function repaintSelection() {
        renderSelectionTableLite(
            { selListEl: ui.selList, selCountEl: ui.selCount },
            renderer.getSelectedSpecies?.()
        );
    }

    const unbindSelRemove = bindSelectionRemove(ui.selList, (selId) => {
        if (typeof renderer.removeSelectedBySelId === "function") {
            renderer.removeSelectedBySelId(selId);
            repaintSelection();
            return;
        }

        // fallback: si tu renderer solo tiene clearSelection, no rompemos la UI
        console.warn("[selection] removeSelectedBySelId no existe. selId=", selId);
    });

    // ---------------- sampling controller ----------------
    const samplingCtl = createSamplingFiltersController({ renderer });
    samplingCtl.attachEventHandlers();
    // ---------------- sampling UI state (panel Selección) ----------------
    let lastSamplingResult = null;

    function buildSamplingRows(result) {
        const ing = Array.isArray(result?.ingroup?.picked) ? result.ingroup.picked : [];
        const out = Array.isArray(result?.outgroupPicked) ? result.outgroupPicked : [];

        // normaliza a {key,name,rank,group}
        const norm = (x, group) => ({
            key: x?.key || "",
            name: x?.name || "",
            rank: x?.rank || "",
            group
        });

        const rows = []
            .concat(ing.map((x) => norm(x, "ingroup")))
            .concat(out.map((x) => norm(x, "outgroup")))
            .filter((x) => x.key);

        // unique by key (por si algo se repite)
        const seen = new Set();
        const uniq = [];
        for (const r of rows) {
            if (seen.has(r.key)) continue;
            seen.add(r.key);
            uniq.push(r);
        }

        // orden estable: primero outgroup, luego ingroup; dentro por rank/name
        uniq.sort((a, b) => {
            if (a.group !== b.group) return a.group === "outgroup" ? -1 : 1;
            const ra = String(a.rank || ""), rb = String(b.rank || "");
            const cmpR = ra.localeCompare(rb);
            if (cmpR) return cmpR;
            return String(a.name || "").localeCompare(String(b.name || ""));
        });

        return uniq;
    }

    function setText(id, txt) {
        const el = document.getElementById(id);
        if (el) el.textContent = txt;
    }

    function setBadgeMode(modeText, isSampling) {
        const badge = document.getElementById("selModeBadge");
        if (!badge) return;

        badge.textContent = modeText || "Manual";
        badge.classList.remove("bg-secondary-lt", "text-secondary", "bg-success-lt", "text-success");

        if (isSampling) badge.classList.add("bg-success-lt", "text-success");
        else badge.classList.add("bg-secondary-lt", "text-secondary");
    }

    function renderSelListFromSampling(result) {
        const tbody = document.getElementById("selList");
        if (!tbody) return;

        const rows = buildSamplingRows(result);

        if (!rows.length) {
            tbody.innerHTML = `<tr><td class="text-muted small ps-3" colspan="2">Sin selección.</td></tr>`;
            return;
        }

        const icon = (g) =>
            g === "outgroup"
                ? `<i class="fa-solid fa-circle-dot text-warning me-2" title="Outgroup"></i>`
                : `<i class="fa-solid fa-leaf text-success me-2" title="Ingroup"></i>`;

        tbody.innerHTML = rows.map((r) => `
    <tr>
      <td class="ps-3">
        ${icon(r.group)}
        <span class="small text-muted me-2">${escapeHtml(r.rank || "")}</span>
        <span>${escapeHtml(r.name || "")}</span>
      </td>
      <td class="text-end pe-3">
        <button class="btn btn-sm btn-outline-secondary" type="button" data-copy-key="${escapeHtml(r.key)}" title="Copiar key">
          <i class="fa-solid fa-copy"></i>
        </button>
      </td>
    </tr>
  `).join("");

        // métricas
        const ingN = (result?.ingroup?.picked || []).length;
        const outN = (result?.outgroupPicked || []).length;
        setText("selCount", String(rows.length));
        setText("selRanks", "–"); // si quieres, lo calculamos también
        setText("selTarget", (result?.targetRank || result?.ingroup?.targetRank || "–"));

        // hint
        const hint = document.getElementById("selHint");
        if (hint) hint.textContent = `Ingroup: ${ingN} | Outgroup: ${outN}`;
    }

    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, (c) => ({
            "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
        }[c]));
    }
    // ---------------- escuchar resultado final de sampling ----------------
    window.addEventListener("sampling:final", (ev) => {
        lastSamplingResult = ev.detail || null;
        if (!lastSamplingResult) return;

        // UI panel
        setBadgeMode("Sampling", true);

        const sub = document.getElementById("selSubtitle");
        if (sub) sub.textContent = "Taxones seleccionados por sampling (ingroup + outgroup)";

        renderSelListFromSampling(lastSamplingResult);

        // mostrar barra de estado
        const st = document.getElementById("samplingStatus");
        if (st) st.classList.remove("d-none");
    });
    // ---------------- botones vista sampling ----------------
    document.getElementById("applySamplingView")?.addEventListener("click", () => {
        if (!lastSamplingResult) return;

        const keys = []
            .concat(lastSamplingResult?.ingroup?.picked || [])
            .concat(lastSamplingResult?.outgroupPicked || [])
            .map((x) => x?.key)
            .filter(Boolean);

        // Preferimos revelar keys (si implementaste revealKeys). Si no, abrir a species.
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

        // UI panel vuelve a manual (no tocamos selección manual aquí)
        setBadgeMode("Manual", false);

        const sub = document.getElementById("selSubtitle");
        if (sub) sub.textContent = "Taxones seleccionados para muestreo/exportación";

        const hint = document.getElementById("selHint");
        if (hint) hint.textContent = "";

        const st = document.getElementById("samplingStatus");
        if (st) st.classList.add("d-none");

        // volver a árbol completo
        renderer.setSamplingMode?.("");
        renderer.setSamplingRootKey?.(null);
        renderer.setRankCut?.(null);
        renderer.fitToView?.();

        // repintar selección manual
        repaintSelection?.();
    });
    document.getElementById("selList")?.addEventListener("click", async (e) => {
        const btn = e.target.closest?.("[data-copy-key]");
        if (!btn) return;
        const key = btn.getAttribute("data-copy-key");
        if (!key) return;
        await copyToClipboard(key);
    });

    // ---------------- Expand-to-rank dropdown wiring ----------------
    document.querySelectorAll(".dropdown-menu [data-rank]").forEach((item) => {
        item.addEventListener("click", (e) => {
            e.preventDefault();
            const rank = item.dataset.rank || "";
            const label = item.textContent.trim();

            if (typeof renderer.setRankCut === "function") renderer.setRankCut(rank);

            const lbl = document.getElementById("vizRankLabel");
            if (lbl) lbl.textContent = label;
        });
    });

    // ---------------- Sampling root dropdown ----------------
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

    // ---------------- Search wiring (si tu renderer lo soporta) ----------------
    function setSearchControlsState(info) {
        const prevBtn = document.getElementById("taxSearchPrev");
        const nextBtn = document.getElementById("taxSearchNext");
        const clrBtn = document.getElementById("taxSearchClear");

        const hasMany = (info?.count || 0) > 1;
        const hasAny = (info?.count || 0) > 0;

        if (prevBtn) prevBtn.disabled = !hasMany;
        if (nextBtn) nextBtn.disabled = !hasMany;
        if (clrBtn) clrBtn.disabled = !hasAny;
    }

    function runTaxSearch() {
        const inp = document.getElementById("taxSearch");
        if (!inp) return;

        const q = inp.value.trim();
        if (q.length < 2) return;
        if (typeof renderer.searchStart !== "function") return;

        const res = renderer.searchStart(q);
        setSearchControlsState(res);
    }

    document.getElementById("taxSearchGo")?.addEventListener("click", runTaxSearch);
    document.getElementById("taxSearch")?.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
            e.preventDefault();
            runTaxSearch();
        }
    });

    document.getElementById("taxSearchNext")?.addEventListener("click", () => {
        if (typeof renderer.searchNext !== "function") return;
        setSearchControlsState(renderer.searchNext());
    });

    document.getElementById("taxSearchPrev")?.addEventListener("click", () => {
        if (typeof renderer.searchPrev !== "function") return;
        setSearchControlsState(renderer.searchPrev());
    });

    document.getElementById("taxSearchClear")?.addEventListener("click", () => {
        const inp = document.getElementById("taxSearch");
        if (!inp) return;

        if (typeof renderer.searchClear === "function") {
            setSearchControlsState(renderer.searchClear());
        }

        inp.value = "";
        inp.focus();
    });

    // ---------------- Load ----------------
    async function load() {
        try {
            if (!endpoint || typeof endpoint !== "string" || !endpoint.trim()) {
                throw new Error("TREE_ENDPOINT está vacío o no definido. Revisa tu template (window.TREE_ENDPOINT).");
            }

            console.log("[TREE] endpoint =", endpoint);

            const data = await loadTreeData(endpoint);

            samplingCtl.setData(data);
            renderer.render(data);

            setSearchControlsState({ count: 0, idx: -1 });

            if (ui.tt) ui.tt.style.zIndex = 20;
            if (ui.fsBtn) ui.fsBtn.style.zIndex = 30;

            setCrumb(ui.crumb, "ROOT");
            tooltip.hide();

            repaintSelection();

            const samplingSel = document.getElementById("samplingRoot");
            if (samplingSel) {
                samplingSel.value = "";
                renderer.setSamplingMode?.("");
            }

            samplingCtl.resetDefaults?.();
            samplingCtl.emitSamplingConfigChanged?.();
        } catch (err) {
            console.error(err);
            showLoadError(ui.mount, `Error cargando árbol: ${err?.message || err}`);
        }
    }

    // ---------------- UI buttons ----------------
    ui.loadBtn?.addEventListener("click", load);

    ui.fitBtn?.addEventListener("click", () => {
        if (typeof renderer.fitToView === "function") renderer.fitToView();
    });

    ui.collapseAllBtn?.addEventListener("click", () => {
        if (typeof renderer.collapseAll === "function") renderer.collapseAll();

        const samplingSel = document.getElementById("samplingRoot");
        if (samplingSel) samplingSel.value = "";

        samplingCtl.resetDefaults?.();
        samplingCtl.emitSamplingConfigChanged?.();

        repaintSelection();
    });

    ui.clearSel?.addEventListener("click", () => {
        if (typeof renderer.clearSelection === "function") renderer.clearSelection();
        repaintSelection();
        // si había sampling activo en el panel, lo ocultamos
        const st = document.getElementById("samplingStatus");
        if (st) st.classList.add("d-none");
        setBadgeMode("Manual", false);

    });

    ui.exportSel?.addEventListener("click", () => {
        const payload = selectionToPayload(renderer.getSelectedSpecies?.());
        downloadText("selection.json", JSON.stringify(payload, null, 2), "application/json;charset=utf-8");
    });

    // export txt si tu UI lo tiene (opcional)
    ui.exportSelTxt?.addEventListener?.("click", async () => {
        const payload = selectionToPayload(renderer.getSelectedSpecies?.());
        const txt = toTxtList(payload);
        await copyToClipboard(txt);
    });

    // tooltip safety
    ui.mount?.addEventListener("mouseleave", tooltip.hide);
    ui.mount?.addEventListener("scroll", tooltip.hide);

    // fullscreen: usa mount como target (tu comportamiento original)
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

    // ---------------- Generar sampling ----------------
    document.getElementById("runSampling")?.addEventListener("click", async () => {
        if (typeof samplingCtl.runSamplingAndBuildResult !== "function") {
            console.warn("[sampling] samplingCtl.runSamplingAndBuildResult no existe.");
            return;
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

    // init
    load();

    window.addEventListener("beforeunload", () => {
        try { unbindSelRemove?.(); } catch (_) { }
    });
})();
