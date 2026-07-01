// Mobile Check-in Page JavaScript

(function() {
    'use strict';

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
        loginSection: document.getElementById('loginSection'),
        notLinkedSection: document.getElementById('notLinkedSection'),
        scannerSection: document.getElementById('scannerSection'),

        profilePicture: document.getElementById('profilePicture'),
        displayName: document.getElementById('displayName'),
        employeeBadge: document.getElementById('employeeBadge'),
        logoutButton: document.getElementById('logoutButton'),

        videoElement: document.getElementById('videoElement'),
        canvasElement: document.getElementById('canvasElement'),
        startScanButton: document.getElementById('startScanButton'),
        stopScanButton: document.getElementById('stopScanButton'),

        gpsText: document.getElementById('gpsText'),
        gpsAccuracy: document.getElementById('gpsAccuracy'),

        recentCheckIns: document.getElementById('recentCheckIns'),

        loadingOverlay: document.getElementById('loadingOverlay'),
        loadingMessage: document.getElementById('loadingMessage'),

        resultModal: document.getElementById('resultModal'),
        resultIcon: document.getElementById('resultIcon'),
        resultTitle: document.getElementById('resultTitle'),
        resultMessage: document.getElementById('resultMessage'),
        resultDetails: document.getElementById('resultDetails'),
        closeModalButton: document.getElementById('closeModalButton')
    };

    // State
    let jwtToken = null;
    let userProfile = null;
    let currentGPS = null;
    let videoStream = null;
    let scanning = false;
    let scanInterval = null;
    let lastScannedCode = null;
    let lastScanTime = 0;

    // GPS Configuration
    const GPS_REQUIRED_ACCURACY = 30; // meters - stricter than backend 50m requirement

    /**
     * Initialize page
     */
    function init() {
        console.log('[Mobile Check-in] Initializing page...');

        // Get JWT token from URL or localStorage
        jwtToken = getJWTToken();

        if (!jwtToken) {
            console.log('[Mobile Check-in] No JWT token, showing login');
            showSection('loginSection');
            return;
        }

        console.log('[Mobile Check-in] JWT token found, verifying...');
        verifyTokenAndLoadProfile();

        // Setup event listeners
        setupEventListeners();

        // Start GPS tracking
        startGPSTracking();
    }

    /**
     * Get JWT token from URL parameters or localStorage
     */
    function getJWTToken() {
        const urlParams = new URLSearchParams(window.location.search);
        const urlToken = urlParams.get('jwt');

        if (urlToken) {
            console.log('[Mobile Check-in] Token found in URL, saving to localStorage');
            localStorage.setItem('line_jwt_token', urlToken);
            window.history.replaceState({}, document.title, window.location.pathname);
            return urlToken;
        }

        const storedToken = localStorage.getItem('line_jwt_token');
        console.log('[Mobile Check-in] Token from localStorage:', storedToken ? 'Found' : 'Not found');
        return storedToken;
    }

    /**
     * Verify JWT token and load profile
     */
    async function verifyTokenAndLoadProfile() {
        try {
            showLoading('กำลังตรวจสอบข้อมูล...');

            console.log('[Mobile Check-in] Sending verify request with token:', jwtToken ? jwtToken.substring(0, 20) + '...' : 'NULL');
            const requestBody = { token: jwtToken };
            console.log('[Mobile Check-in] Request body:', JSON.stringify(requestBody).substring(0, 100));

            const response = await fetch('/api/public/auth/line/verify-token', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(requestBody)
            });

            const data = await response.json();
            console.log('[Mobile Check-in] Response status:', response.status, 'Data:', data);

            if (response.ok && data.valid) {
                userProfile = data;
                console.log('[Mobile Check-in] Profile loaded:', userProfile);

                // Check if account is linked
                if (!data.employee_badge) {
                    console.log('[Mobile Check-in] Account not linked');
                    hideLoading();
                    showSection('notLinkedSection');
                    return;
                }

                // Show scanner section
                displayProfile();
                loadRecentCheckIns();
                hideLoading();
                showSection('scannerSection');
            } else {
                console.error('[Mobile Check-in] Token verification failed:', data);
                localStorage.removeItem('line_jwt_token');
                hideLoading();
                showSection('loginSection');
            }
        } catch (error) {
            console.error('[Mobile Check-in] Error verifying token:', error);
            hideLoading();
            showSection('loginSection');
        }
    }

    /**
     * Inline SVG fallback avatar (used when LINE picture URL is missing/broken).
     * Avoids dependency on a static PNG asset.
     */
    const DEFAULT_AVATAR_SVG = 'data:image/svg+xml;utf8,' + encodeURIComponent(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">' +
        '<circle cx="32" cy="32" r="32" fill="#E8E4DF"/>' +
        '<circle cx="32" cy="26" r="11" fill="#CFC9C1"/>' +
        '<path d="M10 58c4-12 14-18 22-18s18 6 22 18z" fill="#CFC9C1"/>' +
        '</svg>'
    );

    /**
     * Display user profile
     */
    function displayProfile() {
        const pictureUrl = userProfile.line_profile.picture_url || DEFAULT_AVATAR_SVG;
        elements.profilePicture.src = pictureUrl;
        elements.profilePicture.onerror = function() {
            this.onerror = null;
            this.src = DEFAULT_AVATAR_SVG;
        };
        elements.displayName.textContent = userProfile.line_profile.display_name;
        elements.employeeBadge.textContent = `รหัสพนักงาน: ${userProfile.employee_badge}`;
    }

    /**
     * Setup event listeners
     */
    function setupEventListeners() {
        elements.startScanButton.addEventListener('click', startScanning);
        elements.stopScanButton.addEventListener('click', stopScanning);
        elements.logoutButton.addEventListener('click', handleLogout);
        elements.closeModalButton.addEventListener('click', closeModal);
    }

    /**
     * Check if GPS accuracy is acceptable for check-in
     */
    function isGPSAccurate(accuracy) {
        return accuracy <= GPS_REQUIRED_ACCURACY;
    }

    /**
     * Update GPS status display and scanner button state
     */
    function updateGPSStatus(position) {
        currentGPS = {
            latitude: position.coords.latitude,
            longitude: position.coords.longitude,
            accuracy: position.coords.accuracy
        };

        const accuracy = Math.round(currentGPS.accuracy);

        if (isGPSAccurate(accuracy)) {
            // Good GPS lock achieved - phone GPS (not WiFi)
            elements.gpsText.textContent = 'GPS พร้อมใช้งาน ✓';
            elements.gpsText.style.color = '#2F855A';
            elements.gpsAccuracy.textContent = `±${accuracy}m`;
            elements.gpsAccuracy.style.color = '#2F855A';

            // Enable scanner button
            if (elements.startScanButton) {
                elements.startScanButton.disabled = false;
            }

            console.log(`[GPS] Good accuracy achieved: ${accuracy}m (GPS lock)`);
        } else {
            // Waiting for GPS lock (likely using WiFi positioning)
            elements.gpsText.textContent = 'กำลังรอสัญญาณ GPS...';
            elements.gpsText.style.color = '#B7791F';
            elements.gpsAccuracy.textContent = `±${accuracy}m`;
            elements.gpsAccuracy.style.color = '#B7791F';

            // Disable scanner button until GPS accuracy improves
            if (elements.startScanButton) {
                elements.startScanButton.disabled = true;
            }

            console.log(`[GPS] Waiting for better accuracy: ${accuracy}m > ${GPS_REQUIRED_ACCURACY}m (likely WiFi)`);
        }
    }

    /**
     * Start GPS tracking with enhanced configuration for phone GPS
     */
    function startGPSTracking() {
        if (!navigator.geolocation) {
            elements.gpsText.textContent = 'ไม่รองรับ GPS';
            elements.gpsText.style.color = '#C53030';
            elements.gpsAccuracy.textContent = '-';
            return;
        }

        console.log('[GPS] Starting GPS tracking with high-accuracy phone GPS mode...');

        navigator.geolocation.watchPosition(
            updateGPSStatus,
            (error) => {
                console.error('[GPS] Error:', error);
                elements.gpsText.textContent = 'ไม่สามารถเข้าถึง GPS';
                elements.gpsText.style.color = '#C53030';
                elements.gpsAccuracy.textContent = '-';

                // Disable scanner when GPS unavailable
                if (elements.startScanButton) {
                    elements.startScanButton.disabled = true;
                }
            },
            {
                enableHighAccuracy: true,  // Request phone GPS (not WiFi)
                maximumAge: 5000,          // Force fresh GPS readings (reduced from 10000ms)
                timeout: 15000             // Allow GPS satellite lock (increased from 5000ms)
            }
        );
    }

    /**
     * Start scanning QR codes
     */
    async function startScanning() {
        try {
            console.log('[Scanner] Starting camera...');
            elements.startScanButton.disabled = true;

            // Request camera access
            videoStream = await navigator.mediaDevices.getUserMedia({
                video: { facingMode: 'environment' }
            });

            elements.videoElement.srcObject = videoStream;
            elements.videoElement.play();

            // Update UI
            elements.startScanButton.style.display = 'none';
            elements.stopScanButton.style.display = 'block';

            // Start scanning
            scanning = true;
            scanInterval = setInterval(scanQRCode, 300);

            console.log('[Scanner] Camera started successfully');
        } catch (error) {
            console.error('[Scanner] Error starting camera:', error);
            showResult(
                'error',
                'ไม่สามารถเข้าถึงกล้องได้',
                'กรุณาอนุญาตการเข้าถึงกล้องในเบราว์เซอร์'
            );
            elements.startScanButton.disabled = false;
        }
    }

    /**
     * Stop scanning QR codes
     */
    function stopScanning() {
        console.log('[Scanner] Stopping camera...');

        scanning = false;
        if (scanInterval) {
            clearInterval(scanInterval);
            scanInterval = null;
        }

        if (videoStream) {
            videoStream.getTracks().forEach(track => track.stop());
            videoStream = null;
        }

        elements.videoElement.srcObject = null;
        elements.startScanButton.style.display = 'block';
        elements.stopScanButton.style.display = 'none';
        elements.startScanButton.disabled = false;

        console.log('[Scanner] Camera stopped');
    }

    /**
     * Scan QR code from video stream
     */
    function scanQRCode() {
        if (!scanning || !elements.videoElement.videoWidth) return;

        const canvas = elements.canvasElement;
        const context = canvas.getContext('2d', { willReadFrequently: true });

        canvas.width = elements.videoElement.videoWidth;
        canvas.height = elements.videoElement.videoHeight;

        context.drawImage(elements.videoElement, 0, 0, canvas.width, canvas.height);

        const imageData = context.getImageData(0, 0, canvas.width, canvas.height);
        const code = jsQR(imageData.data, imageData.width, imageData.height);

        if (code && code.data) {
            // Prevent duplicate scans
            const now = Date.now();
            if (code.data === lastScannedCode && now - lastScanTime < 3000) {
                return;
            }

            lastScannedCode = code.data;
            lastScanTime = now;

            console.log('[Scanner] QR Code detected:', code.data);
            processQRCode(code.data);
        }
    }

    /**
     * Extract token from QR data (handles both URL and direct token)
     */
    function extractToken(qrData) {
        console.log('[QR Parser] Raw QR data:', qrData);

        // Check if qrData is a URL
        if (qrData.startsWith('http://') || qrData.startsWith('https://')) {
            try {
                const url = new URL(qrData);
                const token = url.searchParams.get('token');
                console.log('[QR Parser] Extracted token from URL:', token ? token.substring(0, 20) + '...' : 'NULL');
                return token;
            } catch (error) {
                console.error('[QR Parser] Error parsing URL:', error);
                return qrData;
            }
        }

        // Already a direct token
        console.log('[QR Parser] Direct token detected');
        return qrData;
    }

    /**
     * Process scanned QR code
     */
    async function processQRCode(qrData) {
        stopScanning();

        // Validate GPS availability
        if (!currentGPS) {
            showResult('error', 'ไม่พบตำแหน่ง GPS', 'กรุณาเปิดใช้งาน GPS และลองใหม่อีกครั้ง');
            return;
        }

        showLoading('กำลังบันทึกเวลา...');

        try {
            // Extract token from QR data (handles both URL and direct token)
            const qrToken = extractToken(qrData);

            if (!qrToken) {
                hideLoading();
                showResult('error', 'QR Code ไม่ถูกต้อง', 'ไม่พบ token ใน QR Code');
                return;
            }

            console.log('[Check-in] Sending request with token:', qrToken.substring(0, 20) + '...');

            const response = await fetch('/api/public/qr-checkin/scan', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    jwt_token: jwtToken,
                    qr_token: qrToken,
                    latitude: currentGPS.latitude,
                    longitude: currentGPS.longitude,
                    accuracy: currentGPS.accuracy
                })
            });

            const data = await response.json();

            if (response.ok && data.success) {
                console.log('[Check-in] Success:', data);

                // DEBUG: Log complete response structure
                console.log('[DEBUG] Full response data:', JSON.stringify(data, null, 2));
                console.log('[DEBUG] location_validation object:', data.location_validation);
                console.log('[DEBUG] location_validation keys:', Object.keys(data.location_validation || {}));
                console.log('[DEBUG] Trying to access location_name:', data.location_validation?.location_name);
                console.log('[DEBUG] Trying to access terminal_location:', data.location_validation?.terminal_location);

                hideLoading();

                // Format details (escape server-supplied strings to prevent XSS)
                const safeLocationName = escapeHtml(data.location_validation.location_name);
                const safeTimestamp = escapeHtml(formatDateTime(data.attendance_record.timestamp));
                const safeDistance = escapeHtml(data.location_validation.distance);
                const details = `
                    <div><strong>📍 สถานที่:</strong> ${safeLocationName}</div>
                    <div><strong>🕐 เวลา:</strong> ${safeTimestamp}</div>
                    <div><strong>📏 ระยะทาง:</strong> ${safeDistance}m</div>
                `;

                showResult('success', 'บันทึกเวลาสำเร็จ!', data.message, details);

                // Reload recent check-ins
                setTimeout(() => {
                    loadRecentCheckIns();
                }, 1000);
            } else {
                console.error('[Check-in] Failed:', data);

                // Log failed attempt details
                console.warn(
                    `[Check-in FAILED] ${data.detail || data.message} - ` +
                    `GPS: (${currentGPS.latitude}, ${currentGPS.longitude}), ` +
                    `Accuracy: ${currentGPS.accuracy}m`
                );

                hideLoading();

                // Show error with GPS details for debugging
                const errorDetails = currentGPS ? `
                    <div style="margin-top: 10px; padding-top: 10px; border-top: 1px solid #EFC2C2;">
                        <div><strong>🎯 ความแม่นยำ GPS:</strong> ±${Math.round(currentGPS.accuracy)}m</div>
                        <div><strong>📍 ตำแหน่ง:</strong> ${currentGPS.latitude.toFixed(6)}, ${currentGPS.longitude.toFixed(6)}</div>
                    </div>
                ` : '';

                showResult(
                    'error',
                    'บันทึกเวลาไม่สำเร็จ',
                    data.message || data.detail || 'กรุณาลองใหม่อีกครั้ง',
                    errorDetails
                );
            }
        } catch (error) {
            console.error('[Check-in] Error:', error);
            hideLoading();
            showResult('error', 'เกิดข้อผิดพลาด', 'ไม่สามารถเชื่อมต่อกับเซิร์ฟเวอร์ได้');
        }
    }

    /**
     * Load recent check-ins
     */
    async function loadRecentCheckIns() {
        try {
            const response = await fetch(`/api/public/qr-checkin/attendance/employee/badge/${userProfile.employee_badge}?limit=5`);
            const data = await response.json();

            if (response.ok && data.records && data.records.length > 0) {
                displayRecentCheckIns(data.records);
            } else {
                elements.recentCheckIns.innerHTML = '<p class="empty-state">ยังไม่มีบันทึก</p>';
            }
        } catch (error) {
            console.error('[Recent] Error loading recent check-ins:', error);
            elements.recentCheckIns.innerHTML = '<p class="empty-state">ไม่สามารถโหลดข้อมูลได้</p>';
        }
    }

    /**
     * Display recent check-ins
     */
    function displayRecentCheckIns(records) {
        const html = records.map(record => {
            // QR scans tag validation_message with "QR Check-in" or "QR Check-out"
            const validationMsg = record.validation_message || '';
            const isQR = validationMsg.includes('QR Check-in') || validationMsg.includes('QR Check-out');
            const isCheckOut = record.punch_type === 1 || validationMsg.includes('QR Check-out');
            const locationMatch = validationMsg.match(/at (.+?),/);

            // Determine location with context-appropriate fallback
            let location;
            if (locationMatch) {
                location = locationMatch[1];
            } else if (isQR) {
                location = isCheckOut ? 'QR Check-out' : 'QR Check-in';
            } else {
                location = 'จากเครื่องสแกนลายนิ้วมือ';
            }

            const badgeLabel = isQR
                ? (isCheckOut ? '🏃 QR Check-out' : '📱 QR Check-in')
                : '👆 ลายนิ้วมือ';

            const safeTime = escapeHtml(formatDateTime(record.timestamp));
            const safeLocation = escapeHtml(location);
            const safeBadge = escapeHtml(badgeLabel);
            return `
                <div class="recent-item">
                    <div class="recent-item-header">
                        <div class="recent-time">${safeTime}</div>
                        <div class="recent-badge">${safeBadge}</div>
                    </div>
                    <div class="recent-location">📍 ${safeLocation}</div>
                </div>
            `;
        }).join('');

        elements.recentCheckIns.innerHTML = html;
    }

    /**
     * Handle logout
     */
    function handleLogout() {
        if (confirm('ต้องการออกจากระบบหรือไม่?')) {
            stopScanning();
            localStorage.removeItem('line_jwt_token');
            window.location.reload();
        }
    }

    /**
     * Show loading overlay
     */
    function showLoading(message) {
        elements.loadingMessage.textContent = message;
        elements.loadingOverlay.style.display = 'flex';
    }

    /**
     * Hide loading overlay
     */
    function hideLoading() {
        elements.loadingOverlay.style.display = 'none';
    }

    /**
     * Show result modal
     */
    function showResult(type, title, message, details = '') {
        elements.resultIcon.className = `result-icon ${type}`;
        elements.resultTitle.textContent = title;
        elements.resultMessage.textContent = message;
        elements.resultDetails.innerHTML = details;
        elements.resultDetails.style.display = details ? 'block' : 'none';
        elements.resultModal.style.display = 'flex';
    }

    /**
     * Close result modal
     */
    function closeModal() {
        elements.resultModal.style.display = 'none';
        lastScannedCode = null;
        lastScanTime = 0;
    }

    /**
     * Show specific section
     */
    function showSection(sectionId) {
        const sections = ['loginSection', 'notLinkedSection', 'scannerSection'];
        sections.forEach(id => {
            const element = elements[id];
            if (element) {
                element.style.display = (id === sectionId) ? 'block' : 'none';
            }
        });
    }

    /**
     * Format datetime to Thai format
     */
    function formatDateTime(dateString) {
        const date = new Date(dateString);
        return date.toLocaleString('th-TH', {
            timeZone: 'Asia/Bangkok',
            year: 'numeric',
            month: 'short',
            day: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit'
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
        stopScanning();
    });
})();
