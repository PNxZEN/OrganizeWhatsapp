/* Infinite scroll and auto-collapsing filter panel
 * Classic script: shares global scope with the other gallery modules (see gallery_assets/README.md). */

function showInfiniteScrollSpinner(show) {
    let spinner = document.getElementById('infiniteScrollSpinner');
    const container = document.getElementById('galleryContent');
    if (!container) return;
    if (show && renderedCount < filteredMedia.length) {
        if (!spinner) {
            spinner = document.createElement('div');
            spinner.id = 'infiniteScrollSpinner';
            spinner.className = 'infinite-scroll-spinner';
            spinner.innerHTML = `
                        <div class="sync-spinner" style="width: 20px; height: 20px; border-width: 2.5px;"></div>
                        <span>Loading more media...</span>
                    `;
            container.appendChild(spinner);
        } else {
            spinner.style.display = 'flex';
            container.appendChild(spinner);
        }
    } else if (spinner) {
        spinner.style.display = 'none';
    }
}

function setupInfiniteScroll() {
    const container = document.getElementById('galleryContent');
    let rafPending = false;
    container.addEventListener('scroll', () => {
        if (rafPending) return;
        if (container.scrollTop + container.clientHeight >= container.scrollHeight - 350) {
            if (renderedCount < filteredMedia.length) {
                rafPending = true;
                showInfiniteScrollSpinner(true);
                requestAnimationFrame(() => {
                    appendMoreCards();
                    showInfiniteScrollSpinner(false);
                    rafPending = false;
                });
            }
        }
    });
}

let isFilterCollapsed = false;
let lastFilterScrollTop = 0;
let isProgrammaticScroll = false;
let isFilterTransitioning = false;
let userWheelDirection = 0;
let wheelDirectionTimer = null;

function setFilterPanelCollapsed(collapsed, isManual = false) {
    const filterPanel = document.getElementById('filterPanel');
    const container = document.getElementById('galleryContent');
    if (!filterPanel) return;
    if (isFilterCollapsed === collapsed) return;

    isFilterCollapsed = collapsed;
    isFilterTransitioning = true;

    if (collapsed) {
        filterPanel.classList.add('collapsed');
    } else {
        filterPanel.classList.remove('collapsed');
    }
    updateFilterToggleBtnState(collapsed);

    // Lock scroll evaluation during the CSS transition window to completely
    // decouple browser layout reflow / scroll clamping from user intent
    setTimeout(() => {
        isFilterTransitioning = false;
        if (container) {
            lastFilterScrollTop = container.scrollTop;
        }
    }, 320);
}

function toggleFilterPanelManual() {
    setFilterPanelCollapsed(!isFilterCollapsed, true);
}

function setupCollapsibleFilterPanel() {
    const container = document.getElementById('galleryContent');
    const filterPanel = document.getElementById('filterPanel');
    if (!container || !filterPanel) return;

    // Track physical user input direction (mouse wheel / touchpad)
    container.addEventListener('wheel', (e) => {
        userWheelDirection = e.deltaY;
        clearTimeout(wheelDirectionTimer);
        wheelDirectionTimer = setTimeout(() => {
            userWheelDirection = 0;
        }, 200);
    }, { passive: true });

    let touchStartY = 0;
    container.addEventListener('touchstart', (e) => {
        if (e.touches && e.touches.length > 0) {
            touchStartY = e.touches[0].clientY;
        }
    }, { passive: true });

    container.addEventListener('touchmove', (e) => {
        if (e.touches && e.touches.length > 0) {
            const currentY = e.touches[0].clientY;
            userWheelDirection = touchStartY - currentY;
            clearTimeout(wheelDirectionTimer);
            wheelDirectionTimer = setTimeout(() => {
                userWheelDirection = 0;
            }, 200);
        }
    }, { passive: true });

    container.addEventListener('scroll', () => {
        // Ignore programmatic scrolls and events during transition animations
        if (isProgrammaticScroll || isFilterTransitioning) {
            lastFilterScrollTop = container.scrollTop;
            return;
        }

        // If user is interacting with an input or dropdown in the filter panel, do not collapse
        if (filterPanel.contains(document.activeElement)) {
            lastFilterScrollTop = container.scrollTop;
            return;
        }

        const currentScrollTop = container.scrollTop;
        const delta = currentScrollTop - lastFilterScrollTop;

        // 1. If at or near the very top (< 20px), expand the filter panel
        if (currentScrollTop <= 20) {
            if (isFilterCollapsed) {
                setFilterPanelCollapsed(false);
            }
            lastFilterScrollTop = currentScrollTop;
            return;
        }

        // 2. Ignore micro-jitter / sub-pixel movements
        if (Math.abs(delta) < 12) return;

        // 3. Runway Check:
        // Auto-collapsing is only appropriate when the gallery has ample scroll runway.
        // If the chat media items match or are close to the bottom border of the screen,
        // collapsing the panel would cause the items to fit entirely within the viewport,
        // triggering browser scroll clamping and oscillation.
        // We require at least (panelHeight + 120px) of extra scrollable height.
        const panelHeight = filterPanel.offsetHeight || 170;
        const availableRunway = container.scrollHeight - container.clientHeight;

        // Scrolling DOWN:
        // User must be moving down past 80px with positive scroll delta,
        // confirmed downward user intent, and sufficient scroll runway.
        if (delta > 0 && currentScrollTop > 80 && !isFilterCollapsed) {
            if (availableRunway >= panelHeight + 120) {
                setFilterPanelCollapsed(true);
            }
        }
        // Scrolling UP:
        // User must show deliberate upward intent (delta < -25 or userWheelDirection < 0).
        else if ((delta < -25 || userWheelDirection < -10) && isFilterCollapsed) {
            setFilterPanelCollapsed(false);
        }

        lastFilterScrollTop = currentScrollTop;
    }, { passive: true });
}

function updateFilterToggleBtnState(collapsed) {
    const btn = document.getElementById('btnToggleFilters');
    if (!btn) return;
    if (collapsed) {
        btn.style.background = 'rgba(16, 185, 129, 0.15)';
        btn.style.borderColor = 'rgba(16, 185, 129, 0.4)';
        btn.style.color = 'var(--accent)';
    } else {
        btn.style.background = 'rgba(255, 255, 255, 0.05)';
        btn.style.borderColor = 'rgba(255, 255, 255, 0.1)';
        btn.style.color = 'var(--text-primary)';
    }
}
