/* USB device status, device modal and account selector
 * Classic script: shares global scope with the other gallery modules (see gallery_assets/README.md). */

let consecutiveServerFailures = 0;
let modalDevicePollTimer = null;
let lastDeviceFingerprint = '';
let activeWaitingMode = null; // 'detecting' | 'authorizing' | null
let waitingSecondsLeft = 0;
let waitingTimerInterval = null;

let _deviceStatusInFlight = null;
let _deviceStatusSeq = 0;
let _deviceStatusAppliedSeq = 0;
let _accountScanWatchTimer = null;

// Fetches /api/device-status. Plain polls share one in-flight request; options.refresh forces a
// WhatsApp account rescan and options.wait (seconds) waits for an in-flight scan.
// Resolves with the status object (or null) so callers can act on the exact response they asked for.
function checkDeviceStatus(options = {}) {
    const forced = !!(options.refresh || options.wait);
    if (!forced && _deviceStatusInFlight) return _deviceStatusInFlight;
    const request = _fetchDeviceStatus(options).finally(() => {
        if (_deviceStatusInFlight === request) _deviceStatusInFlight = null;
    });
    if (!forced) _deviceStatusInFlight = request;
    return request;
}

function getAccountScanState(status) {
    const st = status || currentDeviceStatus;
    return (st && st.accounts_scan && st.accounts_scan.state) || 'idle';
}

// While the phone is being scanned for WhatsApp backups, re-poll quickly so the sync modal
// shows the result as soon as it lands instead of waiting for the 5 s background poll.
function scheduleAccountScanWatch(status) {
    const syncModal = document.getElementById('modalSync');
    const watching = syncModal && syncModal.classList.contains('open');
    if (getAccountScanState(status) !== 'scanning' || !watching || _accountScanWatchTimer) return;
    _accountScanWatchTimer = setTimeout(() => {
        _accountScanWatchTimer = null;
        checkDeviceStatus();
    }, 1500);
}

async function _fetchDeviceStatus(options = {}) {
    if (isServerShuttingDown) return null;
    if (!isHttpServer) {
        updateDevicePill({ connected: false, authorized: false, offline: true });
        return null;
    }
    const seq = ++_deviceStatusSeq;
    const params = new URLSearchParams();
    if (options.refresh) params.set('refresh', '1');
    if (options.wait) params.set('wait', String(options.wait));
    const query = params.toString();
    try {
        const resp = await fetch('/api/device-status' + (query ? '?' + query : ''));
        if (resp.ok) {
            consecutiveServerFailures = 0;
            const data = await resp.json();

            // Requests can finish out of order (a waiting request outlives later polls). Only apply
            // a response that is newer, or that carries a newer completed account scan.
            const finishedAt = (s) => (s && s.accounts_scan && s.accounts_scan.finished_at) || 0;
            if (seq < _deviceStatusAppliedSeq && finishedAt(data) <= finishedAt(currentDeviceStatus)) {
                return data;
            }
            _deviceStatusAppliedSeq = Math.max(_deviceStatusAppliedSeq, seq);

            const newFingerprint = `${data.connected}_${data.authorized}_${data.serial}_${data.model}`;
            const statusChanged = (newFingerprint !== lastDeviceFingerprint);
            lastDeviceFingerprint = newFingerprint;
            const accountsKey = (s) => s ? `${getAccountScanState(s)}_${(s.accounts || []).length}_${s.selected_account ? s.selected_account.path : ''}` : '';
            const accountsChanged = accountsKey(data) !== accountsKey(currentDeviceStatus);

            currentDeviceStatus = data;
            updateDevicePill(data);
            if (typeof updateSyncModalBackupAge === 'function') {
                updateSyncModalBackupAge();
            }
            scheduleAccountScanWatch(data);

            // If modalDevice is currently open, dynamically update or re-render
            const modalEl = document.getElementById('modalDevice');
            if (modalEl && modalEl.classList.contains('open')) {
                if (statusChanged) {
                    if (data.connected && data.authorized) {
                        stopDeviceWaiting();
                        showToast(`Device ready: ${data.model || 'Connected'}`, 'success');
                    } else if (data.connected && !data.authorized && activeWaitingMode === 'detecting') {
                        // Transition from detecting to waiting for authorization
                        activeWaitingMode = 'authorizing';
                        waitingSecondsLeft = 20;
                        showToast('Device detected! Tap "Allow USB debugging" on phone.', 'warning');
                    } else if (!data.connected && activeWaitingMode) {
                        stopDeviceWaiting();
                        showToast('Device disconnected.', 'info');
                    }
                    renderDeviceModalBody();
                } else if (activeWaitingMode) {
                    updateWaitingDisplay();
                } else if (accountsChanged) {
                    renderDeviceModalBody();
                }
            }

            // Real-time device event hook for Reclaim Studio
            if (currentViewMode === 'reclaim') {
                if (data.connected && data.authorized) {
                    if (!window._isPhoneConnectedForClean || statusChanged) {
                        loadPhoneStorageInfo();
                    }
                } else if (!data.connected && window._isPhoneConnectedForClean) {
                    loadPhoneStorageInfo();
                }
            }
            return data;
        } else if (resp.status >= 500) {
            consecutiveServerFailures++;
            if (consecutiveServerFailures >= 3) {
                if (!isServerShuttingDown && !isShutdownInitiator) {
                    renderShutdownScreen(false);
                }
            }
        }
    } catch (e) {
        consecutiveServerFailures++;
        updateDevicePill({ connected: false, authorized: false });
        if (consecutiveServerFailures >= 3) {
            if (!isServerShuttingDown && !isShutdownInitiator) {
                renderShutdownScreen(false);
            }
        }
    }
    return null;
}

