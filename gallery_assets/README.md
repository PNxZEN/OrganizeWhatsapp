# Gallery frontend modules

`gallery.html` is the page shell: markup for the layout and modals, plus the ordered list of
stylesheets and scripts in this folder. There is no build step: the files are served as-is.

## How the modules load

- **Classic scripts, one shared global scope.** Every file in `js/` is a plain `<script src>`
  (not an ES module). Top-level `function`s and `let`/`const`s are visible to every other file
  and to the inline `onclick="..."` handlers in the markup. This is deliberate: ES modules would
  break those handlers and would not load when the gallery is opened directly from disk
  (`file://`, CORS blocks module scripts there).
- **Order matters.** Files run in the order listed in `gallery.html`. Code that runs at load time
  (event listener registration, `const` initialisers) may only use names declared in the same
  file or an earlier one. Function bodies can call anything, because they run later.
- **`app.js` loads last** and holds the `DOMContentLoaded` bootstrap, so every module is defined
  before the app starts.
- **CSS order matters too**: later stylesheets override earlier ones with equal specificity.

## Where things live

| Folder | Contents |
| --- | --- |
| `js/core/` | Shared state, formatting, escaping, toasts and modal stack, tab lifecycle, shutdown, saved app state, history navigation |
| `js/features/` | One file per UI feature: sidebar, chat selection, filters, grid, lightbox, sync, device, tutorial, settings, reclaim studio, restore, backups, duplicates, recycle bin, live sync |
| `css/` | One stylesheet per UI area, in cascade order |

## Rendering untrusted text

Chat names, file names, sender names and device/account labels come from WhatsApp data and
other people's phones. Before interpolating them into HTML:

- text and attribute values: `escapeHtml(value)`
- a JS string argument inside an inline handler: `onclick="fn('${escapeJsAttr(value)}')"`
- a relative file URL (works over `file://` too): `encodePathForUrl(relPath)`, or
  `getMediaUrl(relPath)` which also picks the `/api/media` route in server mode

## Serving and packaging

- The local server serves `/gallery_assets/*` straight from the application folder, with
  explicit `text/javascript` / `text/css` types.
- `core.gallery.install_gallery_frontend()` copies `gallery.html` and this folder into the
  output directory so the gallery also works when opened from disk.
- The Windows portable build and the Unix release archive include this folder.
