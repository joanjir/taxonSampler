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

import { postDownload, getCookie } from "../shared/helpers.js";
import { copyToClipboard } from "../tree/ui.js";
import { saveAs } from "../shared/save_as.js";

/**
 * Dynamically load SheetJS with style support (xlsx-js-style) from CDN.
 * Returns the XLSX global.
 */
let _xlsxPromise = null;
function loadXLSX() {
  if (window.XLSX) return Promise.resolve(window.XLSX);
  if (_xlsxPromise) return _xlsxPromise;
  _xlsxPromise = new Promise((resolve, reject) => {
    const s = document.createElement("script");
    // Use xlsx-js-style for cell styling support (yellow headers, bold, etc.)
    s.src = "https://cdn.jsdelivr.net/npm/xlsx-js-style@1.2.0/dist/xlsx.bundle.js";
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

  /** Guard: block export when there are no species */
  function requireSpecies(last) {
    if (!last) {
      Swal.fire({ icon: 'info', title: 'Nothing to export', text: 'Run sampling first to generate results.', confirmButtonColor: '#198754' });
      return false;
    }
    if (isDbSamplingResult(last) && !(last.species?.length)) {
      Swal.fire({ icon: 'info', title: 'No species', text: 'The sampling returned 0 species. Adjust your scope or filters and try again.', confirmButtonColor: '#198754' });
      return false;
    }
    return true;
  }

  document.getElementById("exportSelJson")?.addEventListener("click", async () => {
    const last = getLastSampling();
    if (!requireSpecies(last)) return;

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

  document.getElementById("exportSelNames")?.addEventListener("click", async () => {
    const last = getLastSampling();
    if (!requireSpecies(last)) return;

    if (last && isDbSamplingResult(last)) {
      const species = last.species || [];
      const names = species.map(s => s.organism_name || "").filter(Boolean);
      const txt = names.join("\n") + "\n";
      await saveAs(txt, "species_names.txt", "text/plain");
      return;
    }

    // Tree-based: export picked keys as names
    const payload = getExportPayload({ allowManualFallback: true });
    if (!payload) return;
    const ing = payload?.ingroup?.picked || [];
    const out = payload?.outgroupPicked || [];
    const keys = [].concat(out.map(x => x?.key)).concat(ing.map(x => x?.key)).filter(Boolean);
    const txt = keys.join("\n") + (keys.length ? "\n" : "");
    await saveAs(txt, "species_names.txt", "text/plain");
  });

  document.getElementById("exportSelTxt")?.addEventListener("click", async () => {
    const last = getLastSampling();
    if (!requireSpecies(last)) return;

    if (last && isDbSamplingResult(last)) {
      // DB sampling: export species list as TXT
      const species = last.species || [];
      const lines = species.map((s, i) =>
        `${i + 1}\t${s.organism_name || ""}\t${s.taxid || ""}\t${s.accession || ""}\t${s.clade_group || ""}\t${s.species_score ?? ""}`
      );
      const header = "#\torganism_name\ttaxid\taccession\tclade\tspecies_score";
      const txt = header + "\n" + lines.join("\n") + "\n";
      await saveAs(txt, "sampling.txt", "text/plain");
      return;
    }

    const payload = getExportPayload({ allowManualFallback: true });
    if (!payload) return;
    await postDownload("/taxonomy/sampling/export/txt/", payload, "sampling.txt");
  });

  document.getElementById("exportSelNewick")?.addEventListener("click", async () => {
    const last = getLastSampling();
    if (!requireSpecies(last)) return;

    if (last && isDbSamplingResult(last)) {
      // DB sampling: request server-generated Newick from the new endpoint
      try {
        const url = window.NEWICK_ENDPOINT || "/api/v1/taxonomy/sampling/newick/";
        await postDownload(url, last, "taxonomic_hierarchy.newick");
      } catch (err) {
        console.error("[exports] Newick export error:", err);
        Swal.fire({ icon: 'error', title: 'Export failed', text: 'Newick export failed: ' + (err.message || err), confirmButtonColor: '#198754' });
      }
      return;
    }

    const payload = getExportPayload({ allowManualFallback: false });
    if (!payload) return;
    await postDownload("/taxonomy/sampling/export/newick/", payload, "taxonomic_hierarchy.newick");
  });

  document.getElementById("exportSelExcel")?.addEventListener("click", async () => {
    const last = getLastSampling();
    if (!requireSpecies(last)) return;
    if (!isDbSamplingResult(last)) {
      Swal.fire({ icon: 'info', title: 'Not available', text: 'Excel export is only available after DB sampling.', confirmButtonColor: '#198754' });
      return;
    }

    try {
      const XLSX = await loadXLSX();
      const species = last.species || [];

      // Build rows with fields organized for scientific publication supplementary tables
      // Order follows common conventions in genomics papers: ID → Taxonomy → Assembly → Quality
      const rows = species.map((s, i) => {
        // Convert bytes to Mb for readability (common in publications)
        const genomeSizeMb = s.total_sequence_length 
          ? (s.total_sequence_length / 1_000_000).toFixed(2) 
          : "";
        // Convert kb to Mb for N50 (more standard in publications)
        const scaffoldN50Mb = s.scaffold_n50_kb 
          ? (s.scaffold_n50_kb / 1000).toFixed(3) 
          : "";
        const contigN50Mb = s.contig_n50_kb 
          ? (s.contig_n50_kb / 1000).toFixed(3) 
          : "";
        
        return {
          // === Identification ===
          "#":                    i + 1,
          "Organism":             s.organism_name || "",
          "Assembly Accession":   s.accession || "",
          "NCBI TaxID":           s.taxid || "",
          // === Taxonomy (hierarchical) ===
          "Kingdom":              s.kingdom || "",
          "Phylum":               s.phylum || "",
          "Class":                s.class || "",
          "Order":                s.order || "",
          "Family":               s.family || "",
          "Genus":                s.genus || "",
          // === Assembly metrics ===
          "Assembly Level":       s.genome_level || "",
          "RefSeq Category":      s.refseq_category || "",
          "Genome Size (Mb)":     genomeSizeMb,
          "GC Content (%)":       s.gc_percent ? s.gc_percent.toFixed(1) : "",
          "Scaffold N50 (Mb)":    scaffoldN50Mb,
          "Contig N50 (Mb)":      contigN50Mb,
          "Coverage (X)":         s.genome_coverage ?? "",
          "Scaffolds":            s.scaffold_count ?? "",
          "Chromosomes":          s.chromosome_count ?? "",
          // === Annotation ===
          "Total Genes":          s.genes ?? "",
          "Protein-Coding":       s.protein_coding ?? "",
          "BUSCO Complete (%)":   s.busco_complete ?? "",
          // === Quality scores ===
          "Quality Score":        s.quality_score ? s.quality_score.toFixed(2) : "",
          "Assembly Score":       s.assembly_score ? s.assembly_score.toFixed(2) : "",
          // === Metadata ===
          "Release Date":         s.release_date || "",
          "Source Database":      s.source_database || "",
          "Sequencing Tech":      s.sequencing_tech || "",
          // === Sampling info ===
          "Clade Group":          s.clade_group || "",
          "COL Match":            s.col_name || "",
        };
      });

      // Create workbook with two sheets: Species + Clades
      const wb = XLSX.utils.book_new();

      // Sheet 1: Species
      const wsSpecies = XLSX.utils.json_to_sheet(rows);
      
      // Auto-width columns
      const colWidths = Object.keys(rows[0] || {}).map(k => ({
        wch: Math.max(k.length, ...rows.map(r => String(r[k] ?? "").length).slice(0, 50)) + 2
      }));
      wsSpecies["!cols"] = colWidths;
      
      // Apply yellow background and bold font to header row (row 0)
      const headerRange = XLSX.utils.decode_range(wsSpecies["!ref"]);
      for (let col = headerRange.s.c; col <= headerRange.e.c; col++) {
        const cellRef = XLSX.utils.encode_cell({ r: 0, c: col });
        if (wsSpecies[cellRef]) {
          wsSpecies[cellRef].s = {
            fill: { patternType: "solid", fgColor: { rgb: "FFFF00" } },
            font: { bold: true, sz: 11 },
            alignment: { horizontal: "center", vertical: "center" },
            border: {
              bottom: { style: "thin", color: { rgb: "000000" } }
            }
          };
        }
      }
      
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
        
        // Apply yellow background to header row
        const cladesRange = XLSX.utils.decode_range(wsClades["!ref"]);
        for (let col = cladesRange.s.c; col <= cladesRange.e.c; col++) {
          const cellRef = XLSX.utils.encode_cell({ r: 0, c: col });
          if (wsClades[cellRef]) {
            wsClades[cellRef].s = {
              fill: { patternType: "solid", fgColor: { rgb: "FFFF00" } },
              font: { bold: true, sz: 11 },
              alignment: { horizontal: "center", vertical: "center" },
              border: {
                bottom: { style: "thin", color: { rgb: "000000" } }
              }
            };
          }
        }
        
        XLSX.utils.book_append_sheet(wb, wsClades, "Clades");
      }

      // Download with Save-As dialog
      const wbOut = XLSX.write(wb, { bookType: "xlsx", type: "array" });
      const xlsxBlob = new Blob([wbOut], { type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" });
      await saveAs(xlsxBlob, "sampling_report.xlsx", xlsxBlob.type);
      
      console.log("[exports] Excel export complete with styled headers");
    } catch (err) {
      console.error("[exports] Excel export error:", err);
      Swal.fire({ icon: 'error', title: 'Export failed', text: 'Excel export failed: ' + (err.message || err), confirmButtonColor: '#198754' });
    }
  });

  document.getElementById("copySel")?.addEventListener("click", async () => {
    const last = getLastSampling();
    if (!requireSpecies(last)) return;

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

  // ── NCBI Downloads ──────────────────────────────────────────
  // Two options:
  //   1) Direct download via Django proxy — streams ZIP with progress bar
  //   2) Generate script (Bash / PowerShell) — user runs it later

  const NCBI_INCLUDE_MAP = {
    genome:  "GENOME_FASTA",
    protein: "PROT_FASTA",
    gbff:    "GENOME_GBFF",
  };

  function mapIncludeTypes(includeFlag) {
    return includeFlag.split(",").map(f => NCBI_INCLUDE_MAP[f.trim()]).filter(Boolean);
  }

  // ── Script generators (Bash & PowerShell) ──────────────────

  const FOLDER_MAP = { genome: "genome_download", protein: "protein_download", gbff: "GBFF_download" };
  function _folderName(flag) {
    return FOLDER_MAP[flag] || "NCBI_download";
  }

  function buildNcbiScript(species, includeFlag, label, outZip) {
    const now = new Date().toISOString().slice(0, 10);
    const accessions = species.map(s => s.accession).filter(Boolean);
    if (!accessions.length) return null;
    const apiTypes = mapIncludeTypes(includeFlag);
    const manifest = species.filter(s => s.accession)
      .map(s => `#   ${s.accession}  ${s.organism_name || ""}`).join("\n");
    const qsTypes = apiTypes.map(t => `include_annotation_type=${t}`).join("&");
    const folder = _folderName(includeFlag);
    return `#!/bin/bash
# NCBI ${label} Download Script — Generated by TaxonSampler on ${now}
# Species: ${accessions.length} | Data: ${includeFlag}
# Uses hydrated=FULLY_HYDRATED for faster server-side packaging

mkdir -p ${folder}

${manifest}
accessions=(
${accessions.map(a => `  "${a}"`).join("\n")}
)

total=\${#accessions[@]}
echo ""
echo "TaxonSampler — NCBI ${label} Download"
echo "================================================"
echo "  Species: $total"
echo "  Output:  ${folder}/"
echo "================================================"

MAX_PARALLEL=3
idx=0
for acc in "\${accessions[@]}"; do
  idx=$((idx+1))
  echo "  [$idx/$total] Downloading $acc ..."
  url="${apiTypes.length ? `https://api.ncbi.nlm.nih.gov/datasets/v2/genome/accession/$acc/download?${qsTypes}&hydrated=FULLY_HYDRATED` : `https://api.ncbi.nlm.nih.gov/datasets/v2/genome/accession/$acc/download?hydrated=FULLY_HYDRATED`}"
  curl -sL "$url" -o "${folder}/\${acc}.zip" &
  # Wait if we already have MAX_PARALLEL downloads running
  if [ $(jobs -r | wc -l) -ge $MAX_PARALLEL ]; then
    wait -n
  fi
done
wait  # wait for remaining downloads

echo ""
echo "Extracting downloaded ZIPs..."
for zipfile in ${folder}/*.zip; do
  acc=$(basename "$zipfile" .zip)
  if unzip -o -q "$zipfile" -d "${folder}/$acc" 2>/dev/null; then
    echo "  ✔ Extracted $acc"
    rm -f "$zipfile"
  else
    echo "  ✖ Failed to extract $acc"
  fi
done

echo ""
echo "================================================"
echo "  Done. Files extracted in ${folder}/"
echo "================================================"
`;
  }

  function buildNcbiPsScript(species, includeFlag, label, outZip) {
    const now = new Date().toISOString().slice(0, 10);
    const accessions = species.map(s => s.accession).filter(Boolean);
    if (!accessions.length) return null;
    const apiTypes = mapIncludeTypes(includeFlag);
    const manifest = species.filter(s => s.accession)
      .map(s => `#   ${s.accession}  ${s.organism_name || ""}`).join("\n");
    const qsTypes = apiTypes.map(t => `include_annotation_type=${t}`).join("&");
    const folder = _folderName(includeFlag);
    return `# NCBI ${label} Download Script (PowerShell) — Generated by TaxonSampler on ${now}
# Species: ${accessions.length} | Data: ${includeFlag}
# Uses hydrated=FULLY_HYDRATED for faster server-side packaging

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$OutDir = "${folder}"
New-Item -ItemType Directory -Path $OutDir -Force | Out-Null

${manifest}
$Accessions = @(
${accessions.map(a => `  "${a}"`).join("\n")}
)

$Total = $Accessions.Count
Write-Host ""
Write-Host "TaxonSampler - NCBI ${label} Download"
Write-Host "================================================"
Write-Host "  Species: $Total"
Write-Host "  Output:  $OutDir/"
Write-Host "================================================"

$Idx = 0
foreach ($Acc in $Accessions) {
  $Idx++
  Write-Host "  [$Idx/$Total] Downloading $Acc ..."
  $url = "${apiTypes.length ? `https://api.ncbi.nlm.nih.gov/datasets/v2/genome/accession/$Acc/download?${qsTypes}&hydrated=FULLY_HYDRATED` : `https://api.ncbi.nlm.nih.gov/datasets/v2/genome/accession/$Acc/download?hydrated=FULLY_HYDRATED`}"
  $dest = Join-Path $OutDir "$Acc.zip"
  Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
}

Write-Host ""
Write-Host "Extracting downloaded ZIPs..."
foreach ($ZipFile in (Get-ChildItem -Path $OutDir -Filter *.zip)) {
  $AccName = $ZipFile.BaseName
  $ExtractDir = Join-Path $OutDir $AccName
  try {
    Expand-Archive -Path $ZipFile.FullName -DestinationPath $ExtractDir -Force
    Write-Host "  OK Extracted $AccName"
    Remove-Item $ZipFile.FullName -Force
  } catch {
    Write-Host "  FAIL Failed to extract $AccName"
  }
}

Write-Host ""
Write-Host "================================================"
Write-Host "  Done. Files extracted in $OutDir/"
Write-Host "================================================"
`;
  }

  // ── Direct download (browser → NCBI API, no proxy) ─────────
  // Downloads in batches with retry + checkpoint/resume.
  // Calls NCBI directly for speed; falls back to Django proxy if CORS fails.

  const DL_BATCH_SIZE   = 1;     // 1 accession per request (GET) — much more reliable
  const DL_CONCURRENCY  = 5;
  const DL_MAX_RETRIES  = 5;
  const DL_CKPT_KEY     = "ncbi_dl_checkpoint";
  const NCBI_DL_BASE    = "https://api.ncbi.nlm.nih.gov/datasets/v2/genome/accession";

  // Flag: did direct NCBI calls work? (avoids retrying proxy fallback per batch)
  let _ncbiDirectWorks = null;  // null = untested, true/false = tested

  // ── Checkpoint helpers (localStorage) ────────────────────────

  function _getCkpts() {
    try { return JSON.parse(localStorage.getItem(DL_CKPT_KEY) || "{}"); } catch { return {}; }
  }
  function _saveCkpt(id, data) {
    const all = _getCkpts();
    all[id] = { ...data, ts: Date.now() };
    localStorage.setItem(DL_CKPT_KEY, JSON.stringify(all));
  }
  function _clearCkpt(id) {
    const all = _getCkpts(); delete all[id];
    localStorage.setItem(DL_CKPT_KEY, JSON.stringify(all));
  }
  function _makeCkptId(accessions, includeTypes) {
    const src = accessions.join(",") + "|" + includeTypes.join(",");
    let h = 0;
    for (let i = 0; i < src.length; i++) { h = ((h << 5) - h) + src.charCodeAt(i); h |= 0; }
    return `dl_${Math.abs(h).toString(36)}_${accessions.length}`;
  }
  // Purge checkpoints older than 7 days
  (function _purgeCkpts() {
    const all = _getCkpts(), cutoff = Date.now() - 7 * 86_400_000;
    for (const id of Object.keys(all)) { if ((all[id].ts || 0) < cutoff) delete all[id]; }
    localStorage.setItem(DL_CKPT_KEY, JSON.stringify(all));
  })();

  // ── fetchBatch: direct NCBI with proxy fallback + retry ───

  async function _streamResponse(resp, onProgress) {
    const total  = parseInt(resp.headers.get("Content-Length") || "0", 10);
    const reader = resp.body.getReader();
    const chunks = [];
    let received = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
      received += value.length;
      if (onProgress) onProgress(received, total);
    }
    return new Blob(chunks, { type: "application/zip" });
  }

  async function _fetchDirect(accessions, includeTypes) {
    // GET per-accession endpoint — much more reliable than bulk POST
    const acc = accessions[0];  // DL_BATCH_SIZE=1, so always 1 accession
    const qs = includeTypes.map(t => `include_annotation_type=${encodeURIComponent(t)}`).join("&")
              + "&hydrated=FULLY_HYDRATED";
    const url = `${NCBI_DL_BASE}/${encodeURIComponent(acc)}/download?${qs}`;
    const resp = await fetch(url, {
      method: "GET",
      headers: { "Accept": "application/zip" },
    });
    if (!resp.ok) throw new Error(`NCBI HTTP ${resp.status}`);
    return resp;
  }

  async function _fetchViaProxy(accessions, includeTypes, filename) {
    const csrf = getCookie("csrftoken");
    const resp = await fetch("/api/v1/taxonomy/ncbi/download/", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf || "" },
      body: JSON.stringify({ accessions, include_types: includeTypes, filename }),
    });
    if (!resp.ok) {
      let msg = `HTTP ${resp.status}`;
      try { const j = await resp.json(); msg = j.error || msg; } catch { /* ignore */ }
      throw new Error(msg);
    }
    return resp;
  }

  async function fetchBatch(accessions, includeTypes, filename, onProgress) {
    let lastErr;

    for (let attempt = 1; attempt <= DL_MAX_RETRIES; attempt++) {
      try {
        let resp;

        // Try direct NCBI first (much faster — no proxy double-transfer)
        if (_ncbiDirectWorks !== false) {
          try {
            resp = await _fetchDirect(accessions, includeTypes);
            _ncbiDirectWorks = true;
          } catch (directErr) {
            console.warn("[ncbi-dl] direct NCBI failed, using proxy:", directErr.message);
            _ncbiDirectWorks = false;
            resp = await _fetchViaProxy(accessions, includeTypes, filename);
          }
        } else {
          resp = await _fetchViaProxy(accessions, includeTypes, filename);
        }

        return await _streamResponse(resp, onProgress);
      } catch (err) {
        lastErr = err;
        console.warn(`[ncbi-dl] batch attempt ${attempt}/${DL_MAX_RETRIES} failed:`, err.message);
        if (attempt < DL_MAX_RETRIES) {
          if (onProgress) onProgress(-1, 0);          // signal "retrying"
          await new Promise(r => setTimeout(r, 2000 * Math.pow(2, attempt - 1)));
        }
      }
    }
    throw lastErr;
  }

  // ── Direct download with checkpoint / resume ────────────────
  // Downloads up to DL_CONCURRENCY batches in parallel for speed.

  let _dlCancelled = false;   // cancel flag for in-progress download

  // ── Floating progress badge (visible when modal is closed) ──
  let _dlFloatingEl = null;
  let _dlState = { completedAcc: 0, totalAcc: 0, label: "", logHtml: "", running: false };

  function _createFloatingBadge() {
    if (_dlFloatingEl) return;
    const el = document.createElement("div");
    el.id = "ncbiDlFloat";
    el.style.cssText = "position:fixed;bottom:20px;right:20px;z-index:99999;"
      + "background:#198754;color:#fff;padding:10px 16px;border-radius:8px;"
      + "cursor:pointer;font-size:13px;box-shadow:0 2px 12px rgba(0,0,0,.3);"
      + "display:flex;align-items:center;gap:8px;transition:opacity .3s;";
    el.innerHTML = `<span class="spinner-border spinner-border-sm"></span>`
      + `<span id="ncbiDlFloatText">Downloading…</span>`;
    el.title = "Click to see download progress";
    el.addEventListener("click", _reopenDlModal);
    document.body.appendChild(el);
    _dlFloatingEl = el;
  }

  function _updateFloatingBadge() {
    if (!_dlFloatingEl) return;
    const txt = _dlFloatingEl.querySelector("#ncbiDlFloatText");
    if (txt) {
      const pct = _dlState.totalAcc
        ? Math.round(_dlState.completedAcc / _dlState.totalAcc * 100) : 0;
      txt.textContent = `${_dlState.label}: ${_dlState.completedAcc}/${_dlState.totalAcc} (${pct}%)`;
    }
  }

  function _removeFloatingBadge() {
    if (_dlFloatingEl) { _dlFloatingEl.remove(); _dlFloatingEl = null; }
  }

  function _reopenDlModal() {
    const s = _dlState;
    const pct = s.totalAcc ? Math.min(s.completedAcc === s.totalAcc ? 100 : 99,
      Math.round(s.completedAcc / s.totalAcc * 100)) : 0;
    Swal.fire({
      title: `Downloading ${s.label}`,
      html: `
        <div class="text-start small mb-2" id="dlStatus">${s.completedAcc} / ${s.totalAcc} accessions</div>
        <div class="progress" style="height: 22px;">
          <div id="dlBar" class="progress-bar bg-success progress-bar-striped progress-bar-animated"
               role="progressbar" style="width: ${pct}%;">${pct} %</div>
        </div>
        <div class="text-muted small mt-2" id="dlDetail">Downloading…</div>
        <div class="text-muted small mt-1" id="dlLog" style="max-height:120px;overflow-y:auto;font-family:monospace;font-size:11px;">${s.logHtml}</div>`,
      allowOutsideClick: true,
      showConfirmButton: true,
      confirmButtonText: "Continue in background",
      confirmButtonColor: "#198754",
      showCancelButton: true,
      cancelButtonText: "Cancel download",
      cancelButtonColor: "#dc3545",
    }).then(result => {
      if (result.dismiss === Swal.DismissReason.cancel) {
        _dlCancelled = true;
        _removeFloatingBadge();
      }
    });
    // scroll log to bottom
    const logEl = document.getElementById("dlLog");
    if (logEl) logEl.scrollTop = logEl.scrollHeight;
  }

  async function doDirectDownload(accessions, includeTypes, label, outZipBase, totalAcc) {
    const batches = [];
    for (let i = 0; i < totalAcc; i += DL_BATCH_SIZE) batches.push(accessions.slice(i, i + DL_BATCH_SIZE));

    const jobId = _makeCkptId(accessions, includeTypes);
    const ckpt  = _getCkpts()[jobId];

    // doneBatches: Set of batch indices already downloaded (for resume)
    let doneBatches = new Set();
    let completedAcc = 0;

    // ── Resume from checkpoint? ───────────────────────────────
    if (ckpt && ckpt.done && ckpt.done.length > 0 && ckpt.done.length < batches.length) {
      const { isConfirmed } = await Swal.fire({
        icon: "question",
        title: "Resume previous download?",
        html: `<div class="text-start small">
          <p>A previous download of <strong>${label}</strong> was interrupted.</p>
          <p><strong>${ckpt.doneAcc}</strong> of <strong>${totalAcc}</strong> accessions
          were already saved to disk.</p>
          <p>Resume from accession <strong>${ckpt.done.length + 1}</strong>?</p>
        </div>`,
        showCancelButton: true,
        confirmButtonText: "Resume",
        cancelButtonText: "Start over",
        confirmButtonColor: "#198754",
      });
      if (isConfirmed) {
        doneBatches  = new Set(ckpt.done);
        completedAcc = ckpt.doneAcc;
      } else {
        _clearCkpt(jobId);
      }
    }

    // ── Init checkpoint ───────────────────────────────────────
    if (doneBatches.size === 0) {
      _saveCkpt(jobId, { label, outZipBase, totalAcc, totalBatches: batches.length, done: [], doneAcc: 0 });
    }

    _dlCancelled = false;
    _dlState = { completedAcc, totalAcc, label, logHtml: "", running: true };
    _createFloatingBadge();
    _updateFloatingBadge();

    Swal.fire({
      title: `Downloading ${label}`,
      html: `
        <div class="text-start small mb-2" id="dlStatus">Connecting to NCBI…</div>
        <div class="progress" style="height: 22px;">
          <div id="dlBar" class="progress-bar bg-success progress-bar-striped progress-bar-animated"
               role="progressbar" style="width: 0%;">0 %</div>
        </div>
        <div class="text-muted small mt-2" id="dlDetail">Preparing download…</div>
        <div class="text-muted small mt-1" id="dlLog" style="max-height:120px;overflow-y:auto;font-family:monospace;font-size:11px;"></div>`,
      allowOutsideClick: true,
      showConfirmButton: true,
      confirmButtonText: "Continue in background",
      confirmButtonColor: "#198754",
      showCancelButton: true,
      cancelButtonText: "Cancel download",
      cancelButtonColor: "#dc3545",
    }).then(result => {
      if (result.dismiss === Swal.DismissReason.cancel) {
        _dlCancelled = true;
        _removeFloatingBadge();
      }
    });

    const logLine = (msg) => {
      _dlState.logHtml += `${msg}<br>`;
      const el = document.getElementById("dlLog");
      if (el) { el.innerHTML += `${msg}<br>`; el.scrollTop = el.scrollHeight; }
    };

    // Show download mode
    logLine(_ncbiDirectWorks === false
      ? "⚡ Proxy mode (NCBI direct blocked by CORS)"
      : "⚡ Direct NCBI mode — maximum speed");

    let savedCount = 0;
    // Track bytes received per concurrent slot for combined progress
    const slotBytes = new Array(DL_CONCURRENCY).fill(0);

    function updateGlobalProgress() {
      _dlState.completedAcc = completedAcc;
      _updateFloatingBadge();
      const barEl = document.getElementById("dlBar");
      if (!barEl) return;
      const pctDone = Math.min(completedAcc === totalAcc ? 100 : 99,
                               Math.round(completedAcc / totalAcc * 100));
      barEl.style.width = `${pctDone}%`;
      barEl.textContent = `${pctDone} %`;
    }

    // ── Process remaining batches in parallel waves ───────────
    const remaining = [];
    for (let b = 0; b < batches.length; b++) {
      if (!doneBatches.has(b)) remaining.push(b);
    }

    let failedBatchIdx = -1;
    let failedErr = null;

    for (let w = 0; w < remaining.length; w += DL_CONCURRENCY) {
      if (_dlCancelled || failedBatchIdx >= 0) break;

      const wave = remaining.slice(w, w + DL_CONCURRENCY);
      const statusEl = document.getElementById("dlStatus");
      const detailEl = document.getElementById("dlDetail");

      if (statusEl) {
        const waveNum = Math.floor(w / DL_CONCURRENCY) + 1;
        const totalWaves = Math.ceil(remaining.length / DL_CONCURRENCY);
        statusEl.innerHTML = `Wave <strong>${waveNum}</strong> / <strong>${totalWaves}</strong>`
          + ` — ${wave.length} accession${wave.length > 1 ? "s" : ""} in parallel…`;
      }

      // Reset slot bytes for this wave
      slotBytes.fill(0);

      const wavePromises = wave.map((batchIdx, slot) => {
        const batch = batches[batchIdx];
        const acc = batch[0];  // DL_BATCH_SIZE=1 → 1 accession per batch
        const batchFile = `${outZipBase}_${acc}.zip`;

        logLine(`▶ ${acc} [${batchIdx + 1}/${batches.length}]`);

        return fetchBatch(batch, includeTypes, batchFile, (received, _total) => {
          if (received === -1) {
            logLine(`&nbsp;&nbsp;⟳ ${acc} retrying…`);
            return;
          }
          slotBytes[slot] = received;
          const totalReceived = slotBytes.reduce((a, b) => a + b, 0);
          const mb = (totalReceived / 1_048_576).toFixed(1);
          if (detailEl) detailEl.textContent =
            `Downloading… ${mb} MB received (${wave.length} streams)`;
        }).then(async (blob) => {
          await saveAs(blob, batchFile, "application/zip");
          savedCount++;
          completedAcc += batch.length;
          doneBatches.add(batchIdx);

          logLine(`&nbsp;&nbsp;✔ ${acc} (${(blob.size / 1_048_576).toFixed(1)} MB)`);

          // Update checkpoint
          const ckptNow = _getCkpts()[jobId] || { done: [] };
          ckptNow.done = [...doneBatches];
          ckptNow.doneAcc = completedAcc;
          _saveCkpt(jobId, ckptNow);
          updateGlobalProgress();
        }).catch((err) => {
          const acc = batch[0];
          logLine(`&nbsp;&nbsp;✖ ${acc} failed: ${err.message}`);
          if (failedBatchIdx < 0) { failedBatchIdx = batchIdx; failedErr = err; }
        });
      });

      await Promise.all(wavePromises);
    }

    // ── Handle cancel ─────────────────────────────────────────
    _dlState.running = false;
    _removeFloatingBadge();
    if (_dlCancelled) {
      Swal.fire({
        icon: "info", title: "Download paused",
        html: `<p>${completedAcc} of ${totalAcc} accessions saved.</p>
               <p class="small text-muted">You can resume this download later — progress is saved.</p>`,
        confirmButtonColor: "#198754",
      });
      return;
    }

    // ── Handle failure ────────────────────────────────────────
    if (failedBatchIdx >= 0) {
      Swal.fire({
        icon: "warning",
        title: "Download interrupted",
        html: `<div class="text-start small">
          <p>Accession <strong>${batches[failedBatchIdx]?.[0] || failedBatchIdx + 1}</strong> failed after
          ${DL_MAX_RETRIES} retries.</p>
          <p><strong>${completedAcc}</strong> of <strong>${totalAcc}</strong> accessions were
          already saved (${savedCount} ZIP file${savedCount !== 1 ? "s" : ""}).</p>
          <p class="text-muted">Progress is saved — click the same download button to resume.</p>
          <p class="text-danger small mt-2"><strong>Error:</strong> ${failedErr?.message || "Unknown error"}</p>
        </div>`,
        confirmButtonText: "OK",
        confirmButtonColor: "#198754",
      });
      return;
    }

    // ── All batches complete ──────────────────────────────────
    _clearCkpt(jobId);
    Swal.fire({
      icon: "success", title: "Download complete",
      html: `<p>${completedAcc} assemblies downloaded (${savedCount} ZIP file${savedCount !== 1 ? "s" : ""}).</p>`,
      confirmButtonColor: "#198754",
    });
  }

  // ── Unified handler: choose direct download or script ──────

  function ncbiHandler(includeFlag, label, outZipBase) {
    return async () => {
      const last = getLastSampling();
      if (!requireSpecies(last)) return;
      if (!isDbSamplingResult(last)) {
        Swal.fire({ icon: "info", title: "Not available", text: "NCBI downloads require DB sampling results.", confirmButtonColor: "#198754" });
        return;
      }
      const species = last.species || [];
      const accessions = species.map(s => s.accession).filter(Boolean);
      if (!accessions.length) {
        Swal.fire({ icon: "warning", title: "No accessions", text: "None of the sampled species have assembly accessions.", confirmButtonColor: "#198754" });
        return;
      }

      const { value: mode } = await Swal.fire({
        title: `${label}`,
        html: `<div class="text-start small">
          <p><strong>${accessions.length}</strong> assemblies available.</p>
          <p class="mb-1">Choose an option:</p>
        </div>`,
        input: "radio",
        inputOptions: {
          direct: "\u{1F4E5} Download now — ZIP streamed directly to your browser",
          bash:   "\u{1F4C4} Generate Bash script (.sh) — to run later on Linux/macOS/WSL",
          ps1:    "\u{1F4C4} Generate PowerShell script (.ps1) — to run later on Windows",
        },
        inputValue: "direct",
        showCancelButton: true,
        confirmButtonText: "Continue",
        confirmButtonColor: "#198754",
        inputValidator: (v) => !v ? "Select an option" : undefined,
      });
      if (!mode) return;

      if (mode === "direct") {
        try {
          await doDirectDownload(accessions, mapIncludeTypes(includeFlag), label, outZipBase, accessions.length);
        } catch (err) {
          console.error("[ncbi-download]", err);
          Swal.fire({ icon: "error", title: "Download failed", text: err.message, confirmButtonColor: "#198754" });
        }
      } else if (mode === "bash") {
        const script = buildNcbiScript(species, includeFlag, label, `${outZipBase}.zip`);
        if (!script) return;
        const { isConfirmed } = await Swal.fire({
          icon: "info",
          title: "Script ready",
          html: `<div class="text-start">
            <div class="alert alert-warning py-2 mb-3">
              <i class="fa-solid fa-triangle-exclamation me-1"></i>
              <strong>This does NOT download your data yet.</strong>
            </div>
            <p class="small">A <code>.sh</code> script file will be saved to your computer.
            To start the actual download you need to:</p>
            <ol class="small">
              <li>Open a <strong>Bash</strong> terminal (Linux, macOS, or WSL)</li>
              <li>Navigate to the folder where the file was saved</li>
              <li>Run: <code>bash ${outZipBase}.sh</code></li>
            </ol>
          </div>`,
          confirmButtonText: "Save script file",
          confirmButtonColor: "#198754",
          showCancelButton: true,
          cancelButtonText: "Cancel",
        });
        if (isConfirmed) await saveAs(script, `${outZipBase}.sh`, "application/octet-stream");
      } else {
        const script = buildNcbiPsScript(species, includeFlag, label, `${outZipBase}.zip`);
        if (!script) return;
        const { isConfirmed } = await Swal.fire({
          icon: "info",
          title: "Script ready",
          html: `<div class="text-start">
            <div class="alert alert-warning py-2 mb-3">
              <i class="fa-solid fa-triangle-exclamation me-1"></i>
              <strong>This does NOT download your data yet.</strong>
            </div>
            <p class="small">A <code>.ps1</code> script file will be saved to your computer.
            To start the actual download you need to:</p>
            <ol class="small">
              <li>Open <strong>PowerShell</strong> on Windows</li>
              <li>Navigate to the folder where the file was saved</li>
              <li>Run: <code>.\\${outZipBase}.ps1</code></li>
            </ol>
          </div>`,
          confirmButtonText: "Save script file",
          confirmButtonColor: "#198754",
          showCancelButton: true,
          cancelButtonText: "Cancel",
        });
        if (isConfirmed) await saveAs(script, `${outZipBase}.ps1`, "application/octet-stream");
      }
    };
  }

  document.getElementById("dlNcbiGenome")?.addEventListener("click",
    ncbiHandler("genome", "Genomes (FASTA)", "download_genomes"));
  document.getElementById("dlNcbiProtein")?.addEventListener("click",
    ncbiHandler("protein", "Proteomes (FAA)", "download_proteomes"));
  document.getElementById("dlNcbiGbff")?.addEventListener("click",
    ncbiHandler("gbff", "GenBank (GBFF)", "download_gbff"));
  document.getElementById("dlNcbiAll")?.addEventListener("click",
    ncbiHandler("genome,protein,gbff", "All Data", "download_all_ncbi"));

  // ══════════════════════════════════════════════════════════════════
  // Import JSON configuration
  // ══════════════════════════════════════════════════════════════════
  
  const importBtn = document.getElementById("importSelJson");
  const importFileInput = document.getElementById("importSelJsonFile");
  
  if (importBtn && importFileInput) {
    // Click button → trigger hidden file input
    importBtn.addEventListener("click", () => {
      importFileInput.value = ""; // Reset to allow re-selecting same file
      importFileInput.click();
    });
    
    // File selected → read and import
    importFileInput.addEventListener("change", async (e) => {
      const file = e.target.files?.[0];
      if (!file) return;
      
      try {
        const text = await file.text();
        const data = JSON.parse(text);
        
        // Validate structure
        if (!data || !Array.isArray(data.species)) {
          Swal.fire({
            icon: 'error',
            title: 'Invalid format',
            text: 'The file does not contain a valid sampling configuration. Expected a JSON with "species" array.',
            confirmButtonColor: '#198754'
          });
          return;
        }
        
        // Dispatch event to restore the sampling state
        window.dispatchEvent(new CustomEvent("sampling:import", { detail: data }));
        
        // Build scope info for display
        let scopeHtml = '';
        if (data.scope_filters && Object.keys(data.scope_filters).length > 0) {
          const scopeParts = Object.entries(data.scope_filters)
            .map(([rank, name]) => `${rank}: <strong>${name}</strong>`)
            .join(' → ');
          scopeHtml = `<p class="small text-success mb-1"><i class="fa-solid fa-filter me-1"></i>Scope: ${scopeParts}</p>`;
        }
        
        let targetsHtml = '';
        if (data.target_keys && data.target_keys.length > 0) {
          targetsHtml = `<p class="small text-info mb-1"><i class="fa-solid fa-bullseye me-1"></i>Targets: <strong>${data.target_keys.length}</strong> clades</p>`;
        }
        
        Swal.fire({
          icon: 'success',
          title: 'Configuration loaded',
          html: `<div class="text-start">
            <p>Imported <strong>${data.species?.length || 0}</strong> species.</p>
            ${scopeHtml}
            ${targetsHtml}
            ${data.strategy ? `<p class="small text-muted mb-1">Strategy: <strong>${data.strategy}</strong></p>` : ''}
            ${data.start_rank && data.end_rank ? `<p class="small text-muted mb-1">Rank range: <strong>${data.start_rank} → ${data.end_rank}</strong></p>` : ''}
            ${data.total_available ? `<p class="small text-muted mb-1">Available in scope: <strong>${data.total_available}</strong></p>` : ''}
            <hr class="my-2">
            <p class="small text-info mb-0"><i class="fa-solid fa-info-circle me-1"></i>Check the <strong>Filters panel (Step 2)</strong> on the right to see the restored configuration.</p>
          </div>`,
          confirmButtonColor: '#198754',
        });
        
      } catch (err) {
        console.error("[exports] Import error:", err);
        Swal.fire({
          icon: 'error',
          title: 'Import failed',
          text: 'Could not parse the JSON file. Make sure it is a valid sampling export.',
          confirmButtonColor: '#198754'
        });
      }
    });
  }
}
