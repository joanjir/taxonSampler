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
import { saveAs } from "../shared/save_as.js";

/**
 * Dynamically load SheetJS (xlsx) from CDN if not already loaded.
 * Returns the XLSX global.
 */
let _xlsxPromise = null;
function loadXLSX() {
  if (window.XLSX) return Promise.resolve(window.XLSX);
  if (_xlsxPromise) return _xlsxPromise;
  _xlsxPromise = new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://cdn.sheetjs.com/xlsx-0.20.3/package/dist/xlsx.full.min.js";
    s.onload = () => resolve(window.XLSX);
    s.onerror = () => reject(new Error("Failed to load SheetJS library"));
    document.head.appendChild(s);
  });
  return _xlsxPromise;
}

/**
 * Detect if a payload is a DB sampling result (species array)
 * vs tree-based sampling (ingroup/outgroupPicked).
 */
function isDbSamplingResult(payload) {
  return Array.isArray(payload?.species) || (Array.isArray(payload) && payload[0]?.accession != null);
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
      await saveAs(data, "sampling.json", "application/json;charset=utf-8");
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
      await saveAs(txt, "sampling.txt");
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

  document.getElementById("exportSelExcel")?.addEventListener("click", async () => {
    const last = getLastSampling();
    if (!last || !isDbSamplingResult(last)) {
      alert("Excel export is only available after DB sampling.");
      return;
    }

    try {
      const XLSX = await loadXLSX();
      const species = last.species || [];

      // Build rows with all available fields
      const rows = species.map((s, i) => ({
        "#":               i + 1,
        "Organism Name":   s.organism_name || "",
        "Scientific Name": s.scientific_name || s.organism_name || "",
        "TaxID":           s.taxid || "",
        "Accession":       s.accession || "",
        "Kingdom":         s.kingdom || "",
        "Phylum":          s.phylum || "",
        "Class":           s.class || "",
        "Order":           s.order || "",
        "Family":          s.family || "",
        "Genus":           s.genus || "",
        "COL Name":        s.col_name || "",
        "Clade Group":     s.clade_group || "",
        "Genome Level":    s.genome_level || "",
        "RefSeq Category": s.refseq_category || "",
        "Coverage":        s.genome_coverage ?? "",
        "Genome Size (bp)": s.total_sequence_length ?? "",
        "GC %":            s.gc_percent ?? "",
        "Contig N50 (kb)": s.contig_n50_kb ?? "",
        "Scaffold N50 (kb)": s.scaffold_n50_kb ?? "",
        "Scaffolds":       s.scaffold_count ?? "",
        "Chromosomes":     s.chromosome_count ?? "",
        "Genes":           s.genes ?? "",
        "Protein Coding":  s.protein_coding ?? "",
        "Quality Score":   s.quality_score ?? "",
        "Release Date":    s.release_date || "",
        "Source DB":       s.source_database || "",
        "Sequencing Tech": s.sequencing_tech || "",
        "BUSCO Complete %": s.busco_complete ?? "",
      }));

      // Create workbook with two sheets: Species + Clades
      const wb = XLSX.utils.book_new();

      // Sheet 1: Species
      const wsSpecies = XLSX.utils.json_to_sheet(rows);
      // Auto-width columns
      const colWidths = Object.keys(rows[0] || {}).map(k => ({
        wch: Math.max(k.length, ...rows.map(r => String(r[k] ?? "").length).slice(0, 50)) + 2
      }));
      wsSpecies["!cols"] = colWidths;
      XLSX.utils.book_append_sheet(wb, wsSpecies, "Species");

      // Sheet 2: Clades allocation
      const clades = (last.clades || []).map(c => ({
        "Clade":     c.name || "",
        "Rank":      c.rank || "",
        "Available": c.species_available ?? "",
        "Quota":     c.quota ?? "",
        "Sampled":   c.selected ?? "",
      }));
      if (clades.length) {
        const wsClades = XLSX.utils.json_to_sheet(clades);
        XLSX.utils.book_append_sheet(wb, wsClades, "Clades");
      }

      // Download with Save-As dialog
      const wbOut = XLSX.write(wb, { bookType: "xlsx", type: "array" });
      const xlsxBlob = new Blob([wbOut], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
      await saveAs(xlsxBlob, "sampling_report.xlsx", xlsxBlob.type);
    } catch (err) {
      console.error("[exports] Excel export error:", err);
      alert("Excel export failed: " + (err.message || err));
    }
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
