// taxonomy/static/taxonomy/js/tree/config.js

export const VIS = {
    NODE_H: 20,
    PAD_X: 8,
    MAX_W: 260,
    MIN_W: 34,
    DUR: 160,
    CB_SIZE: 12,
    CB_GAP: 6,
    BTN_H: 14,
    BTN_W: 34,
    ROW_GAP: 50,
    COL_GAP: 200,
    MAX_INITIAL_DEPTH: 0  // Start fully collapsed (only root visible)
};

export const AUTOFIT = {
    maxNodesForFit: 60,
    areaFillThreshold: 0.75,
    minIntervalMs: 250
};

export const RANK_STYLE = {
    species: { fill: '#e0f2fe', stroke: '#0284c7' },
    default: { fill: '#ffffff', stroke: '#111827' }
};

export function rankStyle(rank) {
    const k = (rank || '').toLowerCase();
    return (k === 'species' || k === 'subspecies') ? RANK_STYLE.species : RANK_STYLE.default;
}

export function isSciName(name) {
    const parts = (name || '').trim().split(/\s+/);
    return parts.length >= 2;
}

export function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
}
