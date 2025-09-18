/**
 * Configuration Manager - Loads app configuration from API
 * Version 2.0 - Fixed HTTPS mixed content issue
 */

class ConfigManager {
    constructor() {
        this.config = null;
        this.loaded = false;
        this.basePath = this.detectBasePath();
        this.version = '3.0-https-redirect-fix-' + Date.now();
        console.log('ConfigManager initialized - Version:', this.version);
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
                baseUrl: `${this.basePath}/api`,
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

    /**
     * SIMPLIFIED URL GENERATION - NGINX REVERSE PROXY COMPATIBLE
     * Uses relative URLs - nginx handles HTTPS termination
     * Eliminates all protocol detection issues permanently
     */
    getApiUrl(endpoint = '') {
        // Clean up endpoint
        const cleanEndpoint = endpoint.startsWith('/') ? endpoint.slice(1) : endpoint;

        // Extract endpoint path and query string if present
        const [endpointPath, queryString] = cleanEndpoint.split('?');

        // Add trailing slash for FastAPI routes (except for specific endpoints)
        const noSlashEndpoints = ['devices/time', 'devices/health', 'auto-import/status', 'devices/sync-time', 'refresh', 'attendance/summary'];
        // Also exclude endpoints that match patterns like employees/{id}/status
        const statusEndpointPattern = /^employees\/\d+\/status$/;
        const endpointWithoutSlash = endpointPath ? endpointPath.replace(/\/$/, '') : '';
        const containsMarkLate = endpointPath && endpointPath.includes('/mark-late');
        const needsSlash = endpointPath &&
                          !endpointPath.endsWith('/') &&
                          !noSlashEndpoints.includes(endpointWithoutSlash) &&
                          !statusEndpointPattern.test(endpointWithoutSlash) &&
                          !containsMarkLate &&
                          !queryString;

        const finalEndpointPath = needsSlash ? endpointPath + '/' : endpointPath;
        const finalEndpoint = queryString ? `${finalEndpointPath}?${queryString}` : finalEndpointPath;

        // NGINX REVERSE PROXY SOLUTION - RELATIVE URLs ONLY
        // Browser automatically uses same protocol as page (HTTPS)
        // No protocol detection needed - nginx handles everything
        const relativeUrl = `${this.basePath}/api/${finalEndpoint}`;

        console.log('✅ NGINX PROXY URL:', {
            endpoint,
            cleanEndpoint,
            finalEndpoint,
            relativeUrl,
            basePath: this.basePath,
            version: 'nginx-proxy-v1.0'
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