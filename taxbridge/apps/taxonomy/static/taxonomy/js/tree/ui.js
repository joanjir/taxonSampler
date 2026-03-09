// taxonomy/static/taxonomy/js/tree/ui.js
import { escapeHtml } from "../shared/config.js";

/**
 * UI utilities (DOM-only).
 * Renders the <tbody> table with real <tr> rows + metrics/badges.
 */

export function createUIRefs() {
  const mount = document.getElementById("treeMount");
  if (!mount) throw new Error("#treeMount not found in the DOM");

  return {
    mount,
    tt: document.getElementById("tt"),
    crumb: document.getElementById("crumb"),

    loadBtn: document.getElementById("loadBtn"),
    fitBtn: document.getElementById("fitBtn"),
    collapseAllBtn: document.getElementById("collapseAllBtn"),
    zoomInBtn: document.getElementById("zoomInBtn"),
    zoomOutBtn: document.getElementById("zoomOutBtn"),
    homeBtn: document.getElementById("homeBtn"),

    clearFilters: document.getElementById("clearFilters"),
    clearSel: document.getElementById("clearSel"),

    // Selection panel 
    selCard: document.getElementById("selCard"),
    selModeBadge: document.getElementById("selModeBadge"),
    selSubtitle: document.getElementById("selSubtitle"),
    selHint: document.getElementById("selHint"),
    selList: document.getElementById("selList"),
    selCount: document.getElementById("selCount"),
    selRanks: document.getElementById("selRanks"),
    selTarget: document.getElementById("selTarget"),
    samplingStatus: document.getElementById("samplingStatus"),
    applySamplingView: document.getElementById("applySamplingView"),
    clearSamplingView: document.getElementById("clearSamplingView"),

    // Export actions 
    exportSelJson: document.getElementById("exportSelJson"),
    exportSelTxt: document.getElementById("exportSelTxt"),
    exportSelNewick: document.getElementById("exportSelNewick"),
    copySel: document.getElementById("copySel"),

    fsBtn: document.getElementById("fsBtn"),
    fsIcon: document.getElementById("fsIcon"),

    samplingNote: document.getElementById("samplingNote"),
  };
}

export function makeTooltip(mount, tt) {
  const hasTT = !!tt;

  function show(clientX, clientY, text) {
    if (!hasTT) return;

    const rect = mount.getBoundingClientRect();
    const x = clientX - rect.left;
    const y = clientY - rect.top;

    tt.textContent = text;
    tt.style.left = x + 14 + "px";
    tt.style.top = y + 14 + "px";
    tt.style.opacity = "1";
    tt.style.transform = "translateY(0)";
  }

  function hide() {
    if (!hasTT) return;
    tt.style.opacity = "0";
    tt.style.transform = "translateY(4px)";
  }

  return { show, hide };
}

export function setCrumb(crumbEl, text) {
  if (!crumbEl) return;
  crumbEl.textContent = text || "ROOT";
}

/**
 * Renders the selection/sampling panel in the <tbody>.
 *
 * items: [{ name, rank, key }]
 * opts:
 *  - mode: "manual" | "sampling"
 *  - targetRank: string|null
 *  - hint: string|null
 *  - onRemove: (item) => void 
 */
