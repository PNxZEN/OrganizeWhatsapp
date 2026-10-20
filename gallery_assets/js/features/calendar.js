/* Interactive calendar date range picker
 * Classic script: shares global scope with the other gallery modules (see gallery_assets/README.md). */

// Interactive Calendar Date Picker State & Logic
let calCurrentYear = 2024;
let calCurrentMonth = 0; // 0 = Jan, 11 = Dec
let calMinYear = 2020;
let calMaxYear = 2026;
let calSelectedStartDate = null; // 'YYYY-MM-DD'
let calSelectedEndDate = null;   // 'YYYY-MM-DD'
const calActiveDaysSet = new Set();
let calCurrentView = 'month-grid';
let calInitialized = false;

const CAL_MONTH_NAMES = [
    'January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December'
];
const CAL_MONTH_SHORT = [
    'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
    'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'
];

function calPadZero(n) {
    return n < 10 ? '0' + n : '' + n;
}

function calToYMD(year, month, day) {
    return `${year}-${calPadZero(month + 1)}-${calPadZero(day)}`;
}

function calGetDaysInMonth(year, month) {
    return new Date(year, month + 1, 0).getDate();
}

function calGetFirstDayOfWeek(year, month) {
    return new Date(year, month, 1).getDay();
}

function formatCalDateStr(ymd) {
    if (!ymd) return '';
    const parts = ymd.split('-');
    if (parts.length < 3) return ymd;
    const y = parts[0];
    const m = parseInt(parts[1], 10) - 1;
    const d = parseInt(parts[2], 10);
    return `${CAL_MONTH_SHORT[m]} ${d}, ${y}`;
}

function updateDateFilterButtonUI() {
    const startInput = document.getElementById('startDateFilter');
    const endInput = document.getElementById('endDateFilter');
    const btn = document.getElementById('dateFilterBtn');
    const label = document.getElementById('dateFilterLabel');
    const clearBtn = document.getElementById('dateFilterClear');
    if (!label || !btn) return;

    const s = startInput ? startInput.value : '';
    const e = endInput ? endInput.value : '';

    if (!s && !e) {
        label.innerText = 'All Dates';
        btn.classList.remove('active-filter');
        if (clearBtn) clearBtn.style.display = 'none';
    } else if (s && e && s === e) {
        label.innerText = formatCalDateStr(s);
        btn.classList.add('active-filter');
        if (clearBtn) clearBtn.style.display = 'inline-flex';
    } else if (s && e) {
        label.innerText = `${formatCalDateStr(s)} - ${formatCalDateStr(e)}`;
        btn.classList.add('active-filter');
        if (clearBtn) clearBtn.style.display = 'inline-flex';
    } else if (s) {
        label.innerText = `From ${formatCalDateStr(s)}`;
        btn.classList.add('active-filter');
        if (clearBtn) clearBtn.style.display = 'inline-flex';
    } else if (e) {
        label.innerText = `Until ${formatCalDateStr(e)}`;
        btn.classList.add('active-filter');
        if (clearBtn) clearBtn.style.display = 'inline-flex';
    }
}

function toggleCalendarPopover() {
    const popover = document.getElementById('calendarPopover');
    if (!popover) return;
    if (popover.style.display === 'none' || !popover.style.display) {
        calSwitchView('month-grid');
        popover.style.display = 'block';
    } else {
        closeCalendarPopover();
    }
}

function closeCalendarPopover() {
    const popover = document.getElementById('calendarPopover');
    if (popover) {
        popover.style.display = 'none';
    }
}

function calSwitchView(viewName) {
    calCurrentView = viewName;
    const viewGrid = document.getElementById('calViewMonthGrid');
    const viewMonth = document.getElementById('calViewMonthSlider');
    const viewYear = document.getElementById('calViewYearSlider');

    if (viewGrid) viewGrid.style.display = (viewName === 'month-grid') ? 'block' : 'none';
    if (viewMonth) viewMonth.style.display = (viewName === 'month-slider') ? 'block' : 'none';
    if (viewYear) viewYear.style.display = (viewName === 'year-slider') ? 'block' : 'none';

    if (viewName === 'month-grid') renderCalendarGrid();
    else if (viewName === 'month-slider') renderMonthSlider();
    else if (viewName === 'year-slider') renderYearSlider();
}

function calNavMonth(direction) {
    let month = calCurrentMonth + direction;
    let year = calCurrentYear;
    if (month < 0) {
        month = 11;
        year--;
    } else if (month > 11) {
        month = 0;
        year++;
    }
    // Stop at the data range edges instead of wrapping to the other end of the same year
    if (year < calMinYear || year > calMaxYear) return;
    calCurrentMonth = month;
    calCurrentYear = year;
    renderCalendarGrid();
}

