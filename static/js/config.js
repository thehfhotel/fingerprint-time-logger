/**
 * Configuration Manager - Loads app configuration from API
 */

class ConfigManager {
    constructor() {
        this.config = null;
        this.loaded = false;
    }

    async loadConfig() {
        if (this.loaded) return this.config;
        
        try {
            const response = await fetch('/api/devices/app-config');
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
                baseUrl: "/api",
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
}

// Global configuration instance
const appConfig = new ConfigManager();

// Load configuration when script loads
appConfig.loadConfig();