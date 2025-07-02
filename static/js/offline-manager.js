/**
 * Offline Manager - Phase 4: Dashboard Offline Experience
 * Handles offline detection, sync status, and cached data management
 */

class OfflineManager {
    constructor() {
        this.isOnline = navigator.onLine;
        this.lastSyncTime = null;
        this.cacheStatus = { fresh: false, age: 0 };
        this.syncInProgress = false;
        // Use proxy endpoint from dashboard instead of direct API URL
        this.apiBaseUrl = '';
        this.healthCheckInterval = null;
        this.retryAttempts = 0;
        this.maxRetryAttempts = 3;
        
        this.init();
    }
    
    init() {
        this.setupEventListeners();
        this.createOfflineUI();
        this.startHealthMonitoring();
        this.loadCachedData();
    }
    
    setupEventListeners() {
        // Browser online/offline detection
        window.addEventListener('online', () => {
            this.isOnline = true;
            this.updateConnectionStatus();
            this.attemptReconnection();
        });
        
        window.addEventListener('offline', () => {
            this.isOnline = false;
            this.updateConnectionStatus();
            this.showOfflineNotification();
        });
        
        // Visibility change for background sync
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden && this.isOnline) {
                this.checkSyncStatus();
            }
        });
    }
    
    createOfflineUI() {
        // Create offline status bar
        const statusBar = document.querySelector('.status-bar');
        if (statusBar) {
            // Add sync status indicator
            const syncStatus = document.createElement('div');
            syncStatus.className = 'status-item sync-status';
            syncStatus.innerHTML = `
                <div class="status-dot" id="sync-dot"></div>
                <span id="sync-text">Checking sync...</span>
            `;
            statusBar.appendChild(syncStatus);
            
            // Add data freshness indicator
            const dataFreshness = document.createElement('div');
            dataFreshness.className = 'status-item data-freshness';
            dataFreshness.innerHTML = `
                <span id="data-age">Data: Loading...</span>
            `;
            statusBar.appendChild(dataFreshness);
            
            // Add sync controls
            const syncControls = document.createElement('div');
            syncControls.className = 'status-item sync-controls';
            syncControls.innerHTML = `
                <button id="manual-sync-btn" class="sync-btn" onclick="offlineManager.triggerManualSync()">
                    <span class="sync-icon">⟳</span> Sync
                </button>
                <button id="refresh-cache-btn" class="sync-btn" onclick="offlineManager.refreshCache()">
                    <span class="cache-icon">⟲</span> Refresh
                </button>
            `;
            statusBar.appendChild(syncControls);
        }
        
        // Create offline notification area
        const notificationArea = document.createElement('div');
        notificationArea.id = 'offline-notifications';
        notificationArea.className = 'offline-notifications';
        document.body.appendChild(notificationArea);
        
        this.addOfflineStyles();
    }
    
    addOfflineStyles() {
        const style = document.createElement('style');
        style.textContent = `
            /* Offline UI Styles */
            .sync-status .status-dot {
                animation: pulse 2s infinite;
            }
            
            .sync-status .status-dot.syncing {
                background-color: #ff9800;
                animation: spin 1s linear infinite;
            }
            
            .sync-status .status-dot.error {
                background-color: #f44336;
                animation: blink 1s infinite;
            }
            
            .sync-status .status-dot.offline {
                background-color: #9e9e9e;
                animation: none;
            }
            
            .data-freshness {
                font-size: 0.8rem;
                opacity: 0.9;
            }
            
            .data-freshness.stale {
                color: #ff9800;
            }
            
            .data-freshness.offline {
                color: #f44336;
            }
            
            .sync-controls {
                gap: 0.5rem;
            }
            
            .sync-btn {
                background: rgba(255, 255, 255, 0.2);
                border: 1px solid rgba(255, 255, 255, 0.3);
                color: white;
                padding: 0.25rem 0.5rem;
                border-radius: 4px;
                font-size: 0.8rem;
                cursor: pointer;
                transition: all 0.2s ease;
            }
            
            .sync-btn:hover {
                background: rgba(255, 255, 255, 0.3);
                transform: translateY(-1px);
            }
            
            .sync-btn:disabled {
                opacity: 0.5;
                cursor: not-allowed;
                transform: none;
            }
            
            .sync-icon, .cache-icon {
                display: inline-block;
                transition: transform 0.2s ease;
            }
            
            .sync-btn.syncing .sync-icon {
                animation: spin 1s linear infinite;
            }
            
            .offline-notifications {
                position: fixed;
                top: 20px;
                right: 20px;
                z-index: 1000;
                max-width: 350px;
            }
            
            .notification {
                background: white;
                border-radius: 8px;
                padding: 1rem;
                margin-bottom: 0.5rem;
                box-shadow: 0 4px 12px rgba(0,0,0,0.15);
                border-left: 4px solid #2196f3;
                animation: slideIn 0.3s ease;
            }
            
            .notification.warning {
                border-left-color: #ff9800;
            }
            
            .notification.error {
                border-left-color: #f44336;
            }
            
            .notification.success {
                border-left-color: #4caf50;
            }
            
            .notification-title {
                font-weight: bold;
                margin-bottom: 0.25rem;
            }
            
            .notification-message {
                font-size: 0.9rem;
                color: #666;
            }
            
            .offline-indicator {
                position: fixed;
                bottom: 20px;
                left: 50%;
                transform: translateX(-50%);
                background: #f44336;
                color: white;
                padding: 0.5rem 1rem;
                border-radius: 20px;
                font-size: 0.9rem;
                box-shadow: 0 2px 8px rgba(0,0,0,0.2);
                z-index: 999;
                animation: slideUp 0.3s ease;
            }
            
            .progressive-loading {
                background: linear-gradient(90deg, #f0f0f0 25%, #e0e0e0 50%, #f0f0f0 75%);
                background-size: 200% 100%;
                animation: loading 1.5s infinite;
            }
            
            @keyframes pulse {
                0%, 100% { opacity: 1; }
                50% { opacity: 0.5; }
            }
            
            @keyframes spin {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
            }
            
            @keyframes blink {
                0%, 100% { opacity: 1; }
                50% { opacity: 0.3; }
            }
            
            @keyframes slideIn {
                from { transform: translateX(100%); opacity: 0; }
                to { transform: translateX(0); opacity: 1; }
            }
            
            @keyframes slideUp {
                from { transform: translate(-50%, 100%); opacity: 0; }
                to { transform: translate(-50%, 0); opacity: 1; }
            }
            
            @keyframes loading {
                0% { background-position: 200% 0; }
                100% { background-position: -200% 0; }
            }
            
            /* Offline mode adjustments */
            body.offline-mode .employee-card {
                border-left: 3px solid #ff9800;
            }
            
            body.offline-mode .employee-header::after {
                content: " (Cached)";
                font-size: 0.8rem;
                opacity: 0.8;
            }
            
            /* Loading overlay styles */
            .loading-overlay {
                position: fixed;
                top: 0;
                left: 0;
                width: 100%;
                height: 100%;
                background: rgba(0, 0, 0, 0.5);
                display: flex;
                justify-content: center;
                align-items: center;
                z-index: 9999;
                transition: opacity 0.3s ease;
            }
            
            .loading-spinner {
                background: white;
                padding: 2rem;
                border-radius: 8px;
                text-align: center;
                box-shadow: 0 4px 20px rgba(0,0,0,0.2);
            }
            
            .spinner {
                width: 40px;
                height: 40px;
                border: 3px solid #f3f3f3;
                border-top: 3px solid #667eea;
                border-radius: 50%;
                animation: spin 1s linear infinite;
                margin: 0 auto 1rem;
            }
            
            .loading-text {
                color: #666;
                font-size: 0.9rem;
            }
            
            /* Enhanced error states */
            .error-recovery {
                background: #fff3cd;
                border: 1px solid #ffeaa7;
                border-radius: 4px;
                padding: 1rem;
                margin: 1rem 0;
                text-align: center;
            }
            
            .error-recovery-title {
                font-weight: bold;
                color: #856404;
                margin-bottom: 0.5rem;
            }
            
            .error-recovery-actions {
                display: flex;
                gap: 0.5rem;
                justify-content: center;
                margin-top: 1rem;
            }
            
            .recovery-btn {
                background: #667eea;
                color: white;
                border: none;
                padding: 0.5rem 1rem;
                border-radius: 4px;
                cursor: pointer;
                font-size: 0.9rem;
                transition: background 0.2s ease;
            }
            
            .recovery-btn:hover {
                background: #5a6fd8;
            }
            
            .recovery-btn:disabled {
                background: #ccc;
                cursor: not-allowed;
            }
        `;
        document.head.appendChild(style);
    }
    
    startHealthMonitoring() {
        // Check health every 30 seconds
        this.healthCheckInterval = setInterval(() => {
            this.checkSyncStatus();
        }, 30000);
        
        // Initial check
        setTimeout(() => this.checkSyncStatus(), 1000);
    }
    
    async checkSyncStatus() {
        try {
            const response = await fetch(`${this.apiBaseUrl}/api/devices/health`, {
                timeout: 5000
            });
            
            if (response.ok) {
                const healthData = await response.json();
                this.updateSyncStatus(healthData);
                this.retryAttempts = 0;
            } else {
                throw new Error(`Health check failed: ${response.status}`);
            }
        } catch (error) {
            console.warn('Health check failed:', error);
            this.handleSyncError(error);
        }
    }
    
    updateSyncStatus(healthData) {
        const syncDot = document.getElementById('sync-dot');
        const syncText = document.getElementById('sync-text');
        
        if (!syncDot || !syncText) return;
        
        const overall = healthData.overall_health;
        const syncService = healthData.sync_service;
        const isErrorClassificationEnabled = healthData.error_classification_enabled;
        
        // Update sync status indicator
        syncDot.className = 'status-dot';
        
        // Use enhanced status display if error classification is enabled
        if (isErrorClassificationEnabled) {
            switch (overall) {
                case 'healthy':
                    syncDot.classList.add('connected');
                    syncText.textContent = 'Sync: Healthy';
                    this.showStatusDetails(healthData, 'success');
                    break;
                case 'degraded':
                    syncDot.classList.add('syncing');
                    syncText.textContent = 'Sync: Degraded';
                    this.showStatusDetails(healthData, 'warning');
                    break;
                case 'unstable':
                    syncDot.classList.add('error');
                    syncText.textContent = 'Sync: Unstable';
                    this.showStatusDetails(healthData, 'warning');
                    break;
                case 'critical':
                    syncDot.classList.add('error');
                    syncText.textContent = 'Sync: Critical';
                    this.showStatusDetails(healthData, 'error');
                    break;
                default:
                    syncDot.classList.add('offline');
                    syncText.textContent = 'Sync: Unknown';
            }
            
            // Show health score and recommendation
            if (healthData.health_score !== undefined) {
                const healthPercentage = Math.round(healthData.health_score * 100);
                syncText.title = `Health Score: ${healthPercentage}% - ${healthData.recommendation || ''}`;
            }
        } else {
            // Legacy status display
            switch (overall) {
                case 'healthy':
                    syncDot.classList.add('connected');
                    syncText.textContent = 'Sync: Online';
                    break;
                case 'degraded':
                    syncDot.classList.add('syncing');
                    syncText.textContent = 'Sync: Degraded';
                    break;
                case 'critical':
                case 'warning':
                    syncDot.classList.add('error');
                    syncText.textContent = 'Sync: Issues';
                    break;
                default:
                    syncDot.classList.add('offline');
                    syncText.textContent = 'Sync: Unknown';
            }
        }
        
        // Update last sync time
        if (syncService && syncService.uptime_seconds > 0) {
            this.lastSyncTime = new Date();
            this.updateDataFreshness();
        }
        
        // Update cache status
        this.cacheStatus = {
            fresh: overall === 'healthy',
            age: syncService ? syncService.uptime_seconds : 0
        };
    }
    
    showStatusDetails(healthData, type) {
        // Only show details for degraded/unstable/critical states
        if (['degraded', 'unstable', 'critical'].includes(healthData.overall_health)) {
            // Show brief notification with error analysis
            if (healthData.error_analysis && healthData.error_analysis.total_events > 0) {
                const analysis = healthData.error_analysis;
                const message = `${analysis.total_events} events (${analysis.informational_count} informational, ${analysis.critical_count} critical)`;
                
                // Only show notification occasionally to avoid spam
                if (!this.lastStatusNotification || Date.now() - this.lastStatusNotification > 300000) { // 5 minutes
                    this.showNotification(
                        `Sync Status: ${healthData.overall_health.charAt(0).toUpperCase() + healthData.overall_health.slice(1)}`,
                        message,
                        type
                    );
                    this.lastStatusNotification = Date.now();
                }
            }
        }
    }
    
    updateDataFreshness() {
        const dataAge = document.getElementById('data-age');
        if (!dataAge) return;
        
        if (this.lastSyncTime) {
            const ageMinutes = Math.floor((new Date() - this.lastSyncTime) / 60000);
            
            dataAge.className = 'data-age';
            
            if (ageMinutes < 5) {
                dataAge.textContent = 'Data: Fresh';
                dataAge.classList.remove('stale', 'offline');
            } else if (ageMinutes < 30) {
                dataAge.textContent = `Data: ${ageMinutes}m ago`;
                dataAge.classList.add('stale');
                dataAge.classList.remove('offline');
            } else {
                dataAge.textContent = `Data: ${ageMinutes}m ago`;
                dataAge.classList.add('offline');
                dataAge.classList.remove('stale');
            }
        } else {
            dataAge.textContent = 'Data: Unknown';
            dataAge.classList.add('offline');
        }
    }
    
    handleSyncError(error) {
        this.retryAttempts++;
        
        const syncDot = document.getElementById('sync-dot');
        const syncText = document.getElementById('sync-text');
        
        if (syncDot && syncText) {
            syncDot.className = 'status-dot error';
            syncText.textContent = this.isOnline ? 'Sync: Error' : 'Sync: Offline';
        }
        
        if (this.retryAttempts >= this.maxRetryAttempts) {
            // Try to use cached data first
            const cachedData = localStorage.getItem('attendance_cache');
            
            if (cachedData) {
                this.showNotification(
                    'Using Cached Data',
                    'Unable to connect to server. Showing cached attendance data.',
                    'warning'
                );
                this.loadCachedData();
            } else {
                // No cached data available, show error recovery
                this.showErrorRecovery();
                this.showNotification(
                    'Connection Failed',
                    'No cached data available. Please check your connection.',
                    'error'
                );
            }
        }
    }
    
    updateConnectionStatus() {
        const deviceStatus = document.querySelector('.status-item .status-dot');
        const statusText = document.querySelector('.status-item span');
        
        if (deviceStatus) {
            if (this.isOnline) {
                deviceStatus.classList.remove('disconnected', 'offline');
                deviceStatus.classList.add('connected');
            } else {
                deviceStatus.classList.remove('connected');
                deviceStatus.classList.add('disconnected', 'offline');
            }
        }
        
        // Update body class for offline styling
        document.body.classList.toggle('offline-mode', !this.isOnline);
        
        // Show/hide offline indicator
        this.toggleOfflineIndicator();
    }
    
    toggleOfflineIndicator() {
        let indicator = document.getElementById('offline-indicator');
        
        if (!this.isOnline) {
            if (!indicator) {
                indicator = document.createElement('div');
                indicator.id = 'offline-indicator';
                indicator.className = 'offline-indicator';
                indicator.textContent = 'Working Offline - Using Cached Data';
                document.body.appendChild(indicator);
            }
        } else {
            if (indicator) {
                indicator.remove();
            }
        }
    }
    
    async triggerManualSync() {
        if (this.syncInProgress) return;
        
        // Check if the new unified import button exists, use that instead
        const importBtn = document.getElementById('importButton');
        const syncBtn = document.getElementById('manual-sync-btn');
        
        // If the new import button exists, delegate to it
        if (importBtn && window.importFingerprintLog) {
            console.log('Delegating manual sync to unified import function');
            this.showNotification(
                'Using Import Function',
                'Synchronizing data via Import Fingerprint Log',
                'info'
            );
            return window.importFingerprintLog();
        }
        
        // Fallback: Show helpful message if no sync mechanism available
        if (!syncBtn) {
            console.warn('No sync button available - showing user guidance');
            this.showNotification(
                'Sync via Import Button',
                'Use the "Import Fingerprint Log" button in the header to sync data',
                'info'
            );
            return;
        }
        
        // Legacy sync functionality (direct API call to sync service)
        this.syncInProgress = true;
        syncBtn.disabled = true;
        syncBtn.classList.add('syncing');
        
        try {
            // Use direct API call to the API server (port 8000)
            const response = await fetch('/api/devices/sync/attendance', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            
            if (response.ok) {
                const result = await response.json();
                this.showNotification(
                    'Sync Initiated',
                    `Started sync for ${result.successfully_queued} device${result.successfully_queued !== 1 ? 's' : ''}`,
                    'success'
                );
                
                // Refresh data after a delay
                setTimeout(() => {
                    this.refreshAttendanceData();
                }, 2000);
            } else {
                throw new Error(`Sync failed: ${response.status}`);
            }
        } catch (error) {
            console.error('Manual sync failed:', error);
            this.showNotification(
                'Sync Failed',
                'Unable to start sync. Please use Import Fingerprint Log button.',
                'error'
            );
        } finally {
            this.syncInProgress = false;
            syncBtn.disabled = false;
            syncBtn.classList.remove('syncing');
        }
    }
    
    async refreshCache() {
        // Check if the new unified import button exists, use that instead
        const importBtn = document.getElementById('importButton');
        const refreshBtn = document.getElementById('refresh-cache-btn');
        
        // If the new import button exists, delegate to it
        if (importBtn && window.importFingerprintLog) {
            console.log('Delegating cache refresh to unified import function');
            this.showNotification(
                'Using Import Function',
                'Refreshing data via Import Fingerprint Log',
                'info'
            );
            return window.importFingerprintLog();
        }
        
        // Fallback: Show helpful message if no refresh mechanism available
        if (!refreshBtn) {
            console.warn('No refresh button available - showing user guidance');
            this.showNotification(
                'Refresh via Import Button',
                'Use the "Import Fingerprint Log" button in the header to refresh data',
                'info'
            );
            return;
        }
        
        // Legacy refresh functionality (if refresh button still exists)
        refreshBtn.disabled = true;
        
        try {
            // Use the dashboard refresh endpoint
            const response = await fetch('/api/refresh', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                signal: AbortSignal.timeout(60000)
            });
            
            if (response.ok) {
                const result = await response.json();
                this.showNotification(
                    'Data Refreshed',
                    `Successfully imported fingerprint data`,
                    'success'
                );
                
                // Refresh the dashboard data
                this.refreshAttendanceData();
            } else {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.message || `Server error: ${response.status}`);
            }
        } catch (error) {
            console.error('Cache refresh failed:', error);
            
            let errorMessage = 'Unable to refresh data';
            if (error.name === 'TimeoutError') {
                errorMessage = 'Import timed out - operation may still be processing';
            } else if (error.message) {
                errorMessage = error.message;
            }
            
            this.showNotification(
                'Refresh Failed',
                errorMessage,
                'error'
            );
        } finally {
            refreshBtn.disabled = false;
        }
    }
    
    refreshAttendanceData() {
        // Trigger socket.io refresh if available
        if (window.socket && window.socket.connected) {
            window.socket.emit('request_update');
        } else {
            // Fallback to page reload
            window.location.reload();
        }
    }
    
    loadCachedData() {
        // Check for cached attendance data
        const cachedData = localStorage.getItem('attendance_cache');
        if (cachedData) {
            try {
                const data = JSON.parse(cachedData);
                const cacheAge = Date.now() - data.timestamp;
                
                if (cacheAge < 3600000) { // 1 hour
                    this.displayCachedData(data.attendance);
                    this.lastSyncTime = new Date(data.timestamp);
                    this.updateDataFreshness();
                }
            } catch (error) {
                console.warn('Failed to load cached data:', error);
            }
        }
    }
    
    displayCachedData(attendanceData) {
        // Display cached data with offline indicators
        if (attendanceData && attendanceData.data) {
            // Show progressive loading
            this.showProgressiveLoading();
            
            // Update the dashboard with cached data
            setTimeout(() => {
                if (window.updateDashboard) {
                    window.updateDashboard(attendanceData);
                }
                this.hideProgressiveLoading();
                
                // Show offline data notification
                this.showNotification(
                    'Offline Mode',
                    'Displaying cached attendance data',
                    'info'
                );
            }, 500);
        }
    }
    
    showProgressiveLoading() {
        const container = document.getElementById('employeeContainer');
        if (container) {
            container.classList.add('progressive-loading');
        }
        
        // Add loading overlay
        let loadingOverlay = document.getElementById('loading-overlay');
        if (!loadingOverlay) {
            loadingOverlay = document.createElement('div');
            loadingOverlay.id = 'loading-overlay';
            loadingOverlay.className = 'loading-overlay';
            loadingOverlay.innerHTML = `
                <div class="loading-spinner">
                    <div class="spinner"></div>
                    <div class="loading-text">Loading cached data...</div>
                </div>
            `;
            document.body.appendChild(loadingOverlay);
        }
    }
    
    hideProgressiveLoading() {
        const container = document.getElementById('employeeContainer');
        if (container) {
            container.classList.remove('progressive-loading');
        }
        
        const loadingOverlay = document.getElementById('loading-overlay');
        if (loadingOverlay) {
            loadingOverlay.style.opacity = '0';
            setTimeout(() => loadingOverlay.remove(), 300);
        }
    }
    
    cacheAttendanceData(attendanceData) {
        const cacheData = {
            attendance: attendanceData,
            timestamp: Date.now()
        };
        
        try {
            localStorage.setItem('attendance_cache', JSON.stringify(cacheData));
        } catch (error) {
            console.warn('Failed to cache data:', error);
        }
    }
    
    showNotification(title, message, type = 'info') {
        const notificationArea = document.getElementById('offline-notifications');
        if (!notificationArea) return;
        
        const notification = document.createElement('div');
        notification.className = `notification ${type}`;
        notification.innerHTML = `
            <div class="notification-title">${title}</div>
            <div class="notification-message">${message}</div>
        `;
        
        notificationArea.appendChild(notification);
        
        // Auto remove after 5 seconds
        setTimeout(() => {
            notification.style.opacity = '0';
            setTimeout(() => notification.remove(), 300);
        }, 5000);
    }
    
    showOfflineNotification() {
        this.showNotification(
            'Connection Lost',
            'You are now offline. Displaying cached data.',
            'warning'
        );
    }
    
    attemptReconnection() {
        this.showNotification(
            'Connection Restored',
            'Checking for updates...',
            'success'
        );
        
        // Reset retry attempts
        this.retryAttempts = 0;
        
        // Remove any error recovery UI
        this.removeErrorRecoveryUI();
        
        // Trigger immediate health check
        setTimeout(() => this.checkSyncStatus(), 1000);
        
        // Refresh data
        if (window.refreshAttendanceData) {
            setTimeout(() => window.refreshAttendanceData(), 2000);
        }
    }
    
    showErrorRecovery() {
        // Remove existing error recovery UI
        this.removeErrorRecoveryUI();
        
        const container = document.getElementById('employeeContainer');
        if (!container) return;
        
        const errorRecovery = document.createElement('div');
        errorRecovery.id = 'error-recovery';
        errorRecovery.className = 'error-recovery';
        errorRecovery.innerHTML = `
            <div class="error-recovery-title">Connection Problems</div>
            <div>Unable to connect to the server. You can:</div>
            <div class="error-recovery-actions">
                <button class="recovery-btn" onclick="offlineManager.retryConnection()">
                    Try Again
                </button>
                <button class="recovery-btn" onclick="offlineManager.forceOfflineMode()">
                    Use Offline Mode
                </button>
                <button class="recovery-btn" onclick="window.location.reload()">
                    Reload Page
                </button>
            </div>
        `;
        
        container.insertBefore(errorRecovery, container.firstChild);
    }
    
    removeErrorRecoveryUI() {
        const errorRecovery = document.getElementById('error-recovery');
        if (errorRecovery) {
            errorRecovery.remove();
        }
    }
    
    async retryConnection() {
        this.retryAttempts = 0;
        this.removeErrorRecoveryUI();
        
        this.showNotification(
            'Retrying Connection',
            'Attempting to reconnect...',
            'info'
        );
        
        // Try to reconnect
        await this.checkSyncStatus();
        
        // If still failing, show cached data
        if (this.retryAttempts >= this.maxRetryAttempts) {
            this.forceOfflineMode();
        }
    }
    
    forceOfflineMode() {
        this.removeErrorRecoveryUI();
        
        this.showNotification(
            'Offline Mode',
            'Switched to offline mode. Using cached data.',
            'warning'
        );
        
        // Load cached data
        this.loadCachedData();
        
        // Update UI to reflect offline state
        document.body.classList.add('offline-mode');
        this.toggleOfflineIndicator();
    }
    
    // Enhanced health monitoring with smart retry
    async smartRetry(operation, maxRetries = 3) {
        let lastError;
        
        for (let i = 0; i < maxRetries; i++) {
            try {
                const result = await operation();
                return result;
            } catch (error) {
                lastError = error;
                
                // Exponential backoff
                const delay = Math.min(1000 * Math.pow(2, i), 10000);
                await new Promise(resolve => setTimeout(resolve, delay));
            }
        }
        
        throw lastError;
    }
    
    // Enhanced data synchronization
    async syncWithFallback() {
        try {
            // Try to get fresh data from API
            const response = await this.smartRetry(async () => {
                const res = await fetch(`${this.apiBaseUrl}/api/attendance/`, {
                    timeout: 10000
                });
                
                if (!res.ok) {
                    throw new Error(`HTTP ${res.status}`);
                }
                
                return res.json();
            });
            
            // Update with fresh data
            if (window.updateDashboard) {
                window.updateDashboard(response);
            }
            
            // Cache the fresh data
            this.cacheAttendanceData(response);
            
            this.showNotification(
                'Data Updated',
                'Successfully synchronized with server',
                'success'
            );
            
        } catch (error) {
            console.warn('Sync failed, using cached data:', error);
            
            // Fall back to cached data
            this.loadCachedData();
            
            // Show error recovery if no cached data
            const cachedData = localStorage.getItem('attendance_cache');
            if (!cachedData) {
                this.showErrorRecovery();
            }
        }
    }
    
    destroy() {
        if (this.healthCheckInterval) {
            clearInterval(this.healthCheckInterval);
        }
        
        window.removeEventListener('online', this.updateConnectionStatus);
        window.removeEventListener('offline', this.updateConnectionStatus);
        document.removeEventListener('visibilitychange', this.checkSyncStatus);
    }
}

// Initialize offline manager when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        window.offlineManager = new OfflineManager();
    });
} else {
    window.offlineManager = new OfflineManager();
}