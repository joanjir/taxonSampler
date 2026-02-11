// taxonomy/static/taxonomy/js/pages/home.js
// Dashboard page JavaScript - Charts, Table, and Modals

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
  // CHARTS
  // ============================================
  function initAssemblyProgressBar() {
    const genomeLevelData = window.HOME_DATA?.genomeLevels || [];
    if (!genomeLevelData.length) return;

    const levelColors = {
      "Complete Genome": "bg-success",
      "Chromosome": "bg-primary",
      "Scaffold": "bg-warning",
      "Contig": "bg-secondary",
      "Unspecified": "bg-muted"
    };
    
    const total = genomeLevelData.reduce((sum, d) => sum + d.value, 0);
    const progressBar = document.getElementById("assemblyProgressBar");
    const legend = document.getElementById("assemblyLegend");
    
    if (progressBar && legend && total > 0) {
      progressBar.innerHTML = genomeLevelData.map(d => {
        const pct = (d.value / total * 100).toFixed(1);
        const colorClass = levelColors[d.label] || "bg-secondary";
        return `<div class="progress-bar ${colorClass}" role="progressbar" style="width: ${pct}%" aria-label="${d.label}"></div>`;
      }).join('');
      
      legend.innerHTML = genomeLevelData.map(d => {
        const colorClass = levelColors[d.label] || "bg-secondary";
        return `<div class="d-flex align-items-center">
          <span class="${colorClass} me-2" style="width: 12px; height: 12px; display: inline-block; border-radius: 2px;"></span>
          <span class="text-secondary small">${d.label}</span>
          <span class="ms-1 fw-bold">${d.value}</span>
        </div>`;
      }).join('');
    }
  }

  function initPhylaChart() {
    const phylaData = window.HOME_DATA?.phylaStats || [];
    const chartEl = document.getElementById("chartPhyla");
    
    if (!chartEl) return;
    
    if (!phylaData.length) {
      chartEl.innerHTML = '<div class="text-muted text-center py-5">No data</div>';
      return;
    }

    phylaData.sort((a, b) => b.value - a.value);
    
    const phylaColors = [
      "#206bc4", "#2fb344", "#f59f00", "#d63939", "#ae3ec9",
      "#17a2b8", "#fd7e14", "#6f42c1", "#20c997", "#e83e8c",
      "#6c757d", "#0dcaf0", "#198754", "#ffc107", "#dc3545"
    ];
    
    new ApexCharts(chartEl, {
      chart: {
        type: "bar",
        height: 300,
        fontFamily: "inherit",
        toolbar: { show: false }
      },
      series: [{
        name: "Species",
        data: phylaData.map(d => d.value)
      }],
      plotOptions: {
        bar: {
          horizontal: true,
          borderRadius: 4,
          distributed: true,
          dataLabels: { position: "top" }
        }
      },
      dataLabels: { enabled: false },
      xaxis: {
        categories: phylaData.map(d => d.label),
        labels: { style: { fontSize: "11px" } }
      },
      yaxis: {
        labels: { style: { fontSize: "11px" } }
      },
      colors: phylaColors,
      legend: { show: false },
      tooltip: {
        y: {
          formatter: function(val) { return val + " species"; }
        }
      }
    }).render();
  }

  // ============================================
  // TABLE
  // ============================================
  let currentPage = 1;
  const pageSize = 50;
  
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
      tbody.innerHTML = '<tr><td colspan="9" class="text-center text-muted py-4">Loading...</td></tr>';
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
      console.error("Error loading genomes:", err);
      const tbody = tableBody();
      if (tbody) {
        tbody.innerHTML = '<tr><td colspan="8" class="text-center text-danger py-4">Error loading data</td></tr>';
      }
    }
  }

  function renderTable(genomes) {
    const tbody = tableBody();
    if (!tbody) return;
    
    if (!genomes.length) {
      tbody.innerHTML = '<tr><td colspan="8" class="text-center text-muted py-4">No genomes found</td></tr>';
      return;
    }

    tbody.innerHTML = genomes.map(g => `
      <tr>
        <td><code class="small">${g.accession}</code></td>
        <td><strong>${g.organism_name || '-'}</strong></td>
        <td><span class="badge ${genomeLevelBadge(g.genome_level)}">${g.genome_level || '-'}</span></td>
        <td>${g.genes || '-'}</td>
        <td>
          ${g.has_proteome 
            ? `<span class="badge bg-green-lt text-green"><i class="ti ti-check me-1"></i>${g.proteome_quality || 'Yes'}</span>`
            : '<span class="badge bg-secondary-lt text-secondary">No</span>'
          }
        </td>
        <td>
          <span class="badge ${matchStatusBadge(g.col_match_status)}">
            ${matchStatusLabel(g.col_match_status)}
          </span>
        </td>
        <td>
          ${g.col_status 
            ? `<span class="badge ${colStatusBadge(g.col_status)}">${g.col_status}</span>`
            : (g.col_match_status === 'no_match' 
                ? '<span class="badge bg-red-lt text-red"><i class="ti ti-x me-1"></i>Not in COL</span>'
                : '-')
          }
        </td>
        <td>
          <div class="btn-list">
            <button class="btn btn-sm btn-ghost-secondary" onclick="viewGenome('${g.accession}')" title="View details">
              <i class="ti ti-eye"></i>
            </button>
            <button class="btn btn-sm btn-ghost-primary" onclick="editGenome('${g.accession}')" title="Edit COL match">
              <i class="ti ti-edit"></i>
            </button>
          </div>
        </td>
      </tr>
    `).join("");
  }

  function renderPagination(total) {
    const pag = pagination();
    if (!pag) return;
    
    const totalPages = Math.ceil(total / pageSize);
    if (totalPages <= 1) {
      pag.innerHTML = "";
      return;
    }

    let html = "";
    
    html += `<li class="page-item ${currentPage <= 1 ? 'disabled' : ''}">
      <a class="page-link" href="#" data-page="${currentPage - 1}">&laquo;</a>
    </li>`;

    const start = Math.max(1, currentPage - 2);
    const end = Math.min(totalPages, currentPage + 2);
    
    for (let i = start; i <= end; i++) {
      html += `<li class="page-item ${i === currentPage ? 'active' : ''}">
        <a class="page-link" href="#" data-page="${i}">${i}</a>
      </li>`;
    }

    html += `<li class="page-item ${currentPage >= totalPages ? 'disabled' : ''}">
      <a class="page-link" href="#" data-page="${currentPage + 1}">&raquo;</a>
    </li>`;

    pag.innerHTML = html;
  }

  function initTableEvents() {
    const pag = pagination();
    if (pag) {
      pag.addEventListener("click", (e) => {
        if (e.target.matches(".page-link")) {
          e.preventDefault();
          const page = parseInt(e.target.dataset.page);
          if (page && page !== currentPage) {
            currentPage = page;
            loadGenomes();
          }
        }
      });
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
    const viewEl = document.getElementById('viewGenomeModal');
    const editEl = document.getElementById('editGenomeModal');
    
    if (viewEl) viewModal = new bootstrap.Modal(viewEl);
    if (editEl) editModal = new bootstrap.Modal(editEl);
    
    // View to Edit button
    const viewToEditBtn = document.getElementById('viewToEditBtn');
    if (viewToEditBtn) {
      viewToEditBtn.addEventListener('click', function() {
        if (viewModal) viewModal.hide();
        if (currentViewAccession) {
          window.editGenome(currentViewAccession);
        }
      });
    }
    
    // COL Search
    let colSearchTimeout;
    const colSearchInput = document.getElementById('colSearchInput');
    if (colSearchInput) {
      colSearchInput.addEventListener('input', function() {
        clearTimeout(colSearchTimeout);
        const query = this.value.trim();
        
        if (query.length < 2) {
          document.getElementById('colSearchResults').innerHTML = '';
          return;
        }
        
        colSearchTimeout = setTimeout(async () => {
          try {
            const endpoint = window.HOME_DATA?.endpoints?.colSearch || '/api/v1/taxonomy/col/search/';
            const resp = await fetch(`${endpoint}?q=${encodeURIComponent(query)}`);
            const data = await resp.json();
            
            if (data.results.length === 0) {
              document.getElementById('colSearchResults').innerHTML = `
                <div class="list-group-item text-muted text-center">No results found</div>
              `;
              return;
            }
            
            document.getElementById('colSearchResults').innerHTML = data.results.map(r => `
              <a href="#" class="list-group-item list-group-item-action" onclick="selectColTaxon(${r.id}, '${r.name.replace(/'/g, "\\'")}', '${r.classification.replace(/'/g, "\\'")}', '${r.status}'); return false;">
                <div class="d-flex align-items-center">
                  <span class="badge bg-${r.status === 'accepted' ? 'green' : 'blue'}-lt me-2">${r.status}</span>
                  <div>
                    <div class="fw-bold">${r.name}</div>
                    <div class="small text-muted">${r.classification}</div>
                    ${r.accepted_name ? `<div class="small text-info">→ ${r.accepted_name}</div>` : ''}
                  </div>
                </div>
              </a>
            `).join('');
          } catch (err) {
            console.error("COL search error:", err);
          }
        }, 300);
      });
    }
  }

  // View genome details
  window.viewGenome = async function(accession) {
    currentViewAccession = accession;
    const body = document.getElementById('viewGenomeBody');
    if (!body) return;
    
    body.innerHTML = '<div class="text-center py-5"><div class="spinner-border text-primary" role="status"></div></div>';
    if (viewModal) viewModal.show();
    
    try {
      const endpoint = window.HOME_DATA?.endpoints?.genomeDetail || '/api/v1/taxonomy/genomes/';
      const resp = await fetch(`${endpoint}${accession}/`);
      const data = await resp.json();
      
      body.innerHTML = renderGenomeDetails(data);
    } catch (err) {
      console.error("Error loading genome:", err);
      body.innerHTML = '<div class="alert alert-danger">Error loading genome details</div>';
    }
  };

  function renderGenomeDetails(g) {
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
    
    return `
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
            <div class="card-header"><h4 class="card-title">Proteome</h4></div>
            <div class="card-body">
              ${g.has_proteome 
                ? `<span class="badge bg-green-lt text-green"><i class="ti ti-check me-1"></i>Available</span>
                   <span class="ms-2">${g.proteome_quality || ''}</span>`
                : '<span class="badge bg-secondary-lt">Not available</span>'
              }
            </div>
          </div>
        </div>
        
        ${buscoHtml}
      </div>
    `;
  }

  // Edit genome
  window.editGenome = async function(accession) {
    document.getElementById('editAccession').value = accession;
    document.getElementById('editAccessionDisplay').textContent = accession;
    document.getElementById('colSearchResults').innerHTML = '';
    document.getElementById('selectedColSection').style.display = 'none';
    document.getElementById('selectedColId').value = '';
    
    if (editModal) editModal.show();
    
    try {
      const endpoint = window.HOME_DATA?.endpoints?.genomeDetail || '/api/v1/taxonomy/genomes/';
      const resp = await fetch(`${endpoint}${accession}/`);
      const data = await resp.json();
      
      document.getElementById('editOrganismName').textContent = data.organism_name || '-';
      document.getElementById('editMatchStatus').value = data.col_match_status || 'unmatched';
      document.getElementById('editMatchNotes').value = data.col_match_notes || '';
      
      if (data.external_taxon) {
        const classPath = data.external_taxon.classification_path?.map(p => p.name).join(' > ') || '';
        document.getElementById('currentMatchInfo').innerHTML = `
          <div class="d-flex align-items-center">
            <span class="badge bg-${data.external_taxon.status === 'accepted' ? 'green' : 'blue'}-lt me-2">
              ${data.external_taxon.status}
            </span>
            <div>
              <div class="fw-bold">${data.external_taxon.name}</div>
              <div class="small text-muted">${classPath}</div>
            </div>
          </div>
        `;
      } else {
        document.getElementById('currentMatchInfo').innerHTML = '<span class="text-muted">No COL match</span>';
      }
      
      document.getElementById('colSearchInput').value = data.organism_name || '';
    } catch (err) {
      console.error("Error loading genome:", err);
    }
  };

  // Select COL taxon
  window.selectColTaxon = function(id, name, classification, status) {
    document.getElementById('selectedColId').value = id;
    document.getElementById('selectedColName').textContent = name;
    document.getElementById('selectedColClassification').textContent = classification;
    document.getElementById('selectedColSection').style.display = 'block';
    document.getElementById('colSearchResults').innerHTML = '';
    document.getElementById('editMatchStatus').value = 'matched';
  };

  // Clear COL selection
  window.clearColSelection = function() {
    document.getElementById('selectedColId').value = '';
    document.getElementById('selectedColSection').style.display = 'none';
  };

  // Save genome match
  window.saveGenomeMatch = async function() {
    const accession = document.getElementById('editAccession').value;
    const colId = document.getElementById('selectedColId').value;
    const status = document.getElementById('editMatchStatus').value;
    const notes = document.getElementById('editMatchNotes').value;
    
    try {
      const endpoint = window.HOME_DATA?.endpoints?.genomeUpdate || '/api/v1/taxonomy/genomes/';
      const resp = await fetch(`${endpoint}${accession}/update/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': getCsrfToken()
        },
        body: JSON.stringify({
          col_match_status: status,
          external_taxon_id: colId ? parseInt(colId) : null,
          col_match_notes: notes
        })
      });
      
      const data = await resp.json();
      
      if (data.success) {
        if (editModal) editModal.hide();
        loadGenomes();
        showToast('Success', 'COL match updated successfully', 'success');
      } else {
        showToast('Error', data.error || 'Failed to save changes', 'danger');
      }
    } catch (err) {
      console.error("Save error:", err);
      showToast('Error', 'Failed to save changes', 'danger');
    }
  };

  // ============================================
  // TAB EVENTS
  // ============================================
  function initTabEvents() {
    let speciesListLoaded = false;
    document.querySelectorAll('[data-bs-toggle="tab"]').forEach(tab => {
      tab.addEventListener('shown.bs.tab', function(e) {
        if (e.target.getAttribute('href') === '#tab-species' && !speciesListLoaded) {
          loadGenomes();
          speciesListLoaded = true;
        }
      });
    });
  }

  // ============================================
  // INIT
  // ============================================
  document.addEventListener("DOMContentLoaded", function() {
    initAssemblyProgressBar();
    initPhylaChart();
    initTableEvents();
    initModals();
    initTabEvents();
  });

  // Export for external access
  window.HomeModule = {
    loadGenomes: loadGenomes
  };

})();