function updateDevicePill(status) {
    const dot = document.getElementById('deviceDot');
    const text = document.getElementById('deviceText');
    if (!dot || !text) return;

    if (status.offline) {
        dot.className = 'status-dot dot-none';
        text.innerText = 'Static File Mode';
        return;
    }

    if (status.connected && status.authorized) {
        dot.className = 'status-dot dot-ready';
        const label = status.model || status.serial || 'Device';
        text.innerText = `${label}: Ready`;
    } else if (status.connected && !status.authorized) {
        dot.className = 'status-dot dot-action';
        if (status.usb_debugging === false) {
            const label = status.model || 'Phone';
            text.innerText = `${label}: Enable USB Debugging`;
        } else {
            text.innerText = 'Allow USB on Phone';
        }
    } else {
        dot.className = 'status-dot dot-none';
        text.innerText = 'No Device Detected';
    }
}

let _lastDevStateKey = null;
async function openDeviceModal() {
    renderDeviceModalBody();
    openModal('modalDevice');
    if (isHttpServer) {
        await checkDeviceStatus();
        renderDeviceModalBody();
        _lastDevStateKey = `${currentDeviceStatus.connected}-${currentDeviceStatus.authorized}-${currentDeviceStatus.usb_debugging}-${currentDeviceStatus.serial}`;
        // Active polling while modal is open (every 1.2s) so cable plug/unplug reflects immediately
        if (modalDevicePollTimer) clearInterval(modalDevicePollTimer);
        modalDevicePollTimer = setInterval(async () => {
            await checkDeviceStatus();
            const stateKey = `${currentDeviceStatus.connected}-${currentDeviceStatus.authorized}-${currentDeviceStatus.usb_debugging}-${currentDeviceStatus.serial}`;
            if (stateKey !== _lastDevStateKey && !activeWaitingMode) {
                _lastDevStateKey = stateKey;
                renderDeviceModalBody();
            }
        }, 1200);
    }
}

function stopDeviceWaiting() {
    if (waitingTimerInterval) {
        clearInterval(waitingTimerInterval);
        waitingTimerInterval = null;
    }
    activeWaitingMode = null;
    waitingSecondsLeft = 0;
    renderDeviceModalBody();
}

function startDeviceWaiting(mode, durationSeconds) {
    if (waitingTimerInterval) clearInterval(waitingTimerInterval);
    activeWaitingMode = mode;
    waitingSecondsLeft = durationSeconds;

    renderDeviceModalBody();

    // Run active 1-second polling loop
    waitingTimerInterval = setInterval(async () => {
        waitingSecondsLeft--;
        if (!activeWaitingMode) {
            clearInterval(waitingTimerInterval);
            waitingTimerInterval = null;
            return;
        }

        if (waitingSecondsLeft <= 0) {
            const timedOutMode = activeWaitingMode;
            stopDeviceWaiting();
            if (timedOutMode === 'detecting') {
                showToast('Search timed out. No device detected.', 'info');
            } else {
                showToast('Authorization wait timed out. Check your phone screen and try again.', 'warning');
            }
            return;
        }

        // Actively poll on every tick
        await checkDeviceStatus();
        updateWaitingDisplay();
    }, 1000);
}

