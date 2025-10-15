// Mobile Check-in Page JavaScript

(function() {
    'use strict';

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

            const response = await fetch('/qr-checkin/api/auth/line/verify-token', {
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
     * Display user profile
     */
    function displayProfile() {
        elements.profilePicture.src = userProfile.line_profile.picture_url || '/static/img/default-avatar.png';
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
            elements.gpsText.style.color = '#28a745';
            elements.gpsAccuracy.textContent = `±${accuracy}m`;
            elements.gpsAccuracy.style.color = '#28a745';

            // Enable scanner button
            if (elements.startScanButton) {
                elements.startScanButton.disabled = false;
            }

            console.log(`[GPS] Good accuracy achieved: ${accuracy}m (GPS lock)`);
        } else {
            // Waiting for GPS lock (likely using WiFi positioning)
            elements.gpsText.textContent = 'กำลังรอสัญญาณ GPS...';
            elements.gpsText.style.color = '#ffc107';
            elements.gpsAccuracy.textContent = `±${accuracy}m`;
            elements.gpsAccuracy.style.color = '#ffc107';

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
            elements.gpsText.style.color = '#dc3545';
            elements.gpsAccuracy.textContent = '-';
            return;
        }

        console.log('[GPS] Starting GPS tracking with high-accuracy phone GPS mode...');

        navigator.geolocation.watchPosition(
            updateGPSStatus,
            (error) => {
                console.error('[GPS] Error:', error);
                elements.gpsText.textContent = 'ไม่สามารถเข้าถึง GPS';
                elements.gpsText.style.color = '#dc3545';
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
            alert('ไม่สามารถเข้าถึงกล้องได้ กรุณาอนุญาตการเข้าถึงกล้องในเบราว์เซอร์');
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
            const response = await fetch('/qr-checkin/api/qr-checkin/scan', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    jwt_token: jwtToken,
                    qr_token: qrData,
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

                // Format details
                const details = `
                    <div><strong>📍 สถานที่:</strong> ${data.location_validation.location_name}</div>
                    <div><strong>🕐 เวลา:</strong> ${formatDateTime(data.attendance_record.timestamp)}</div>
                    <div><strong>📏 ระยะทาง:</strong> ${data.location_validation.distance}m</div>
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
                    <div style="margin-top: 10px; padding-top: 10px; border-top: 1px solid #f5c6cb;">
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
            const response = await fetch(`/qr-checkin/api/attendance/?badge=${userProfile.employee_badge}&limit=5`);
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
            const metadata = record.metadata || '';
            const isQR = metadata.includes('QR Check-in');
            const locationMatch = metadata.match(/at (.+?),/);
            const location = locationMatch ? locationMatch[1] : 'ลายนิ้วมือ';

            return `
                <div class="recent-item">
                    <div class="recent-item-header">
                        <div class="recent-time">${formatDateTime(record.timestamp)}</div>
                        <div class="recent-badge">${isQR ? '📱 QR' : '👆 ลายนิ้วมือ'}</div>
                    </div>
                    <div class="recent-location">📍 ${location}</div>
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
