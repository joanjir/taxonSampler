// taxonomy/static/taxonomy/js/tree/taxon_detail.js
/**
 * Taxon Detail Modal — Shows detailed information about a species/taxon
 * 
 * Displays:
 * - COL ID with link
 * - NCBI TaxID with link
 * - Full classification path
 * - Linked genome assemblies
 */

const ENDPOINT = window.TAXON_DETAIL_ENDPOINT || "/api/v1/taxonomy/taxon/detail/";

// DOM references
let modal = null;
let bsModal = null;

function getElements() {
  return {
    modal: document.getElementById("taxonDetailModal"),
    nameEl: document.getElementById("taxonDetailName"),
    rankEl: document.getElementById("taxonDetailRank"),
    loadingEl: document.getElementById("taxonDetailLoading"),
    contentEl: document.getElementById("taxonDetailContent"),
    colIdEl: document.getElementById("taxonColId"),
    colLinkEl: document.getElementById("taxonColLink"),
    ncbiCardEl: document.getElementById("taxonNcbiCard"),
    ncbiIdEl: document.getElementById("taxonNcbiId"),
    ncbiLinkEl: document.getElementById("taxonNcbiLink"),
    classPathEl: document.getElementById("taxonClassificationPath"),
    genomesSection: document.getElementById("taxonGenomesSection"),
    genomeCountEl: document.getElementById("taxonGenomeCount"),
    genomesEmptyEl: document.getElementById("taxonGenomesEmpty"),
    genomesListEl: document.getElementById("taxonGenomesList"),
    genomesBodyEl: document.getElementById("taxonGenomesBody"),
  };
}

/**
 * Format N50 value for display
 */
function formatN50(kb) {
  if (kb == null) return "—";
  if (kb >= 1000) return `${(kb / 1000).toFixed(1)} Mb`;
  return `${kb.toFixed(0)} Kb`;
}

/**
 * Get badge class for genome level
 */
function getLevelBadgeClass(level) {
  const l = (level || "").toLowerCase();
  if (l.includes("complete")) return "bg-green-lt text-green";
  if (l.includes("chromosome")) return "bg-blue-lt text-blue";
  if (l.includes("scaffold")) return "bg-yellow-lt text-yellow";
  if (l.includes("contig")) return "bg-orange-lt text-orange";
  return "bg-secondary-lt text-secondary";
}

/**
 * Get badge class for RefSeq category
 */
function getRefSeqBadgeClass(cat) {
  const c = (cat || "").toLowerCase();
  if (c.includes("reference")) return "bg-success-lt text-success";
  if (c.includes("representative")) return "bg-primary-lt text-primary";
  return "bg-secondary-lt text-secondary";
}

/**
 * Build classification path badges - using neutral gray tones
 */
// Canonical rank order (root → leaf)
const _RANK_PRIORITY = {
  domain:0, superkingdom:0, kingdom:1, subkingdom:2,
  phylum:3, subphylum:4, class:5, subclass:6,
  order:7, suborder:8, family:9, subfamily:10,
  genus:11, subgenus:12, species:13, subspecies:14,
  variety:15, form:16,
};
function sortPath(path) {
  if (!path || !path.length) return [];
  return [...path].sort((a, b) => {
    const pa = _RANK_PRIORITY[(a.rank||'').toLowerCase()] ?? 50;
    const pb = _RANK_PRIORITY[(b.rank||'').toLowerCase()] ?? 50;
    return pa - pb;
  });
}

function buildClassificationPath(path) {
  if (!path || !path.length) return "<span class='text-muted'>—</span>";
  const sorted = sortPath(path);
  return sorted.map((item, idx) => {
    const rank = item.rank || "unknown";
    const name = item.name || "—";
    const isLast = idx === sorted.length - 1;
    
    // Color per taxonomic rank
    const rankColors = {
      domain:       "bg-purple-lt text-purple",
      superkingdom: "bg-purple-lt text-purple",
      kingdom:      "bg-blue-lt text-blue",
      phylum:       "bg-cyan-lt text-cyan",
      subphylum:    "bg-cyan-lt text-cyan",
      class:        "bg-teal-lt text-teal",
      subclass:     "bg-teal-lt text-teal",
      order:        "bg-green-lt text-green",
      suborder:     "bg-green-lt text-green",
      family:       "bg-yellow-lt text-yellow",
      subfamily:    "bg-yellow-lt text-yellow",
      genus:        "bg-orange-lt text-orange",
      subgenus:     "bg-orange-lt text-orange",
      species:      "bg-red-lt text-red",
      subspecies:   "bg-pink-lt text-pink",
    };
    const colorCls = rankColors[rank.toLowerCase()] || "bg-secondary-lt text-secondary";
    
    const badge = `<span class="badge ${colorCls}" title="${rank}">
      <span style="font-size:0.6rem;opacity:0.7;">${rank}</span> ${name}
    </span>`;
    const arrow = isLast ? "" : '<i class="ti ti-chevron-right text-muted mx-1" style="font-size:0.7rem;"></i>';
    
    return badge + arrow;
  }).join("");
}

/**
 * Build genomes table rows
 */
