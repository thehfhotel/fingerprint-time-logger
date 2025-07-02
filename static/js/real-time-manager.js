/**
 * Real-Time Manager - Simplified for Single User
 * Handles real-time data updates without caching complexity
 */

class RealTimeManager {
    constructor() {
        this.isOnline = navigator.onLine;
        this.healthCheckInterval = null;
        this.refreshInterval = null;
        this.retryAttempts = 0;
        this.maxRetryAttempts = 3;
        this.apiBaseUrl = '';
        
        this.init();
    }
    
    init() {
        this.setupEventListeners();
        this.createStatusUI();
        this.startHealthMonitoring();
        this.startPeriodicRefresh();
    }
    
    setupEventListeners() {
        // Browser online/offline detection
        window.addEventListener('online', () => {
            this.isOnline = true;
            this.updateConnectionStatus();
            this.refreshData();
        });
        
        window.addEventListener('offline', () => {
            this.isOnline = false;
            this.updateConnectionStatus();
            this.showOfflineNotification();
        });
        
        // Visibility change for refresh on tab focus
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden && this.isOnline) {
                this.refreshData();
            }
        });
    }
    
    createStatusUI() {
        // Create status bar
        const statusBar = document.createElement('div');
        statusBar.id = 'connection-status';
        statusBar.className = 'connection-status';
        statusBar.innerHTML = `
            <div class="status-indicator">
                <span class="status-dot online" id="status-dot"></span>
                <span class="status-text" id="status-text">Connected</span>
            </div>
            <button id="refresh-btn" class="refresh-btn" onclick="realTimeManager.refreshData()">
                <span class="refresh-icon">⟳</span> Refresh
            </button>
        `;
        
        document.body.appendChild(statusBar);
        
        // Add CSS styles
        this.addStatusStyles();
    }
    
    addStatusStyles() {
        const styles = document.createElement('style');
        styles.textContent = `
            .connection-status {
                position: fixed;
                top: 10px;
                right: 10px;
                background: rgba(0, 0, 0, 0.8);
                color: white;
                padding: 0.5rem;
                border-radius: 8px;
                z-index: 1000;
                display: flex;
                align-items: center;
                gap: 1rem;
                font-size: 0.85rem;
                backdrop-filter: blur(10px);
            }
            
            .status-indicator {
                display: flex;
                align-items: center;
                gap: 0.5rem;
            }
            
            .status-dot {
                width: 8px;
                height: 8px;
                border-radius: 50%;
                display: inline-block;
            }
            
            .status-dot.online {
                background-color: #4caf50;
                animation: pulse 2s infinite;
            }
            
            .status-dot.offline {
                background-color: #f44336;
                animation: none;
            }
            
            .status-dot.connecting {
                background-color: #ff9800;
                animation: spin 1s linear infinite;
            }
            
            .refresh-btn {
                background: rgba(255, 255, 255, 0.2);
                border: 1px solid rgba(255, 255, 255, 0.3);
                color: white;
                padding: 0.25rem 0.5rem;
                border-radius: 4px;
                font-size: 0.8rem;
                cursor: pointer;
                transition: all 0.2s ease;
            }
            
            .refresh-btn:hover {
                background: rgba(255, 255, 255, 0.3);
                transform: translateY(-1px);
            }
            
            .refresh-btn:disabled {
                opacity: 0.5;
                cursor: not-allowed;
                transform: none;
            }
            
            @keyframes pulse {
                0% { opacity: 1; }
                50% { opacity: 0.7; }
                100% { opacity: 1; }
            }
            
            @keyframes spin {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
            }
            
            .notification {
                position: fixed;
                top: 70px;
                right: 10px;
                background: rgba(0, 0, 0, 0.9);
                color: white;
                padding: 1rem;
                border-radius: 8px;
                z-index: 1001;
                max-width: 300px;
                backdrop-filter: blur(10px);
                transform: translateX(100%);
                transition: transform 0.3s ease;
            }
            
            .notification.show {
                transform: translateX(0);
            }
            
            .notification.success {
                border-left: 4px solid #4caf50;
            }
            
            .notification.error {
                border-left: 4px solid #f44336;
            }
            
            .notification.warning {
                border-left: 4px solid #ff9800;
            }
        `;
        
        document.head.appendChild(styles);
    }
    
    updateConnectionStatus() {
        const statusDot = document.getElementById('status-dot');
        const statusText = document.getElementById('status-text');
        const refreshBtn = document.getElementById('refresh-btn');
        
        if (this.isOnline) {
            statusDot.className = 'status-dot online';
            statusText.textContent = 'Connected';
            refreshBtn.disabled = false;
        } else {
            statusDot.className = 'status-dot offline';
            statusText.textContent = 'Offline';
            refreshBtn.disabled = true;
        }
    }
    
    showOfflineNotification() {
        this.showNotification(
            'Connection Lost',
            'You are currently offline. Data may not be up to date.',
            'warning'
        );
    }
    
    showNotification(title, message, type = 'info') {
        const notification = document.createElement('div');
        notification.className = `notification ${type}`;
        notification.innerHTML = `
            <div style="font-weight: bold; margin-bottom: 0.5rem;">${title}</div>
            <div>${message}</div>
        `;
        
        document.body.appendChild(notification);
        
        // Show notification
        setTimeout(() => notification.classList.add('show'), 100);
        
        // Auto hide after 4 seconds
        setTimeout(() => {
            notification.classList.remove('show');
            setTimeout(() => notification.remove(), 300);
        }, 4000);
    }
    
    startHealthMonitoring() {
        this.healthCheckInterval = setInterval(async () => {
            try {
                const response = await fetch(`${this.apiBaseUrl}/api/devices/health`, {
                    method: 'GET',
                    headers: { 'Accept': 'application/json' }
                });
                
                if (response.ok) {
                    if (!this.isOnline) {
                        this.isOnline = true;
                        this.updateConnectionStatus();
                        this.refreshData();
                    }
                    this.retryAttempts = 0;
                } else {
                    throw new Error(`Health check failed: ${response.status}`);
                }
            } catch (error) {
                console.warn('Health check failed:', error);
                this.retryAttempts++;
                
                if (this.retryAttempts >= this.maxRetryAttempts && this.isOnline) {
                    this.isOnline = false;
                    this.updateConnectionStatus();
                }
            }
        }, 15000); // Check every 15 seconds
    }
    
    startPeriodicRefresh() {
        // Refresh data every 30 seconds when online and page is visible
        this.refreshInterval = setInterval(() => {
            if (this.isOnline && !document.hidden) {
                this.refreshData();
            }
        }, 30000); // 30 seconds
    }
    
    async refreshData() {
        if (!this.isOnline) {
            this.showNotification(
                'Offline',
                'Cannot refresh data while offline.',
                'warning'
            );
            return;
        }
        
        const statusDot = document.getElementById('status-dot');
        const refreshBtn = document.getElementById('refresh-btn');
        
        try {
            // Show connecting state
            statusDot.className = 'status-dot connecting';
            refreshBtn.disabled = true;
            
            // Refresh attendance data
            if (window.updateDashboard) {
                const response = await fetch(`${this.apiBaseUrl}/api/attendance/`, {
                    method: 'GET',
                    headers: { 'Accept': 'application/json' }
                });
                
                if (response.ok) {
                    const data = await response.json();
                    window.updateDashboard(data);
                    
                    this.showNotification(
                        'Data Updated',
                        'Successfully refreshed attendance data',
                        'success'
                    );
                } else {
                    throw new Error(`Failed to fetch data: ${response.status}`);
                }
            }
            
            // Refresh Thai names if on thai-names page
            if (window.loadThaiNames) {
                window.loadThaiNames();
            }
            
        } catch (error) {
            console.error('Data refresh failed:', error);
            this.showNotification(
                'Refresh Failed',
                'Unable to refresh data. Please check your connection.',
                'error'
            );
        } finally {
            // Restore online state
            statusDot.className = 'status-dot online';
            refreshBtn.disabled = false;
        }
    }
    
    destroy() {
        if (this.healthCheckInterval) {
            clearInterval(this.healthCheckInterval);
        }
        
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
        }
        
        // Remove UI elements
        const statusBar = document.getElementById('connection-status');
        if (statusBar) {
            statusBar.remove();
        }
        
        // Remove event listeners
        window.removeEventListener('online', this.updateConnectionStatus);
        window.removeEventListener('offline', this.updateConnectionStatus);
        document.removeEventListener('visibilitychange', this.refreshData);
    }
}

// Initialize when DOM is loaded
let realTimeManager;
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        realTimeManager = new RealTimeManager();
    });
} else {
    realTimeManager = new RealTimeManager();
}