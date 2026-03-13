/**
 * Discoveries Tab - Weekly species discovery from NCBI
 * Manages the display and actions for newly discovered species.
 */
(function () {
  "use strict";
  console.log("[Discoveries v2] JS loaded, isAdmin:", window.HOME_DATA?.isAdmin);

  const isAdmin = window.HOME_DATA?.isAdmin || false;
  const csrfToken = document.querySelector("[name=csrfmiddlewaretoken]")?.value || "";

  let currentPage = 1;
  const pageSize = 15;
  let currentFilter = "pending";

  // ─── DOM references ────────────────────────────────────
  const tbody = document.getElementById("discoveriesTableBody");
  const tableInfo = document.getElementById("discoveryTableInfo");
  const pagination = document.getElementById("discoveryPagination");
  const statusFilter = document.getElementById("discoveryStatusFilter");
  const btnStartDiscovery = document.getElementById("btn-start-discovery");
  const btnBulkImport = document.getElementById("btn-bulk-import");
  const runningAlert = document.getElementById("discovery-running-alert");

  if (!tbody) return; // Tab not rendered

  // ─── Event listeners ──────────────────────────────────
  statusFilter?.addEventListener("change", () => {
    currentFilter = statusFilter.value;
    currentPage = 1;
    loadDiscoveries();
  });

  btnStartDiscovery?.addEventListener("click", startDiscovery);
  btnBulkImport?.addEventListener("click", bulkImportDiscoveries);

  // ─── Load discoveries on tab click ────────────────────
  const tabLink = document.querySelector('a[href="#tab-discoveries"]');
  if (tabLink) {
    tabLink.addEventListener("shown.bs.tab", () => {
      loadDiscoveries();
    });
    // Also load if it's already the active tab
    if (tabLink.classList.contains("active")) {
      loadDiscoveries();
    }
  }

  // ─── Fetch and render discoveries ─────────────────────
  async function loadDiscoveries() {
    tbody.innerHTML = `<tr><td colspan="${isAdmin ? 9 : 8}" class="text-center text-muted py-4">
      <div class="spinner-border spinner-border-sm me-2"></div> Loading...</td></tr>`;

    try {
      const params = new URLSearchParams({
        page: currentPage,
        page_size: pageSize,
        status: currentFilter,
      });
      const resp = await fetch(`/api/v1/taxonomy/discovery/species/?${params}`);
      const data = await resp.json();

      renderTable(data.results);
      renderPagination(data.total, data.page, data.total_pages);
      tableInfo.textContent = data.total > 0
        ? `Showing ${(data.page - 1) * pageSize + 1}-${Math.min(data.page * pageSize, data.total)} of ${data.total}`
        : "No species found";
    } catch (err) {
      console.error("Error loading discoveries:", err);
      tbody.innerHTML = `<tr><td colspan="${isAdmin ? 9 : 8}" class="text-center text-danger py-4">Error loading data</td></tr>`;
    }
  }

  function renderTable(species) {
    if (!species || species.length === 0) {
      tbody.innerHTML = `<tr><td colspan="${isAdmin ? 9 : 8}" class="text-center text-muted py-4">
        <i class="ti ti-search-off fs-1 d-block mb-2"></i>
        No new species found${currentFilter === "pending" ? ". Run a scan to discover new species." : "."}
      </td></tr>`;
      return;
    }

    tbody.innerHTML = species.map(sp => {
      const qualityBadge = sp.quality_score >= 0.7
        ? '<span class="badge bg-green-lt text-green">High</span>'
        : sp.quality_score >= 0.5
          ? '<span class="badge bg-yellow-lt text-yellow">Medium</span>'
          : '<span class="badge bg-red-lt text-red">Low</span>';

      const levelIcon = {
        "Complete Genome": "ti-circle-check text-green",
        "Chromosome": "ti-brand-chrome text-blue",
        "Scaffold": "ti-stack-2 text-yellow",
      }[sp.genome_level] || "ti-box text-secondary";

      const statusBadge = sp.is_imported
        ? '<span class="badge bg-green-lt text-green"><i class="ti ti-check me-1"></i>Imported</span>'
        : sp.is_dismissed
          ? '<span class="badge bg-secondary-lt text-secondary"><i class="ti ti-x me-1"></i>Dismissed</span>'
          : '<span class="badge bg-lime-lt text-lime"><i class="ti ti-sparkles me-1"></i>New</span>';

      const kingdomEmoji = {
        metazoa: "🦁", fungi: "🍄", viridiplantae: "🌿",
        bacteria: "🦠", archaea: "🧬",
      }[sp.kingdom] || "🧬";

      const coverage = sp.genome_coverage != null ? `${sp.genome_coverage.toFixed(1)}x` : "-";
      const proteinCoding = sp.protein_coding != null ? sp.protein_coding.toLocaleString() : "-";

      let actions = "";
      if (isAdmin && !sp.is_imported && !sp.is_dismissed) {
        actions = `
          <div class="btn-group btn-group-sm">
            <button class="btn btn-sm btn-success" onclick="window._importDiscovery(${sp.id})" title="Import">
              <i class="ti ti-download"></i>
            </button>
            <button class="btn btn-sm btn-outline-secondary" onclick="window._dismissDiscovery(${sp.id})" title="Dismiss">
              <i class="ti ti-x"></i>
            </button>
          </div>`;
      } else if (isAdmin) {
        actions = '<span class="text-muted">-</span>';
      }

      return `<tr>
        <td>
          <div class="fw-bold">${escapeHtml(sp.scientific_name)}</div>
          ${sp.common_name ? `<div class="text-secondary small">${escapeHtml(sp.common_name)}</div>` : ""}
          <div class="text-muted small">taxid: ${sp.taxid}</div>
        </td>
        <td>${kingdomEmoji} ${capitalize(sp.kingdom)}</td>
        <td><code class="small">${sp.accession}</code></td>
        <td><i class="ti ${levelIcon} me-1"></i>${sp.genome_level || "-"}</td>
        <td class="text-end">${qualityBadge}<br><small class="text-muted">${(sp.quality_score * 100).toFixed(0)}%</small></td>
        <td class="text-end">${proteinCoding}</td>
        <td class="text-end">${coverage}</td>
        <td>${statusBadge}</td>
        ${isAdmin ? `<td>${actions}</td>` : ""}
      </tr>`;
    }).join("");
  }

  function renderPagination(total, page, totalPages) {
    if (totalPages <= 1) {
      pagination.innerHTML = "";
      return;
    }
    let html = "";
    if (page > 1) {
      html += `<li class="page-item"><a class="page-link" href="#" onclick="window._discoveryPage(${page - 1}); return false;">&laquo;</a></li>`;
    }
    const start = Math.max(1, page - 2);
    const end = Math.min(totalPages, page + 2);
    for (let i = start; i <= end; i++) {
      html += `<li class="page-item ${i === page ? "active" : ""}"><a class="page-link" href="#" onclick="window._discoveryPage(${i}); return false;">${i}</a></li>`;
    }
    if (page < totalPages) {
      html += `<li class="page-item"><a class="page-link" href="#" onclick="window._discoveryPage(${page + 1}); return false;">&raquo;</a></li>`;
    }
    pagination.innerHTML = html;
  }

  // ─── Actions ───────────────────────────────────────────
  async function startDiscovery() {


    let selectedKingdoms = Array.from(document.querySelectorAll('#discovery-kingdoms-group input[type="checkbox"]:checked')).map(cb => cb.value);
    if (selectedKingdoms.length === 0) {
      Swal.fire({ icon: 'warning', title: 'No domains selected', text: 'Please select at least one domain/kingdom to scan.', confirmButtonColor: '#206bc4' });
      return;
    }

    // Expand 'eukaryota' to its three kingdoms for backend
    let backendKingdoms = [];
    selectedKingdoms.forEach(k => {
      if (k === 'eukaryota') {
        backendKingdoms.push('metazoa', 'fungi', 'viridiplantae');
      } else {
        backendKingdoms.push(k);
      }
    });

    // Map for pretty labels
    const prettyLabels = { eukaryota: 'Eukaryota', bacteria: 'Bacteria', archaea: 'Archaea' };
    const selectedLabels = selectedKingdoms.map(k => prettyLabels[k] || (k.charAt(0).toUpperCase() + k.slice(1)));

    const result = await Swal.fire({
      title: 'Start discovery scan?',
      html: `This will scan NCBI for new species in: <b>${selectedLabels.join(', ')}</b>.<br>It may take several minutes.`,
      icon: 'question',
      showCancelButton: true,
      confirmButtonText: 'Start scan',
      cancelButtonText: 'Cancel',
      confirmButtonColor: '#206bc4',
      cancelButtonColor: '#6c757d',
    });
    if (!result.isConfirmed) return;

    btnStartDiscovery.disabled = true;
    btnStartDiscovery.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Scanning...';
    runningAlert?.classList.remove("d-none");

    try {
      const resp = await fetch("/api/v1/taxonomy/discovery/start/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken,
        },
        body: JSON.stringify({ kingdoms: backendKingdoms }),
      });
      const data = await resp.json();

      if (data.success) {
        // Poll for completion
        pollDiscoveryStatus();
      } else {
        Swal.fire({ icon: 'error', title: 'Discovery error', text: data.error || 'Error starting discovery', confirmButtonColor: '#206bc4' });
        resetButton();
      }
    } catch (err) {
      console.error("Error starting discovery:", err);
      Swal.fire({ icon: 'error', title: 'Connection error', text: 'Error starting discovery scan', confirmButtonColor: '#206bc4' });
      resetButton();
    }
  }

  function pollDiscoveryStatus() {
    const interval = setInterval(async () => {
      try {
        const resp = await fetch("/api/v1/taxonomy/discovery/runs/");
        const data = await resp.json();
        const latest = data.runs?.[0];

        if (latest && latest.status === "completed") {
          clearInterval(interval);
          resetButton();
          runningAlert?.classList.add("d-none");
          loadDiscoveries();
          if (latest.new_species_found > 0) {
            showToast(`${latest.new_species_found} new species found!`, "success");
          } else {
            showToast("No new species found this time.", "info");
          }
        } else if (latest && latest.status === "failed") {
          clearInterval(interval);
          resetButton();
          runningAlert?.classList.add("d-none");
          showToast("Discovery scan failed.", "danger");
        }
      } catch {
        // continue polling
      }
    }, 5000);
  }

  function resetButton() {
    if (btnStartDiscovery) {
      btnStartDiscovery.disabled = false;
      btnStartDiscovery.innerHTML = '<i class="ti ti-radar me-1"></i> Scan Now';
    }
  }

  async function importDiscovery(speciesId) {
    const confirmResult = await Swal.fire({
      title: 'Import species?',
      text: 'This will import the species and fetch its genome data.',
      icon: 'question',
      showCancelButton: true,
      confirmButtonText: 'Import',
      cancelButtonText: 'Cancel',
      confirmButtonColor: '#206bc4',
      cancelButtonColor: '#6c757d',
    });
    if (!confirmResult.isConfirmed) return;
    try {
      const resp = await fetch(`/api/v1/taxonomy/discovery/${speciesId}/import/`, {
        method: "POST",
        headers: { "X-CSRFToken": csrfToken },
      });
      const data = await resp.json();
      if (data.success) {
        showToast(`${data.scientific_name} imported!`, "success");
        loadDiscoveries();
      } else {
        Swal.fire({ icon: 'error', text: data.error || 'Import failed', confirmButtonColor: '#206bc4' });
      }
    } catch (err) {
      Swal.fire({ icon: 'error', text: 'Error importing species', confirmButtonColor: '#206bc4' });
    }
  }

  async function dismissDiscovery(speciesId) {
    try {
      const resp = await fetch(`/api/v1/taxonomy/discovery/${speciesId}/dismiss/`, {
        method: "POST",
        headers: { "X-CSRFToken": csrfToken },
      });
      const data = await resp.json();
      if (data.success) {
        loadDiscoveries();
      } else {
        Swal.fire({ icon: 'error', text: data.error || 'Dismiss failed', confirmButtonColor: '#206bc4' });
      }
    } catch (err) {
      Swal.fire({ icon: 'error', text: 'Error dismissing species', confirmButtonColor: '#206bc4' });
    }
  }

  // ─── Bulk Import ────────────────────────────────────────
  async function bulkImportDiscoveries() {
    console.log("[Discoveries] bulkImportDiscoveries clicked");
    // First check how many pending
    try {
      const checkResp = await fetch("/api/v1/taxonomy/discovery/species/?status=pending&page_size=1");
      const checkData = await checkResp.json();
      if (checkData.total === 0) {
        Swal.fire({ icon: 'info', title: 'Nothing to import', text: 'There are no pending species to import.', confirmButtonColor: '#206bc4' });
        return;
      }

      const result = await Swal.fire({
        title: 'Import all pending species?',
        html: `This will import <b>${checkData.total}</b> species:<br>` +
              `<ul class="text-start mt-2"><li>Create Taxon records</li><li>Fetch GCF genome data from NCBI</li><li>Match with Catalogue of Life</li></ul>` +
              `<small class="text-muted">This may take a while for large batches.</small>`,
        icon: 'question',
        showCancelButton: true,
        confirmButtonText: `Import ${checkData.total} species`,
        cancelButtonText: 'Cancel',
        confirmButtonColor: '#2fb344',
        cancelButtonColor: '#6c757d',
      });
      if (!result.isConfirmed) return;

      btnBulkImport.disabled = true;
      btnBulkImport.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Importing...';
      runningAlert?.classList.remove("d-none");
      if (runningAlert) runningAlert.querySelector("span").textContent = `Importing ${checkData.total} species (fetching genomes + COL matching)...`;

      const resp = await fetch("/api/v1/taxonomy/discovery/bulk-import/", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": csrfToken,
        },
      });
      const data = await resp.json();

      if (data.success) {
        pollBulkImport(checkData.total);
      } else {
        Swal.fire({ icon: 'error', title: 'Import error', text: data.error || 'Error starting bulk import', confirmButtonColor: '#206bc4' });
        resetBulkButton();
      }
    } catch (err) {
      console.error("Error starting bulk import:", err);
      Swal.fire({ icon: 'error', title: 'Connection error', text: 'Error starting bulk import', confirmButtonColor: '#206bc4' });
      resetBulkButton();
    }
  }

  function pollBulkImport(originalTotal) {
    const interval = setInterval(async () => {
      try {
        const resp = await fetch("/api/v1/taxonomy/discovery/species/?status=pending&page_size=1");
        const data = await resp.json();
        const remaining = data.total;
        const done = originalTotal - remaining;

        if (btnBulkImport) {
          btnBulkImport.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span> ${done}/${originalTotal}`;
        }
        if (runningAlert) {
          runningAlert.querySelector("span").textContent = `Importing species... ${done}/${originalTotal} done`;
        }

        if (remaining === 0) {
          clearInterval(interval);
          resetBulkButton();
          runningAlert?.classList.add("d-none");
          loadDiscoveries();
          showToast(`${done} species imported with genome data + COL matching!`, "success");
        }
      } catch {
        // continue polling
      }
    }, 3000);
  }

  function resetBulkButton() {
    if (btnBulkImport) {
      btnBulkImport.disabled = false;
      btnBulkImport.innerHTML = '<i class="ti ti-database-import me-1"></i> Import All';
    }
  }

  // ─── Helpers ───────────────────────────────────────────
  function escapeHtml(str) {
    if (!str) return "";
    return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  function capitalize(str) {
    return str ? str.charAt(0).toUpperCase() + str.slice(1) : "";
  }

  function showToast(message, type = "info") {
    // Use Tabler toast if available, else simple alert
    const container = document.querySelector(".toast-container") || document.body;
    const toast = document.createElement("div");
    toast.className = `toast show align-items-center text-white bg-${type} border-0`;
    toast.setAttribute("role", "alert");
    toast.style.cssText = "position: fixed; top: 20px; right: 20px; z-index: 9999; min-width: 300px;";
    toast.innerHTML = `
      <div class="d-flex">
        <div class="toast-body">${message}</div>
        <button type="button" class="btn-close btn-close-white me-2 m-auto" onclick="this.closest('.toast').remove()"></button>
      </div>`;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 5000);
  }

  // ─── Expose to global scope for inline onclick ────────
  window._discoveryPage = function (page) {
    currentPage = page;
    loadDiscoveries();
  };
  window._importDiscovery = importDiscovery;
  window._dismissDiscovery = dismissDiscovery;
})();
