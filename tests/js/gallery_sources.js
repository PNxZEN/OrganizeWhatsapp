/**
 * Loads the gallery frontend sources exactly as the browser does:
 * gallery.html plus every stylesheet and script it links from gallery_assets/, in page order.
 */

const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const galleryPath = path.join(ROOT, 'gallery.html');

function loadGallerySources() {
    const html = fs.readFileSync(galleryPath, 'utf8');
    const read = (rel) => ({ path: rel, code: fs.readFileSync(path.join(ROOT, rel), 'utf8') });
    const styles = [...html.matchAll(/<link rel="stylesheet" href="(gallery_assets\/[^"]+)"/g)].map(m => read(m[1]));
    const scripts = [...html.matchAll(/<script src="(gallery_assets\/[^"]+)"><\/script>/g)].map(m => read(m[1]));
    const css = styles.map(s => s.code).join('\n');
    const js = scripts.map(s => s.code).join('\n');
    return {
        html,
        styles,
        scripts,
        css,
        js,
        // Everything the user can end up seeing, for content-wide assertions
        bundle: [html, css, js].join('\n'),
    };
}

module.exports = { ROOT, galleryPath, loadGallerySources };
