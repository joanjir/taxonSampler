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
  // DataTable instance
  // ------------------------------------------------------------------
  let _dt = null;

  function _ensureDT() {
    if (_dt) return _dt;
    const $ = window.jQuery;
    const tbl = document.getElementById("selTable");
    if (!tbl || !$ || !$.fn.DataTable) return null;

    // Remove any placeholder rows with colspan (breaks DT init)
    tbl.querySelector("tbody").innerHTML = "";

    _dt = $(tbl).DataTable({
      paging: false,
      ordering: true,
      info: false,
      lengthChange: false,
      autoWidth: false,
      dom: "t",                       // table only — filters live in thead
      language: {
        emptyTable: "No taxa selected.",
        zeroRecords: "No matching records.",
      },
      columnDefs: [
        { targets: 0, className: "ps-2 text-muted small" },
        { targets: [3, 4, 5], className: "text-center" },
        { targets: 6, orderable: false, className: "text-end pe-2" },
      ],
      initComplete: function () {
        const filterRow = document.createElement("tr");
        filterRow.className = "sel-col-filters";
        // cols: 0=#  1=Clade  2=Species  3=Quality  4=Assembly  5=Level  6=Actions
        const searchable = { 1: "Clade…", 2: "Species…", 3: "Quality…", 4: "Assembly…", 5: "Level…" };
        this.api().columns().every(function () {
          const idx = this.index();
          const th = document.createElement("th");
          if (searchable[idx]) {
            const input = document.createElement("input");
            input.type = "search";
            input.className = "form-control form-control-sm sel-col-input";
            input.placeholder = searchable[idx];
            const col = this;
            input.addEventListener("keyup", () => { col.search(input.value).draw(); });
            input.addEventListener("click", (e) => e.stopPropagation()); // avoid sorting
            th.appendChild(input);
          }
          filterRow.appendChild(th);
        });
        tbl.querySelector("thead").appendChild(filterRow);
      },
    });

    return _dt;
  }

  /** Clear DT and load new rows (each row = 7-element array). */
  function _dtLoad(rows) {
    const dt = _ensureDT();
    if (!dt) return;
    dt.clear();
    if (rows.length) dt.rows.add(rows);
    dt.draw();
  }

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
      "text-dark",
    );

    if (isSampling) badge.classList.add("bg-success-lt", "text-dark");
    else badge.classList.add("bg-secondary-lt", "text-dark");
  }

  // ------------------------------------------------------------------
  // Selection badge counter
  // ------------------------------------------------------------------
  function updateSelectionBadge(count) {
    const badge = document.getElementById("selBadge");
    if (!badge) return;
    if (count > 0) {
      badge.textContent = String(count);
      badge.className = "badge rounded-pill bg-primary-lt text-dark ms-2";
      badge.style.display = "";
    } else {
      badge.style.display = "none";
    }
  }

  // ------------------------------------------------------------------
  // Manual selection rendering
  // ------------------------------------------------------------------
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

    if (!items.length) { _dtLoad([]); return; }

    const sorted = items.slice().sort((a, b) =>
      String(a.rank || "").localeCompare(String(b.rank || "")) ||
      String(a.name || "").localeCompare(String(b.name || "")),
    );

    const rows = sorted.map((x, i) => {
      const selId = String(x.id || x.key || "");
      const rank = String(x.rank || "");
      const name = String(x.name || "");
      const nameHtml = ["species", "subspecies"].includes(rank.toLowerCase())
        ? `<em>${escapeHtml(name)}</em>`
        : escapeHtml(name);
      return [
        i + 1,
        escapeHtml(rank),
        nameHtml,
        "",
        "",
        "",
        `<button type="button" class="btn btn-sm btn-outline-danger py-0 px-1" data-sel-remove="${escapeHtml(selId)}" title="Remove"><i class="fa-solid fa-trash-can"></i></button>`,
      ];
    });

    _dtLoad(rows);
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

    // Only update clades table when data includes clades info (Step 2).
    // Step 3 (assembly filter) doesn't carry clades — preserve existing.
    if (Array.isArray(result?.clades)) {
      renderDbSamplingClades(result);
    }

    if (!species.length) {
      setText("selCount", "0");
      _dtLoad([]);
      return;
    }

    const rows = species.map((s, i) => {
      const name = s.organism_name || s.name || "";
      const clade = s.clade_group || s.clade || "";

      // Quality score (from db_engine)
      const hasSp = s.species_score !== undefined && s.species_score !== null;
      const spScore = hasSp ? s.species_score : 0;
      const spColor = spScore >= 0.6 ? "success" : spScore >= 0.3 ? "warning" : "secondary";
      const spScoreHtml = hasSp
        ? `<span class="badge bg-${spColor}-lt text-dark" title="Quality: level, N50, coverage, BUSCO, annotation">${spScore.toFixed(2)}</span>`
        : `<span class="text-muted">—</span>`;

      // Assembly score (from assembly_engine, Step 3)
      const hasAsm = s.assembly_score !== undefined;
      const asmColor = hasAsm
        ? (s.assembly_score >= 0.6 ? "success" : s.assembly_score >= 0.3 ? "warning" : "danger")
        : "";
      const asmScoreHtml = hasAsm
        ? `<span class="badge bg-${asmColor}-lt text-dark">${s.assembly_score.toFixed(2)}</span>`
        : `<span class="text-muted">—</span>`;

      // Genome level
      const levelHtml = s.genome_level
        ? `<span class="badge bg-azure-lt text-dark">${escapeHtml(s.genome_level)}</span>`
        : `<span class="text-muted">—</span>`;

      return [
        i + 1,
        `<span class="small" title="${escapeHtml(clade)}">${escapeHtml(clade)}</span>`,
        `<em>${escapeHtml(name)}</em>`,
        spScoreHtml,
        asmScoreHtml,
        levelHtml,
        `<button class="btn btn-sm btn-outline-secondary py-0 px-1" type="button" data-copy-key="${escapeHtml(name)}" title="Copy name"><i class="fa-solid fa-copy"></i></button>`
        + `<button class="btn btn-sm btn-outline-danger py-0 px-1 ms-1 sel-remove-org" type="button" data-org="${escapeHtml(name)}" title="Remove from selection"><i class="fa-solid fa-trash"></i></button>`,
      ];
    });

    _dtLoad(rows);

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
      _dtLoad([]);
      return;
    }

    const icon = (g) =>
      g === "outgroup"
        ? `<i class="fa-solid fa-circle-dot text-warning" title="Outgroup"></i>`
        : `<i class="fa-solid fa-leaf text-success" title="Ingroup"></i>`;

    const data = rows.map((r, i) => {
      const nameTag = ["species", "subspecies"].includes((r.rank || "").toLowerCase())
        ? `<em>${escapeHtml(r.name || "")}</em>`
        : escapeHtml(r.name || "");
      return [
        icon(r.group),
        `<span class="small text-muted">${escapeHtml(r.rank || "")}</span>`,
        nameTag,
        "",
        "",
        "",
        `<button class="btn btn-sm btn-outline-secondary py-0 px-1" type="button" data-copy-key="${escapeHtml(r.key)}" title="Copy key"><i class="fa-solid fa-copy"></i></button>`,
      ];
    });

    _dtLoad(data);

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
    const table = document.getElementById("selTable");
    if (!table) return () => {};

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

      // Handle remove organism from sampling selection
      const rmOrgBtn = e.target.closest?.(".sel-remove-org");
      if (rmOrgBtn) {
        const orgName = rmOrgBtn.getAttribute("data-org");
        if (orgName && lastSamplingResult?.species) {
          // Remove from species array
          lastSamplingResult.species = lastSamplingResult.species.filter(
            s => (s.organism_name || s.name) !== orgName
          );
          lastSamplingResult.total_selected = lastSamplingResult.species.length;
          
          // Repaint
          repaintSelection();
          
          // Update phylo tree if available
          if (window.removeOrganismFromSelection) {
            // Use the global function to also update phylo tree
            // But since we already updated here, just log it
            console.log(`[selection] Removed ${orgName} from selection`);
          }
          
          // Dispatch event to update phylo tree
          window.dispatchEvent(new CustomEvent("selection:changed", { 
            detail: lastSamplingResult 
          }));
        }
        return;
      }

      const cpBtn = e.target.closest?.("[data-copy-key]");
      if (cpBtn) {
        const key = cpBtn.getAttribute("data-copy-key") || "";
        if (key) await copyToClipboard(key);
      }
    };

    table.addEventListener("click", handler);
    return () => table.removeEventListener("click", handler);
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