function updateWaitingDisplay() {
    const btnAction = document.getElementById('btnDeviceAction');
    const countdownEl = document.getElementById('deviceWaitingCountdown');
    if (countdownEl) {
        countdownEl.innerText = `${waitingSecondsLeft}s`;
    }
    if (btnAction && activeWaitingMode) {
        btnAction.disabled = false;
        const label = activeWaitingMode === 'detecting' ? 'Searching' : 'Waiting';
        btnAction.innerHTML = `
                    <div class="sync-spinner" style="width:13px;height:13px;border:2px solid rgba(255,255,255,0.4);border-top-color:#ffffff;display:inline-block;margin-right:8px;vertical-align:middle;"></div>
                    <span>${label} (${waitingSecondsLeft}s)... <span style="font-size:11px;opacity:0.85;text-decoration:underline;margin-left:4px;">Cancel</span></span>
                `;
    }
}

function renderDeviceModalBody() {
    const body = document.getElementById('modalDeviceBody');
    const btnAction = document.getElementById('btnDeviceAction');
    if (!body) return;

    if (!isHttpServer) {
        body.innerHTML = `
                    <p style="color:var(--text-secondary);">
                        The gallery is open as a static file (<code>file://</code>).
                        Device management requires running the local server.
                    </p>
                    <div style="background:rgba(255,255,255,0.05);padding:12px;border-radius:6px;margin-top:12px;">
                        Launch <strong>start_gallery.bat</strong> or <strong>WhatsApp Organizer.bat</strong> to enable full device controls.
                    </div>
                `;
        if (btnAction) btnAction.style.display = 'none';
        return;
    }

    // Case A: Active waiting countdown is running
    if (activeWaitingMode === 'detecting') {
        body.innerHTML = `
                    <div style="background:rgba(59,130,246,0.1);border:1px solid rgba(59,130,246,0.25);padding:14px;border-radius:8px;margin-bottom:16px;">
                        <div style="display:flex;align-items:center;gap:10px;">
                            <div class="sync-spinner" style="width:16px;height:16px;border-width:2px;"></div>
                            <strong style="color:#60a5fa;font-size:14px;">Scanning for USB Connection... (<span id="deviceWaitingCountdown">${waitingSecondsLeft}s</span>)</strong>
                        </div>
                        <p style="margin-top:8px;font-size:13px;color:var(--text-primary);line-height:1.5;">
                            Scanning for attached devices. Please plug in your phone via a data-capable USB cable now.
                        </p>
                    </div>
                    <ul style="margin-left:20px;font-size:13px;line-height:1.8;color:var(--text-secondary);">
                        <li>Ensure USB debugging is enabled in Developer Options.</li>
                        <li>Use a data-capable USB cable directly connected to the computer.</li>
                        <li>Select "File Transfer" mode if prompted on your phone screen.</li>
                    </ul>
                `;
        updateWaitingDisplay();
        return;
    }

    if (activeWaitingMode === 'authorizing') {
        body.innerHTML = `
                    <div style="background:rgba(245,158,11,0.1);border:1px solid rgba(245,158,11,0.25);padding:14px;border-radius:8px;margin-bottom:16px;">
                        <div style="display:flex;align-items:center;gap:10px;">
                            <div class="sync-spinner" style="width:16px;height:16px;border-width:2px;border-top-color:#fbbf24;"></div>
                            <strong style="color:#fbbf24;font-size:14px;">Waiting for Phone Authorization... (<span id="deviceWaitingCountdown">${waitingSecondsLeft}s</span>)</strong>
                        </div>
                        <p style="margin-top:8px;font-size:13px;color:var(--text-primary);line-height:1.5;">
                            Device detected (<strong>${escapeHtml(currentDeviceStatus.serial || 'USB Device')}</strong>). Please unlock your phone and tap <strong>"Allow"</strong>.
                        </p>
                    </div>
                    <ol style="margin-left:20px;font-size:13px;line-height:1.8;color:var(--text-secondary);">
                        <li>Unlock your Android phone screen.</li>
                        <li>Look for the prompt: <strong>"Allow USB debugging?"</strong></li>
                        <li>Check <strong>"Always allow from this computer"</strong> and tap <strong>OK</strong>.</li>
                    </ol>
                `;
        updateWaitingDisplay();
        return;
    }

    // Case B: Connected & Authorized (Ready)
    if (currentDeviceStatus.connected && currentDeviceStatus.authorized) {
        const selAcc = currentDeviceStatus.selected_account;
        const hasMulti = Boolean(currentDeviceStatus.has_multiple_accounts);
        let accountCardHtml = '';
        if (!selAcc && getAccountScanState() === 'scanning') {
            accountCardHtml = `
                        <div style="margin-bottom:14px;padding:12px 14px;background:rgba(59,130,246,0.08);border:1px solid rgba(59,130,246,0.25);border-radius:8px;display:flex;align-items:center;gap:10px;font-size:13px;color:#93c5fd;">
                            <div class="sync-spinner" style="width:14px;height:14px;border-width:2px;"></div>
                            <span>Scanning phone for WhatsApp accounts and backups...</span>
                        </div>
                    `;
        } else if (selAcc) {
            const isBiz = selAcc.app_type === 'whatsapp_business';
            const badgeColor = isBiz ? '#3b82f6' : 'var(--accent)';
            const badgeBg = isBiz ? 'rgba(59,130,246,0.15)' : 'rgba(16,185,129,0.15)';
            const badgeText = isBiz ? 'WhatsApp Business' : 'WhatsApp';
            const phoneOrId = selAcc.phone_number ? (selAcc.push_name ? `${selAcc.phone_number} (${selAcc.push_name})` : selAcc.phone_number) : (selAcc.account_id !== 'main' ? `Account ${selAcc.account_id}` : 'Primary Account');
            accountCardHtml = `
                        <div style="margin-bottom:14px;padding:14px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:8px;">
                            <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:8px;">
                                <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                                    <span style="font-size:11px;font-weight:700;padding:2px 8px;border-radius:4px;background:${badgeBg};color:${badgeColor};border:1px solid ${badgeColor}40;">
                                        ${badgeText}
                                    </span>
                                    <strong style="font-size:14px;color:var(--text-primary);">${escapeHtml(phoneOrId)}</strong>
                                </div>
                                ${hasMulti ? `<button class="action-btn" style="font-size:11px;padding:4px 10px;background:rgba(255,255,255,0.08);border:1px solid rgba(255,255,255,0.15);" onclick="openAccountSelectorModal()">Switch Account</button>` : ''}
                            </div>
                            <div style="font-size:12px;color:var(--text-secondary);display:flex;flex-wrap:wrap;gap:12px;margin-top:6px;">
                                <span><strong>Backup:</strong> ${escapeHtml(selAcc.latest_db_file || 'msgstore.db')} (${escapeHtml(selAcc.latest_backup_str || 'N/A')} • ${escapeHtml(selAcc.size_str || '0 MB')})</span>
                            </div>
                            <div style="font-size:11px;color:var(--text-muted);margin-top:4px;word-break:break-all;font-family:monospace;">
                                ${escapeHtml(selAcc.path)}
                            </div>
                        </div>
                    `;
        }

        body.innerHTML = `
                    <div style="display:flex;align-items:center;gap:12px;background:rgba(16,185,129,0.1);border:1px solid rgba(16,185,129,0.25);padding:14px;border-radius:8px;margin-bottom:12px;">
                        <svg class="icon" viewBox="0 0 24 24" style="width:24px;height:24px;fill:var(--accent);"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z"/></svg>
                        <div>
                            <strong style="color:var(--text-primary);font-size:14px;">Android Device Connected and Authorized</strong>
                            <div style="font-size:12px;color:var(--text-secondary);margin-top:2px;">
                                Model: ${escapeHtml(currentDeviceStatus.model || 'Unknown')} | Serial: ${escapeHtml(currentDeviceStatus.serial || 'Unknown')}
                            </div>
                        </div>
                    </div>
                    ${accountCardHtml}
                    <div style="padding:14px;background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.08);border-radius:8px;">
                        <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;">
                            <div style="flex:1;min-width:200px;">
                                <div style="font-size:13px;font-weight:600;color:var(--text-primary);display:flex;align-items:center;gap:6px;">
                                    <svg class="icon" viewBox="0 0 24 24" style="width:16px;height:16px;fill:#fbbf24;"><path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4zm0 10.99h7c-.53 4.12-3.28 7.79-7 8.94V12H5V6.3l7-3.11v8.8z"/></svg>
                                    Banking Apps &amp; Safety
                                </div>
                                <div style="font-size:12px;color:var(--text-secondary);margin-top:4px;line-height:1.4;">
                                    Turn off Developer Options via USB before disconnecting so banking apps (YONO SBI, Google Pay, PhonePe) work immediately.
                                </div>
                            </div>
                            <button class="action-btn" id="btnDisableDevOptions" style="background:rgba(245,158,11,0.15);border:1px solid rgba(245,158,11,0.3);color:#fbbf24;white-space:nowrap;font-size:12px;padding:8px 14px;" onclick="handleDisableDeveloperOptions(this, 'devOptionsFeedback')">
                                Disable Developer Options
                            </button>
                        </div>
                        <div id="devOptionsFeedback" style="font-size:12px;margin-top:10px;"></div>
                    </div>
                `;
        if (btnAction) {
            btnAction.disabled = false;
            btnAction.innerText = 'Refresh Status';
            btnAction.style.display = 'inline-block';
        }
    } else if (currentDeviceStatus.connected && !currentDeviceStatus.authorized) {
        // Case C: Connected but Unauthorized
        if (currentDeviceStatus.usb_debugging === false) {
            // Case C1: Physically plugged in, but USB Debugging is OFF
            body.innerHTML = `
                        <div style="background:rgba(59,130,246,0.1);border:1px solid rgba(59,130,246,0.25);padding:14px;border-radius:8px;margin-bottom:16px;">
                            <div style="display:flex;align-items:center;gap:8px;">
                                <svg class="icon" viewBox="0 0 24 24" style="width:20px;height:20px;fill:#60a5fa;"><path d="M17 1.01L7 1c-1.1 0-2 .9-2 2v18c0 1.1.9 2 2 2h10c1.1 0 2-.9 2-2V3c0-1.1-.9-1.99-2-1.99zM17 19H7V5h10v14z"/></svg>
                                <strong style="color:#60a5fa;font-size:14px;">Phone Plugged In (${escapeHtml(currentDeviceStatus.model || 'Android')}), but USB Debugging is OFF</strong>
                            </div>
                            <p style="margin-top:8px;font-size:13px;color:var(--text-primary);line-height:1.5;">
                                Your device is physically connected via USB. WhatsApp Organizer requires <strong>USB Debugging</strong> enabled to sync and back up your chat data.
                            </p>
                        </div>
                        <ol style="margin-left:20px;font-size:13px;line-height:1.8;color:var(--text-secondary);">
                            <li>Open <strong>Settings</strong> on your phone.</li>
                            <li>Go to <strong>About Phone</strong> and tap <strong>Build Number</strong> 7 times (enter PIN if prompted).</li>
                            <li>Go to <strong>System &gt; Developer Options</strong> (or Additional Settings).</li>
                            <li>Turn ON <strong>USB Debugging</strong>.</li>
                        </ol>
                        <div style="margin-top:12px;padding:10px 14px;background:rgba(16,185,129,0.1);border:1px solid rgba(16,185,129,0.25);border-radius:6px;display:flex;align-items:center;justify-content:space-between;gap:8px;">
                            <span style="font-size:12px;color:var(--text-secondary);">Developer Options &amp; USB Debugging:</span>
                            <span style="font-size:12px;font-weight:600;color:var(--accent);background:rgba(16,185,129,0.15);padding:3px 8px;border-radius:4px;">OFF (Banking Apps Safe)</span>
                        </div>
                    `;
            if (btnAction) {
                btnAction.disabled = false;
                btnAction.innerText = 'Check Again';
                btnAction.style.display = 'inline-block';
            }
        } else {
            // Case C2: USB debugging enabled, waiting for screen authorization
            body.innerHTML = `
                        <div style="background:rgba(245,158,11,0.1);border:1px solid rgba(245,158,11,0.25);padding:14px;border-radius:8px;margin-bottom:16px;">
                            <strong style="color:#fbbf24;font-size:14px;">Action Required on Your Phone Screen</strong>
                            <p style="margin-top:6px;font-size:13px;color:var(--text-primary);">
                                Device detected (<strong>${escapeHtml(currentDeviceStatus.serial || currentDeviceStatus.model || 'USB Device')}</strong>) but USB debugging is unauthorized.
                            </p>
                        </div>
                        <ol style="margin-left:20px;font-size:13px;line-height:1.8;color:var(--text-secondary);">
                            <li>Unlock your Android phone.</li>
                            <li>Look for the prompt: <strong>"Allow USB debugging?"</strong></li>
                            <li>Check <strong>"Always allow from this computer"</strong> and tap <strong>OK</strong>.</li>
                        </ol>
                    `;
            if (btnAction) {
                btnAction.disabled = false;
                btnAction.innerText = 'Wait for Authorization';
                btnAction.style.display = 'inline-block';
            }
        }
    } else {
        // Case D: Disconnected
        body.innerHTML = `
                    <div style="background:rgba(255,255,255,0.04);border:1px solid var(--border-color);padding:14px;border-radius:8px;margin-bottom:16px;">
                        <strong style="color:var(--text-primary);font-size:14px;">No Android Device Detected</strong>
                        <p style="margin-top:6px;font-size:13px;color:var(--text-secondary);">
                            Please connect your phone via a USB cable.
                        </p>
                    </div>
                    <ul style="margin-left:20px;font-size:13px;line-height:1.8;color:var(--text-secondary);">
                        <li>Ensure USB debugging is enabled in Developer Options.</li>
                        <li>Use a data-capable USB cable directly connected to the computer.</li>
                        <li>Select "File Transfer" mode if prompted on your phone.</li>
                    </ul>
                `;
        if (btnAction) {
            btnAction.disabled = false;
            btnAction.innerText = 'Detect Phone';
            btnAction.style.display = 'inline-block';
        }
    }
}

