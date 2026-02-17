// taxonomy/static/taxonomy/js/tree/exports.js
/**
 * Export handlers for the selection panel.
 *
 * Binds the export buttons (JSON, TXT, Newick, clipboard)
 * to backend download endpoints or client-side copy.
 *
 * Supports both tree-based sampling (ingroup/outgroup) and
 * DB-based sampling (species array).
 */

import { postDownload } from "../shared/helpers.js";
import { copyToClipboard } from "../tree/ui.js";

/**
 * Detect if a payload is a DB sampling result (species array)
 * vs tree-based sampling (ingroup/outgroupPicked).
 */
function isDbSamplingResult(payload) {
  return Array.isArray(payload?.species) || (Array.isArray(payload) && payload[0]?.accession != null);
}

/**
 * Client-side download helper — saves a blob directly without posting to server.
 */
function clientDownload(content, filename, mimeType = "text/plain;charset=utf-8") {
  const blob = new Blob([content], { type: mimeType });
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(href);
}

/**
 * @param {{ getExportPayload: Function, getLastSampling: Function }} deps
 */
export function initExportHandlers({ getExportPayload, getLastSampling }) {
  document.getElementById("exportSelJson")?.addEventListener("click", async () => {
    const last = getLastSampling();

    if (last && isDbSamplingResult(last)) {
      // DB sampling: export as client-side JSON
      const data = JSON.stringify(last, null, 2);
      clientDownload(data, "sampling.json", "application/json;charset=utf-8");
      return;
    }

    // Tree-based sampling: post to server
    const payload = getExportPayload({ allowManualFallback: true });
    if (!payload) return;
    await postDownload("/taxonomy/sampling/export/json/", payload, "sampling.json");
  });

  document.getElementById("exportSelTxt")?.addEventListener("click", async () => {
    const last = getLastSampling();

    if (last && isDbSamplingResult(last)) {
      // DB sampling: export species list as TXT
      const species = last.species || [];
      const lines = species.map((s, i) =>
        `${i + 1}\t${s.organism_name || ""}\t${s.taxid || ""}\t${s.accession || ""}\t${s.clade_group || ""}`
      );
      const header = "#\torganism_name\ttaxid\taccession\tclade";
      const txt = header + "\n" + lines.join("\n") + "\n";
      clientDownload(txt, "sampling.txt");
      return;
    }

    const payload = getExportPayload({ allowManualFallback: true });
    if (!payload) return;
    await postDownload("/taxonomy/sampling/export/txt/", payload, "sampling.txt");
  });

  document.getElementById("exportSelNewick")?.addEventListener("click", async () => {
    const last = getLastSampling();

    if (last && isDbSamplingResult(last)) {
      // DB sampling: request server-generated Newick from the new endpoint
      try {
        const url = window.NEWICK_ENDPOINT || "/api/v1/taxonomy/sampling/newick/";
        await postDownload(url, last, "sampling_taxonomic.newick");
      } catch (err) {
        console.error("[exports] Newick export error:", err);
        alert("Newick export failed: " + (err.message || err));
      }
      return;
    }

    const payload = getExportPayload({ allowManualFallback: false });
    if (!payload) return;
    await postDownload("/taxonomy/sampling/export/newick/", payload, "sampling_taxonomic.newick");
  });

  document.getElementById("copySel")?.addEventListener("click", async () => {
    const last = getLastSampling();

    if (last && isDbSamplingResult(last)) {
      // DB sampling: copy species names
      const species = last.species || [];
      const names = species.map(s => s.organism_name || s.name || "").filter(Boolean);
      if (names.length) {
        await copyToClipboard(names.join("\n") + "\n");
      }
      return;
    }

    // Tree-based sampling: copy keys
    if (!last) return;
    const ing = last?.ingroup?.picked || [];
    const out = last?.outgroupPicked || [];
    const keys = []
      .concat(out.map((x) => x?.key))
      .concat(ing.map((x) => x?.key))
      .filter(Boolean);

    await copyToClipboard(keys.join("\n") + (keys.length ? "\n" : ""));
  });
}
