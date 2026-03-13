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

  function buildNcbiScript(species, includeFlag, label, outZip) {
    const now = new Date().toISOString().slice(0, 10);
    const accessions = species.map(s => s.accession).filter(Boolean);
    if (!accessions.length) return null;
    const apiTypes = mapIncludeTypes(includeFlag);
    const manifest = species.filter(s => s.accession)
      .map(s => `#   ${s.accession}  ${s.organism_name || ""}`).join("\n");
    const typesJson = apiTypes.map(t => `"${t}"`).join(",");
    const BS = 200;
    return `#!/usr/bin/env bash
# NCBI ${label} Download Script — Generated by TaxonSampler on ${now}
# Species: ${accessions.length} | Data: ${includeFlag}
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
OUTPUT_ZIP="${outZip}"
API_URL="https://api.ncbi.nlm.nih.gov/datasets/v2/genome/download"
BATCH_SIZE=${BS}
${manifest}
ACCESSIONS=(
${accessions.map(a => `  "${a}"`).join("\n")}
)
echo "TaxonSampler — NCBI ${label} Download (\${#ACCESSIONS[@]} species)"
echo "================================================"
if ! command -v curl &>/dev/null; then echo "ERROR: curl not found"; exit 1; fi
HEADERS=(-H "Content-Type: application/json" -H "Accept: application/zip")
[ -n "\${NCBI_API_KEY:-}" ] && HEADERS+=(-H "api-key: \$NCBI_API_KEY") && echo "Using API key"
TOTAL=\${#ACCESSIONS[@]}; PART=0
for (( i=0; i<TOTAL; i+=BATCH_SIZE )); do
  BATCH=("\${ACCESSIONS[@]:i:BATCH_SIZE}"); PART=$((PART+1))
  JSON_ACC=""
  for acc in "\${BATCH[@]}"; do [ -n "$JSON_ACC" ] && JSON_ACC="$JSON_ACC,"; JSON_ACC="$JSON_ACC\\"$acc\\""; done
  PAYLOAD='{"accessions":['$JSON_ACC'],"include_annotation_type":[${typesJson}]}'
  [ "$TOTAL" -le "$BATCH_SIZE" ] && DEST="$OUTPUT_ZIP" || DEST="\${OUTPUT_ZIP%.zip}_part\${PART}.zip"
  echo ""
  echo ">> Batch $PART (\${#BATCH[@]} of $TOTAL accessions)"
  echo "   Downloading from NCBI (this may take several minutes)..."
  # Run curl in background — monitor real file size instead of curl's broken progress bar
  curl -s -X POST "$API_URL" "\${HEADERS[@]}" -d "$PAYLOAD" -o "$DEST" --fail &
  CURL_PID=$!
  SECONDS_ELAPSED=0
  while kill -0 "$CURL_PID" 2>/dev/null; do
    sleep 2
    SECONDS_ELAPSED=$((SECONDS_ELAPSED + 2))
    if [ -f "$DEST" ]; then
      BYTES=$(wc -c < "$DEST" 2>/dev/null || echo 0)
      MB=$(awk 'BEGIN{printf "%.1f", '"$BYTES"'/1048576}')
      printf "\\r   Downloaded: %s MB (%ds elapsed)" "$MB" "$SECONDS_ELAPSED"
    else
      printf "\\r   Waiting for NCBI response... (%ds)" "$SECONDS_ELAPSED"
    fi
  done
  wait "$CURL_PID" || { echo ""; echo "ERROR: download of batch $PART failed!"; exit 1; }
  BYTES=$(wc -c < "$DEST" 2>/dev/null || echo 0)
  MB=$(awk 'BEGIN{printf "%.1f", '"$BYTES"'/1048576}')
  echo ""
  echo "   Download complete: $MB MB"
  echo "   Extracting $DEST ..."
  unzip -o "$DEST"; rm -f "$DEST"
  echo "   Extraction complete."
done
echo ""
echo "================================================"
echo "Done! \${#ACCESSIONS[@]} assemblies saved to: $SCRIPT_DIR/"
`;
  }

  function buildNcbiPsScript(species, includeFlag, label, outZip) {
    const now = new Date().toISOString().slice(0, 10);
    const accessions = species.map(s => s.accession).filter(Boolean);
    if (!accessions.length) return null;
    const apiTypes = mapIncludeTypes(includeFlag);
    const manifest = species.filter(s => s.accession)
      .map(s => `#   ${s.accession}  ${s.organism_name || ""}`).join("\n");
    const BS = 200;
    return `# NCBI ${label} Download Script (PowerShell) — Generated by TaxonSampler on ${now}
# Species: ${accessions.length} | Data: ${includeFlag}
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path; Set-Location $ScriptDir
$OutputZip = "${outZip}"; $ApiUrl = "https://api.ncbi.nlm.nih.gov/datasets/v2/genome/download"; $BatchSize = ${BS}
${manifest}
$Accessions = @(
${accessions.map(a => `  "${a}"`).join("\n")}
)
Write-Host "TaxonSampler - NCBI ${label} Download ($($Accessions.Count) species)"
Write-Host "================================================"
$Headers = @{ "Accept" = "application/zip" }
if ($env:NCBI_API_KEY) { $Headers["api-key"] = $env:NCBI_API_KEY; Write-Host "Using API key" }
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
$Total = $Accessions.Count; $Part = 0
for ($i = 0; $i -lt $Total; $i += $BatchSize) {
  $Batch = $Accessions[$i .. [Math]::Min($i + $BatchSize - 1, $Total - 1)]; $Part++
  $Body = @{ accessions = $Batch; include_annotation_type = @(${apiTypes.map(t => `"${t}"`).join(", ")}) } | ConvertTo-Json -Depth 3 -Compress
  if ($Total -le $BatchSize) { $Dest = $OutputZip } else { $Dest = $OutputZip -replace '\\.zip$', "_part$Part.zip" }
  Write-Host ""
  Write-Host ">> Batch $Part ($($Batch.Count) of $Total accessions)"
  Write-Host "   Downloading from NCBI (this may take several minutes)..."
  # Stream download with real-time MB progress (no misleading progress bar)
  $ProgressPreference = 'SilentlyContinue'
  $bodyBytes = [System.Text.Encoding]::UTF8.GetBytes($Body)
  $req = [System.Net.HttpWebRequest]::Create($ApiUrl)
  $req.Method = 'POST'; $req.ContentType = 'application/json'; $req.Accept = 'application/zip'
  $req.Timeout = 600000; $req.ReadWriteTimeout = 600000
  foreach ($k in $Headers.Keys) { if ($k -ne 'Accept') { $req.Headers.Add($k, $Headers[$k]) } }
  $reqStream = $req.GetRequestStream()
  $reqStream.Write($bodyBytes, 0, $bodyBytes.Length); $reqStream.Close()
  $resp = $req.GetResponse()
  $respStream = $resp.GetResponseStream()
  $fs = [System.IO.File]::Create($Dest)
  $buf = New-Object byte[] 65536; $totalRead = 0; $sw = [System.Diagnostics.Stopwatch]::StartNew()
  do {
    $read = $respStream.Read($buf, 0, $buf.Length)
    if ($read -gt 0) { $fs.Write($buf, 0, $read); $totalRead += $read }
    if ($sw.ElapsedMilliseconds -ge 2000) {
      $mb = [math]::Round($totalRead / 1MB, 1)
      Write-Host "${'`'}r   Downloaded: $mb MB" -NoNewline
      $sw.Restart()
    }
  } while ($read -gt 0)
  $fs.Close(); $respStream.Close(); $resp.Close()
  $mb = [math]::Round($totalRead / 1MB, 1)
  Write-Host "${'`'}r   Download complete: $mb MB      "
  Write-Host "   Extracting $Dest ..."
  Expand-Archive -Path $Dest -DestinationPath . -Force; Remove-Item $Dest -Force -ErrorAction SilentlyContinue
  Write-Host "   Extraction complete."
}
Write-Host ""
Write-Host "================================================"
Write-Host "Done! $($Accessions.Count) assemblies saved to: $ScriptDir/"
`;
  }

  // ── Direct download (streaming through Django proxy) ───────

  const DL_BATCH_SIZE = 20;

  async function fetchBatch(accessions, includeTypes, filename, onProgress) {
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
    const total = parseInt(resp.headers.get("Content-Length") || "0", 10);
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

  async function doDirectDownload(accessions, includeTypes, label, outZipBase, totalAcc) {
    const batches = [];
    for (let i = 0; i < totalAcc; i += DL_BATCH_SIZE) batches.push(accessions.slice(i, i + DL_BATCH_SIZE));

    Swal.fire({
      title: `Downloading ${label}`,
      html: `
        <div class="text-start small mb-2" id="dlStatus">Connecting to NCBI…</div>
        <div class="progress" style="height: 22px;">
          <div id="dlBar" class="progress-bar bg-success progress-bar-striped progress-bar-animated"
               role="progressbar" style="width: 0%;">0 %</div>
        </div>
        <div class="text-muted small mt-2" id="dlDetail">Preparing download…</div>`,
      allowOutsideClick: false, showConfirmButton: false, showCancelButton: false,
    });

    let completedAcc = 0;
    const savedFiles = [];

    for (let b = 0; b < batches.length; b++) {
      const batch = batches[b];
      const from = completedAcc + 1, to = completedAcc + batch.length;
      const statusEl = document.getElementById("dlStatus");
      const barEl = document.getElementById("dlBar");
      const detailEl = document.getElementById("dlDetail");

      if (statusEl) statusEl.innerHTML = batches.length > 1
        ? `Batch <strong>${b + 1}</strong> of <strong>${batches.length}</strong> — downloading from NCBI…`
        : `Downloading <strong>${totalAcc}</strong> assemblies from NCBI…`;
      if (detailEl) detailEl.textContent = `Accessions ${from}–${to} of ${totalAcc}`;

      const batchFile = batches.length > 1 ? `${outZipBase}_part${b + 1}.zip` : `${outZipBase}.zip`;

      // basePct: percentage already covered by completed batches
      // batchShare: percentage this batch represents
      const basePct = completedAcc / totalAcc * 100;
      const batchShare = batch.length / totalAcc * 100;

      const blob = await fetchBatch(batch, includeTypes, batchFile, (received, total) => {
        if (!barEl) return;
        const mb = (received / 1_048_576).toFixed(1);

        if (total > 0) {
          // NCBI sent Content-Length — use real byte progress
          const pct = Math.min(99, (basePct + batchShare * (received / total)).toFixed(0));
          barEl.style.width = `${pct}%`; barEl.textContent = `${pct} %`;
          if (detailEl) detailEl.textContent = `Accessions ${from}–${to} · ${mb} / ${(total / 1_048_576).toFixed(1)} MB`;
        } else {
          // No Content-Length — use logarithmic curve (approaches ~90% of batch share, never 100%)
          const fakeRatio = 1 - Math.exp(-received / (10 * 1_048_576));
          const pct = Math.min(99, Math.round(basePct + batchShare * fakeRatio * 0.9));
          barEl.style.width = `${pct}%`; barEl.textContent = `${pct} %`;
          if (detailEl) detailEl.textContent = `Accessions ${from}–${to} · ${mb} MB received — downloading…`;
        }
      });

      savedFiles.push({ blob, name: batchFile });
      completedAcc += batch.length;
      // Only set to 100% if ALL batches are done
      const pctDone = Math.min(completedAcc === totalAcc ? 100 : 99, Math.round(completedAcc / totalAcc * 100));
      if (barEl) { barEl.style.width = `${pctDone}%`; barEl.textContent = `${pctDone} %`; }
    }

    // Show saving status before triggering file save
    const barEl = document.getElementById("dlBar");
    const statusEl = document.getElementById("dlStatus");
    if (barEl) { barEl.style.width = "100%"; barEl.textContent = "100 %"; }
    if (statusEl) statusEl.innerHTML = "Saving files…";

    Swal.close();
    for (const { blob, name } of savedFiles) await saveAs(blob, name, "application/zip");

    Swal.fire({
      icon: "success", title: "Download complete",
      html: `<p>${completedAcc} assemblies downloaded (${savedFiles.length} ZIP file${savedFiles.length > 1 ? "s" : ""}).</p>`,
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
