// taxonomy/static/taxonomy/js/pages/home.js
// Dashboard page JavaScript - Charts only (Species table removed)

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

  function initKingdomChart() {
    const kingdomData = window.HOME_DATA?.kingdomStats || [];
    const chartEl = document.getElementById("chartKingdoms");
    
    if (!chartEl) return;
    
    if (!kingdomData.length) {
      chartEl.innerHTML = '<div class="text-muted text-center py-5">No data</div>';
      return;
    }

    kingdomData.sort((a, b) => b.value - a.value);
    
    const kingdomColors = [
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
        name: "Genomes",
        data: kingdomData.map(d => d.value)
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
        categories: kingdomData.map(d => d.label),
        labels: { style: { fontSize: "11px" } }
      },
      yaxis: {
        labels: { style: { fontSize: "11px" } }
      },
      colors: kingdomColors,
      legend: { show: false },
      tooltip: {
        y: {
          formatter: function(val, opts) {
            var idx = opts.dataPointIndex;
            var domain = (kingdomData && kingdomData[idx] && kingdomData[idx].domain) ? kingdomData[idx].domain : 'Unknown';
            return val + " genomes — Domain: " + domain;
          }
        }
      }
    }).render();
  }

  // ============================================
  // INIT
  // ============================================
  document.addEventListener("DOMContentLoaded", function() {
    initAssemblyProgressBar();
    initKingdomChart();
  });

})();