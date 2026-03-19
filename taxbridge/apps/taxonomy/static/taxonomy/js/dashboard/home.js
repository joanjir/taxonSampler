// taxonomy/static/taxonomy/js/dashboard/home.js
// Dashboard charts

(function() {
  "use strict";

  // ============================================
  // Donut helper
  // ============================================
  function renderDonut(elId, data, colors, height) {
    const el = document.getElementById(elId);
    if (!el) return;
    const filtered = data.filter(d => d.value > 0);
    if (!filtered.length) {
      el.innerHTML = '<div class="text-muted text-center py-5">No data</div>';
      return;
    }
    new ApexCharts(el, {
      chart: { type: "donut", height: height || 280, fontFamily: "inherit" },
      series: filtered.map(d => d.value),
      labels: filtered.map(d => d.label),
      colors: colors.slice(0, filtered.length),
      legend: { position: "bottom", fontSize: "13px" },
      dataLabels: {
        formatter: function(val, opts) {
          try {
            if (!opts || !opts.w || !opts.w.config || opts.seriesIndex === undefined) return val;
            return opts.w.config.series[opts.seriesIndex];
          } catch (e) {
            console.warn('[donut] dataLabels formatter error:', e);
            return val;
          }
        }
      },
      plotOptions: {
        pie: {
          donut: {
            size: "55%",
            labels: {
              show: true,
              total: {
                show: true,
                label: "Total",
                fontSize: "14px",
                fontWeight: 600,
                formatter: function(w) {
                  try {
                    if (!w || !w.globals || !w.globals.seriesTotals) return "Total";
                    return w.globals.seriesTotals.reduce(function(a, b) { return a + b; }, 0);
                  } catch (e) {
                    console.warn('[donut] total formatter error:', e);
                    return "Total";
                  }
                }
              }
            }
          }
        }
      },
      tooltip: {
        y: {
          formatter: function(val, opts) {
            try {
              if (!opts || !opts.w || !opts.w.globals || !opts.w.globals.seriesTotals) return String(val);
              var total = opts.w.globals.seriesTotals.reduce(function(a, b) { return a + b; }, 0);
              if (total === 0) return String(val);
              var pct = (val / total * 100).toFixed(1);
              return val + " (" + pct + "%)";
            } catch (e) {
              console.warn('[donut] tooltip formatter error:', e);
              return String(val);
            }
          }
        }
      }
    }).render();
  }

  // ============================================
  // Kingdom bar chart
  // ============================================
  function initKingdomChart() {
    var kingdomData = window.HOME_DATA?.kingdomStats || [];
    var chartEl = document.getElementById("chartKingdoms");
    if (!chartEl) return;
    if (!kingdomData.length) {
      chartEl.innerHTML = '<div class="text-muted text-center py-5">No data</div>';
      return;
    }
    kingdomData.sort(function(a, b) { return b.value - a.value; });

    // Domain-based colors
    var domainColors = {
      "Eukarya": "#4299e1",
      "Bacteria": "#48bb78",
      "Archaea": "#ed8936",
      "": "#a0aec0"
    };
    var barColors = kingdomData.map(function(d) {
      return domainColors[d.domain] || domainColors[""];
    });

    new ApexCharts(chartEl, {
      chart: {
        type: "bar",
        height: Math.max(320, kingdomData.length * 34),
        fontFamily: "inherit",
        toolbar: { show: false }
      },
      series: [{ name: "Genomes", data: kingdomData.map(function(d) { return d.value; }) }],
      plotOptions: {
        bar: { horizontal: true, borderRadius: 3, distributed: true, barHeight: "60%" }
      },
      dataLabels: {
        enabled: true,
        formatter: function(val) { return val; },
        offsetX: 5,
        style: { fontSize: "11px", fontWeight: 600, colors: ["#495057"] }
      },
      xaxis: {
        categories: kingdomData.map(function(d) { return d.label; }),
        labels: { style: { fontSize: "11px" } }
      },
      yaxis: { labels: { style: { fontSize: "11px" } } },
      colors: barColors,
      legend: { show: false },
      tooltip: {
        y: {
          formatter: function(val, opts) {
            try {
              if (!opts || opts.dataPointIndex === undefined) return String(val) + " genomes";
              var idx = opts.dataPointIndex;
              var domain = kingdomData[idx]?.domain || "Unknown";
              return String(val) + " genomes — " + domain;
            } catch (e) {
              console.warn('[kingdom] tooltip formatter error:', e);
              return String(val) + " genomes";
            }
          }
        }
      }
    }).render();
  }

  // ============================================
  // INIT
  // ============================================
  document.addEventListener("DOMContentLoaded", function() {
    var data = window.HOME_DATA || {};

    // Taxonomic Integration — all genomes, 3 categories
    renderDonut("chartTaxIntegration", data.taxIntegration || [], [
      "#2f9e44", "#7048e8", "#e8590c"
    ], 300);

    // Assembly Level — blues/teals palette
    renderDonut("chartAssembly", data.genomeLevels || [], [
      "#1864ab", "#0b7285", "#d97706", "#868e96"
    ], 280);

    // Kingdom bar chart
    initKingdomChart();
  });

})();
