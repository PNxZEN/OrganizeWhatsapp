/* Formatting helpers (bytes, dates, JIDs) and Explorer reveal
 * Classic script: shares global scope with the other gallery modules (see gallery_assets/README.md). */

// Formatter utilities
// The system file manager's own name, for "Show in ..." labels (the browser runs on the same computer)
function fileManagerName() {
    const p = String((navigator.userAgentData && navigator.userAgentData.platform) || navigator.platform || navigator.userAgent || '').toLowerCase();
    if (p.includes('mac')) return 'Finder';
    if (p.includes('win')) return 'File Explorer';
    return 'Files';
}

function applyFileManagerLabels() {
    document.querySelectorAll('[data-file-manager-label]').forEach(el => {
        el.textContent = el.getAttribute('data-file-manager-label').replace('{fm}', fileManagerName());
    });
}

async function revealInExplorer(relPath) {
    try {
        const res = await fetch(`/api/open-folder?rel_path=${encodeURIComponent(relPath)}`);
        if (!res.ok) {
            console.error("Failed to open folder, status:", res.status);
            if (typeof showToast === 'function') {
                showToast(res.status === 404
                    ? 'This file is no longer in its folder.'
                    : `Could not open ${fileManagerName()} on this computer.`, 'warning');
            }
        }
    } catch (e) {
        console.error("Error calling open-folder API:", e);
        if (typeof showToast === 'function') {
            showToast('Could not reach server', 'error');
        }
    }
}

function formatBytes(bytes, decimals = 1) {
    if (!bytes || isNaN(bytes) || bytes <= 0) return '0 Bytes';
    const k = 1024;
    const dm = decimals < 0 ? 0 : decimals;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.min(Math.floor(Math.log(bytes) / Math.log(k)), sizes.length - 1);
    return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
}

function extractDateFromFilename(filenameOrPath) {
    if (!filenameOrPath) return null;
    const fn = filenameOrPath.split('/').pop().split('\\').pop();
    // WhatsApp pattern: IMG-20241026-WA0034.jpg, VID-20230514-WA0001.mp4, etc.
    const match1 = fn.match(/\b(20\d{2})(\d{2})(\d{2})\b/);
    if (match1) {
        const [_, y, m, d] = match1;
        const year = parseInt(y, 10);
        const month = parseInt(m, 10);
        const day = parseInt(d, 10);
        if (year >= 2000 && year <= 2035 && month >= 1 && month <= 12 && day >= 1 && day <= 31) {
            return { year, month, day, dateStr: `${y}-${m}-${d} 00:00:00` };
        }
    }
    // Pattern 2: WhatsApp Image 2024-10-26 at 14.32.05
    const match2 = fn.match(/\b(20\d{2})-(\d{2})-(\d{2})(?:\s+at\s+(\d{2})\.(\d{2})\.(\d{2}))?/i);
    if (match2) {
        const [_, y, m, d, hh, mm, ss] = match2;
        const timePart = hh ? ` ${hh}:${mm}:${ss}` : ' 00:00:00';
        return { year: parseInt(y, 10), month: parseInt(m, 10), day: parseInt(d, 10), dateStr: `${y}-${m}-${d}${timePart}` };
    }
    return null;
}

function getMonthGroupForItem(item) {
    if (!item) return 'Unknown Date';
    let dateStr = item.received_at;
    if (!dateStr && (item.filename || item.rel_path)) {
        const parsed = extractDateFromFilename(item.filename || item.rel_path);
        if (parsed) dateStr = parsed.dateStr;
    }
    if (dateStr) {
        try {
            const date = new Date(dateStr.replace(/-/g, '/'));
            if (!isNaN(date.getTime())) {
                return date.toLocaleDateString('en-US', { year: 'numeric', month: 'long' });
            }
        } catch (e) {}
    }
    if (item.rel_path && item.rel_path.startsWith('_unmatched/')) {
        const parts = item.rel_path.split('/');
        if (parts.length > 2) return parts.slice(1, -1).join(' / ');
        return 'Unindexed Media';
    }
    return 'Unindexed Media';
}

function formatDate(dateStr, relPath = '', includeTime = false) {
    let effectiveDate = dateStr;
    let isFromFilename = false;
    if (!effectiveDate && relPath) {
        const parsed = extractDateFromFilename(relPath);
        if (parsed) {
            effectiveDate = parsed.dateStr;
            isFromFilename = true;
        }
    }
    if (!effectiveDate) {
        if (relPath && relPath.startsWith('_unmatched/')) {
            const parts = relPath.split('/');
            if (parts.length > 2) return parts.slice(1, -1).join(' / ');
            return 'Unindexed';
        }
        return 'Unknown Date';
    }
    try {
        const date = new Date(effectiveDate.replace(/-/g, '/'));
        if (isNaN(date.getTime())) return effectiveDate;
        const dStr = date.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
        if (includeTime) {
            const tStr = date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true });
            const res = `${dStr}, ${tStr}`;
            return isFromFilename ? `${res} (from filename)` : res;
        }
        return isFromFilename ? `${dStr} (from filename)` : dStr;
    } catch (e) {
        return effectiveDate;
    }
}

function formatDateTime(dateStr, relPath = '') {
    return formatDate(dateStr, relPath, true);
}

// Display name for a chat or contact name; raw phone JIDs are formatted, missing names become ''
function chatNameForDisplay(name) {
    const n = name || '';
    return n.endsWith('@s.whatsapp.net') ? formatJIDName(n) : n;
}

function formatJIDName(jid) {
    if (!jid) return 'Unknown';
    if (jid.endsWith('@s.whatsapp.net')) {
        const num = jid.split('@')[0];
        // Indian numbers (+91 XXXXX-XXXXX)
        if (num.startsWith('91') && num.length === 12) {
            return `+91 ${num.substring(2, 7)}-${num.substring(7)}`;
        }
        // US/Canada numbers (+1 (XXX) XXX-XXXX)
        if (num.startsWith('1') && num.length === 11) {
            return `+1 (${num.substring(1, 4)}) ${num.substring(4, 7)}-${num.substring(7)}`;
        }
        // UK numbers (+44 XXXX XXXXXX)
        if (num.startsWith('44') && num.length === 12) {
            return `+44 ${num.substring(2, 6)} ${num.substring(6)}`;
        }
        return `+${num}`;
    }
    if (jid.endsWith('@g.us')) {
        return jid.split('@')[0];
    }
    if (jid.endsWith('@broadcast')) {
        if (jid === 'status@broadcast') return 'Status Updates';
        return `Broadcast List (${jid.split('@')[0]})`;
    }
    if (jid.endsWith('@lid')) {
        const lidNum = jid.split('@')[0];
        return `LID User (${lidNum.substring(0, 6)}...)`;
    }
    return jid;
}
