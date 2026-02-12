// taxonomy/static/taxonomy/js/tree/exports.js
/**
 * Export handlers for the selection panel.
 *
 * Binds the export buttons (JSON, TXT, Newick, clipboard)
 * to backend download endpoints or client-side copy.
 */

import { postDownload } from "../shared/helpers.js";
import { copyToClipboard } from "../tree/ui.js";

/**
 * @param {{ getExportPayload: Function, getLastSampling: Function }} deps
 */
export function initExportHandlers({ getExportPayload, getLastSampling }) {
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
    const payload = getLastSampling();
    if (!payload) return;

    const ing = payload?.ingroup?.picked || [];
    const out = payload?.outgroupPicked || [];
    const keys = []
      .concat(out.map((x) => x?.key))
      .concat(ing.map((x) => x?.key))
      .filter(Boolean);

    await copyToClipboard(keys.join("\n") + (keys.length ? "\n" : ""));
  });
}
