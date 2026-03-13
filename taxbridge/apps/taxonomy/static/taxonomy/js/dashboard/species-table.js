// taxonomy/static/taxonomy/js/pages/taxon-sync-species.js
// Species List functionality for taxon-sync dashboard

(function() {
  "use strict";

  // ============================================
  // UTILITIES
  // ============================================
  function getCsrfToken() {
    return document.querySelector('[name=csrfmiddlewaretoken]')?.value 
      || document.cookie.split('; ').find(r => r.startsWith('csrftoken='))?.split('=')[1] 
      || '';
  }

  function showToast(title, message, type) {
    if (type === 'success') {
      Swal.fire({ icon: 'success', title, text: message, timer: 2500, showConfirmButton: false });
    } else {
      Swal.fire({ icon: 'error', title, text: message, confirmButtonColor: '#206bc4' });
    }
  }

  // Badge helpers
  function genomeLevelBadge(level) {
    const badges = {
      "Complete Genome": "bg-green-lt text-green",
      "Chromosome": "bg-blue-lt text-blue",
      "Scaffold": "bg-yellow-lt text-yellow",
      "Contig": "bg-secondary-lt text-secondary"
    };
    return badges[level] || "bg-secondary-lt text-secondary";
  }

  function matchStatusBadge(status) {
    const badges = {
      "matched": "bg-green-lt text-green",
      "unmatched": "bg-yellow-lt text-yellow",
      "not_in_col": "bg-yellow-lt text-yellow",
      "mismatch": "bg-red-lt text-red",
      "manual": "bg-purple-lt text-purple"
    };
    return badges[status] || "bg-secondary-lt text-secondary";
  }

  function colStatusBadge(status) {
    const badges = {
      "accepted": "bg-green-lt text-green",
      "synonym": "bg-blue-lt text-blue",
      "not_in_col": "bg-red-lt text-red",
      "misapplied": "bg-yellow-lt text-yellow",
      "unknown": "bg-secondary-lt text-secondary"
    };
    return badges[status] || "bg-secondary-lt text-secondary";
  }

  function matchStatusLabel(status) {
    const labels = {
      "matched": "Linked",
      "unmatched": "Unlinked",
      "not_in_col": "Unlinked",
      "mismatch": "Unlinked",
      "manual": "Manual"
    };
    return labels[status] || status;
  }

  // ============================================
  // TABLE
  // ============================================
  let currentPage = 1;
  const pageSize = 6;
  
  const tableBody = () => document.getElementById("genomesTableBody");
  const tableInfo = () => document.getElementById("tableInfo");
  const pagination = () => document.getElementById("pagination");
  const searchInput = () => document.getElementById("searchInput");
  const statusFilter = () => document.getElementById("statusFilter");
  const colStatusFilter = () => document.getElementById("colStatusFilter");

  async function loadGenomes() {
    const params = new URLSearchParams({
      page: currentPage,
      page_size: pageSize,
    });
    
    const search = searchInput()?.value.trim();
    const status = statusFilter()?.value;
    const colStatus = colStatusFilter()?.value;
    
    if (search) params.set("search", search);
    if (status) params.set("col_match_status", status);
    if (colStatus) params.set("col_status", colStatus);

    const tbody = tableBody();
    if (tbody) {
      tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted py-4">Loading...</td></tr>';
    }

    try {
      const endpoint = window.HOME_DATA?.endpoints?.genomesList || '/api/v1/taxonomy/genomes/';
      const resp = await fetch(endpoint + "?" + params.toString());
      const data = await resp.json();
      
      renderTable(data.results || []);
      renderPagination(data.count || 0);
      
      const info = tableInfo();
      if (info) {
        info.textContent = `Showing ${data.results?.length || 0} of ${data.count || 0} genomes`;
      }
    } catch (err) {
      console.error("[taxon-sync] Failed to load genomes:", err);
      const tbody = tableBody();
      if (tbody) {
        tbody.innerHTML = '<tr><td colspan="8" class="text-center text-danger py-4">Error loading data</td></tr>';
      }
    }
  }

  const isAdmin = window.HOME_DATA?.isAdmin || false;

  function renderTable(genomes) {
    const tbody = tableBody();
    if (!tbody) return;

    const colCount = isAdmin ? 8 : 7;

    if (!genomes.length) {
      tbody.innerHTML = `<tr><td colspan="${colCount}" class="text-center text-muted py-4">No genomes found</td></tr>`;
      return;
    }

    tbody.innerHTML = genomes.map(g => `
      <tr>
        <td><code class="small">${g.accession}</code></td>
        <td><strong>${g.organism_name || '-'}</strong></td>
        <td><span class="badge ${genomeLevelBadge(g.genome_level)}">${g.genome_level || '-'}</span></td>
        <td>${g.genes || '-'}</td>
        <td>
          ${g.protein_coding 
            ? `<span class="badge bg-blue-lt text-blue">${g.protein_coding.toLocaleString()}</span>`
            : '<span class="badge bg-secondary-lt text-secondary">-</span>'
          }
        </td>
        <td>
          <span class="badge ${matchStatusBadge(g.col_match_status)}">
            ${matchStatusLabel(g.col_match_status)}
          </span>
        </td>
        <td>
          <span class="badge ${colStatusBadge(g.col_status)}">
            ${g.col_status === 'not_in_col' ? 'Not in COL' : (g.col_status || '-')}
          </span>
        </td>
        ${isAdmin ? `
        <td>
          <div class="btn-list">
            <button class="btn btn-sm btn-ghost-primary" onclick="viewGenome('${g.accession}')" title="View details">
              <i class="ti ti-eye"></i>
            </button>
            ${(g.col_match_status === 'unmatched' || g.col_match_status === 'not_in_col' || g.col_match_status === 'mismatch' || g.col_match_status === 'manual' || g.col_status === 'synonym') ? `
            <button class="btn btn-sm btn-ghost-secondary" onclick="editGenome('${g.accession}')" title="Manual COL match">
              <i class="ti ti-edit"></i>
            </button>
            ` : ''}
          </div>
        </td>
        ` : `
        <td>
          <button class="btn btn-sm btn-ghost-primary" onclick="viewGenome('${g.accession}')" title="View details">
            <i class="ti ti-eye"></i>
          </button>
        </td>
        `}
      </tr>
    `).join('');
  }

  function renderPagination(totalItems) {
    const pag = pagination();
    if (!pag) return;

    const totalPages = Math.ceil(totalItems / pageSize);
    if (totalPages <= 1) {
      pag.innerHTML = '';
      return;
    }

    let html = '';
    if (currentPage > 1) {
      html += `<li class="page-item"><a class="page-link" href="#" onclick="goToPage(${currentPage - 1}); return false;">Previous</a></li>`;
    }

    const startPage = Math.max(1, currentPage - 2);
    const endPage = Math.min(totalPages, currentPage + 2);

    if (startPage > 1) {
      html += `<li class="page-item"><a class="page-link" href="#" onclick="goToPage(1); return false;">1</a></li>`;
      if (startPage > 2) {
        html += `<li class="page-item disabled"><span class="page-link">…</span></li>`;
      }
    }

    for (let p = startPage; p <= endPage; p++) {
      html += `<li class="page-item ${p === currentPage ? 'active' : ''}">
        <a class="page-link" href="#" onclick="goToPage(${p}); return false;">${p}</a>
      </li>`;
    }

    if (endPage < totalPages) {
      if (endPage < totalPages - 1) {
        html += `<li class="page-item disabled"><span class="page-link">…</span></li>`;
      }
      html += `<li class="page-item"><a class="page-link" href="#" onclick="goToPage(${totalPages}); return false;">${totalPages}</a></li>`;
    }

    if (currentPage < totalPages) {
      html += `<li class="page-item"><a class="page-link" href="#" onclick="goToPage(${currentPage + 1}); return false;">Next</a></li>`;
    }

    pag.innerHTML = html;
  }

  window.goToPage = function(page) {
    currentPage = page;
    loadGenomes();
  };

  function initTableEvents() {
    if (!tableBody()) {
      console.log('[taxon-sync] Table not found, skipping table events');
      return;
    }

    let searchTimeout;
    const search = searchInput();
    if (search) {
      search.addEventListener("input", () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
          currentPage = 1;
          loadGenomes();
        }, 300);
      });
    }

    const status = statusFilter();
    if (status) {
      status.addEventListener("change", () => {
        currentPage = 1;
        loadGenomes();
      });
    }

    const colStatus = colStatusFilter();
    if (colStatus) {
      colStatus.addEventListener("change", () => {
        currentPage = 1;
        loadGenomes();
      });
    }
  }

  // ============================================
  // VIEW & EDIT MODALS
  // ============================================
  let currentViewAccession = null;
  let viewModal = null;
  let editModal = null;

  function initModals() {
    if (typeof bootstrap === 'undefined' || !bootstrap.Modal) {
      console.warn('[taxon-sync] Bootstrap Modal not available');
      return;
    }
    
    const viewEl = document.getElementById('viewGenomeModal');
    const editEl = document.getElementById('editGenomeModal');
    
    if (viewEl) {
      viewModal = new bootstrap.Modal(viewEl);
      
      // Forward to Edit button
      const viewToEditBtn = document.getElementById('viewToEditBtn');
      if (viewToEditBtn) {
        viewToEditBtn.addEventListener('click', function() {
          if (currentViewAccession) {
            viewModal.hide();
            editGenome(currentViewAccession);
          }
        });
      }
    }
    
    if (editEl) {
      editModal = new bootstrap.Modal(editEl);
    }

    // COL Search in Edit Modal — uses editSpeciesName as the search input
    const speciesNameInput = document.getElementById('editSpeciesName');
    const btnSearchCol = document.getElementById('btnSearchCol');
    
    if (speciesNameInput) {
      speciesNameInput.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') {
          e.preventDefault();
          const query = this.value.trim();
          if (query.length >= 2) searchCOLTaxa(query);
        }
      });
    }
    
    if (btnSearchCol) {
      btnSearchCol.addEventListener('click', function() {
        const query = speciesNameInput?.value.trim();
        if (query && query.length >= 2) searchCOLTaxa(query);
      });
    }

    const btnSearchGbif = document.getElementById('btnSearchGbif');
    if (btnSearchGbif) {
      btnSearchGbif.addEventListener('click', function() {
        const query = speciesNameInput?.value.trim();
        if (query && query.length >= 2) searchGBIFTaxa(query);
      });
    }
    
    // Listen for changes on tax fields to update counter
    document.querySelectorAll('.tax-field').forEach(input => {
      input.addEventListener('input', updateTaxFieldCount);
    });
    
    // Toggle label for extended ranks
    const extRanksEl = document.getElementById('extendedRanks');
    const toggleLabel = document.getElementById('toggleExtendedRanks');
    if (extRanksEl && toggleLabel) {
      extRanksEl.addEventListener('show.bs.collapse', () => {
        toggleLabel.querySelector('.ti').classList.replace('ti-chevron-down', 'ti-chevron-up');
        toggleLabel.childNodes[1].textContent = 'Hide extended ranks ';
      });
      extRanksEl.addEventListener('hide.bs.collapse', () => {
        toggleLabel.querySelector('.ti').classList.replace('ti-chevron-up', 'ti-chevron-down');
        toggleLabel.childNodes[1].textContent = 'Show all COL ranks ';
      });
    }
  }

  // Global functions
  window.viewGenome = async function(accession) {
    if (!viewModal) {
      Swal.fire({ icon: 'warning', text: 'Modal not available', confirmButtonColor: '#206bc4' });
      return;
    }

    currentViewAccession = accession;
    const body = document.getElementById('viewGenomeBody');
    body.innerHTML = '<div class="text-center py-5"><div class="spinner-border text-primary" role="status"></div></div>';
    viewModal.show();

    try {
      const endpoint = window.HOME_DATA?.endpoints?.genomeDetail || '/api/v1/taxonomy/genomes/';
      const resp = await fetch(`${endpoint}${accession}/`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      renderGenomeView(data);
    } catch (err) {
      console.error('Failed to load genome details:', err);
      body.innerHTML = '<div class="text-center py-5 text-danger">Failed to load genome details</div>';
    }
  };

  window.editGenome = async function(accession) {
    if (!editModal) {
      Swal.fire({ icon: 'warning', text: 'Modal not available', confirmButtonColor: '#206bc4' });
      return;
    }

    document.getElementById('editAccession').value = accession;
    document.getElementById('editAccessionDisplay').textContent = accession;
    editModal.show();

    try {
      const endpoint = window.HOME_DATA?.endpoints?.genomeDetail || '/api/v1/taxonomy/genomes/';
      const resp = await fetch(`${endpoint}${accession}/`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const data = await resp.json();
      populateEditForm(data);
    } catch (err) {
      console.error('Failed to load genome for editing:', err);
      showToast('Error', 'Failed to load genome data for editing', 'error');
    }
  };

  // ── helpers for external links ──
  function ncbiGenomeUrl(acc) { return `https://www.ncbi.nlm.nih.gov/datasets/genome/${acc}/`; }
  function ncbiTaxUrl(taxid) { return `https://www.ncbi.nlm.nih.gov/Taxonomy/Browser/wwwtax.cgi?id=${taxid}`; }
  function colSpeciesUrl(id)  { return `https://www.catalogueoflife.org/data/taxon/${id}`; }

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

  function renderGenomeView(g) {
    const body = document.getElementById('viewGenomeBody');
    const ext = g.external_taxon;
    const path = sortPath(ext?.classification_path || []);

    // ── Taxonomy rows (table grid, no pills/circles) ──
    const taxRows = path.map(p => {
      const r = (p.rank || '').toLowerCase();
      return `<tr>
        <td style="color:#888;width:35%;font-size:.8rem;text-transform:capitalize">${r}</td>
        <td class="fw-medium" style="font-size:.85rem">${p.name}</td>
      </tr>`;
    }).join('');

    // ── COL link ──
    const colLink = ext && ext.system === 'col' && ext.external_id
      ? `<a href="${colSpeciesUrl(ext.external_id)}" target="_blank" rel="noopener" class="btn btn-sm btn-outline-success"><i class="ti ti-external-link me-1"></i>COL</a>`
      : '';

    // ── Match indicator ──
    const matchIcon = g.col_match_status === 'matched' ? 'ti-link'
      : g.col_match_status === 'manual' ? 'ti-hand-stop'
      : 'ti-unlink';

    // ── Source note ──
    const sourceNote = ext
      ? (ext.system === 'manual'
          ? 'Taxonomy derived from genus sibling in COL'
          : `COL &middot; ${ext.status || ''}`)
      : '';

    // ── BUSCO ──
    const buscoHtml = g.busco_complete != null ? `
      <div class="col-12">
        <div class="border rounded">
          <div class="px-3 py-2 d-flex align-items-center justify-content-between" style="background:#f8f9fa;border-bottom:1px solid #e6e7e9;border-radius:.25rem .25rem 0 0">
            <span style="font-size:.8rem;font-weight:600"><i class="ti ti-chart-dots-3 me-1" style="font-size:.75rem;opacity:.5"></i>BUSCO Quality</span>
            ${g.busco_lineage ? `<span style="font-size:.75rem;color:#666">${g.busco_lineage}</span>` : ''}
          </div>
          <div class="px-3 py-2">
            <div class="d-flex align-items-center gap-2">
              <div class="progress flex-grow-1" style="height:8px;background:#e9ecef;border-radius:4px">
                <div class="progress-bar" role="progressbar" style="width:${g.busco_complete || 0}%;background:#5eba7d;border-radius:4px"></div>
              </div>
              <span style="font-size:.8rem;font-weight:500;min-width:70px;text-align:right">${g.busco_complete?.toFixed(1)}% complete</span>
            </div>
          </div>
        </div>
      </div>` : '';

    body.innerHTML = `
      <!-- Header -->
      <div style="background:#f8f9fa;border-bottom:1px solid #e6e7e9;padding:1.5rem 1.5rem 1rem;border-radius:.25rem .25rem 0 0;position:relative">
        <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close" style="position:absolute;top:1rem;right:1rem;opacity:.5"></button>
        <div style="font-size:.7rem;color:#888;text-transform:uppercase;letter-spacing:1px;margin-bottom:.25rem">Species Details</div>
        <h3 style="margin:0;font-weight:700;color:#1e293b">
          <em>${g.organism_name}</em>
        </h3>
        ${g.common_name ? `<div style="color:#666;font-size:.9rem;margin-top:.15rem">${g.common_name}</div>` : ''}
        <div style="margin-top:.75rem;display:flex;align-items:center;gap:.5rem;flex-wrap:wrap">
          <a href="${ncbiGenomeUrl(g.accession)}" target="_blank" rel="noopener" class="btn btn-sm btn-outline-primary"><i class="ti ti-external-link me-1"></i>${g.accession}</a>
          ${g.taxon ? `<a href="${ncbiTaxUrl(g.taxon.taxid)}" target="_blank" rel="noopener" class="btn btn-sm btn-outline-primary"><i class="ti ti-external-link me-1"></i>TaxID ${g.taxon.taxid}</a>` : ''}
          ${colLink}
          <span class="badge ${matchStatusBadge(g.col_match_status)}" style="font-size:.75rem">
            <i class="ti ${matchIcon}" style="font-size:.7rem"></i> ${matchStatusLabel(g.col_match_status)}
          </span>
        </div>
      </div>

      ${g.col_match_notes ? `<div style="background:#fffbe6;border-bottom:1px solid #f0e6b8;padding:.5rem 1.5rem;font-size:.8rem;color:#8a6d3b"><i class="ti ti-info-circle me-1"></i>${g.col_match_notes}</div>` : ''}

      <!-- Body sections -->
      <div class="p-3">
        <div class="row g-3">

          <!-- Taxonomy -->
          ${taxRows ? `
          <div class="col-12">
            <div class="border rounded">
              <div class="px-3 py-2 d-flex align-items-center justify-content-between" style="background:#f8f9fa;border-bottom:1px solid #e6e7e9;border-radius:.25rem .25rem 0 0">
                <span style="font-size:.8rem;font-weight:600"><i class="ti ti-hierarchy-2 me-1" style="font-size:.75rem;opacity:.5"></i>Taxonomy</span>
                ${sourceNote ? `<span style="font-size:.75rem;color:#888">${sourceNote}</span>` : ''}
              </div>
              <div class="px-3 py-2">
                <table class="table table-sm table-borderless mb-0">${taxRows}</table>
              </div>
            </div>
          </div>` : ''}
          <div class="col-md-6">
            <div class="border rounded h-100">
              <div class="px-3 py-2" style="background:#f8f9fa;border-bottom:1px solid #e6e7e9;border-radius:.25rem .25rem 0 0">
                <span style="font-size:.8rem;font-weight:600"><i class="ti ti-building-factory me-1" style="font-size:.75rem;opacity:.5"></i>Assembly</span>
              </div>
              <div class="px-3 py-2">
                <table class="table table-sm table-borderless mb-0" style="font-size:.85rem">
                  <tr><td style="color:#888;width:40%">Level</td><td class="fw-medium">${g.genome_level || '-'}</td></tr>
                  <tr><td style="color:#888">RefSeq</td><td>${g.refseq_category || '-'}</td></tr>
                  <tr><td style="color:#888">Source</td><td>${g.source_database || '-'}</td></tr>
                  <tr><td style="color:#888">Release</td><td>${g.release_date || '-'}</td></tr>
                  ${g.sequencing_tech ? `<tr><td style="color:#888">Sequencing</td><td>${g.sequencing_tech}</td></tr>` : ''}
                  ${g.assembly_method ? `<tr><td style="color:#888">Method</td><td>${g.assembly_method}</td></tr>` : ''}
                </table>
              </div>
            </div>
          </div>

          <!-- Quality -->
          <div class="col-md-6">
            <div class="border rounded h-100">
              <div class="px-3 py-2" style="background:#f8f9fa;border-bottom:1px solid #e6e7e9;border-radius:.25rem .25rem 0 0">
                <span style="font-size:.8rem;font-weight:600"><i class="ti ti-certificate me-1" style="font-size:.75rem;opacity:.5"></i>Quality</span>
              </div>
              <div class="px-3 py-2">
                <table class="table table-sm table-borderless mb-0" style="font-size:.85rem">
                  <tr><td style="color:#888;width:40%">Coverage</td><td>${g.genome_coverage ? g.genome_coverage.toFixed(1) + 'x' : '-'}</td></tr>
                  <tr><td style="color:#888">Score</td><td class="fw-medium">${g.quality_score?.toFixed(2) || '-'}</td></tr>
                  <tr><td style="color:#888">Contig N50</td><td>${g.contig_n50_kb ? g.contig_n50_kb.toFixed(1) + ' kb' : '-'}</td></tr>
                  <tr><td style="color:#888">Scaffold N50</td><td>${g.scaffold_n50_kb ? g.scaffold_n50_kb.toFixed(1) + ' kb' : '-'}</td></tr>
                </table>
              </div>
            </div>
          </div>

          <!-- Genome -->
          <div class="col-md-6">
            <div class="border rounded h-100">
              <div class="px-3 py-2" style="background:#f8f9fa;border-bottom:1px solid #e6e7e9;border-radius:.25rem .25rem 0 0">
                <span style="font-size:.8rem;font-weight:600"><i class="ti ti-circle-dashed me-1" style="font-size:.75rem;opacity:.5"></i>Genome</span>
              </div>
              <div class="px-3 py-2">
                <table class="table table-sm table-borderless mb-0" style="font-size:.85rem">
                  <tr><td style="color:#888;width:40%">Size</td><td class="fw-medium">${g.total_sequence_length ? (g.total_sequence_length / 1e6).toFixed(1) + ' Mb' : '-'}</td></tr>
                  <tr><td style="color:#888">GC</td><td>${g.gc_percent ? g.gc_percent.toFixed(1) + '%' : '-'}</td></tr>
                  <tr><td style="color:#888">Chromosomes</td><td>${g.chromosome_count || '-'}</td></tr>
                  <tr><td style="color:#888">Scaffolds</td><td>${g.scaffold_count || '-'}</td></tr>
                  <tr><td style="color:#888">Contigs</td><td>${g.contig_count || '-'}</td></tr>
                </table>
              </div>
            </div>
          </div>

          <!-- Genes -->
          <div class="col-md-6">
            <div class="border rounded h-100">
              <div class="px-3 py-2" style="background:#f8f9fa;border-bottom:1px solid #e6e7e9;border-radius:.25rem .25rem 0 0">
                <span style="font-size:.8rem;font-weight:600"><i class="ti ti-dna-2 me-1" style="font-size:.75rem;opacity:.5"></i>Genes</span>
              </div>
              <div class="px-3 py-2">
                <table class="table table-sm table-borderless mb-0" style="font-size:.85rem">
                  <tr><td style="color:#888;width:40%">Total</td><td class="fw-medium">${g.genes?.toLocaleString() || '-'}</td></tr>
                  <tr><td style="color:#888">Protein Coding</td><td>${g.protein_coding?.toLocaleString() || '-'}</td></tr>
                  <tr><td style="color:#888">Non-coding</td><td>${g.non_coding_genes?.toLocaleString() || '-'}</td></tr>
                  <tr><td style="color:#888">Pseudogenes</td><td>${g.pseudogenes?.toLocaleString() || '-'}</td></tr>
                  ${g.annotation_provider ? `<tr><td style="color:#888">Annotation</td><td>${g.annotation_provider}${g.annotation_status ? ' &middot; ' + g.annotation_status : ''}</td></tr>` : ''}
                </table>
              </div>
            </div>
          </div>

          ${buscoHtml}

          ${g.has_proteome ? `
          <div class="col-12">
            <div class="border rounded">
              <div class="px-3 py-2 d-flex align-items-center justify-content-between" style="background:#f8f9fa;border-bottom:1px solid #e6e7e9;border-radius:.25rem .25rem 0 0">
                <span style="font-size:.8rem;font-weight:600"><i class="ti ti-atom me-1" style="font-size:.75rem;opacity:.5"></i>Proteome</span>
              </div>
              <div class="px-3 py-2" style="font-size:.85rem">${g.proteome_quality || 'Available'}</div>
            </div>
          </div>` : ''}

        </div>
      </div>
    `;
  }

  // Helper: count filled taxonomy fields and update badge
  function updateTaxFieldCount() {
    const all = document.querySelectorAll('.tax-field');
    const ext = document.querySelectorAll('.tax-ext');
    let total = 0, extFilled = 0;
    all.forEach(i => { if (i.value.trim()) total++; });
    ext.forEach(i => { if (i.value.trim()) extFilled++; });
    
    const badge = document.getElementById('taxFieldCount');
    if (badge) badge.textContent = `${total} filled`;
    
    const extLabel = document.getElementById('extRankFilled');
    if (extLabel) extLabel.textContent = extFilled ? `(${extFilled} filled)` : '';
    
    // Auto-expand extended section if any extended field has data
    if (extFilled > 0) {
      const extRanksEl = document.getElementById('extendedRanks');
      if (extRanksEl && !extRanksEl.classList.contains('show')) {
        new bootstrap.Collapse(extRanksEl, { toggle: true });
      }
    }
  }

  function populateEditForm(data) {
    document.getElementById('editOrganismName').textContent = data.organism_name || '-';
    document.getElementById('editAccessionDisplay').textContent = data.accession || '-';
    document.getElementById('editMatchNotes').value = data.col_match_notes || '';
    
    // Species name = search input (unified)
    document.getElementById('editSpeciesName').value =
      (data.taxon?.scientific_name) || data.organism_name || '';
    
    // Current match badge in header
    const matchBadge = document.getElementById('currentMatchBadge');
    if (matchBadge) {
      matchBadge.innerHTML = `<span class="badge ${matchStatusBadge(data.col_match_status)}">${matchStatusLabel(data.col_match_status)}</span>`;
    }
    
    // Fill ALL taxonomy fields from external_taxon classification or genome
    const cls = data.external_taxon?.classification || {};
    document.querySelectorAll('.tax-field').forEach(input => {
      const rank = input.dataset.rank;
      let val = cls[rank] || '';
      if (!val && rank === 'phylum') val = data.phylum || '';
      if (!val && rank === 'class') val = data.class_name || '';
      input.value = val;
    });
    
    // Update counter
    updateTaxFieldCount();
    
    // Show current COL match if exists
    const currentMatchSection = document.getElementById('currentMatchSection');
    const currentMatchInfo = document.getElementById('currentMatchInfo');
    
    if (data.external_taxon) {
      const ext = data.external_taxon;
      const pathStr = sortPath(ext.classification_path || []).map(p => p.name).join(' > ') || 'No classification';
      currentMatchInfo.innerHTML = `
        <div class="d-flex align-items-center">
          <div class="flex-grow-1">
            <div class="fw-bold text-success">${ext.name}</div>
            <div class="small text-muted">${pathStr}</div>
            <div class="small">Status: <span class="badge ${colStatusBadge(ext.status)}">${ext.status}</span></div>
          </div>
          <button type="button" class="btn btn-sm btn-ghost-danger" onclick="clearCurrentMatch()">
            <i class="ti ti-x"></i> Remove
          </button>
        </div>
      `;
      currentMatchInfo.className = 'alert alert-success mb-0 py-2';
      currentMatchSection.style.display = 'block';
    } else {
      currentMatchSection.style.display = 'none';
    }
    
    // Clear search results and selection
    document.getElementById('colSearchResults').innerHTML = '';
    document.getElementById('selectedColSection').style.display = 'none';
    document.getElementById('selectedColId').value = '';
  }

  async function searchCOLTaxa(query) {
    const results = document.getElementById('colSearchResults');
    if (!results) return;
    results.innerHTML = '<div class="list-group-item text-muted"><i class="ti ti-loader ti-spin me-1"></i>Searching COL...</div>';
    try {
      const endpoint = window.HOME_DATA?.endpoints?.colSearch || '/api/v1/taxonomy/col/search/';
      const resp = await fetch(`${endpoint}?q=${encodeURIComponent(query)}`);
      const data = await resp.json();
      
      if (data.results && data.results.length > 0) {
        results.innerHTML = data.results.map(r => {
          const rawJson = JSON.stringify(r.classification_raw || {}).replace(/'/g, "\\'").replace(/"/g, '&quot;');
          return `
          <a href="#" class="list-group-item list-group-item-action" 
             onclick="selectCOLTaxon(${r.id}, '${r.name.replace(/'/g, "\\'")}', '${(r.classification || '').replace(/'/g, "\\'")}', '${rawJson}'); return false;">
            <div class="d-flex w-100 justify-content-between">
              <h6 class="mb-1">${r.name} <span class="badge bg-primary-lt ms-1">COL</span></h6>
              <small class="text-success">${r.status || 'accepted'}</small>
            </div>
            <p class="mb-1 small text-muted">${r.classification || ''}</p>
          </a>
        `}).join('');
      } else {
        results.innerHTML = '<div class="list-group-item text-muted">No results found in COL</div>';
      }
    } catch (err) {
      console.error('COL search failed:', err);
      results.innerHTML = '<div class="list-group-item text-danger">COL search failed</div>';
    }
  }

  async function searchGBIFTaxa(query) {
    const results = document.getElementById('colSearchResults');
    if (!results) return;
    results.innerHTML = '<div class="list-group-item text-muted"><i class="ti ti-loader ti-spin me-1"></i>Searching GBIF...</div>';
    try {
      const endpoint = window.HOME_DATA?.endpoints?.gbifSearch || '/api/v1/taxonomy/gbif/search/';
      const resp = await fetch(`${endpoint}?q=${encodeURIComponent(query)}`);
      const data = await resp.json();

      if (data.error) throw new Error(data.error);

      if (data.results && data.results.length > 0) {
        results.innerHTML = data.results.map(r => {
          const rawJson = JSON.stringify(r.classification_raw || {}).replace(/'/g, "\\'").replace(/"/g, '&quot;');
          return `
          <a href="#" class="list-group-item list-group-item-action" 
             onclick="selectGBIFTaxon('${r.name.replace(/'/g, "\\'")}', '${(r.classification || '').replace(/'/g, "\\'")}', '${rawJson}'); return false;">
            <div class="d-flex w-100 justify-content-between">
              <h6 class="mb-1">${r.name} <span class="badge bg-lime-lt ms-1">GBIF</span></h6>
              <small class="text-${r.status === 'accepted' ? 'success' : 'info'}">${r.status || 'accepted'}</small>
            </div>
            <p class="mb-1 small text-muted">${r.classification || ''}</p>
          </a>
        `}).join('');
      } else {
        results.innerHTML = '<div class="list-group-item text-muted">No results found in GBIF</div>';
      }
    } catch (err) {
      console.error('GBIF search failed:', err);
      results.innerHTML = '<div class="list-group-item text-danger">GBIF search failed: ' + err.message + '</div>';
    }
  }

  window.selectCOLTaxon = function(id, name, classification, classificationRawStr) {
    document.getElementById('selectedColId').value = id;
    document.getElementById('selectedColName').textContent = name;
    document.getElementById('selectedColClassification').textContent = classification || 'No classification available';
    document.getElementById('selectedColSection').style.display = 'block';
    document.getElementById('colSearchResults').innerHTML = '';
    
    // Fill ALL taxonomy fields from COL classification
    try {
      const raw = typeof classificationRawStr === 'string'
        ? JSON.parse(classificationRawStr.replace(/&quot;/g, '"'))
        : classificationRawStr || {};
      document.querySelectorAll('.tax-field').forEach(input => {
        const rank = input.dataset.rank;
        if (raw[rank]) input.value = raw[rank];
      });
      updateTaxFieldCount();
    } catch (e) {
      console.warn('Could not parse COL classification:', e);
    }
  };

  // Select a GBIF result — fills taxonomy but does NOT set a COL external_taxon_id
  window.selectGBIFTaxon = function(name, classification, classificationRawStr) {
    // Clear any COL selection (GBIF is taxonomy-only, not a COL link)
    document.getElementById('selectedColId').value = '';
    document.getElementById('selectedColSection').style.display = 'none';
    document.getElementById('colSearchResults').innerHTML = '';

    // Fill taxonomy fields from GBIF data
    try {
      const raw = typeof classificationRawStr === 'string'
        ? JSON.parse(classificationRawStr.replace(/&quot;/g, '"'))
        : classificationRawStr || {};
      document.querySelectorAll('.tax-field').forEach(input => {
        const rank = input.dataset.rank;
        if (raw[rank]) input.value = raw[rank];
      });
      updateTaxFieldCount();
    } catch (e) {
      console.warn('Could not parse GBIF classification:', e);
    }

    showToast('GBIF', `Taxonomy filled from GBIF for "${name}"`, 'success');
  };

  window.clearColSelection = function() {
    document.getElementById('selectedColSection').style.display = 'none';
    document.getElementById('selectedColId').value = '';
  };

  window.clearCurrentMatch = function() {
    const currentMatchInfo = document.getElementById('currentMatchInfo');
    currentMatchInfo.innerHTML = '<span class="text-muted">No COL match</span>';
    currentMatchInfo.className = 'alert alert-light';
  };

  window.saveGenomeMatch = async function() {
    const accession = document.getElementById('editAccession').value;
    const colId = document.getElementById('selectedColId').value;
    const speciesName = document.getElementById('editSpeciesName').value.trim();
    const notes = document.getElementById('editMatchNotes').value;
    
    if (!accession) {
      Swal.fire({ icon: 'warning', text: 'No genome selected for editing', confirmButtonColor: '#206bc4' });
      return;
    }

    // Build taxonomy from ALL form inputs dynamically
    const taxonomy = {};
    document.querySelectorAll('.tax-field').forEach(input => {
      const val = input.value.trim();
      if (val) taxonomy[input.dataset.rank] = val;
    });

    try {
      const endpoint = window.HOME_DATA?.endpoints?.genomeUpdate || '/api/v1/taxonomy/genomes/';
      const resp = await fetch(`${endpoint}${accession}/update/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCsrfToken()
        },
        body: JSON.stringify({
          species_name: speciesName || null,
          external_taxon_id: colId ? parseInt(colId) : null,
          taxonomy: taxonomy,
          col_match_notes: notes
        })
      });

      if (!resp.ok) {
        const errData = await resp.json().catch(() => ({}));
        throw new Error(errData.error || `HTTP ${resp.status}`);
      }
      
      showToast('Success', 'Manual COL match saved', 'success');
      editModal.hide();
      loadGenomes(); // Refresh table
    } catch (err) {
      console.error('Failed to save manual match:', err);
      showToast('Error', `Failed to save: ${err.message}`, 'error');
    }
  };

  // ============================================
  // TAB EVENTS
  // ============================================
  function initTabEvents() {
    let speciesListLoaded = false;
    
    // Always try to load on initialization if tab exists
    const speciesTab = document.getElementById('tab-species');
    if (speciesTab) {
      console.log('[taxon-sync] Species tab found, loading data...');
      loadGenomes();
      speciesListLoaded = true;
    }
    
    // Load when tab becomes visible
    document.querySelectorAll('[data-bs-toggle="tab"]').forEach(tab => {
      tab.addEventListener('shown.bs.tab', function(e) {
        console.log('[taxon-sync] Tab shown:', e.target.getAttribute('href'));
        if (e.target.getAttribute('href') === '#tab-species' && !speciesListLoaded) {
          loadGenomes();
          speciesListLoaded = true;
        }
      });
    });
    
    // Also try with click events
    document.querySelectorAll('a[href="#tab-species"]').forEach(tab => {
      tab.addEventListener('click', function() {
        console.log('[taxon-sync] Species tab clicked');
        setTimeout(() => {
          loadGenomes();
        }, 100);
      });
    });
  }

  // ============================================
  // INIT
  // ============================================
  document.addEventListener("DOMContentLoaded", function() {
    initTableEvents();
    initTabEvents();
    initModals();
  });

  // Export for external access
  window.TaxonSyncSpeciesModule = {
    loadGenomes: loadGenomes
  };

})();