function openAccountSelectorModal() {
    renderAccountSelectorModalBody();
    openModal('modalAccountSelector');
}

function renderAccountSelectorModalBody() {
    const body = document.getElementById('modalAccountSelectorBody');
    if (!body) return;
    const accounts = (currentDeviceStatus && currentDeviceStatus.accounts) ? currentDeviceStatus.accounts : [];
    if (!accounts.length) {
        body.innerHTML = `
                    <p style="color:var(--text-secondary);font-size:13px;">
                        No active WhatsApp accounts detected on the connected device.
                    </p>
                `;
        return;
    }

    const currentSelectedPath = (currentDeviceStatus && currentDeviceStatus.selected_account_path) ||
        (currentDeviceStatus && currentDeviceStatus.selected_account && currentDeviceStatus.selected_account.path) ||
        accounts[0].path;

    let html = `
                <p style="font-size:13px;color:var(--text-secondary);margin-bottom:14px;">
                    Multiple WhatsApp installations or accounts were found on your device. Choose which account to synchronize:
                </p>
                <div style="display:flex;flex-direction:column;gap:10px;">
            `;

    accounts.forEach((acc) => {
        const isSelected = (acc.path === currentSelectedPath);
        const isBiz = acc.app_type === 'whatsapp_business';
        const badgeColor = isBiz ? '#3b82f6' : 'var(--accent)';
        const badgeBg = isBiz ? 'rgba(59,130,246,0.15)' : 'rgba(16,185,129,0.15)';
        const badgeText = isBiz ? 'WhatsApp Business' : 'WhatsApp';
        const hasValidPhone = acc.phone_number && !['whatsapp', 'whatsapp business', 'unknown'].includes(acc.phone_number.toLowerCase());
        const phoneOrId = hasValidPhone ? (acc.push_name ? `${acc.phone_number} (${acc.push_name})` : acc.phone_number) : (acc.account_id !== 'main' ? `Account ${acc.account_id}` : (isBiz ? 'Business Account' : 'Primary Account'));
        const isRec = Boolean(acc.is_active_recommendation);

        html += `
                    <label style="display:block;padding:12px 14px;background:rgba(255,255,255,0.03);border:1px solid ${isSelected ? 'var(--accent)' : 'rgba(255,255,255,0.1)'};border-radius:8px;cursor:pointer;transition:border-color 0.2s;" onmouseover="this.style.borderColor='var(--accent)'" onmouseout="if(!this.querySelector('input').checked)this.style.borderColor='rgba(255,255,255,0.1)'">
                        <div style="display:flex;align-items:flex-start;gap:12px;">
                            <input type="radio" name="accSelectionRadio" value="${escapeHtml(acc.path)}" data-phone="${escapeHtml(acc.phone_number || '')}" ${isSelected ? 'checked' : ''} style="margin-top:3px;accent-color:var(--accent);">
                            <div style="flex:1;">
                                <div style="display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap;">
                                    <div style="display:flex;align-items:center;gap:8px;">
                                        <span style="font-size:11px;font-weight:700;padding:2px 8px;border-radius:4px;background:${badgeBg};color:${badgeColor};border:1px solid ${badgeColor}40;">
                                            ${badgeText}
                                        </span>
                                        <strong style="font-size:14px;color:var(--text-primary);">${escapeHtml(phoneOrId)}</strong>
                                    </div>
                                    ${isRec ? `<span style="font-size:11px;color:var(--accent);background:rgba(16,185,129,0.12);padding:2px 8px;border-radius:10px;font-weight:600;">Recommended (Freshest)</span>` : ''}
                                </div>
                                <div style="font-size:12px;color:var(--text-secondary);margin-top:6px;display:flex;flex-wrap:wrap;gap:12px;">
                                    <span><strong>Backup:</strong> ${escapeHtml(acc.latest_db_file || 'msgstore.db')} (${escapeHtml(acc.latest_backup_str || 'N/A')})</span>
                                    <span><strong>Size:</strong> ${escapeHtml(acc.size_str || '0 MB')}</span>
                                </div>
                                <div style="font-size:11px;color:var(--text-muted);margin-top:4px;word-break:break-all;font-family:monospace;">
                                    ${escapeHtml(acc.path)}
                                </div>
                            </div>
                        </div>
                    </label>
                `;
    });

    html += `</div>`;
    body.innerHTML = html;
}

