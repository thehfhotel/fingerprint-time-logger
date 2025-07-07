/**
 * WebSocket adapter to maintain compatibility with Socket.IO interface
 * This allows gradual migration from Socket.IO to native WebSocket
 */

class WebSocketAdapter {
    constructor() {
        this.ws = null;
        this.connected = false;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5; // Will be updated from config
        this.reconnectDelay = 1000; // Will be updated from config
        this.pingInterval = 30000; // Will be updated from config
        this.eventHandlers = {};
        this.connectionHandlers = {
            connect: [],
            disconnect: []
        };
        this.initConfig();
    }

    async initConfig() {
        try {
            await appConfig.loadConfig();
            this.maxReconnectAttempts = appConfig.get('websocket.reconnectAttempts') || 5;
            this.reconnectDelay = appConfig.get('websocket.reconnectDelay') || 1000;
            this.pingInterval = appConfig.get('websocket.pingInterval') || 30000;
        } catch (error) {
            console.warn('Failed to load WebSocket config, using defaults');
        }
    }

    connect() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const wsUrl = `${protocol}//${window.location.host}/ws`;
        
        try {
            this.ws = new WebSocket(wsUrl);
            
            this.ws.onopen = () => {
                console.log('WebSocket connected');
                this.connected = true;
                this.reconnectAttempts = 0;
                this.connectionHandlers.connect.forEach(handler => handler());
            };

            this.ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    const eventType = data.type || 'message';
                    
                    if (this.eventHandlers[eventType]) {
                        this.eventHandlers[eventType].forEach(handler => {
                            handler(data.data || data);
                        });
                    }
                } catch (e) {
                    console.error('Failed to parse WebSocket message:', e);
                }
            };

            this.ws.onerror = (error) => {
                console.error('WebSocket error:', error);
            };

            this.ws.onclose = () => {
                console.log('WebSocket disconnected');
                this.connected = false;
                this.connectionHandlers.disconnect.forEach(handler => handler());
                
                // Attempt to reconnect
                if (this.reconnectAttempts < this.maxReconnectAttempts) {
                    this.reconnectAttempts++;
                    const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);
                    console.log(`Reconnecting in ${delay}ms... (attempt ${this.reconnectAttempts})`);
                    setTimeout(() => this.connect(), delay);
                }
            };

            // Send periodic ping to keep connection alive
            setInterval(() => {
                if (this.connected && this.ws.readyState === WebSocket.OPEN) {
                    this.ws.send(JSON.stringify({ type: 'ping' }));
                }
            }, this.pingInterval); // Configurable ping interval

        } catch (e) {
            console.error('Failed to create WebSocket:', e);
        }
    }

    on(event, handler) {
        if (event === 'connect' || event === 'disconnect') {
            this.connectionHandlers[event].push(handler);
        } else {
            if (!this.eventHandlers[event]) {
                this.eventHandlers[event] = [];
            }
            this.eventHandlers[event].push(handler);
        }
    }

    emit(event, data) {
        if (this.connected && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({
                type: event,
                data: data
            }));
        } else {
            console.warn('WebSocket not connected. Cannot emit:', event);
        }
    }

    disconnect() {
        if (this.ws) {
            this.reconnectAttempts = this.maxReconnectAttempts; // Prevent auto-reconnect
            this.ws.close();
            this.ws = null;
        }
    }
}

// Create a Socket.IO compatible interface
const io = () => {
    const adapter = new WebSocketAdapter();
    
    // Auto-connect on creation
    setTimeout(() => adapter.connect(), 100);
    
    return adapter;
};

// Make it globally available for compatibility
window.io = io;