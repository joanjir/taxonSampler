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
        await postDownload(url, last, "sampling_taxonomic.newick");
      } catch (err) {
        console.error("[exports] Newick export error:", err);
        Swal.fire({ icon: 'error', title: 'Export failed', text: 'Newick export failed: ' + (err.message || err), confirmButtonColor: '#198754' });
      }
      return;
    }

    const payload = getExportPayload({ allowManualFallback: false });
    if (!payload) return;
    await postDownload("/taxonomy/sampling/export/newick/", payload, "sampling_taxonomic.newick");
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
        "Species Score":   s.species_score ?? "",
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

  // ── NCBI Download Scripts ──────────────────────────────────
  // Generate shell scripts that use NCBI `datasets` CLI to download
  // genomic data for the sampled species.

  /**
   * Map our short include flags to NCBI Datasets API v2 annotation types.
   */
  const NCBI_INCLUDE_MAP = {
    genome:  "GENOME_FASTA",
    protein: "PROT_FASTA",
    gbff:    "GENOME_GBFF",
  };

  function mapIncludeTypes(includeFlag) {
    return includeFlag.split(",").map(f => NCBI_INCLUDE_MAP[f.trim()]).filter(Boolean);
  }

  /**
   * Build a bash script that downloads NCBI data via the REST API (curl).
   * No external CLI tools required — only curl and unzip.
   * @param {Array} species - species list from sampling result
   * @param {string} includeFlag - genome | protein | gbff | genome,protein,gbff
   * @param {string} label - human-readable label (e.g. "Genomes (FASTA)")
   * @param {string} outZip - output zip filename
   * @returns {string} bash script content
   */
  function buildNcbiScript(species, includeFlag, label, outZip) {
    const now = new Date().toISOString().slice(0, 10);
    const accessions = species
      .map(s => s.accession)
      .filter(Boolean);

    if (!accessions.length) return null;

    const apiTypes = mapIncludeTypes(includeFlag);

    // Commented manifest for reference
    const manifest = species
      .filter(s => s.accession)
      .map(s => `#   ${s.accession}  ${s.organism_name || ""}`)
      .join("\n");

    // JSON array of accessions for the API payload
    const accJson = accessions.map(a => `"${a}"`).join(",");
    const typesJson = apiTypes.map(t => `"${t}"`).join(",");

    // Batch size: NCBI API handles up to ~500 accessions per request
    const BATCH_SIZE = 200;

    return `#!/usr/bin/env bash
# ============================================================
# NCBI ${label} Download Script
# Generated by TaxBridge on ${now}
# Species: ${accessions.length} | Data: ${includeFlag}
# ============================================================
#
# Prerequisites: curl, unzip (standard on most systems)
#
# Optional: set NCBI_API_KEY for higher rate limits:
#   export NCBI_API_KEY="your-key-here"
#   (Get one free at https://www.ncbi.nlm.nih.gov/account/settings/)
#
# Usage:
#   chmod +x ${outZip.replace(".zip", ".sh")}
#   ./${outZip.replace(".zip", ".sh")}
#
# ============================================================

set -euo pipefail

# Work in the same folder where this script lives
SCRIPT_DIR="$(cd "$(dirname "\${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

OUTPUT_ZIP="${outZip}"
API_URL="https://api.ncbi.nlm.nih.gov/datasets/v2/genome/download"
BATCH_SIZE=${BATCH_SIZE}

# ── Accession manifest ──
${manifest}

# Full accession list
ACCESSIONS=(
${accessions.map(a => `  "${a}"`).join("\n")}
)

echo "============================================================"
echo " TaxBridge — NCBI ${label} Download"
echo " Species: \${#ACCESSIONS[@]}"
echo " Data:    ${includeFlag}"
echo "============================================================"
echo ""

# ── Check curl is available ──
if ! command -v curl &> /dev/null; then
    echo "ERROR: 'curl' not found. Please install curl."
    exit 1
fi

# ── Build curl headers ──
HEADERS=(-H "Content-Type: application/json" -H "Accept: application/zip")
if [ -n "\${NCBI_API_KEY:-}" ]; then
    HEADERS+=(-H "api-key: \$NCBI_API_KEY")
    echo "Using NCBI API key for higher rate limits."
fi

# ── Download in batches of $BATCH_SIZE ──
TOTAL=\${#ACCESSIONS[@]}
PART=0

for (( i=0; i<TOTAL; i+=BATCH_SIZE )); do
    BATCH=("\${ACCESSIONS[@]:i:BATCH_SIZE}")
    PART=$((PART + 1))

    # Build JSON array of this batch
    JSON_ACC=""
    for acc in "\${BATCH[@]}"; do
        [ -n "$JSON_ACC" ] && JSON_ACC="$JSON_ACC,"
        JSON_ACC="$JSON_ACC\\"$acc\\""
    done

    PAYLOAD='{"accessions":['$JSON_ACC'],"include_annotation_type":[${typesJson}]}'

    if [ "$TOTAL" -le "$BATCH_SIZE" ]; then
        DEST="$OUTPUT_ZIP"
        echo "Downloading \${#BATCH[@]} assemblies..."
    else
        DEST="\${OUTPUT_ZIP%.zip}_part\${PART}.zip"
        echo "Downloading batch $PART (\${#BATCH[@]} of $TOTAL assemblies)..."
    fi

    curl -X POST "$API_URL" \\
        "\${HEADERS[@]}" \\
        -d "$PAYLOAD" \\
        -o "$DEST" \\
        --progress-bar --fail

    echo ""
    echo "Extracting $DEST ..."
    unzip -o "$DEST"

    # Clean up zip after extraction
    rm -f "$DEST"
done

echo ""
echo "============================================================"
echo " Done! Files saved to: $SCRIPT_DIR/"
echo "============================================================"
`;
  }

  /**
   * Build a PowerShell script that downloads NCBI data via the REST API.
   * No external CLI tools required — only Invoke-WebRequest and Expand-Archive.
   */
  function buildNcbiPsScript(species, includeFlag, label, outZip) {
    const now = new Date().toISOString().slice(0, 10);
    const accessions = species
      .map(s => s.accession)
      .filter(Boolean);

    if (!accessions.length) return null;

    const apiTypes = mapIncludeTypes(includeFlag);

    const manifest = species
      .filter(s => s.accession)
      .map(s => `#   ${s.accession}  ${s.organism_name || ""}`)
      .join("\n");

    const BATCH_SIZE = 200;

    return `# ============================================================
# NCBI ${label} Download Script (PowerShell)
# Generated by TaxBridge on ${now}
# Species: ${accessions.length} | Data: ${includeFlag}
# ============================================================
#
# Prerequisites: PowerShell 5.1+ (built-in on Windows 10/11)
#
# Optional: set NCBI_API_KEY for higher rate limits:
#   $env:NCBI_API_KEY = "your-key-here"
#   (Get one free at https://www.ncbi.nlm.nih.gov/account/settings/)
#
# Usage:
#   .\\${outZip.replace(".zip", ".ps1")}
#
# ============================================================

$ErrorActionPreference = "Stop"

# Work in the same folder where this script lives
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$OutputZip = "${outZip}"
$ApiUrl    = "https://api.ncbi.nlm.nih.gov/datasets/v2/genome/download"
$BatchSize = ${BATCH_SIZE}

# ── Accession manifest ──
${manifest}

# Accession list
$Accessions = @(
${accessions.map(a => `    "${a}"`).join("\n")}
)

Write-Host "============================================================"
Write-Host " TaxBridge - NCBI ${label} Download"
Write-Host " Species: $($Accessions.Count)"
Write-Host " Data:    ${includeFlag}"
Write-Host "============================================================"
Write-Host ""

# ── Build headers ──
$Headers = @{ "Accept" = "application/zip" }
if ($env:NCBI_API_KEY) {
    $Headers["api-key"] = $env:NCBI_API_KEY
    Write-Host "Using NCBI API key for higher rate limits."
}

# Allow large downloads (PS 5.1 default buffer is small)
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12

# ── Download in batches of $BatchSize ──
$Total = $Accessions.Count
$Part  = 0

for ($i = 0; $i -lt $Total; $i += $BatchSize) {
    $Batch = $Accessions[$i .. [Math]::Min($i + $BatchSize - 1, $Total - 1)]
    $Part++

    $Body = @{
        accessions              = $Batch
        include_annotation_type = @(${apiTypes.map(t => `"${t}"`).join(", ")})
    } | ConvertTo-Json -Depth 3 -Compress

    if ($Total -le $BatchSize) {
        $Dest = $OutputZip
        Write-Host "Downloading $($Batch.Count) assemblies..."
    } else {
        $Dest = $OutputZip -replace '\\.zip$', "_part$Part.zip"
        Write-Host "Downloading batch $Part ($($Batch.Count) of $Total assemblies)..."
    }

    Invoke-WebRequest -Uri $ApiUrl \`
        -Method POST \`
        -ContentType "application/json" \`
        -Headers $Headers \`
        -Body $Body \`
        -OutFile $Dest \`
        -UseBasicParsing

    Write-Host ""
    Write-Host "Extracting $Dest ..."
    Expand-Archive -Path $Dest -DestinationPath . -Force

    # Clean up zip after extraction
    Remove-Item -Path $Dest -Force -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "============================================================"
Write-Host " Done! Files saved to: $ScriptDir/"
Write-Host "============================================================"
`;
  }

  /**
   * Handler factory for NCBI download script buttons.
   * Offers user choice between Bash and PowerShell via SweetAlert.
   */
  function ncbiScriptHandler(includeFlag, label, outZipBase) {
    return async () => {
      const last = getLastSampling();
      if (!requireSpecies(last)) return;
      if (!isDbSamplingResult(last)) {
        Swal.fire({ icon: 'info', title: 'Not available', text: 'NCBI download scripts require DB sampling results.', confirmButtonColor: '#198754' });
        return;
      }

      const species = last.species || [];
      const accessions = species.filter(s => s.accession);
      if (!accessions.length) {
        Swal.fire({ icon: 'warning', title: 'No accessions', text: 'None of the sampled species have assembly accessions.', confirmButtonColor: '#198754' });
        return;
      }

      // Ask user: Bash or PowerShell?
      const { value: format } = await Swal.fire({
        title: `Download ${label}`,
        html: `<div class="text-start small">
          <p>Generate a script to download <strong>${accessions.length}</strong> assemblies directly from the NCBI Datasets API.</p>
          <p>Only requires <code>curl</code> (Bash) or <code>PowerShell 5.1+</code> (Windows) — no extra tools needed.</p>
          <p class="mb-1">Choose script format:</p>
        </div>`,
        input: 'radio',
        inputOptions: {
          'bash': 'Bash (.sh) — Linux / macOS / Git Bash / WSL',
          'ps1':  'PowerShell (.ps1) — Windows',
        },
        inputValue: 'bash',
        showCancelButton: true,
        confirmButtonText: 'Generate',
        confirmButtonColor: '#198754',
        inputValidator: (v) => !v ? 'Select a format' : undefined,
      });

      if (!format) return;

      if (format === 'bash') {
        const script = buildNcbiScript(species, includeFlag, label, `${outZipBase}.zip`);
        if (script) await saveAs(script, `${outZipBase}.sh`, "application/octet-stream");
      } else {
        const script = buildNcbiPsScript(species, includeFlag, label, `${outZipBase}.zip`);
        if (script) await saveAs(script, `${outZipBase}.ps1`, "application/octet-stream");
      }
    };
  }

  document.getElementById("dlScriptGenome")?.addEventListener("click",
    ncbiScriptHandler("genome", "Genomes (FASTA)", "download_genomes"));

  document.getElementById("dlScriptProtein")?.addEventListener("click",
    ncbiScriptHandler("protein", "Proteomes (FAA)", "download_proteomes"));

  document.getElementById("dlScriptGbff")?.addEventListener("click",
    ncbiScriptHandler("gbff", "GenBank (GBFF)", "download_gbff"));

  document.getElementById("dlScriptAll")?.addEventListener("click",
    ncbiScriptHandler("genome,protein,gbff", "All Data (genome+protein+gbff)", "download_all_ncbi"));

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