async function confirmAccountSelection() {
    const checked = document.querySelector('input[name="accSelectionRadio"]:checked');
    if (!checked) {
        closeModal('modalAccountSelector');
        return;
    }
    const path = checked.value;
    const phone = checked.getAttribute('data-phone') || '';
    const btn = document.getElementById('btnConfirmAccountSelection');
    if (btn) btn.disabled = true;

    try {
        const resp = await fetch('/api/phone/select-account', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ account_path: path, phone_number: phone })
        });
        const res = await resp.json();
        if (resp.ok) {
            showToast('WhatsApp account updated.', 'success');
            if (currentDeviceStatus) {
                currentDeviceStatus.selected_account_path = path;
                currentDeviceStatus.has_selected_account = true;
                if (currentDeviceStatus.accounts) {
                    const found = currentDeviceStatus.accounts.find(a => a.path === path);
                    if (found) currentDeviceStatus.selected_account = found;
                }
            }
            await checkDeviceStatus();
            closeModal('modalAccountSelector');
            if (window._pendingSyncAfterAccountSelect) {
                window._pendingSyncAfterAccountSelect = false;
                // Resume the interrupted pre-flight instead of making the user click Start again
                setTimeout(async () => {
                    await openSyncModal();
                    const summaryView = document.getElementById('syncViewSummary');
                    if (summaryView && summaryView.style.display !== 'none') {
                        startSyncFromSummary();
                    }
                }, 300);
            }
        } else {
            showToast(res.message || 'Failed to update account.', 'error');
        }
    } catch (e) {
        showToast(`Error: ${e.message}`, 'error');
    } finally {
        if (btn) btn.disabled = false;
    }
}

