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

        footerLocation: document.getElementById('footerLocation'),
        footerGPS: document.getElementById('footerGPS'),
        todayCount: document.getElementById('todayCount'),

        errorOverlay: document.getElementById('errorOverlay'),
        errorTitle: document.getElementById('errorTitle'),
        errorMessage: document.getElementById('errorMessage'),
        retryButton: document.getElementById('retryButton'),

        fullscreenButton: document.getElementById('fullscreenButton')
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

        // Load terminal data
        loadTerminalData();

        // Setup event listeners
        setupEventListeners();

        // Connect WebSocket
        connectWebSocket();
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

        const terminal = terminalData.terminal;
        const location = terminal.location_name || `Terminal ${terminal.id}`;
        const gps = terminal.gps_location || {};

        elements.terminalName.textContent = location;
        elements.terminalLocation.textContent = `📍 ${location}`;

        elements.footerLocation.textContent = location;
        if (gps.latitude && gps.longitude) {
            elements.footerGPS.textContent = `${gps.latitude.toFixed(6)}, ${gps.longitude.toFixed(6)}`;
        }

        // Load today's check-in count
        loadTodayCount();
    }

    /**
     * Display QR code
     */
    function displayQRCode(qrImageBase64, expiresAt) {
        // Create QR code image
        const img = document.createElement('img');
        img.src = `data:image/png;base64,${qrImageBase64}`;
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
     * Load today's check-in count
     */
    async function loadTodayCount() {
        try {
            const today = new Date().toISOString().split('T')[0];
            const response = await fetch(`/fingerprintlogs/api/attendance/?date=${today}&device=${TERMINAL_ID}`);
            const data = await response.json();

            if (response.ok && data.total) {
                elements.todayCount.textContent = data.total;
            }
        } catch (error) {
            console.error('[QR Terminal] Error loading today count:', error);
        }
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
            loadTodayCount();
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

        // Fullscreen button
        elements.fullscreenButton.addEventListener('click', toggleFullscreen);

        // Keyboard shortcut for fullscreen (F11 alternative: F)
        document.addEventListener('keydown', (e) => {
            if (e.key === 'f' || e.key === 'F') {
                toggleFullscreen();
            }
        });
    }

    /**
     * Toggle fullscreen mode
     */
    function toggleFullscreen() {
        const elem = document.documentElement;

        if (!document.fullscreenElement) {
            if (elem.requestFullscreen) {
                elem.requestFullscreen();
            } else if (elem.webkitRequestFullscreen) {
                elem.webkitRequestFullscreen();
            } else if (elem.msRequestFullscreen) {
                elem.msRequestFullscreen();
            }
            elements.fullscreenButton.textContent = '⛶';
        } else {
            if (document.exitFullscreen) {
                document.exitFullscreen();
            } else if (document.webkitExitFullscreen) {
                document.webkitExitFullscreen();
            } else if (document.msExitFullscreen) {
                document.msExitFullscreen();
            }
            elements.fullscreenButton.textContent = '⛶';
        }
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
