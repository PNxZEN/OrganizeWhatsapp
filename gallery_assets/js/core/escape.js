/* HTML / JS string escaping helpers
 * Classic script: shares global scope with the other gallery modules (see gallery_assets/README.md). */

function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function escapeJs(str) {
    if (!str) return '';
    return String(str).replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/\r?\n/g, '\\n');
}

// Escapes a value for use inside a single-quoted JS string that itself sits inside a
// double-quoted HTML attribute, e.g. onclick="fn('${escapeJsAttr(value)}')".
function escapeJsAttr(str) {
    return escapeHtml(escapeJs(str));
}

// Builds a relative URL from a slash-separated relative path, encoding every segment
// so names containing '#', '%', '?' or quotes resolve correctly (also over file://).
function encodePathForUrl(relPath) {
    return String(relPath || '').split('/').map(seg => encodeURIComponent(seg)).join('/');
}