async function handleDeviceAction() {
    const btnAction = document.getElementById('btnDeviceAction');
    if (!isHttpServer) return;

    // If in active waiting mode, clicking cancels the wait
    if (activeWaitingMode) {
        stopDeviceWaiting();
        showToast('Wait cancelled.', 'info');
        return;
    }

    // Case 1: Phone is disconnected -> Fast detection, if not detected start 15s search!
    if (!currentDeviceStatus || !currentDeviceStatus.connected) {
        if (btnAction) {
            btnAction.disabled = true;
            btnAction.innerHTML = '<div class="sync-spinner" style="width:13px;height:13px;border:2px solid rgba(255,255,255,0.4);border-top-color:#ffffff;display:inline-block;margin-right:8px;vertical-align:middle;"></div><span>Detecting...</span>';
        }
        await checkDeviceStatus();
        if (currentDeviceStatus.connected) {
            renderDeviceModalBody();
            showToast(currentDeviceStatus.authorized ? `Device ready: ${currentDeviceStatus.model || 'Connected'}` : 'Device detected! Check phone screen.', 'success');
        } else {
            startDeviceWaiting('detecting', 15);
        }
        return;
    }

    // Case 2: Phone is connected & authorized -> Instant refresh
    if (currentDeviceStatus.connected && currentDeviceStatus.authorized) {
        if (btnAction) {
            btnAction.disabled = true;
            btnAction.innerHTML = '<div class="sync-spinner" style="width:13px;height:13px;border:2px solid rgba(255,255,255,0.4);border-top-color:#ffffff;display:inline-block;margin-right:8px;vertical-align:middle;"></div><span>Checking...</span>';
        }
        await checkDeviceStatus();
        renderDeviceModalBody();
        showToast(`Device ready: ${currentDeviceStatus.model || 'Connected'}`, 'success');
        return;
    }

    // Case 3: Phone is connected but unauthorized
    if (currentDeviceStatus.connected && !currentDeviceStatus.authorized) {
        if (currentDeviceStatus.usb_debugging === false) {
            if (btnAction) {
                btnAction.disabled = true;
                btnAction.innerHTML = '<div class="sync-spinner" style="width:13px;height:13px;border:2px solid rgba(255,255,255,0.4);border-top-color:#ffffff;display:inline-block;margin-right:8px;vertical-align:middle;"></div><span>Checking...</span>';
            }
            await checkDeviceStatus();
            renderDeviceModalBody();
            if (currentDeviceStatus.usb_debugging) {
                showToast('USB Debugging detected! Please tap Allow on your phone screen.', 'success');
            } else {
                showToast(`Phone connected (${currentDeviceStatus.model || 'Android'}). Please turn ON USB Debugging in Settings.`, 'info');
            }
        } else {
            startDeviceWaiting('authorizing', 20);
        }
    }
}

