// taxonomy/static/taxonomy/js/shared/save_as.js
/**
 * Cross-browser "Save As" dialog.
 *
 * Shows a Bootstrap modal where the user can edit the filename before
 * downloading.  Works in all browsers (Firefox, Chrome, Edge, Safari).
 *
 * Usage:
 *   import { saveAs } from "../shared/save_as.js";
 *   await saveAs(blobOrString, "report.xlsx", "application/octet-stream");
 */

let _modalEl = null;
let _bsModal = null;
let _resolve = null;

/**
 * Ensure the modal DOM exists (created once, reused).
 */
function ensureModal() {
  if (_modalEl) return;

  _modalEl = document.createElement("div");
  _modalEl.id = "saveAsModal";
  _modalEl.className = "modal modal-blur fade";
  _modalEl.tabIndex = -1;
  _modalEl.setAttribute("aria-hidden", "true");
  _modalEl.innerHTML = `
    <div class="modal-dialog modal-sm modal-dialog-centered" role="document">
      <div class="modal-content">
        <div class="modal-header py-2">
          <h5 class="modal-title">
            <i class="fa-solid fa-floppy-disk me-2 text-primary"></i>Save As
          </h5>
          <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
        </div>
        <div class="modal-body">
          <label for="saveAsFilename" class="form-label small fw-semibold mb-1">File name</label>
          <input type="text" id="saveAsFilename" class="form-control form-control-sm" autocomplete="off" spellcheck="false" />
          <div class="form-text small text-muted mt-1" id="saveAsHint"></div>
        </div>
        <div class="modal-footer py-2">
          <button type="button" class="btn btn-sm" data-bs-dismiss="modal">Cancel</button>
          <button type="button" class="btn btn-sm btn-primary" id="saveAsConfirm">
            <i class="fa-solid fa-download me-1"></i>Save
          </button>
        </div>
      </div>
    </div>
  `;
  document.body.appendChild(_modalEl);

  // eslint-disable-next-line no-undef
  _bsModal = new bootstrap.Modal(_modalEl, { backdrop: "static" });

  // Confirm button
  _modalEl.querySelector("#saveAsConfirm").addEventListener("click", () => {
    const name = _modalEl.querySelector("#saveAsFilename").value.trim();
    _bsModal.hide();
    if (_resolve) _resolve(name || null);
    _resolve = null;
  });

  // Cancel / close
  _modalEl.addEventListener("hidden.bs.modal", () => {
    if (_resolve) _resolve(null); // user cancelled
    _resolve = null;
  });

  // Enter key = confirm
  _modalEl.querySelector("#saveAsFilename").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      _modalEl.querySelector("#saveAsConfirm").click();
    }
  });
}

/**
 * Show the Save-As modal and return the chosen filename (or null if cancelled).
 */
function askFilename(defaultName, hint) {
  ensureModal();
  const inp = _modalEl.querySelector("#saveAsFilename");
  const hintEl = _modalEl.querySelector("#saveAsHint");
  inp.value = defaultName;
  hintEl.textContent = hint || "";

  return new Promise((resolve) => {
    _resolve = resolve;
    _bsModal.show();
    // Select the name part (before the extension) for easy editing
    setTimeout(() => {
      inp.focus();
      const dotIdx = defaultName.lastIndexOf(".");
      if (dotIdx > 0) {
        inp.setSelectionRange(0, dotIdx);
      } else {
        inp.select();
      }
    }, 200);
  });
}

/**
 * Trigger a browser download with the given filename.
 */
function triggerDownload(blob, filename) {
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(href);
}

/**
 * Save content with a "Save As" dialog (filename prompt).
 *
 * @param {string|Blob|ArrayBuffer} content - The data to save.
 * @param {string} defaultFilename - Suggested filename.
 * @param {string} [mimeType="text/plain;charset=utf-8"] - MIME type (ignored if content is already a Blob).
 * @returns {Promise<boolean>} true if saved, false if cancelled.
 */
export async function saveAs(content, defaultFilename, mimeType = "text/plain;charset=utf-8") {
  const ext = defaultFilename.includes(".")
    ? defaultFilename.slice(defaultFilename.lastIndexOf("."))
    : "";

  const hint = ext
    ? `Type: ${ext.toUpperCase().slice(1)} file`
    : "";

  const chosenName = await askFilename(defaultFilename, hint);
  if (!chosenName) return false; // cancelled

  const blob = content instanceof Blob
    ? content
    : new Blob([content || ""], { type: mimeType });

  triggerDownload(blob, chosenName);
  return true;
}