function renderCalendarGrid() {
    const monthText = document.getElementById('calMonthText');
    const yearText = document.getElementById('calYearText');
    const grid = document.getElementById('calDaysGrid');
    if (monthText) monthText.innerText = CAL_MONTH_NAMES[calCurrentMonth];
    if (yearText) yearText.innerText = calCurrentYear;
    if (!grid) return;

    grid.innerHTML = '';

    const daysInMonth = calGetDaysInMonth(calCurrentYear, calCurrentMonth);
    const firstDayOfWeek = calGetFirstDayOfWeek(calCurrentYear, calCurrentMonth);

    // Previous month padding cells
    const prevMonth = (calCurrentMonth === 0) ? 11 : calCurrentMonth - 1;
    const prevYear = (calCurrentMonth === 0) ? calCurrentYear - 1 : calCurrentYear;
    const daysInPrevMonth = calGetDaysInMonth(prevYear, prevMonth);

    for (let i = firstDayOfWeek - 1; i >= 0; i--) {
        const dayNum = daysInPrevMonth - i;
        const cell = document.createElement('div');
        cell.className = 'cal-day-cell other-month';
        cell.innerText = dayNum;
        grid.appendChild(cell);
    }

    // Current month cells
    for (let d = 1; d <= daysInMonth; d++) {
        const cell = document.createElement('button');
        cell.type = 'button';
        cell.className = 'cal-day-cell';
        cell.innerText = d;
        const ymd = calToYMD(calCurrentYear, calCurrentMonth, d);

        const isStart = (ymd === calSelectedStartDate);
        const isEnd = (ymd === calSelectedEndDate);
        const inRange = (calSelectedStartDate && calSelectedEndDate && ymd > calSelectedStartDate && ymd < calSelectedEndDate);

        if (isStart) cell.classList.add('range-start');
        if (isEnd) cell.classList.add('range-end');
        if (inRange) cell.classList.add('in-range');

        if (calActiveDaysSet.has(ymd)) {
            const dot = document.createElement('span');
            dot.className = 'cal-day-dot';
            cell.appendChild(dot);
        }

        cell.addEventListener('click', () => calOnDayClick(ymd));
        grid.appendChild(cell);
    }

    // Next month padding cells to complete 7-column grid
    const totalCells = firstDayOfWeek + daysInMonth;
    const remaining = (totalCells % 7 === 0) ? 0 : 7 - (totalCells % 7);
    for (let d = 1; d <= remaining; d++) {
        const cell = document.createElement('div');
        cell.className = 'cal-day-cell other-month';
        cell.innerText = d;
        grid.appendChild(cell);
    }
}

function calOnDayClick(ymd) {
    // If already selecting this exact single day, clicking it again toggles it off
    if (calSelectedStartDate === ymd && calSelectedEndDate === ymd) {
        clearDateFilter();
        return;
    }

    // If no start date, or we already have a multi-day range selected (start !== end),
    // start a new single-day selection
    if (!calSelectedStartDate || (calSelectedStartDate && calSelectedEndDate && calSelectedStartDate !== calSelectedEndDate)) {
        calSelectedStartDate = ymd;
        calSelectedEndDate = ymd;
        calApplyDateRange(ymd, ymd);
    } else {
        // We currently have a single day selected (calSelectedStartDate === calSelectedEndDate)
        // Clicking another day creates a range [min, max]
        const s = (ymd < calSelectedStartDate) ? ymd : calSelectedStartDate;
        const e = (ymd < calSelectedStartDate) ? calSelectedStartDate : ymd;
        calSelectedStartDate = s;
        calSelectedEndDate = e;
        calApplyDateRange(s, e);
    }
    renderCalendarGrid();
}

function renderMonthSlider() {
    const heroVal = document.getElementById('calMonthSliderVal');
    const heroSub = document.getElementById('calMonthSliderSub');
    const slider = document.getElementById('calMonthSlider');
    const chipsContainer = document.getElementById('calMonthChips');

    if (heroVal) heroVal.innerText = CAL_MONTH_NAMES[calCurrentMonth];
    if (heroSub) heroSub.innerText = `Month ${calCurrentMonth + 1} of 12`;
    if (slider) slider.value = calCurrentMonth;

    if (chipsContainer) {
        chipsContainer.innerHTML = '';
        CAL_MONTH_SHORT.forEach((shortName, idx) => {
            const chip = document.createElement('div');
            chip.className = 'cal-chip' + (idx === calCurrentMonth ? ' active' : '');
            chip.innerText = shortName;
            chip.addEventListener('click', () => {
                calCurrentMonth = idx;
                renderMonthSlider();
            });
            chipsContainer.appendChild(chip);
        });
    }
}

