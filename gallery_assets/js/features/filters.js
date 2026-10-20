/* Media type filter buttons and filter listeners
 * Classic script: shares global scope with the other gallery modules (see gallery_assets/README.md). */

// Filter handlers
let activeTypes = new Set(['all']);
let activeType = 'all'; // For backwards compatibility

function updateTypeFilterButtonsUI() {
    const buttons = document.querySelectorAll('.type-filters .filter-btn');
    buttons.forEach(btn => {
        const t = btn.getAttribute('data-type');
        if (activeTypes.has(t)) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });
    activeType = activeTypes.has('all') ? 'all' : Array.from(activeTypes).join(',');
}

function showGalleryLoadingOverlay(show, text = 'Updating media gallery...') {
    const overlay = document.getElementById('galleryLoadingOverlay');
    const textEl = document.getElementById('galleryLoadingText');
    if (!overlay) return;
    if (show) {
        if (textEl) textEl.innerText = text;
        overlay.style.display = 'flex';
    } else {
        overlay.style.display = 'none';
    }
}

function setupFilterListeners() {
    initCalendarDatePicker();

    const search = document.getElementById('searchFilter');
    const sender = document.getElementById('senderFilter');
    const sort = document.getElementById('sortFilter');
    const start = document.getElementById('startDateFilter');
    const end = document.getElementById('endDateFilter');
    const hideDups = document.getElementById('hideDuplicatesFilter');
    const direction = document.getElementById('directionFilter');
    const starred = document.getElementById('starredFilter');
    const forwarded = document.getElementById('forwardedFilter');
    const freqForwarded = document.getElementById('freqForwardedFilter');

    const apply = () => filterAndRenderMedia();
    const debouncedApply = debounce(() => filterAndRenderMedia(), 120);

    search.addEventListener('input', debouncedApply);
    sender.addEventListener('change', apply);
    sort.addEventListener('change', apply);
    start.addEventListener('change', () => {
        updateDateFilterButtonUI();
        apply();
    });
    end.addEventListener('change', () => {
        updateDateFilterButtonUI();
        apply();
    });
    hideDups.addEventListener('change', apply);
    direction.addEventListener('change', apply);
    starred.addEventListener('change', apply);
    forwarded.addEventListener('change', apply);
    freqForwarded.addEventListener('change', apply);

    const buttons = document.querySelectorAll('.type-filters .filter-btn');
    buttons.forEach(btn => {
        btn.addEventListener('click', (e) => {
            const targetBtn = e.target.closest('.filter-btn');
            if (!targetBtn) return;
            const typeClicked = targetBtn.getAttribute('data-type');

            if (typeClicked === 'all') {
                activeTypes.clear();
                activeTypes.add('all');
            } else {
                activeTypes.delete('all');
                if (activeTypes.has(typeClicked)) {
                    activeTypes.delete(typeClicked);
                    if (activeTypes.size === 0) {
                        activeTypes.add('all');
                    }
                } else {
                    activeTypes.add(typeClicked);
                }
            }

            updateTypeFilterButtonsUI();
            filterAndRenderMedia();
            targetBtn.blur();
        });
    });
}
