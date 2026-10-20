/* Media type detection and resolution probing
 * Classic script: shares global scope with the other gallery modules (see gallery_assets/README.md). */

function isImageItem(item) {
    if (!item) return false;
    const mime = (item.mime_type || '').toLowerCase();
    const fn = (item.filename || '').toLowerCase();
    return mime.startsWith('image/') || /\.(jpg|jpeg|png|webp|gif|bmp|heic|heif)$/i.test(fn);
}

function isVideoItem(item) {
    if (!item) return false;
    const mime = (item.mime_type || '').toLowerCase();
    const fn = (item.filename || '').toLowerCase();
    return mime.startsWith('video/') || /\.(mp4|3gp|mov|mkv|avi|webm)$/i.test(fn);
}

function resolveAndDisplayImageDims(item, targetSpanId) {
    if (!item) return;
    const span = document.getElementById(targetSpanId);
    if (!span) return;

    // 1. If stored in item metadata
    if (item.width && item.height) {
        span.innerText = `${item.width} x ${item.height} px`;
        return;
    }

    // 2. Non-images (videos, audio, docs): do not attempt Image() loading
    if (!isImageItem(item)) {
        const fn = (item.filename || '').toLowerCase();
        const mime = (item.mime_type || '').toLowerCase();
        const isVid = mime.startsWith('video/') || /\.(mp4|3gp|mov|m4v|avi|mkv|webm)$/i.test(fn);
        const isAud = mime.startsWith('audio/') || /\.(opus|ogg|mp3|m4a|aac|wav)$/i.test(fn);
        if (isVid) {
            const k = item.rel_path || item.filename;
            if (window._cachedImageDims[k]) {
                const dims = window._cachedImageDims[k];
                const durStr = dims.dur ? ` • ${formatDuration(dims.dur)}` : (item.media_duration ? ` • ${formatDuration(item.media_duration)}` : '');
                span.innerText = `${dims.w} x ${dims.h} px${durStr}`;
                return;
            }
            const dur = item.media_duration ? ` (${formatDuration(item.media_duration)})` : '';
            span.innerText = `Video${dur}`;

            const probeVid = document.createElement('video');
            probeVid.preload = 'metadata';
            const directUrl = (item.rel_path || '').split('/').map(seg => encodeURIComponent(seg)).join('/');
            const primaryUrl = isHttpServer ? ('/api/media?path=' + encodeURIComponent(item.rel_path)) : directUrl;
            probeVid.onloadedmetadata = () => {
                if (probeVid.videoWidth && probeVid.videoHeight) {
                    window._cachedImageDims[k] = { w: probeVid.videoWidth, h: probeVid.videoHeight, dur: probeVid.duration };
                    item.width = probeVid.videoWidth;
                    item.height = probeVid.videoHeight;
                    const curSpan = document.getElementById(targetSpanId);
                    if (curSpan) {
                        const durStr = probeVid.duration ? ` • ${formatDuration(probeVid.duration)}` : '';
                        curSpan.innerText = `${probeVid.videoWidth} x ${probeVid.videoHeight} px${durStr}`;
                    }
                }
            };
            probeVid.src = primaryUrl;
        } else if (isAud) {
            const dur = item.media_duration ? ` (${formatDuration(item.media_duration)})` : '';
            span.innerText = `Audio${dur}`;
        } else {
            span.innerText = 'Document';
        }
        return;
    }

    // 3. If cached in window._cachedImageDims
    const k = item.rel_path || item.filename;
    if (window._cachedImageDims[k]) {
        const dims = window._cachedImageDims[k];
        span.innerText = `${dims.w} x ${dims.h} px`;
        return;
    }

    // 4. Measure using off-screen image
    span.innerText = 'Detecting...';
    const img = new Image();
    const directUrl = (item.rel_path || '').split('/').map(seg => encodeURIComponent(seg)).join('/');
    const primaryUrl = isHttpServer ? ('/api/media?path=' + encodeURIComponent(item.rel_path)) : directUrl;

    const applyNaturalDims = (loadedImg) => {
        if (loadedImg.naturalWidth && loadedImg.naturalHeight) {
            window._cachedImageDims[k] = { w: loadedImg.naturalWidth, h: loadedImg.naturalHeight };
            item.width = loadedImg.naturalWidth;
            item.height = loadedImg.naturalHeight;
            const curSpan = document.getElementById(targetSpanId);
            if (curSpan) {
                curSpan.innerText = `${loadedImg.naturalWidth} x ${loadedImg.naturalHeight} px`;
            }
            return true;
        }
        return false;
    };

    img.onload = () => {
        if (!applyNaturalDims(img)) {
            const curSpan = document.getElementById(targetSpanId);
            if (curSpan) curSpan.innerText = 'Standard';
        }
    };
    img.onerror = () => {
        if (isHttpServer && img.src !== directUrl) {
            const retry = new Image();
            retry.onload = () => {
                if (!applyNaturalDims(retry)) {
                    const curSpan = document.getElementById(targetSpanId);
                    if (curSpan) curSpan.innerText = 'Standard';
                }
            };
            retry.onerror = () => {
                const curSpan = document.getElementById(targetSpanId);
                if (curSpan) curSpan.innerText = 'Standard';
            };
            retry.src = directUrl;
        } else {
            const curSpan = document.getElementById(targetSpanId);
            if (curSpan) curSpan.innerText = 'Standard';
        }
    };
    img.src = primaryUrl;
}
