// QR Terminal Display JavaScript - Kiosk Mode

(function() {
    'use strict';

    // Configuration
    const QR_TOKEN_VALIDITY = 60; // 60 seconds (server-side expiry)
    const QR_GRACE_PERIOD = 15; // 15 seconds grace period after expiry
    const WEBSOCKET_RECONNECT_BASE_DELAY = 5000; // 5 seconds initial delay
    const WEBSOCKET_RECONNECT_MAX_DELAY = 60000; // 60 seconds cap

    /**
     * Escape HTML-special characters to prevent stored XSS via innerHTML.
     */
    function escapeHtml(value) {
        return String(value == null ? '' : value).replace(/[&<>"']/g, function(c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }

    // DOM Elements
    const elements = {
        currentTime: document.getElementById('currentTime'),
        currentDate: document.getElementById('currentDate'),
        connectionStatus: document.querySelector('.connection-status'),
        statusDot: document.querySelector('.status-dot'),
        statusText: document.querySelector('.status-text'),

        qrCodeContainer: document.getElementById('qrCodeContainer'),
        countdown: document.getElementById('countdown'),
        progressBar: document.getElementById('progressBar'),

        recentFeed: document.getElementById('recentFeed'),

        errorOverlay: document.getElementById('errorOverlay'),
        errorTitle: document.getElementById('errorTitle'),
        errorMessage: document.getElementById('errorMessage'),
        retryButton: document.getElementById('retryButton'),

        // Location selector elements
        locationButtons: document.getElementById('locationButtons')
    };

    // State
    let terminalData = null;
    let currentQRToken = null;
    let qrExpiryTime = null;
    let countdownInterval = null;
    let refreshTimeout = null;
    let websocket = null;
    let websocketReconnectAttempt = 0;
    // device_ids whose attendance broadcasts should land in this kiosk's
    // feed. Initialised to [TERMINAL_ID] so the QR-only fallback works
    // before /kiosk/{id} resolves. The fetched response may add more
    // (typically the fingerprint scanner at this branch).
    let allowedDeviceIds = new Set([Number(TERMINAL_ID)]);

    /**
     * Initialize terminal
     */
    function init() {
        console.log(`[QR Terminal] Initializing terminal ${TERMINAL_ID}...`);

        // Start clock
        updateClock();
        setInterval(updateClock, 1000);

        // Load available terminals for location selector
        loadAvailableTerminals();

        // Load terminal data
        loadTerminalData();

        // Backfill today's recent activity for THIS branch from DB
        loadRecentForTerminal();

        // Setup event listeners
        setupEventListeners();

        // Connect WebSocket
        connectWebSocket();
    }

    /**
     * Backfill the recent-activity feed with today's records for THIS terminal.
     * Strictly scoped server-side by device_id so HF and HF Ville never mix.
     */
    async function loadRecentForTerminal() {
        try {
            const response = await fetch(`/api/public/qr-checkin/recent/${TERMINAL_ID}?limit=10`);
            if (!response.ok) {
                console.warn('[Recent] Backfill request failed:', response.status);
                return;
            }
            const data = await response.json();
            if (!data.records || data.records.length === 0) {
                return; // keep the existing empty state
            }
            // Render oldest-first so the newest ends up at the top after prepending.
            const oldestFirst = data.records.slice().reverse();
            oldestFirst.forEach(rec => addFeedItem(rec, false));
            console.log('[Recent] Backfilled', data.records.length, 'records for terminal', TERMINAL_ID);
        } catch (error) {
            console.error('[Recent] Backfill error:', error);
        }
    }

    /**
     * Load available QR terminals for location selector
     */
    async function loadAvailableTerminals() {
        try {
            const response = await fetch('/api/public/qr-checkin/terminals');
            const terminals = await response.json();

            if (response.ok && terminals.length > 0) {
                // Only show selector if there are multiple active terminals
                const activeTerminals = terminals.filter(t => t.is_active);

                if (activeTerminals.length > 1) {
                    renderLocationButtons(activeTerminals);
                } else {
                    // Hide location selector if only one terminal
                    document.getElementById('locationSelector').style.display = 'none';
                }
            } else {
                // Hide selector if no terminals found
                document.getElementById('locationSelector').style.display = 'none';
            }
        } catch (error) {
            console.error('[Location Selector] Error loading terminals:', error);
            // Hide selector on error
            document.getElementById('locationSelector').style.display = 'none';
        }
    }

    /**
     * Render location selector buttons
     */
    function renderLocationButtons(terminals) {
        const container = elements.locationButtons;
        container.innerHTML = '';

        terminals.forEach(terminal => {
            const button = document.createElement('button');
            button.className = 'location-btn';
            button.dataset.terminalId = terminal.id;

            // Mark current terminal as active
            if (terminal.id == TERMINAL_ID) {
                button.classList.add('active');
            }

            const locationLabel = escapeHtml(terminal.location_name || terminal.name);
            button.innerHTML = `
                <span class="location-icon">📍</span>
                <span class="location-name">${locationLabel}</span>
            `;

            button.addEventListener('click', () => switchTerminal(terminal.id));
            container.appendChild(button);
        });

        console.log('[Location Selector] Rendered', terminals.length, 'terminal buttons');
    }

    /**
     * Switch to different terminal
     */
    function switchTerminal(terminalId) {
        if (terminalId == TERMINAL_ID) {
            console.log('[Location Selector] Already on terminal', terminalId);
            return;
        }

        console.log('[Location Selector] Switching to terminal', terminalId);

        // Update URL without page reload
        const url = new URL(window.location);
        url.searchParams.set('terminal', terminalId);
        window.history.pushState({}, '', url);

        // Reload page to reinitialize with new terminal
        window.location.reload();
    }

    /**
     * Load terminal data and QR code
     */
    async function loadTerminalData() {
        try {
            console.log(`[QR Terminal] Loading terminal ${TERMINAL_ID} data...`);

            const response = await fetch(`/api/public/qr-checkin/kiosk/${TERMINAL_ID}`);
            const data = await response.json();

            if (response.ok) {
                terminalData = data;
                console.log('[QR Terminal] Terminal data loaded:', terminalData);

                // Build the allow-set used by the WebSocket filter: this
                // kiosk's own QR scans (device_id == TERMINAL_ID) plus any
                // fingerprint scanners the backend has linked to it.
                allowedDeviceIds = new Set([Number(TERMINAL_ID)]);
                if (Array.isArray(data.linked_fingerprint_device_ids)) {
                    data.linked_fingerprint_device_ids.forEach(id => {
                        allowedDeviceIds.add(Number(id));
                    });
                }
                console.log('[QR Terminal] Allowed device IDs:', [...allowedDeviceIds]);

                // Update UI with terminal info
                updateTerminalInfo();

                // Display QR code
                displayQRCode(data.qr_image, data.expires_at);

                // Update connection status
                updateConnectionStatus('connected', 'เชื่อมต่อแล้ว');

                // Schedule next refresh
                scheduleQRRefresh();
            } else {
                console.error('[QR Terminal] Failed to load terminal data:', data);
                showError('ไม่สามารถโหลดข้อมูลเทอร์มินัลได้', data.message || 'กรุณาลองใหม่อีกครั้ง');
            }
        } catch (error) {
            console.error('[QR Terminal] Error loading terminal data:', error);
            showError('เกิดข้อผิดพลาด', 'ไม่สามารถเชื่อมต่อกับเซิร์ฟเวอร์ได้');
        }
    }

    /**
     * Update terminal information display
     */
    function updateTerminalInfo() {
        if (!terminalData) return;

        // Terminal name is now displayed only in the location selector
        // No additional UI updates needed here
    }

    /**
     * Display QR code
     */
    function displayQRCode(qrImageDataUri, expiresAt) {
        // Create QR code image
        const img = document.createElement('img');
        // API returns complete data URI, use directly
        img.src = qrImageDataUri;
        img.alt = 'QR Code';
        img.style.width = '100%';
        img.style.maxWidth = '400px';

        // Clear container and add image
        elements.qrCodeContainer.innerHTML = '';
        elements.qrCodeContainer.appendChild(img);

        // Store expiry time
        qrExpiryTime = new Date(expiresAt);

        // Start countdown
        startCountdown();

        console.log('[QR Terminal] QR code displayed, expires at:', qrExpiryTime);
    }

    /**
     * Start countdown timer
     */
    function startCountdown() {
        if (countdownInterval) {
            clearInterval(countdownInterval);
        }

        countdownInterval = setInterval(() => {
            const now = new Date();
            const remaining = Math.max(0, Math.floor((qrExpiryTime - now) / 1000));

            // Update countdown display
            elements.countdown.textContent = remaining;

            // Update countdown color
            elements.countdown.classList.remove('warning', 'danger');
            if (remaining <= 10) {
                elements.countdown.classList.add('danger');
            } else if (remaining <= 20) {
                elements.countdown.classList.add('warning');
            }

            // Update progress bar based on actual token validity
            const progress = (remaining / QR_TOKEN_VALIDITY) * 100;
            elements.progressBar.style.width = `${progress}%`;

            // Stop countdown when expired
            if (remaining === 0) {
                clearInterval(countdownInterval);
            }
        }, 1000);
    }

    /**
     * Schedule next QR code refresh
     * Dynamically calculates refresh time to prevent showing expired QR codes
     */
    function scheduleQRRefresh() {
        if (refreshTimeout) {
            clearTimeout(refreshTimeout);
        }

        // Calculate actual remaining time until expiry
        const now = new Date();
        const remainingMs = Math.max(0, qrExpiryTime - now);
        const remainingSeconds = Math.floor(remainingMs / 1000);

        // Refresh 2 seconds before expiry to allow for processing time
        // Add grace period to total validity for smooth user experience
        const totalValiditySeconds = QR_TOKEN_VALIDITY + QR_GRACE_PERIOD;
        const refreshInMs = Math.max(1000, remainingMs - 2000);

        console.log(`[QR Terminal] Scheduling refresh in ${Math.floor(refreshInMs/1000)}s (${remainingSeconds}s remaining, ${QR_GRACE_PERIOD}s grace period)`);

        refreshTimeout = setTimeout(() => {
            console.log('[QR Terminal] Auto-refreshing QR code...');
            loadTerminalData();
        }, refreshInMs);
    }

    /**
     * Connect WebSocket for real-time updates
     */
    function connectWebSocket() {
        try {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const host = window.location.host;
            const wsUrl = `${protocol}//${host}/qr-checkin/ws`;

            console.log('[WebSocket] Connecting to:', wsUrl);

            websocket = new WebSocket(wsUrl);

            websocket.onopen = () => {
                console.log('[WebSocket] Connected');
                websocketReconnectAttempt = 0;
                updateConnectionStatus('connected', 'เชื่อมต่อแล้ว');
            };

            // (websocketReconnectAttempt is reset on successful open above)

            websocket.onmessage = (event) => {
                try {
                    const message = JSON.parse(event.data);
                    console.log('[WebSocket] Message received:', message);

                    if (message.type === 'attendance_update') {
                        handleAttendanceUpdate(message.data);
                    }
                } catch (error) {
                    console.error('[WebSocket] Error parsing message:', error);
                }
            };

            websocket.onerror = (error) => {
                console.error('[WebSocket] Error:', error);
                updateConnectionStatus('disconnected', 'การเชื่อมต่อขัดข้อง');
            };

            websocket.onclose = () => {
                console.log('[WebSocket] Disconnected');

                // Exponential backoff capped at WEBSOCKET_RECONNECT_MAX_DELAY
                websocketReconnectAttempt++;
                const backoffDelay = Math.min(
                    WEBSOCKET_RECONNECT_MAX_DELAY,
                    WEBSOCKET_RECONNECT_BASE_DELAY * Math.pow(2, websocketReconnectAttempt - 1)
                );

                updateConnectionStatus(
                    'disconnected',
                    `กำลังลองเชื่อมต่อใหม่... (ครั้งที่ ${websocketReconnectAttempt})`
                );

                console.log(
                    `[WebSocket] Reconnecting in ${Math.floor(backoffDelay / 1000)}s ` +
                    `(attempt ${websocketReconnectAttempt})...`
                );
                setTimeout(connectWebSocket, backoffDelay);
            };
        } catch (error) {
            console.error('[WebSocket] Error creating connection:', error);
        }
    }

    /**
     * Handle attendance update from WebSocket
     */
    function handleAttendanceUpdate(record) {
        console.log('[Attendance] New record:', record);

        // Show records from any device in this kiosk's allow-set: the
        // kiosk's own TERMINAL_ID plus the fingerprint scanners linked to
        // it (e.g. the at-branch ZK device). The old fallback on
        // metadata.includes('QR Check-in') leaked HF ↔ HF Ville and is
        // intentionally gone.
        if (record.device_id != null && allowedDeviceIds.has(Number(record.device_id))) {
            addFeedItem(record, true);
        }
    }

    /**
     * Add item to recent feed
     */
    function addFeedItem(record, isNew = false) {
        // Remove empty state if present
        const emptyState = elements.recentFeed.querySelector('.empty-state');
        if (emptyState) {
            emptyState.remove();
        }

        // Create feed item
        const item = document.createElement('div');
        item.className = `feed-item ${isNew ? 'new' : ''}`;

        const metadata = record.metadata || '';
        const isQR = metadata.includes('QR Check-in') || metadata.includes('QR Check-out');
        const isCheckOut = record.punch_type === 1 || metadata.includes('QR Check-out');
        const actionLabel = isQR
            ? (isCheckOut ? 'QR Check-out' : 'QR Check-in')
            : 'ลายนิ้วมือ';
        const actionIcon = isQR ? (isCheckOut ? '🏃' : '📱') : '👆';
        const locationMatch = metadata.match(/at (.+?),/);
        // API response is flat — terminalData.terminal_name carries the
        // location name (see QRCodeResponse in app/api/qr_checkin.py).
        const location = locationMatch ? locationMatch[1] : (terminalData?.terminal_name || '');

        const safeBadge = escapeHtml(record.badge_number);
        const safeName = escapeHtml(record.employee_name || `รหัส ${record.badge_number}`);
        const safeTime = escapeHtml(formatTime(record.timestamp));
        const safeLocation = escapeHtml(location);
        item.innerHTML = `
            <div class="feed-header">
                <div class="feed-name">${safeName}</div>
                <div class="feed-badge">${safeBadge}</div>
            </div>
            <div class="feed-details">
                <div class="feed-detail">
                    <span>🕐</span>
                    <span>${safeTime}</span>
                </div>
                <div class="feed-detail">
                    <span>${actionIcon}</span>
                    <span>${actionLabel}</span>
                </div>
                ${location ? `
                <div class="feed-detail">
                    <span>📍</span>
                    <span>${safeLocation}</span>
                </div>
                ` : ''}
            </div>
        `;

        // Add to feed (prepend for newest first)
        elements.recentFeed.insertBefore(item, elements.recentFeed.firstChild);

        // Limit to 10 items
        const items = elements.recentFeed.querySelectorAll('.feed-item');
        if (items.length > 10) {
            items[items.length - 1].remove();
        }

        // Remove 'new' class after animation
        if (isNew) {
            setTimeout(() => {
                item.classList.remove('new');
            }, 2000);
        }
    }

    /**
     * Update connection status
     */
    function updateConnectionStatus(status, text) {
        elements.statusDot.className = `status-dot ${status}`;
        elements.statusText.textContent = text;
    }

    /**
     * Update clock display
     */
    function updateClock() {
        const now = new Date();

        const timeStr = now.toLocaleTimeString('th-TH', {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false
        });

        const dateStr = now.toLocaleDateString('th-TH', {
            year: 'numeric',
            month: 'long',
            day: 'numeric',
            weekday: 'long'
        });

        elements.currentTime.textContent = timeStr;
        elements.currentDate.textContent = dateStr;
    }

    /**
     * Format time to Thai format
     */
    function formatTime(dateString) {
        const date = new Date(dateString);
        return date.toLocaleTimeString('th-TH', {
            hour: '2-digit',
            minute: '2-digit',
            hour12: false
        });
    }

    /**
     * Show error overlay
     */
    function showError(title, message) {
        elements.errorTitle.textContent = title;
        elements.errorMessage.textContent = message;
        elements.errorOverlay.style.display = 'flex';
    }

    /**
     * Hide error overlay
     */
    function hideError() {
        elements.errorOverlay.style.display = 'none';
    }

    /**
     * Setup event listeners
     */
    function setupEventListeners() {
        // Retry button
        elements.retryButton.addEventListener('click', () => {
            hideError();
            loadTerminalData();
        });
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // Cleanup on page unload
    window.addEventListener('beforeunload', () => {
        if (countdownInterval) {
            clearInterval(countdownInterval);
        }
        if (refreshTimeout) {
            clearTimeout(refreshTimeout);
        }
        if (websocket) {
            websocket.close();
        }
    });
})();