function renderYearSlider() {
    const heroVal = document.getElementById('calYearSliderVal');
    const heroSub = document.getElementById('calYearSliderSub');
    const minBound = document.getElementById('calYearMinBound');
    const maxBound = document.getElementById('calYearMaxBound');
    const slider = document.getElementById('calYearSlider');
    const chipsContainer = document.getElementById('calYearChips');

    if (heroVal) heroVal.innerText = calCurrentYear;
    if (heroSub) heroSub.innerText = `${calMinYear} to ${calMaxYear}`;
    if (minBound) minBound.innerText = calMinYear;
    if (maxBound) maxBound.innerText = calMaxYear;

    if (slider) {
        slider.min = calMinYear;
        slider.max = calMaxYear;
        slider.value = calCurrentYear;
    }

    if (chipsContainer) {
        chipsContainer.innerHTML = '';
        for (let y = calMinYear; y <= calMaxYear; y++) {
            const chip = document.createElement('div');
            chip.className = 'cal-year-chip' + (y === calCurrentYear ? ' active' : '');
            chip.innerText = y;
            chip.addEventListener('click', () => {
                calCurrentYear = y;
                renderYearSlider();
            });
            chipsContainer.appendChild(chip);
        }
    }
}

function calApplyDateRange(start, end) {
    const startInput = document.getElementById('startDateFilter');
    const endInput = document.getElementById('endDateFilter');
    if (startInput) startInput.value = start || '';
    if (endInput) endInput.value = end || '';
    updateDateFilterButtonUI();
    filterAndRenderMedia();
}

function clearDateFilter() {
    calSelectedStartDate = null;
    calSelectedEndDate = null;
    calApplyDateRange('', '');
    renderCalendarGrid();
}

// Set min/max values for date picker
function setDateRangeLimits(media) {
    const dates = (media || []).map(m => {
        if (m.received_at) return m.received_at;
        const parsed = extractDateFromFilename(m.rel_path || m.filename);
        return parsed ? parsed.dateStr : null;
    }).filter(Boolean).sort();
    const startInput = document.getElementById('startDateFilter');
    const endInput = document.getElementById('endDateFilter');
    if (!startInput || !endInput) return;

    calActiveDaysSet.clear();
    dates.forEach(d => {
        const ymd = d.split(' ')[0];
        if (ymd) calActiveDaysSet.add(ymd);
    });

    if (dates.length > 0) {
        const minDate = dates[0].split(' ')[0];
        const maxDate = dates[dates.length - 1].split(' ')[0];
        startInput.min = minDate;
        startInput.max = maxDate;
        endInput.min = minDate;
        endInput.max = maxDate;

        const minYear = parseInt(minDate.split('-')[0], 10) || 2020;
        const maxYear = parseInt(maxDate.split('-')[0], 10) || (new Date().getFullYear());
        calMinYear = Math.min(minYear, maxYear);
        calMaxYear = Math.max(minYear, maxYear);

        const latestYear = parseInt(maxDate.split('-')[0], 10);
        const latestMonth = (parseInt(maxDate.split('-')[1], 10) || 1) - 1;
        calCurrentYear = latestYear;
        calCurrentMonth = latestMonth;
    } else {
        startInput.removeAttribute('min');
        startInput.removeAttribute('max');
        endInput.removeAttribute('min');
        endInput.removeAttribute('max');
        calMinYear = 2020;
        calMaxYear = new Date().getFullYear();
        calCurrentYear = calMaxYear;
        calCurrentMonth = new Date().getMonth();
    }

    startInput.value = '';
    endInput.value = '';
    calSelectedStartDate = null;
    calSelectedEndDate = null;
    updateDateFilterButtonUI();
}

