// taxonomy/static/taxonomy/js/tree/selection.js
/**
 * Selection panel manager.
 *
 * Renders the right-side selection panel in both modes:
 *  - Manual: user clicks nodes directly.
 *  - Sampling: results come from the sampling algorithm.
 *
 * Does NOT run sampling logic — that lives on the backend.
 */

import { escapeHtml } from "../shared/config.js";
import { copyToClipboard } from "../tree/ui.js";
import { asArraySelected, setText } from "../shared/helpers.js";

/**
 * @param {{ renderer: Object }} deps
 */
export function createSelectionManager({ renderer }) {
  /** Last sampling result (null = manual mode). */
  let lastSamplingResult = null;

  // ------------------------------------------------------------------
  // Badge mode (Manual / Sampling)
  // ------------------------------------------------------------------
  function setBadgeMode(modeText, isSampling) {
    const badge = document.getElementById("selModeBadge");
    if (!badge) return;

    badge.textContent = modeText || "Manual";
    badge.classList.remove(
      "bg-secondary-lt", "text-secondary",
      "bg-success-lt", "text-success",
    );

    if (isSampling) badge.classList.add("bg-success-lt", "text-success");
    else badge.classList.add("bg-secondary-lt", "text-secondary");
  }

  // ------------------------------------------------------------------
  // Selection badge counter
  // ------------------------------------------------------------------
  function updateSelectionBadge(count) {
    const badge = document.getElementById("selBadge");
    if (!badge) return;
    if (count > 0) {
      badge.textContent = String(count);
      badge.className = "badge rounded-pill bg-primary ms-2";
      badge.style.display = "";
    } else {
      badge.style.display = "none";
    }
  }

  // ------------------------------------------------------------------
  // Manual selection rendering
  // ------------------------------------------------------------------
  function renderSelListTbody(rowsHtml, emptyMsg = "No selection.") {
    const tbody = document.getElementById("selList");
    if (!tbody) return;
    tbody.innerHTML =
      rowsHtml ||
      `<tr><td class="text-muted small ps-3" colspan="2">${escapeHtml(emptyMsg)}</td></tr>`;
  }

  function renderSelectionManualTbody(selectedMap) {
    const items = asArraySelected(selectedMap);

    // Hide clades section in manual mode
    const cladesWrap = document.getElementById("selCladesWrap");
    if (cladesWrap) cladesWrap.classList.add("d-none");

    setText("selCount", String(items.length));
    setText("selRanks", "–");
    setText("selTarget", "–");

    const hint = document.getElementById("selHint");
    if (hint) hint.textContent = "";

    if (!items.length) {
      renderSelListTbody("", "No taxa selected.");
      return;
    }

    const sorted = items.slice().sort((a, b) =>
      String(a.rank || "").localeCompare(String(b.rank || "")) ||
      String(a.name || "").localeCompare(String(b.name || "")),
    );

    const rows = sorted.map((x) => {
      const selId = String(x.id || x.key || "");
      const rank = String(x.rank || "");
      const name = String(x.name || "");
      const nameHtml = rank.toLowerCase() === "species"
        ? `<em>${escapeHtml(name)}</em>`
        : `<span>${escapeHtml(name)}</span>`;
      return `
        <tr>
          <td class="ps-3">
            <span class="small text-muted me-2">${escapeHtml(rank)}</span>
            ${nameHtml}
          </td>
          <td class="text-end pe-3">
            <button type="button"
                    class="btn btn-sm btn-outline-danger"
                    data-sel-remove="${escapeHtml(selId)}"
                    title="Remove">
              Remove
            </button>
          </td>
        </tr>
      `;
    }).join("");

    renderSelListTbody(rows);
  }

  // ------------------------------------------------------------------
  // DB Sampling result rendering
  // ------------------------------------------------------------------
  function renderDbSamplingClades(result) {
    const cladesWrap = document.getElementById("selCladesWrap");
    const cladesBody = document.getElementById("selCladesBody");
    const cladesHint = document.getElementById("selCladesHint");

    const clades = Array.isArray(result?.clades) ? result.clades : [];

    if (!cladesWrap || !cladesBody) return;

    if (!clades.length) {
      cladesWrap.classList.add("d-none");
      return;
    }

    cladesWrap.classList.remove("d-none");

    if (cladesHint) {
      const total = clades.reduce((s, c) => s + (c.selected || 0), 0);
      cladesHint.textContent = `${clades.length} clades · ${total} species selected`;
    }

    cladesBody.innerHTML = clades.map(c => {
      const name = c.name || "Unknown";
      const avail = c.species_available ?? "—";
      const quota = c.quota ?? "—";
      const sel = c.selected ?? "—";
      return `<tr>
        <td title="${escapeHtml(name)}" style="word-break:break-word;white-space:normal;">${escapeHtml(name)}</td>
        <td class="text-end">${avail}</td>
        <td class="text-end">${quota}</td>
        <td class="text-end fw-bold">${sel}</td>
      </tr>`;
    }).join("");
  }

  function renderDbSamplingTbody(result) {
    const species = Array.isArray(result?.species) ? result.species : [];

    // Render the clades breakdown table
    renderDbSamplingClades(result);

    if (!species.length) {
      setText("selCount", "0");
      renderSelListTbody("", "No species selected.");
      return;
    }

    const html = species.map((s, i) => {
      const name = s.organism_name || s.name || "";
      const clade = s.clade_group || s.clade || "";
      const hasAsm = s.assembly_score !== undefined;
      const scoreHtml = hasAsm
        ? `<span class="badge bg-${s.assembly_score >= 0.6 ? 'success' : s.assembly_score >= 0.3 ? 'warning' : 'danger'}-lt small ms-1" title="Assembly score">${s.assembly_score.toFixed(2)}</span>`
        : "";
      const levelHtml = s.genome_level
        ? `<span class="badge bg-light text-muted small ms-1" title="Assembly level">${escapeHtml(s.genome_level)}</span>`
        : "";
      return `
        <tr>
          <td class="ps-3">
            <i class="fa-solid fa-dna text-success me-2" title="DB Sampling"></i>
            <span class="small text-muted me-2">${escapeHtml(clade)}</span>
            <em>${escapeHtml(name)}</em>
            ${scoreHtml}${levelHtml}
          </td>
          <td class="text-end pe-3">
            <button class="btn btn-sm btn-outline-secondary"
                    type="button"
                    data-copy-key="${escapeHtml(name)}"
                    title="Copy name">
              <i class="fa-solid fa-copy"></i>
            </button>
          </td>
        </tr>
      `;
    }).join("");

    renderSelListTbody(html);

    setText("selCount", String(species.length));

    // Compute distinct clades
    const cladeSet = new Set(species.map(s => s.clade_group || s.clade).filter(Boolean));
    setText("selRanks", String(cladeSet.size) + " clades");
    setText("selTarget", result.end_rank || result.strategy || "species");

    const hint = document.getElementById("selHint");
    if (hint) {
      const hasAssembly = species.some(s => s.assembly_score !== undefined);
      const asmNote = hasAssembly ? " | Assembly filtered" : "";
      hint.textContent = `Strategy: ${result.strategy || "—"} | ${species.length} species from ${cladeSet.size} clades${asmNote}`;
    }
  }

  // ------------------------------------------------------------------
  // Sampling rows normalizer (tree-based sampling)
  // ------------------------------------------------------------------
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

    const seen = new Set();
    const uniq = [];
    for (const r of rows) {
      if (seen.has(r.key)) continue;
      seen.add(r.key);
      uniq.push(r);
    }

    uniq.sort((a, b) => {
      if (a.group !== b.group) return a.group === "outgroup" ? -1 : 1;
      const ra = String(a.rank || ""), rb = String(b.rank || "");
      const cmpR = ra.localeCompare(rb);
      if (cmpR) return cmpR;
      return String(a.name || "").localeCompare(String(b.name || ""));
    });

    return uniq;
  }

  // ------------------------------------------------------------------
  // Sampling selection rendering
  // ------------------------------------------------------------------
  function renderSelectionSamplingTbody(result) {
    const rows = buildSamplingRows(result);

    // Hide clades section in tree-based sampling mode
    const cladesWrap = document.getElementById("selCladesWrap");
    if (cladesWrap) cladesWrap.classList.add("d-none");

    if (!rows.length) {
      setText("selCount", "0");
      renderSelListTbody("", "No selection.");
      return;
    }

    const icon = (g) =>
      g === "outgroup"
        ? `<i class="fa-solid fa-circle-dot text-warning me-2" title="Outgroup"></i>`
        : `<i class="fa-solid fa-leaf text-success me-2" title="Ingroup"></i>`;

    const html = rows.map((r) => {
      const nameTag = (r.rank || "").toLowerCase() === "species"
        ? `<em>${escapeHtml(r.name || "")}</em>`
        : `<span>${escapeHtml(r.name || "")}</span>`;
      return `
      <tr>
        <td class="ps-3">
          ${icon(r.group)}
          <span class="small text-muted me-2">${escapeHtml(r.rank || "")}</span>
          ${nameTag}
        </td>
        <td class="text-end pe-3">
          <button class="btn btn-sm btn-outline-secondary"
                  type="button"
                  data-copy-key="${escapeHtml(r.key)}"
                  title="Copy key">
            <i class="fa-solid fa-copy"></i>
          </button>
        </td>
      </tr>
    `).join("");

    renderSelListTbody(html);

    setText("selCount", String(rows.length));
    setText("selRanks", "–");
    setText("selTarget", result?.targetRank || result?.ingroup?.targetRank || "–");

    const hint = document.getElementById("selHint");
    if (hint) {
      const ingN = (result?.ingroup?.picked || []).length;
      const outN = (result?.outgroupPicked || []).length;
      hint.textContent = `Ingroup: ${ingN} | Outgroup: ${outN}`;
    }
  }

  // ------------------------------------------------------------------
  // Event delegation (remove / copy)
  // ------------------------------------------------------------------
  function bindSelListDelegation() {
    const tbody = document.getElementById("selList");
    if (!tbody) return () => {};

    const handler = async (e) => {
      const rmBtn = e.target.closest?.("[data-sel-remove]");
      if (rmBtn) {
        const selId = rmBtn.getAttribute("data-sel-remove");
        if (selId && typeof renderer.removeSelectedBySelId === "function") {
          renderer.removeSelectedBySelId(selId);
          repaintSelection();
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

  // ------------------------------------------------------------------
  // Core: repaint selection (auto-detects mode)
  // ------------------------------------------------------------------
  function repaintSelection() {
    let count = 0;
    if (lastSamplingResult) {
      // DB sampling results have a 'species' array
      if (Array.isArray(lastSamplingResult.species)) {
        renderDbSamplingTbody(lastSamplingResult);
        count = lastSamplingResult.species.length;
      } else {
        renderSelectionSamplingTbody(lastSamplingResult);
        count = Array.isArray(lastSamplingResult.rows)
          ? lastSamplingResult.rows.length
          : 0;
      }
    } else {
      const selectedMap = renderer.getSelectedSpecies?.();
      renderSelectionManualTbody(selectedMap);
      count = asArraySelected(selectedMap).length;
    }
    updateSelectionBadge(count);
  }

  // ------------------------------------------------------------------
  // Payload for export: sampling or manual fallback
  // ------------------------------------------------------------------
  function selectionToPayload(selectedMap) {
    return asArraySelected(selectedMap).map((x) => ({
      id: x.id,
      key: x.key,
      rank: x.rank,
      name: x.name,
    }));
  }

  function getExportPayload({ allowManualFallback = true } = {}) {
    if (lastSamplingResult) {
      // DB sampling result: transform to exportable format
      if (Array.isArray(lastSamplingResult.species)) {
        return lastSamplingResult.species.map(s => ({
          name: s.organism_name || "",
          taxid: s.taxid || "",
          accession: s.accession || "",
          rank: "species",
          clade: s.clade_group || s.clade || "",
        }));
      }
      return lastSamplingResult;
    }
    if (!allowManualFallback) return null;
    return selectionToPayload(renderer.getSelectedSpecies?.());
  }

  // ------------------------------------------------------------------
  // Sampling result state
  // ------------------------------------------------------------------
  function setLastSampling(result) {
    lastSamplingResult = result;
  }

  function getLastSampling() {
    return lastSamplingResult;
  }

  function clearSampling() {
    lastSamplingResult = null;
  }

  // ------------------------------------------------------------------
  // Public API
  // ------------------------------------------------------------------
  const unbind = bindSelListDelegation();

  return {
    repaintSelection,
    getExportPayload,
    setBadgeMode,
    setLastSampling,
    getLastSampling,
    clearSampling,
    unbind,
  };
}
