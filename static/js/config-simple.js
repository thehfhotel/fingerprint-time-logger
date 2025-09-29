/**
 * Simplified Configuration Manager - No Protocol Detection
 * Eliminates HTTPS mixed content issues permanently
 */

class ConfigManager {
    constructor() {
        this.config = null;
        this.loaded = false;
        this.basePath = this.detectBasePath();
        this.version = '3.0-relative-urls-' + Date.now();
        console.log('SimpleConfigManager initialized - Version:', this.version);
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
            // Use relative URL - browser automatically uses correct protocol
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
            this.config = this.getDefaultConfig();
            this.loaded = true;
            return this.config;
        }
    }

    getDefaultConfig() {
        return {
            api: {
                baseUrl: `${window.location.origin}${this.basePath}/api`,
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
                healthCheckInterval: 300000, // Changed from 60s to 5 minutes
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

    /**
     * SIMPLIFIED URL GENERATION - NO PROTOCOL DETECTION
     * Always uses relative URLs - browser handles protocol automatically
     */
    getApiUrl(endpoint = '') {
        // Clean up endpoint
        const cleanEndpoint = endpoint.startsWith('/') ? endpoint.slice(1) : endpoint;

        // Extract endpoint path and query string if present
        const [endpointPath, queryString] = cleanEndpoint.split('?');

        // Add trailing slash for FastAPI routes (except for specific endpoints)
        const noSlashEndpoints = ['devices/time', 'devices/health', 'auto-import/status', 'devices/sync-time', 'refresh', 'attendance/summary'];
        const endpointWithoutSlash = endpointPath ? endpointPath.replace(/\/$/, '') : '';
        const containsMarkLate = endpointPath && endpointPath.includes('/mark-late');
        const needsSlash = endpointPath &&
                          !endpointPath.endsWith('/') &&
                          !noSlashEndpoints.includes(endpointWithoutSlash) &&
                          !containsMarkLate &&
                          !queryString;

        const finalEndpointPath = needsSlash ? endpointPath + '/' : endpointPath;
        const finalEndpoint = queryString ? `${finalEndpointPath}?${queryString}` : finalEndpointPath;

        // SIMPLE RELATIVE URL - NO PROTOCOL DETECTION NEEDED
        const relativeUrl = `${this.basePath}/api/${finalEndpoint}`;

        console.log('✅ SIMPLE URL GENERATED:', {
            endpoint,
            cleanEndpoint,
            finalEndpoint,
            relativeUrl,
            basePath: this.basePath
        });

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