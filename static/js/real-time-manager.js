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
        this.maxRetryAttempts = 3; // Limit to 3 retry attempts
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
            'คุณอยู่ในโหมดออฟไลน์ ข้อมูลอาจไม่เป็นปัจจุบัน',
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
    
    async performHealthCheckWithRetry() {
        let attempts = 0;
        const maxAttempts = 3;

        while (attempts < maxAttempts) {
            try {
                const response = await fetch(appConfig.getApiUrl('devices/health'), {
                    method: 'GET',
                    headers: { 'Accept': 'application/json' },
                    timeout: 10000 // 10 second timeout
                });

                if (response.ok) {
                    if (!this.isOnline) {
                        this.isOnline = true;
                        this.updateConnectionStatus();
                        this.refreshData();
                    }
                    this.retryAttempts = 0;
                    return; // Success, exit retry loop
                } else {
                    throw new Error(`Health check failed: ${response.status}`);
                }
            } catch (error) {
                attempts++;
                console.warn(`Health check attempt ${attempts} failed:`, error);

                if (attempts < maxAttempts) {
                    // Exponential backoff: 1s, 2s, 4s
                    const delay = Math.pow(2, attempts - 1) * 1000;
                    console.log(`Retrying health check in ${delay}ms...`);
                    await new Promise(resolve => setTimeout(resolve, delay));
                } else {
                    // All retries failed
                    this.retryAttempts++;
                    if (this.retryAttempts >= this.maxRetryAttempts && this.isOnline) {
                        this.isOnline = false;
                        this.updateConnectionStatus();
                        console.error('Device health check failed after all retries, marking offline');
                    }
                }
            }
        }
    }

    startHealthMonitoring() {
        // CACHE-FIRST ARCHITECTURE: Backend cache refreshes every 5 minutes
        // Frontend health check aligned with backend refresh cycle
        this.healthCheckInterval = setInterval(async () => {
            await this.performHealthCheckWithRetry();
        }, appConfig.get('ui.healthCheckInterval') || 300000); // 5 minutes (aligned with backend cache)
    }

    startPeriodicRefresh() {
        // CACHE-FIRST ARCHITECTURE: Reduce frontend polling frequency
        // Backend serves from cache (instant response), so we can poll more aggressively
        // Refresh data every 1 minute when online and page is visible
        this.refreshInterval = setInterval(() => {
            if (this.isOnline && !document.hidden) {
                this.refreshData();
            }
        }, 60000); // 1 minute (was 2 minutes) - backend serves from cache instantly
    }
    
    async refreshData() {
        if (!this.isOnline) {
            this.showNotification(
                'Offline',
                'ไม่สามารถรีเฟรชข้อมูลในโหมดออฟไลน์ได้',
                'warning'
            );
            return;
        }
        
        try {
            // Status UI removed - functionality moved to /status page
            
            // Refresh attendance data
            if (window.updateDashboard) {
                const response = await fetch(appConfig.getApiUrl('attendance/summary'), {
                    method: 'GET',
                    headers: { 'Accept': 'application/json' }
                });
                
                if (response.ok) {
                    const data = await response.json();
                    window.updateDashboard(data);
                    
                    this.showNotification(
                        'Data Updated',
                        'รีเฟรชข้อมูลการลงเวลาสำเร็จแล้ว',
                        'success'
                    );
                } else {
                    throw new Error(`Failed to fetch data: ${response.status}`);
                }
            }
            
            // Refresh employee display names if on nickname management page
            if (window.loadEmployeeDisplayNames) {
                window.loadEmployeeDisplayNames();
            }
            
        } catch (error) {
            console.error('Data refresh failed:', error);
            this.showNotification(
                'Refresh Failed',
                'ไม่สามารถรีเฟรชข้อมูลได้ กรุณาตรวจสอบการเชื่อมต่อ',
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