async function handleDisableDeveloperOptions(btnEl, feedbackId) {
    if (!isHttpServer) return;
    const feedbackEl = document.getElementById(feedbackId);
    const origText = btnEl ? btnEl.innerHTML : 'Disable Developer Options';

    // Check if already disabled
    if (currentDeviceStatus && currentDeviceStatus.connected && currentDeviceStatus.usb_debugging === false) {
        if (feedbackEl) {
            feedbackEl.style.color = 'var(--accent)';
            feedbackEl.innerHTML = '<strong>Already Disabled:</strong> USB Debugging is turned OFF. Banking apps are active and safe!';
        }
        if (btnEl) {
            btnEl.style.background = 'rgba(16,185,129,0.15)';
            btnEl.style.borderColor = 'rgba(16,185,129,0.3)';
            btnEl.style.color = 'var(--accent)';
            btnEl.innerHTML = 'Already Disabled';
            btnEl.disabled = true;
        }
        showToast('USB Debugging is already turned off on your phone.', 'success');
        return;
    }

    if (!currentDeviceStatus || !currentDeviceStatus.connected) {
        if (feedbackEl) {
            feedbackEl.style.color = 'var(--danger)';
            feedbackEl.innerText = 'No Android phone detected. Connect phone via USB first.';
        }
        showToast('No Android phone detected.', 'warning');
        return;
    }

    if (!currentDeviceStatus.authorized) {
        if (feedbackEl) {
            feedbackEl.style.color = '#fbbf24';
            feedbackEl.innerText = 'Device unauthorized. Please unlock your phone and tap "Allow USB debugging".';
        }
        showToast('Please unlock your phone and tap "Allow USB debugging".', 'warning');
        return;
    }

    if (btnEl) {
        btnEl.disabled = true;
        btnEl.innerHTML = `
                    <div class="sync-spinner" style="width:12px;height:12px;border-width:2px;display:inline-block;margin-right:6px;"></div>
                    Disabling...
                `;
    }
    if (feedbackEl) {
        feedbackEl.style.color = 'var(--text-secondary)';
        feedbackEl.innerText = 'Sending ADB command to phone...';
    }

    try {
        const resp = await fetch('/api/disable-developer-options', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' }
        });
        let res = {};
        try {
            res = await resp.json();
        } catch (jsonErr) {
            res = { message: 'Server communication error' };
        }

        if (resp.ok && res.status === 'success') {
            if (feedbackEl) {
                feedbackEl.style.color = 'var(--accent)';
                feedbackEl.innerHTML = '<strong>Success:</strong> Developer Options and USB Debugging disabled! Banking apps restored. Safe to unplug.';
            }
            if (btnEl) {
                btnEl.style.background = 'rgba(16,185,129,0.15)';
                btnEl.style.borderColor = 'rgba(16,185,129,0.3)';
                btnEl.style.color = 'var(--accent)';
                btnEl.innerHTML = 'Disabled Successfully';
                btnEl.disabled = true;
            }
            showToast('Developer Options and USB Debugging disabled on phone.', 'success');
            setTimeout(async () => {
                await checkDeviceStatus();
                renderDeviceModalBody();
            }, 1500);
        } else {
            if (feedbackEl) {
                feedbackEl.style.color = 'var(--danger)';
                feedbackEl.innerText = res.message || 'Failed to disable Developer Options.';
            }
            if (btnEl) {
                btnEl.disabled = false;
                btnEl.innerHTML = origText;
            }
            showToast(res.message || 'Failed to disable Developer Options.', 'error');
        }
    } catch (e) {
        if (feedbackEl) {
            feedbackEl.style.color = 'var(--danger)';
            feedbackEl.innerText = `Error: ${e.message}`;
        }
        if (btnEl) {
            btnEl.disabled = false;
            btnEl.innerHTML = origText;
        }
        showToast(`Request failed: ${e.message}`, 'error');
    }
}
