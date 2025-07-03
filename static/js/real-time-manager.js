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
        // Status UI moved to dedicated /status page
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
    
    // Status UI removed - now available on dedicated /status page
    
    // Status styles removed - styling now in dedicated /status page
    
    updateConnectionStatus() {
        // Connection status now tracked on dedicated /status page
        // This method kept for compatibility but no longer updates UI elements
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
        
        try {
            // Status UI removed - functionality moved to /status page
            
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
            // Status management moved to /status page
        }
    }
    
    destroy() {
        if (this.healthCheckInterval) {
            clearInterval(this.healthCheckInterval);
        }
        
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
        }
        
        // UI elements now managed by /status page
        
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