export function renderSelectionPanel(ui, items, opts = {}) {
  if (!ui?.selList) return;

  const mode = (opts.mode || "manual").toLowerCase();
  const targetRank = opts.targetRank || "–";
  const hint = opts.hint || "";

  // Badge + subtitle
  if (ui.selModeBadge) {
    if (mode === "sampling") {
      ui.selModeBadge.textContent = "Sampling";
      ui.selModeBadge.className = "badge bg-success-lt text-success ms-2";
    } else {
      ui.selModeBadge.textContent = "Manual";
      ui.selModeBadge.className = "badge bg-secondary-lt text-secondary ms-2";
    }
  }
  if (ui.selSubtitle) {
    ui.selSubtitle.textContent =
      mode === "sampling"
        ? "Taxa selected by the sampling algorithm"
        : "Taxa selected for sampling/export";
  }

  if (ui.selTarget) ui.selTarget.textContent = targetRank;
  if (ui.selHint) ui.selHint.textContent = hint;

  // metrics
  const total = (items || []).length;
  const ranks = new Set((items || []).map((x) => (x.rank || "").toLowerCase()).filter(Boolean));
  if (ui.selCount) ui.selCount.textContent = String(total);
  if (ui.selRanks) ui.selRanks.textContent = ranks.size ? Array.from(ranks).sort().join(", ") : "–";

  // sampling status bar
  if (ui.samplingStatus) {
    if (mode === "sampling" && total > 0) ui.samplingStatus.classList.remove("d-none");
    else ui.samplingStatus.classList.add("d-none");
  }

  // tabla
  if (!total) {
    ui.selList.innerHTML = `
      <tr>
        <td class="text-muted small ps-3" colspan="2">No selection.</td>
      </tr>`;
    return;
  }

  // stable order: rank -> name
  const sorted = (items || []).slice().sort((a, b) => {
    const ra = (a.rank || "").toLowerCase();
    const rb = (b.rank || "").toLowerCase();
    if (ra !== rb) return ra < rb ? -1 : 1;
    const na = a.name || "";
    const nb = b.name || "";
    return na.localeCompare(nb);
  });

  ui.selList.innerHTML = sorted
    .map((x, idx) => {
      const name = escapeHtml(x.name || "");
      const rank = escapeHtml((x.rank || "").toLowerCase());
      const canRemove = mode === "manual" && typeof opts.onRemove === "function";
      return `
        <tr data-idx="${idx}">
          <td class="ps-3">
            <div class="d-flex flex-column">
              <span>${name}</span>
              <span class="text-muted small">${rank || "?"}</span>
            </div>
          </td>
          <td class="text-end pe-3">
            ${
              canRemove
                ? `<button class="btn btn-sm btn-outline-danger sel-remove" type="button" title="Remove">
                     <i class="fa-solid fa-xmark"></i>
                   </button>`
                : `<span class="text-muted small">—</span>`
            }
          </td>
        </tr>`;
    })
    .join("");

  // bind remove clicks (delegation)
  if (mode === "manual" && typeof opts.onRemove === "function") {
    ui.selList.querySelectorAll(".sel-remove").forEach((btn) => {
      btn.addEventListener("click", (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        const tr = btn.closest("tr");
        const idx = tr ? parseInt(tr.dataset.idx || "-1", 10) : -1;
        if (!Number.isFinite(idx) || idx < 0) return;
        const item = sorted[idx];
        if (item) opts.onRemove(item);
      });
    });
  }
}

export function showInlineNote(noteEl, message, { kind = "muted" } = {}) {
  if (!noteEl) return;

  if (!message) {
    noteEl.innerHTML = "";
    noteEl.style.display = "none";
    return;
  }

  const cls =
    kind === "warning"
      ? "text-warning"
      : kind === "danger"
      ? "text-danger"
      : kind === "success"
      ? "text-success"
      : "text-muted";

  noteEl.innerHTML = `<div class="small ${cls}">${escapeHtml(message)}</div>`;
  noteEl.style.display = "block";
}

export function isFullscreen() {
  return !!(document.fullscreenElement || document.webkitFullscreenElement);
}

export async function toggleFullscreen(el) {
  if (!el) return;

  if (!isFullscreen()) {
    if (el.requestFullscreen) await el.requestFullscreen();
    else if (el.webkitRequestFullscreen) await el.webkitRequestFullscreen();
  } else {
    if (document.exitFullscreen) await document.exitFullscreen();
    else if (document.webkitExitFullscreen) await document.webkitExitFullscreen();
  }
}

export function syncFsIcon(fsIconEl) {
  if (!fsIconEl) return;

  if (isFullscreen()) {
    fsIconEl.classList.remove("fa-expand");
    fsIconEl.classList.add("fa-compress");
  } else {
    fsIconEl.classList.remove("fa-compress");
    fsIconEl.classList.add("fa-expand");
  }
}

export function showLoadError(mount, message) {
  if (!mount) return;
  mount.innerHTML = `<div class="text-danger small" style="padding:10px;">${escapeHtml(
    message
  )}</div>`;
}

// -------- Export helpers --------

export function toTxtList(items) {
  const sorted = (items || []).slice().sort((a, b) => (a.name || "").localeCompare(b.name || ""));
  return sorted.map((x) => x.name || "").filter(Boolean).join("\n") + "\n";
}

export async function copyToClipboard(text) {
  if (!text) return false;
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // fallback
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.left = "-9999px";
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand("copy");
      document.body.removeChild(ta);
      return true;
    } catch {
      document.body.removeChild(ta);
      return false;
    }
  }
}

import { saveAs } from "../shared/save_as.js";

export async function downloadText(filename, text, mime = "text/plain;charset=utf-8") {
  await saveAs(text || "", filename, mime);
}
