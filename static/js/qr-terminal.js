// QR Terminal Display JavaScript - Kiosk Mode

(function() {
    'use strict';

    // Configuration
    const QR_REFRESH_INTERVAL = 30000; // 30 seconds
    const WEBSOCKET_RECONNECT_DELAY = 5000; // 5 seconds

    // DOM Elements
    const elements = {
        terminalName: document.getElementById('terminalName'),
        terminalLocation: document.getElementById('terminalLocation'),
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

        // Setup event listeners
        setupEventListeners();

        // Connect WebSocket
        connectWebSocket();
    }

    /**
     * Load available QR terminals for location selector
     */
    async function loadAvailableTerminals() {
        try {
            const response = await fetch('/fingerprintlogs/api/qr-checkin/terminals');
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

            button.innerHTML = `
                <span class="location-icon">📍</span>
                <span class="location-name">${terminal.location_name || terminal.name}</span>
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

            const response = await fetch(`/fingerprintlogs/api/qr-checkin/kiosk/${TERMINAL_ID}`);
            const data = await response.json();

            if (response.ok) {
                terminalData = data;
                console.log('[QR Terminal] Terminal data loaded:', terminalData);

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

        // API returns flat structure: {terminal_id, terminal_name, ...}
        const location = terminalData.terminal_name || `Terminal ${terminalData.terminal_id}`;

        elements.terminalName.textContent = location;
        elements.terminalLocation.textContent = `📍 ${location}`;
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

            // Update progress bar
            const progress = (remaining / 30) * 100;
            elements.progressBar.style.width = `${progress}%`;

            // Stop countdown when expired
            if (remaining === 0) {
                clearInterval(countdownInterval);
            }
        }, 1000);
    }

    /**
     * Schedule next QR code refresh
     */
    function scheduleQRRefresh() {
        if (refreshTimeout) {
            clearTimeout(refreshTimeout);
        }

        refreshTimeout = setTimeout(() => {
            console.log('[QR Terminal] Auto-refreshing QR code...');
            loadTerminalData();
        }, QR_REFRESH_INTERVAL);
    }

    /**
     * Connect WebSocket for real-time updates
     */
    function connectWebSocket() {
        try {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const host = window.location.host;
            const wsUrl = `${protocol}//${host}/fingerprintlogs/ws`;

            console.log('[WebSocket] Connecting to:', wsUrl);

            websocket = new WebSocket(wsUrl);

            websocket.onopen = () => {
                console.log('[WebSocket] Connected');
                websocketReconnectAttempt = 0;
                updateConnectionStatus('connected', 'เชื่อมต่อแล้ว');
            };

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
                updateConnectionStatus('disconnected', 'ไม่ได้เชื่อมต่อ');

                // Attempt reconnection
                setTimeout(() => {
                    websocketReconnectAttempt++;
                    console.log(`[WebSocket] Reconnecting (attempt ${websocketReconnectAttempt})...`);
                    connectWebSocket();
                }, WEBSOCKET_RECONNECT_DELAY);
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

        // Check if this is for our terminal
        if (record.device_id == TERMINAL_ID || record.metadata?.includes('QR Check-in')) {
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
        const isQR = metadata.includes('QR Check-in');
        const locationMatch = metadata.match(/at (.+?),/);
        const location = locationMatch ? locationMatch[1] : terminalData?.terminal.location_name || '';

        item.innerHTML = `
            <div class="feed-header">
                <div class="feed-name">${record.employee_name || `รหัส ${record.badge_number}`}</div>
                <div class="feed-badge">${record.badge_number}</div>
            </div>
            <div class="feed-details">
                <div class="feed-detail">
                    <span>🕐</span>
                    <span>${formatTime(record.timestamp)}</span>
                </div>
                <div class="feed-detail">
                    <span>${isQR ? '📱' : '👆'}</span>
                    <span>${isQR ? 'QR Check-in' : 'ลายนิ้วมือ'}</span>
                </div>
                ${location ? `
                <div class="feed-detail">
                    <span>📍</span>
                    <span>${location}</span>
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
