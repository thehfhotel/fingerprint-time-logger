/**
 * Configuration Manager - Loads app configuration from API
 */

class ConfigManager {
    constructor() {
        this.config = null;
        this.loaded = false;
        this.basePath = this.detectBasePath();
    }

    detectBasePath() {
        // Detect if we're running under /fingerprintlogs path
        const pathname = window.location.pathname;
        if (pathname.startsWith('/fingerprintlogs')) {
            return '/fingerprintlogs';
        }
        return '';
    }

    async loadConfig() {
        if (this.loaded) return this.config;
        
        try {
            const response = await fetch(`${this.basePath}/api/devices/app-config`);
            if (response.ok) {
                this.config = await response.json();
                this.loaded = true;
                console.log('Configuration loaded:', this.config);
                return this.config;
            } else {
                throw new Error(`Failed to load config: ${response.status}`);
            }
        } catch (error) {
            console.warn('Failed to load configuration, using defaults:', error);
            // Fallback to default configuration
            this.config = this.getDefaultConfig();
            this.loaded = true;
            return this.config;
        }
    }

    getDefaultConfig() {
        return {
            api: {
                baseUrl: `${window.location.protocol}//${window.location.host}${this.basePath}/api`,
                timeout: 30000,
                retryAttempts: 3
            },
            websocket: {
                reconnectAttempts: 5,
                reconnectDelay: 1000,
                pingInterval: 30000
            },
            ui: {
                refreshInterval: 120000,
                healthCheckInterval: 60000,
                dateFormat: "en-US",
                timeFormat: {
                    hour12: false
                }
            },
            device: {
                defaultTimeout: 5,
                maxRetries: 3
            }
        };
    }

    get(path) {
        if (!this.loaded) {
            console.warn('Configuration not loaded yet, using defaults');
            return this.getValueByPath(this.getDefaultConfig(), path);
        }
        return this.getValueByPath(this.config, path);
    }

    getValueByPath(obj, path) {
        return path.split('.').reduce((current, key) => current?.[key], obj);
    }

    getApiUrl(endpoint = '') {
        // Remove leading slash if present to avoid double slashes
        const cleanEndpoint = endpoint.startsWith('/') ? endpoint.slice(1) : endpoint;
        
        // Extract base path and query string if present
        const [basePath, queryString] = cleanEndpoint.split('?');
        
        // Special handling for endpoints that don't work with trailing slashes under Cloudflare Tunnel
        const noSlashEndpoints = ['devices/time', 'devices/health', 'auto-import/status', 'devices/sync-time', 'refresh', 'attendance/summary'];
        
        // Don't add slash if endpoint has query parameters, already ends with slash, or is in noSlashEndpoints
        const needsSlash = basePath && 
                          !basePath.endsWith('/') && 
                          !noSlashEndpoints.includes(basePath) && 
                          !queryString; // Don't add slash if there are query parameters
        
        const finalBasePath = needsSlash ? basePath + '/' : basePath;
        const finalEndpoint = queryString ? `${finalBasePath}?${queryString}` : finalBasePath;
        
        const relativeUrl = `${this.basePath}/api/${finalEndpoint}`;
        console.log('getApiUrl debug - smart slash handling:', { endpoint, cleanEndpoint, basePath, queryString, finalEndpoint, needsSlash, relativeUrl });
        
        return relativeUrl;
    }

    getBasePath() {
        return this.basePath;
    }
}

// Global configuration instance
const appConfig = new ConfigManager();

// Load configuration when script loads
appConfig.loadConfig();