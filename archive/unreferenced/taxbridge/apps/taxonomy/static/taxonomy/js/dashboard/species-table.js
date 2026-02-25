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
      console.log(`${title}: ${message}`);
    } else {
      alert(`${title}: ${message}`);
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
      "needs_review": "bg-red-lt text-red",
      "no_match": "bg-red-lt text-red"
    };
    return badges[status] || "bg-secondary-lt text-secondary";
  }

  function colStatusBadge(status) {
    const badges = {
      "accepted": "bg-green-lt text-green",
      "synonym": "bg-blue-lt text-blue",
      "misapplied": "bg-yellow-lt text-yellow",
      "unknown": "bg-secondary-lt text-secondary"
    };
    return badges[status] || "bg-secondary-lt text-secondary";
  }

  function matchStatusLabel(status) {
    const labels = {
      "matched": "Linked",
      "unmatched": "Unlinked", 
      "needs_review": "Review",
      "no_match": "Review"
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
            ${g.col_status || '-'}
          </span>
        </td>
        ${isAdmin ? `
        <td>
          <div class="btn-list">
            <button class="btn btn-sm btn-ghost-primary" onclick="viewGenome('${g.accession}')" title="View details">
              <i class="ti ti-eye"></i>
            </button>
            <button class="btn btn-sm btn-ghost-secondary" onclick="editGenome('${g.accession}')" title="Edit COL match">
              <i class="ti ti-edit"></i>
            </button>
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

    // COL Search in Edit Modal
    const colSearchInput = document.getElementById('colSearchInput');
    if (colSearchInput) {
      colSearchInput.addEventListener('input', function() {
        const query = this.value.trim();
        if (query.length >= 3) {
          searchCOLTaxa(query);
        } else {
          document.getElementById('colSearchResults').innerHTML = '';
        }
      });
    }
  }

  // Global functions
  window.viewGenome = async function(accession) {
    if (!viewModal) {
      alert('Modal not available');
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
      alert('Modal not available');
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

  function renderGenomeView(g) {
    const body = document.getElementById('viewGenomeBody');

    const buscoHtml = g.busco_complete ? `
      <div class="col-12">
        <div class="card">
          <div class="card-header"><h4 class="card-title">BUSCO Quality</h4></div>
          <div class="card-body">
            <div class="row">
              <div class="col-6 col-md-2 text-center">
                <div class="h3 text-success">${g.busco_complete?.toFixed(1) || '-'}%</div>
                <div class="text-muted small">Complete</div>
              </div>
              <div class="col-6 col-md-2 text-center">
                <div class="h3 text-primary">${g.busco_single_copy?.toFixed(1) || '-'}%</div>
                <div class="text-muted small">Single Copy</div>
              </div>
              <div class="col-6 col-md-2 text-center">
                <div class="h3 text-info">${g.busco_duplicated?.toFixed(1) || '-'}%</div>
                <div class="text-muted small">Duplicated</div>
              </div>
              <div class="col-6 col-md-2 text-center">
                <div class="h3 text-warning">${g.busco_fragmented?.toFixed(1) || '-'}%</div>
                <div class="text-muted small">Fragmented</div>
              </div>
              <div class="col-6 col-md-2 text-center">
                <div class="h3 text-danger">${g.busco_missing?.toFixed(1) || '-'}%</div>
                <div class="text-muted small">Missing</div>
              </div>
              <div class="col-6 col-md-2 text-center">
                <div class="h6">${g.busco_lineage || '-'}</div>
                <div class="text-muted small">Lineage</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    ` : '';

    const colHtml = g.external_taxon ? `
      <div class="alert alert-success">
        <div class="d-flex align-items-center">
          <i class="ti ti-check me-2"></i>
          <div class="flex-grow-1">
            <div class="fw-bold">${g.external_taxon.name}</div>
            <div class="small text-muted">
              ${g.external_taxon.classification_path?.map(p => p.name).join(' > ') || 'Classification not available'}
            </div>
            <div class="small">
              <span class="badge bg-${g.external_taxon.status === 'accepted' ? 'green' : 'blue'}-lt">
                ${g.external_taxon.status}
              </span>
              <span class="text-muted ms-2">ID: ${g.external_taxon.external_id}</span>
            </div>
          </div>
        </div>
      </div>
    ` : `
      <div class="alert alert-${g.col_match_status === 'no_match' ? 'danger' : 'warning'}">
        <i class="ti ti-alert-triangle me-2"></i>
        ${g.col_match_status === 'no_match' ? 'No match found in Catalogue of Life' : 'Not linked to Catalogue of Life'}
      </div>
    `;

    body.innerHTML = `
      <div class="row g-3">
        <div class="col-12">
          <div class="d-flex align-items-center mb-3">
            <div class="flex-grow-1">
              <h3 class="mb-0">${g.organism_name}</h3>
              ${g.common_name ? `<div class="text-muted">${g.common_name}</div>` : ''}
            </div>
            <div class="text-end">
              <div><code class="fs-5">${g.accession}</code></div>
              <span class="badge ${matchStatusBadge(g.col_match_status)}">${matchStatusLabel(g.col_match_status)}</span>
            </div>
          </div>
        </div>

        <div class="col-12">
          <div class="card">
            <div class="card-header">
              <h4 class="card-title"><i class="ti ti-tree me-2"></i>Catalogue of Life</h4>
            </div>
            <div class="card-body">
              ${colHtml}
              ${g.col_match_notes ? `<div class="mt-2 text-muted small"><strong>Notes:</strong> ${g.col_match_notes}</div>` : ''}
            </div>
          </div>
        </div>

        <div class="col-md-6">
          <div class="card h-100">
            <div class="card-header"><h4 class="card-title">NCBI Taxonomy</h4></div>
            <div class="card-body">
              ${g.taxon ? `
                <div><strong>Tax ID:</strong> ${g.taxon.taxid}</div>
                <div><strong>Name:</strong> ${g.taxon.scientific_name}</div>
                <div><strong>Rank:</strong> ${g.taxon.rank}</div>
              ` : '<span class="text-muted">No NCBI taxon linked</span>'}
            </div>
          </div>
        </div>

        <div class="col-md-6">
          <div class="card h-100">
            <div class="card-header"><h4 class="card-title">Assembly Info</h4></div>
            <div class="card-body">
              <div class="row">
                <div class="col-6">
                  <div class="text-muted small">Level</div>
                  <div><span class="badge ${genomeLevelBadge(g.genome_level)}">${g.genome_level || '-'}</span></div>
                </div>
                <div class="col-6">
                  <div class="text-muted small">RefSeq Category</div>
                  <div>${g.refseq_category || '-'}</div>
                </div>
                <div class="col-6 mt-2">
                  <div class="text-muted small">Source</div>
                  <div>${g.source_database || '-'}</div>
                </div>
                <div class="col-6 mt-2">
                  <div class="text-muted small">Release Date</div>
                  <div>${g.release_date || '-'}</div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="col-md-6">
          <div class="card h-100">
            <div class="card-header"><h4 class="card-title">Quality Metrics</h4></div>
            <div class="card-body">
              <div class="row">
                <div class="col-6">
                  <div class="text-muted small">Quality Score</div>
                  <div class="fw-bold">${g.quality_score?.toFixed(2) || '-'}</div>
                </div>
                <div class="col-6">
                  <div class="text-muted small">Coverage</div>
                  <div>${g.genome_coverage ? g.genome_coverage.toFixed(1) + 'x' : '-'}</div>
                </div>
                <div class="col-6 mt-2">
                  <div class="text-muted small">Contig N50</div>
                  <div>${g.contig_n50_kb ? g.contig_n50_kb.toFixed(1) + ' kb' : '-'}</div>
                </div>
                <div class="col-6 mt-2">
                  <div class="text-muted small">Scaffold N50</div>
                  <div>${g.scaffold_n50_kb ? g.scaffold_n50_kb.toFixed(1) + ' kb' : '-'}</div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="col-md-6">
          <div class="card h-100">
            <div class="card-header"><h4 class="card-title">Genome Statistics</h4></div>
            <div class="card-body">
              <div class="row">
                <div class="col-6">
                  <div class="text-muted small">Size</div>
                  <div>${g.total_sequence_length ? (g.total_sequence_length / 1e6).toFixed(1) + ' Mb' : '-'}</div>
                </div>
                <div class="col-6">
                  <div class="text-muted small">GC Content</div>
                  <div>${g.gc_percent ? g.gc_percent.toFixed(1) + '%' : '-'}</div>
                </div>
                <div class="col-4 mt-2">
                  <div class="text-muted small">Chromosomes</div>
                  <div>${g.chromosome_count || '-'}</div>
                </div>
                <div class="col-4 mt-2">
                  <div class="text-muted small">Scaffolds</div>
                  <div>${g.scaffold_count || '-'}</div>
                </div>
                <div class="col-4 mt-2">
                  <div class="text-muted small">Contigs</div>
                  <div>${g.contig_count || '-'}</div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="col-md-6">
          <div class="card h-100">
            <div class="card-header"><h4 class="card-title">Gene Annotation</h4></div>
            <div class="card-body">
              <div class="row">
                <div class="col-6">
                  <div class="text-muted small">Total Genes</div>
                  <div class="fw-bold">${g.genes?.toLocaleString() || '-'}</div>
                </div>
                <div class="col-6">
                  <div class="text-muted small">Protein Coding</div>
                  <div>${g.protein_coding?.toLocaleString() || '-'}</div>
                </div>
                <div class="col-6 mt-2">
                  <div class="text-muted small">Non-coding</div>
                  <div>${g.non_coding_genes?.toLocaleString() || '-'}</div>
                </div>
                <div class="col-6 mt-2">
                  <div class="text-muted small">Pseudogenes</div>
                  <div>${g.pseudogenes?.toLocaleString() || '-'}</div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div class="col-md-6">
          <div class="card h-100">
            <div class="card-header"><h4 class="card-title">Protein Coding</h4></div>
            <div class="card-body">
              ${g.protein_coding 
                ? `<span class="badge bg-blue-lt text-blue">${g.protein_coding.toLocaleString()}</span>`
                : '<span class="badge bg-secondary-lt">Not available</span>'
              }
            </div>
          </div>
        </div>

        ${buscoHtml}
      </div>
    `;
  }

  function populateEditForm(data) {
    document.getElementById('editOrganismName').textContent = data.organism_name || '-';
    document.getElementById('editMatchStatus').value = data.col_match_status || 'unmatched';
    document.getElementById('editMatchNotes').value = data.col_match_notes || '';
    
    // Show current COL match if exists
    const currentMatchSection = document.getElementById('currentMatchSection');
    const currentMatchInfo = document.getElementById('currentMatchInfo');
    
    if (data.col_taxon_name) {
      currentMatchInfo.innerHTML = `
        <div class="d-flex align-items-center">
          <div class="flex-grow-1">
            <div class="fw-bold text-success">${data.col_taxon_name}</div>
            <div class="small text-muted">${data.col_classification || 'No classification'}</div>
            <div class="small">Status: <span class="badge ${colStatusBadge(data.col_status)}">${data.col_status}</span></div>
          </div>
          <button type="button" class="btn btn-sm btn-ghost-danger" onclick="clearCurrentMatch()">
            <i class="ti ti-x"></i> Remove
          </button>
        </div>
      `;
      currentMatchInfo.className = 'alert alert-success';
    } else {
      currentMatchInfo.innerHTML = '<span class="text-muted">No COL match</span>';
      currentMatchInfo.className = 'alert alert-light';
    }
    
    // Clear search
    document.getElementById('colSearchInput').value = data.organism_name || '';
    document.getElementById('colSearchResults').innerHTML = '';
    document.getElementById('selectedColSection').style.display = 'none';
  }

  async function searchCOLTaxa(query) {
    try {
      const endpoint = window.HOME_DATA?.endpoints?.colSearch || '/api/v1/taxonomy/col/search/';
      const resp = await fetch(`${endpoint}?q=${encodeURIComponent(query)}`);
      const data = await resp.json();
      
      const results = document.getElementById('colSearchResults');
      if (!results) return;
      
      if (data.results && data.results.length > 0) {
        results.innerHTML = data.results.map(r => `
          <a href="#" class="list-group-item list-group-item-action" onclick="selectCOLTaxon('${r.id}', '${r.name}', '${r.classification || ''}'); return false;">
            <div class="d-flex w-100 justify-content-between">
              <h6 class="mb-1">${r.name}</h6>
              <small class="text-success">${r.status || 'accepted'}</small>
            </div>
            <p class="mb-1 small text-muted">${r.classification || ''}</p>
          </a>
        `).join('');
      } else {
        results.innerHTML = '<div class="list-group-item text-muted">No results found</div>';
      }
    } catch (err) {
      console.error('COL search failed:', err);
      document.getElementById('colSearchResults').innerHTML = '<div class="list-group-item text-danger">Search failed</div>';
    }
  }

  window.selectCOLTaxon = function(id, name, classification) {
    document.getElementById('selectedColId').value = id;
    document.getElementById('selectedColName').textContent = name;
    document.getElementById('selectedColClassification').textContent = classification || 'No classification available';
    document.getElementById('selectedColSection').style.display = 'block';
    document.getElementById('colSearchResults').innerHTML = '';
    document.getElementById('editMatchStatus').value = 'matched';
  };

  window.clearColSelection = function() {
    document.getElementById('selectedColSection').style.display = 'none';
    document.getElementById('selectedColId').value = '';
    document.getElementById('editMatchStatus').value = 'unmatched';
  };

  window.clearCurrentMatch = function() {
    const currentMatchInfo = document.getElementById('currentMatchInfo');
    currentMatchInfo.innerHTML = '<span class="text-muted">No COL match</span>';
    currentMatchInfo.className = 'alert alert-light';
  };

  window.saveGenomeMatch = async function() {
    const accession = document.getElementById('editAccession').value;
    const colId = document.getElementById('selectedColId').value;
    const matchStatus = document.getElementById('editMatchStatus').value;
    const notes = document.getElementById('editMatchNotes').value;
    
    if (!accession) {
      alert('No genome selected for editing');
      return;
    }

    try {
      const endpoint = window.HOME_DATA?.endpoints?.genomeUpdate || '/api/v1/taxonomy/genomes/';
      const resp = await fetch(`${endpoint}${accession}/`, {
        method: 'PATCH',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCsrfToken()
        },
        body: JSON.stringify({
          col_taxon_id: colId || null,
          col_match_status: matchStatus,
          col_match_notes: notes
        })
      });

      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      
      showToast('Success', 'COL match updated successfully', 'success');
      editModal.hide();
      loadGenomes(); // Refresh table
    } catch (err) {
      console.error('Failed to save genome match:', err);
      showToast('Error', 'Failed to save COL match', 'error');
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