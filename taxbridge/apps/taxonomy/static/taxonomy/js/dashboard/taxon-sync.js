// taxonomy/static/taxonomy/js/pages/taxon_sync.js
// Taxon Sync Dashboard JavaScript

(function() {
  "use strict";

  function getCsrfToken() {
    const cookie = document.cookie.split(';').find(c => c.trim().startsWith('csrftoken='));
    return cookie ? cookie.split('=')[1] : '';
  }

  function clearSyncForm() {
    // Reset form to default values
    const kingdomSelect = document.getElementById('kingdom-select');
    const limitInput = document.getElementById('limit-input');
    const skipQuality = document.getElementById('skip-quality');
    const btnStartSync = document.getElementById('btn-start-sync');
    const manualInput = document.getElementById('manual-kingdom-input');
    const manualRow = document.getElementById('manual-kingdom-row');
    const btnToggleOther = document.getElementById('btn-toggle-other');
    
    if (kingdomSelect) { kingdomSelect.value = 'metazoa'; kingdomSelect.disabled = false; }
    if (limitInput) limitInput.value = '0';
    if (skipQuality) skipQuality.checked = false;
    if (manualInput) manualInput.value = '';
    if (manualRow) manualRow.style.display = 'none';
    if (btnToggleOther) btnToggleOther.innerHTML = '<i class="ti ti-search me-1"></i> Other...';
    
    // Reset button state
    if (btnStartSync) {
      btnStartSync.disabled = false;
      btnStartSync.innerHTML = '<i class="ti ti-rocket me-1"></i> Start Sync';
    }
  }

  document.addEventListener('DOMContentLoaded', function() {
    const btnStartSync = document.getElementById('btn-start-sync');
    const btnCancelSync = document.getElementById('btn-cancel-sync');
    const runningCard = document.getElementById('running-sync-card');
    
    let pollInterval = null;

    // Toggle manual input with "Other" button
    const btnToggleOther = document.getElementById('btn-toggle-other');
    const manualRow = document.getElementById('manual-kingdom-row');
    const kingdomSelect = document.getElementById('kingdom-select');
    if (btnToggleOther && manualRow) {
      btnToggleOther.addEventListener('click', function() {
        const isVisible = manualRow.style.display !== 'none';
        manualRow.style.display = isVisible ? 'none' : '';
        if (isVisible) {
          // Closing: clear input, re-enable select
          const input = document.getElementById('manual-kingdom-input');
          if (input) input.value = '';
          if (kingdomSelect) kingdomSelect.disabled = false;
          btnToggleOther.innerHTML = '<i class="ti ti-search me-1"></i> Other...';
        } else {
          // Opening: disable select, focus input
          if (kingdomSelect) kingdomSelect.disabled = true;
          btnToggleOther.innerHTML = '<i class="ti ti-x me-1"></i> Use Kingdom';
          const input = document.getElementById('manual-kingdom-input');
          if (input) input.focus();
        }
      });
    }

    // Start sync
    if (btnStartSync && !btnStartSync.disabled) {
      btnStartSync.addEventListener('click', async function() {
        const manualInput = document.getElementById('manual-kingdom-input');
        let kingdom = document.getElementById('kingdom-select').value;
        // Use manual input if visible and filled
        if (manualRow && manualRow.style.display !== 'none' && manualInput && manualInput.value.trim()) {
          kingdom = manualInput.value.trim();
        } else if (manualRow && manualRow.style.display !== 'none') {
          Swal.fire({ icon: 'warning', text: 'Please enter a name or TaxID', confirmButtonColor: '#206bc4' });
          return;
        }
        const limit = parseInt(document.getElementById('limit-input').value) || 0;
        const skipQuality = document.getElementById('skip-quality').checked;

        btnStartSync.disabled = true;
        btnStartSync.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span> Starting...';

        try {
          const response = await fetch('/api/v1/taxonomy/taxon-sync/start/', {
            method: 'POST',
            headers: {
              'Content-Type': 'application/json',
              'X-CSRFToken': getCsrfToken(),
            },
            body: JSON.stringify({ kingdom, limit, skip_quality: skipQuality }),
          });

          const data = await response.json();
          
          if (data.success) {
            window.location.reload();
          } else {
            Swal.fire({ icon: 'error', title: 'Sync error', text: data.error || 'Error starting synchronization', confirmButtonColor: '#206bc4' });
            btnStartSync.disabled = false;
            btnStartSync.innerHTML = '<i class="ti ti-rocket me-2"></i> Start Synchronization';
          }
        } catch (e) {
          console.error(e);
          Swal.fire({ icon: 'error', title: 'Connection error', text: 'Could not connect to the server.', confirmButtonColor: '#206bc4' });
          btnStartSync.disabled = false;
          btnStartSync.innerHTML = '<i class="ti ti-rocket me-2"></i> Start Synchronization';
        }
      });
    }

    // Cancel sync
    if (btnCancelSync) {
      btnCancelSync.addEventListener('click', async function() {
        const result = await Swal.fire({
          title: 'Cancel sync?',
          text: 'Are you sure you want to cancel this sync?',
          icon: 'question',
          showCancelButton: true,
          confirmButtonText: 'Yes, cancel it',
          cancelButtonText: 'No, keep it',
          confirmButtonColor: '#d63939',
          cancelButtonColor: '#6c757d',
        });
        if (!result.isConfirmed) return;
        
        const syncId = runningCard.dataset.syncId;
        btnCancelSync.disabled = true;
        
        try {
          const response = await fetch(`/api/v1/taxonomy/taxon-sync/${syncId}/cancel/`, {
            method: 'POST',
            headers: { 'X-CSRFToken': getCsrfToken() },
          });

          if (response.ok) {
            window.location.reload();
          }
        } catch (e) {
          console.error(e);
          btnCancelSync.disabled = false;
        }
      });
    }

    // Poll for updates if sync is running
    if (runningCard) {
      const syncId = runningCard.dataset.syncId;
      
      pollInterval = setInterval(async () => {
        try {
          const response = await fetch(`/api/v1/taxonomy/taxon-sync/${syncId}/status/`);
          
          // Stop polling if sync not found (deleted/flushed)
          if (response.status === 404) {
            console.warn('Sync not found, stopping polling');
            clearInterval(pollInterval);
            window.location.reload();
            return;
          }
          
          const data = await response.json();
          
          // Update progress
          const progressText = document.getElementById('sync-progress-text');
          const statusText = document.getElementById('sync-status-text');
          const phaseBadge = document.getElementById('sync-phase-badge');
          
          progressText.textContent = Math.round(data.progress_percent) + '%';
          
          // Update steps based on status
          const stepNcbi = document.getElementById('step-ncbi');
          const stepTaxa = document.getElementById('step-taxa');
          const stepCol = document.getElementById('step-col');
          const stepCrosswalks = document.getElementById('step-crosswalks');
          
          // Reset all card borders
          [stepNcbi, stepTaxa, stepCol, stepCrosswalks].forEach(s => {
            if (s) s.classList.remove('border-primary', 'border-success', 'border-warning', 'border-purple');
          });
          
          // Get avatars
          const avatarNcbi = stepNcbi?.querySelector('.avatar');
          const avatarTaxa = stepTaxa?.querySelector('.avatar');
          const avatarCol = stepCol?.querySelector('.avatar');
          const avatarCrosswalks = stepCrosswalks?.querySelector('.avatar');
          
          if (data.status === 'fetching_ncbi') {
            stepNcbi.classList.add('border-primary');
            avatarNcbi?.classList.remove('opacity-50');
            if (data.taxa_created > 0) {
              stepTaxa.classList.add('border-success');
              avatarTaxa?.classList.remove('opacity-50');
            }
            statusText.innerHTML = '<strong>Step 1/4:</strong> Downloading genomes from NCBI...';
            phaseBadge.textContent = 'Downloading NCBI';
            phaseBadge.className = 'badge bg-blue-lt text-blue text-uppercase fs-5 me-2';
          } else if (data.status === 'matching_col') {
            avatarNcbi?.classList.remove('opacity-50');
            avatarTaxa?.classList.remove('opacity-50');
            stepCol.classList.add('border-warning');
            avatarCol?.classList.remove('opacity-50');
            statusText.innerHTML = '<strong>Step 3/4:</strong> Linking taxa with Catalogue of Life...';
            phaseBadge.textContent = 'Linking COL';
            phaseBadge.className = 'badge bg-yellow-lt text-yellow text-uppercase fs-5 me-2';
          } else if (data.status === 'completed') {
            avatarNcbi?.classList.remove('opacity-50');
            avatarTaxa?.classList.remove('opacity-50');
            avatarCol?.classList.remove('opacity-50');
            stepCrosswalks.classList.add('border-purple');
            avatarCrosswalks?.classList.remove('opacity-50');
            
            // Customize message: if all genomes were already in DB
            if (data.genomes_created === 0 && data.ncbi_skipped > 0) {
              statusText.innerHTML = `<strong>Completed!</strong> All ${data.ncbi_skipped} genome(s) from NCBI already exist in the database.`;
              phaseBadge.textContent = 'No New Data';
              phaseBadge.className = 'badge bg-azure-lt text-azure text-uppercase fs-5 me-2';
            } else {
              statusText.innerHTML = '<strong>Completed!</strong> All steps finished successfully.';
              phaseBadge.textContent = 'Completed';
              phaseBadge.className = 'badge bg-green-lt text-green text-uppercase fs-5 me-2';
            }
          }
          
          // Update stats
          document.getElementById('stat-ncbi-fetched').textContent = data.ncbi_fetched;
          document.getElementById('stat-taxa-created').textContent = data.taxa_created;
          document.getElementById('stat-col-matched').textContent = data.col_matched;
          document.getElementById('stat-crosswalks').textContent = data.crosswalks_created;
          
          // Show "already in DB" count if any genomes were skipped
          const skippedRow = document.getElementById('stat-ncbi-skipped-row');
          const skippedSpan = document.getElementById('stat-ncbi-skipped');
          if (skippedRow && skippedSpan) {
            skippedSpan.textContent = data.ncbi_skipped || 0;
            if (data.ncbi_skipped > 0) {
              skippedRow.classList.remove('d-none');
            }
          }

          // Refresh if completed
          if (['completed', 'failed', 'cancelled'].includes(data.status)) {
            clearInterval(pollInterval);
            
            // Clear form when completed successfully
            if (data.status === 'completed') {
              clearSyncForm();
            }
            
            setTimeout(() => window.location.reload(), 1500);
          }
        } catch (e) {
          console.error('Error polling status:', e);
        }
      }, 2000);
    }

    // Initialize popovers (only if bootstrap is available)
    if (typeof bootstrap !== 'undefined' && bootstrap.Popover) {
      const popoverTriggerList = document.querySelectorAll('[data-bs-toggle="popover"]');
      popoverTriggerList.forEach(el => new bootstrap.Popover(el));
    }
  });

})();