function buildGenomesTable(genomes) {
  if (!genomes || !genomes.length) return "";
  
  return genomes.map(g => {
    const accession = g.accession || "—";
    const orgName = g.organism_name || "";
    const level = g.assembly_level || "—";
    const refseq = g.refseq_category || "na";
    const n50 = formatN50(g.scaffold_n50_kb);
    
    const ncbiUrl = g.link || `https://www.ncbi.nlm.nih.gov/datasets/genome/${accession}/`;
    
    return `
      <tr>
        <td>
          <a href="${ncbiUrl}" target="_blank" class="text-primary text-decoration-none">
            ${accession} <i class="ti ti-external-link" style="font-size:0.7rem;"></i>
          </a>
        </td>
        <td class="small">${orgName}</td>
        <td><span class="badge ${getLevelBadgeClass(level)}">${level}</span></td>
        <td>${n50}</td>
        <td><span class="badge ${getRefSeqBadgeClass(refseq)}">${refseq}</span></td>
      </tr>
    `;
  }).join("");
}

/**
 * Show the modal with loading state
 */
function showLoading(name, rank) {
  const els = getElements();
  if (!els.modal) return;
  
  els.nameEl.textContent = name || "Loading...";
  els.rankEl.textContent = rank ? `${rank.charAt(0).toUpperCase() + rank.slice(1)}` : "—";
  els.loadingEl.classList.remove("d-none");
  els.contentEl.classList.add("d-none");
  
  if (!bsModal) {
    bsModal = new bootstrap.Modal(els.modal);
  }
  bsModal.show();
}

/**
 * Populate the modal with taxon data
 */
function populateModal(data) {
  const els = getElements();
  if (!els.modal) return;
  
  // Header
  els.nameEl.textContent = data.col?.name || data.name || "Unknown";
  els.rankEl.textContent = data.col?.rank
    ? `${data.col.rank.charAt(0).toUpperCase() + data.col.rank.slice(1)}`
    : "—";
  
  // COL
  els.colIdEl.textContent = data.col?.id || "—";
  if (data.col?.link) {
    els.colLinkEl.href = data.col.link;
    els.colLinkEl.textContent = "View in COL";
    els.colLinkEl.classList.remove("d-none");
  } else if (data.col?.closest_col_link) {
    // No direct COL record, but we found a close match (e.g. parent species)
    els.colIdEl.textContent = `${data.col.closest_col_id} (${data.col.closest_col_rank}: ${data.col.closest_col_name})`;
    els.colLinkEl.href = data.col.closest_col_link;
    els.colLinkEl.innerHTML = `<i class="ti ti-external-link me-1"></i>Closest in COL`;
    els.colLinkEl.classList.remove("d-none");
  } else {
    els.colLinkEl.classList.add("d-none");
  }
  
  // NCBI
  if (data.ncbi?.taxid) {
    els.ncbiIdEl.textContent = data.ncbi.taxid;
    els.ncbiLinkEl.href = data.ncbi.link;
    els.ncbiCardEl.classList.remove("d-none");
    els.ncbiLinkEl.classList.remove("d-none");
  } else {
    els.ncbiIdEl.textContent = "Not linked";
    els.ncbiLinkEl.classList.add("d-none");
  }
  
  // Classification path
  els.classPathEl.innerHTML = buildClassificationPath(data.classification_path);
  
  // Genomes
  const genomes = data.genomes || [];
  els.genomeCountEl.textContent = `${genomes.length} genome${genomes.length !== 1 ? "s" : ""}`;
  
  if (genomes.length) {
    els.genomesEmptyEl.classList.add("d-none");
    els.genomesListEl.classList.remove("d-none");
    els.genomesBodyEl.innerHTML = buildGenomesTable(genomes);
  } else {
    els.genomesEmptyEl.classList.remove("d-none");
    els.genomesListEl.classList.add("d-none");
  }
  
  // Show content, hide loading
  els.loadingEl.classList.add("d-none");
  els.contentEl.classList.remove("d-none");
}

/**
 * Show error in modal
 */
function showError(message) {
  const els = getElements();
  if (!els.modal) return;
  
  els.loadingEl.innerHTML = `
    <div class="text-center text-danger py-4">
      <i class="ti ti-alert-circle" style="font-size: 2rem;"></i>
      <p class="mt-2">${message || "Failed to load taxon information"}</p>
    </div>
  `;
}

/**
 * Fetch taxon details from API
 */
async function fetchTaxonDetail(key, name) {
  try {
    let url = `${ENDPOINT}?key=${encodeURIComponent(key)}`;
    if (name) url += `&name=${encodeURIComponent(name)}`;
    const response = await fetch(url);
    
    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.error || `HTTP ${response.status}`);
    }
    
    return await response.json();
  } catch (error) {
    console.error("[taxon_detail] fetch error:", error);
    throw error;
  }
}

/**
 * Open modal for a given tree key
 */
export async function openTaxonDetail(key, { name, rank } = {}) {
  if (!key) return;
  
  // Show loading state
  showLoading(name, rank);
  
  try {
    const data = await fetchTaxonDetail(key, name);
    populateModal(data);
  } catch (error) {
    showError(error.message);
  }
}

/**
 * Initialize taxon detail functionality
 * Called from main.js to set up double-click handlers
 */
export function initTaxonDetail({ renderer }) {
  // Listen for double-click events on species nodes
  window.addEventListener("tree:taxon-dblclick", (e) => {
    const { key, name, rank } = e.detail || {};
    if (key) {
      openTaxonDetail(key, { name, rank });
    }
  });
  
  return {
    open: openTaxonDetail,
  };
}