function initCalendarDatePicker() {
    if (calInitialized) return;
    calInitialized = true;

    const btn = document.getElementById('dateFilterBtn');
    const clearBtn = document.getElementById('dateFilterClear');
    const prevMonthBtn = document.getElementById('calPrevMonth');
    const nextMonthBtn = document.getElementById('calNextMonth');
    const monthTitle = document.getElementById('calMonthTitle');
    const yearTitle = document.getElementById('calYearTitle');

    const backFromMonthSlider = document.getElementById('calBackFromMonthSlider');
    const backFromYearSlider = document.getElementById('calBackFromYearSlider');
    const monthSlider = document.getElementById('calMonthSlider');
    const yearSlider = document.getElementById('calYearSlider');

    const viewMonthDaysBtn = document.getElementById('calViewMonthDaysBtn');
    const filterEntireMonthBtn = document.getElementById('calFilterEntireMonthBtn');
    const viewYearDaysBtn = document.getElementById('calViewYearDaysBtn');
    const filterEntireYearBtn = document.getElementById('calFilterEntireYearBtn');

    const calClearBtn = document.getElementById('calClearBtn');
    const calThisMonthBtn = document.getElementById('calThisMonthBtn');
    const calCloseBtn = document.getElementById('calCloseBtn');

    if (btn) {
        btn.addEventListener('click', (e) => {
            if (e.target.closest('#dateFilterClear')) return;
            toggleCalendarPopover();
        });
    }

    if (clearBtn) {
        clearBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            clearDateFilter();
        });
    }

    if (prevMonthBtn) prevMonthBtn.addEventListener('click', () => calNavMonth(-1));
    if (nextMonthBtn) nextMonthBtn.addEventListener('click', () => calNavMonth(1));

    if (monthTitle) monthTitle.addEventListener('click', () => calSwitchView('month-slider'));
    if (yearTitle) yearTitle.addEventListener('click', () => calSwitchView('year-slider'));

    if (backFromMonthSlider) backFromMonthSlider.addEventListener('click', () => calSwitchView('month-grid'));
    if (backFromYearSlider) backFromYearSlider.addEventListener('click', () => calSwitchView('month-grid'));

    if (monthSlider) {
        monthSlider.addEventListener('input', (e) => {
            calCurrentMonth = parseInt(e.target.value, 10);
            renderMonthSlider();
        });
    }

    if (yearSlider) {
        yearSlider.addEventListener('input', (e) => {
            calCurrentYear = parseInt(e.target.value, 10);
            renderYearSlider();
        });
    }

    if (viewMonthDaysBtn) {
        viewMonthDaysBtn.addEventListener('click', () => calSwitchView('month-grid'));
    }

    if (filterEntireMonthBtn) {
        filterEntireMonthBtn.addEventListener('click', () => {
            const daysInM = calGetDaysInMonth(calCurrentYear, calCurrentMonth);
            calSelectedStartDate = calToYMD(calCurrentYear, calCurrentMonth, 1);
            calSelectedEndDate = calToYMD(calCurrentYear, calCurrentMonth, daysInM);
            calApplyDateRange(calSelectedStartDate, calSelectedEndDate);
            closeCalendarPopover();
        });
    }

    if (viewYearDaysBtn) {
        viewYearDaysBtn.addEventListener('click', () => calSwitchView('month-grid'));
    }

    if (filterEntireYearBtn) {
        filterEntireYearBtn.addEventListener('click', () => {
            calSelectedStartDate = calToYMD(calCurrentYear, 0, 1);
            calSelectedEndDate = calToYMD(calCurrentYear, 11, 31);
            calApplyDateRange(calSelectedStartDate, calSelectedEndDate);
            closeCalendarPopover();
        });
    }

    if (calClearBtn) {
        calClearBtn.addEventListener('click', () => {
            clearDateFilter();
        });
    }

    if (calThisMonthBtn) {
        calThisMonthBtn.addEventListener('click', () => {
            const now = new Date();
            calCurrentYear = Math.max(calMinYear, Math.min(calMaxYear, now.getFullYear()));
            calCurrentMonth = now.getMonth();
            const daysInM = calGetDaysInMonth(calCurrentYear, calCurrentMonth);
            calSelectedStartDate = calToYMD(calCurrentYear, calCurrentMonth, 1);
            calSelectedEndDate = calToYMD(calCurrentYear, calCurrentMonth, daysInM);
            calApplyDateRange(calSelectedStartDate, calSelectedEndDate);
            renderCalendarGrid();
            closeCalendarPopover();
        });
    }

    if (calCloseBtn) {
        calCloseBtn.addEventListener('click', () => {
            if (calSelectedStartDate && !calSelectedEndDate) {
                calSelectedEndDate = calSelectedStartDate;
                calApplyDateRange(calSelectedStartDate, calSelectedEndDate);
            }
            closeCalendarPopover();
        });
    }

    // Click outside to close popover
    document.addEventListener('click', (e) => {
        const picker = document.getElementById('datePickerInteractive');
        const popover = document.getElementById('calendarPopover');
        if (picker && popover && popover.style.display !== 'none') {
            if (!picker.contains(e.target)) {
                closeCalendarPopover();
            }
        }
    });
}
