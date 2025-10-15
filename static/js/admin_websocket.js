// Global WebSocket Manager for Jazzmin Admin
class AdminWebSocketManager {
    constructor() {
        // Skip initialization on change list pages
        if (window.__SKIP_DASHBOARD_INIT__ || window.__IS_CHANGE_LIST__) {
            console.log('⏭️ Skipping WebSocket manager init - change list page detected');
            this.disabled = true;
            return;
        }

        this.ws = null;
        this.retryCount = 0;
        this.maxRetries = 5;
        this.baseDelay = 2000;
        this.isConnected = false;
        this.reconnectTimeout = null;
        this.pendingMessages = [];
        this.callbacks = {
            connected: [],
            disconnected: [],
            message: [],
            weather: [],
            booking: [],
            ticket: [],
            cache: [],
            // Add change list specific callbacks
            changelist: []
        };

        this.init();
    }

    init() {
        if (this.disabled) return;

        this.connect();
        this.setupEventListeners();
        this.createStatusIndicator();
    }

    getWebSocketUrl() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        return `${protocol}//${window.location.host}/ws/admin/dashboard/`;
    }

    connect() {
        if (this.disabled) return;

        if (this.ws && (this.ws.readyState === WebSocket.CONNECTING || this.ws.readyState === WebSocket.OPEN)) {
            return;
        }

        if (this.retryCount >= this.maxRetries) {
            console.warn('Max WebSocket retries reached. Starting polling fallback.');
            this.startPollingFallback();
            return;
        }

        const url = this.getWebSocketUrl();
        console.log('Connecting to WebSocket:', url);
        this.ws = new WebSocket(url);

        this.ws.onopen = (event) => {
            console.log('✅ Admin WebSocket Connected');
            this.retryCount = 0;
            this.isConnected = true;
            this.updateStatus(true);

            // Send pending messages
            this.pendingMessages.forEach(msg => this.ws.send(msg));
            this.pendingMessages = [];

            // Send join message with page type
            this.send({
                type: 'join',
                user_id: {{ user.id|default:0 }},
                path: window.location.pathname,
                is_changelist: window.__IS_CHANGE_LIST__ || false,
                permissions: {{ perms|safe }}
            });

            this.callbacks.connected.forEach(cb => cb(event));
            document.dispatchEvent(new CustomEvent('admin-ws-connected'));
        };

        this.ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                this.handleMessage(data);

                // Always call message callbacks
                this.callbacks.message.forEach(cb => cb(data));

                // Forward to change list handler if it exists and message is relevant
                if (window.changeListWS &&
                    (data.model || data.app_label || data.type.includes('changelist'))) {
                    window.changeListWS.handleMessage(data);
                }
            } catch (e) {
                console.error('WebSocket message parse error:', e);
            }
        };

        this.ws.onclose = (event) => {
            console.log(`🔌 WebSocket Closed: ${event.code} - ${event.reason}`);
            this.isConnected = false;
            this.updateStatus(false);
            this.callbacks.disconnected.forEach(cb => cb(event));
            document.dispatchEvent(new CustomEvent('admin-ws-disconnected'));
            this.scheduleReconnect();
        };

        this.ws.onerror = (error) => {
            console.error('WebSocket Error:', error);
            this.isConnected = false;
            this.updateStatus(false);
        };
    }

    scheduleReconnect() {
        if (this.disabled) return;

        if (this.reconnectTimeout) clearTimeout(this.reconnectTimeout);

        const delay = this.baseDelay * Math.pow(2, this.retryCount);
        this.retryCount++;

        console.log(`🔄 Reconnecting in ${delay}ms (attempt ${this.retryCount}/${this.maxRetries})`);
        this.reconnectTimeout = setTimeout(() => {
            this.connect();
        }, delay);
    }

    send(data) {
        if (this.disabled) {
            console.warn('WebSocket manager disabled, cannot send message:', data.type);
            return false;
        }

        const message = JSON.stringify({ ...data, timestamp: new Date().toISOString() });

        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
            this.pendingMessages.push(message);
            console.log('📋 Message queued:', data.type);
            return false;
        }

        try {
            this.ws.send(message);
            return true;
        } catch (e) {
            console.error('Send failed:', e);
            this.pendingMessages.push(message);
            return false;
        }
    }

    handleMessage(data) {
        if (this.disabled) return;

        console.log('📨 WS Message:', data.type, data);

        // Handle change list specific messages (forward to changeListWS if exists)
        if (data.type === 'request_changelist_sync' ||
            data.type === 'selection_change' ||
            (data.model && data.app_label)) {
            // These are primarily handled by changeListWS
            return;
        }

        // Route to specific handlers
        switch (data.type) {
            case 'weather_alerts':
                this.callbacks.weather.forEach(cb => cb(data));
                this.showNotification('🌤️ Weather Alert', 'Weather conditions updated', 'info');
                break;

            case 'booking_update':
                this.callbacks.booking.forEach(cb => cb(data));
                this.showNotification('🎫 Booking',
                    `${data.action || 'updated'} - ${data.booking_id ? `Booking #${data.booking_id}` : data.count ? `${data.count} bookings` : 'updated'}`,
                    'primary');
                break;

            case 'ticket_update':
                this.showNotification('🎟️ Ticket',
                    `Status: ${data.new_status || data.action || 'updated'}`,
                    data.new_status === 'used' ? 'success' : 'info');
                break;

            case 'cache_cleared':
                this.callbacks.cache.forEach(cb => cb(data));
                this.showNotification('🔄 Cache', 'Analytics cache refreshed', 'warning');
                // Only refresh dashboard on actual dashboard page
                if (window.location.pathname === '/admin/' || window.location.pathname === '/admin') {
                    if (typeof refreshDashboard === 'function') refreshDashboard();
                }
                break;

            case 'connection_confirmed':
                this.sendInitialDataRequest();
                break;

            case 'error':
                console.error('WebSocket Error:', data.message);
                this.showNotification('❌ Connection Error', data.message || 'WebSocket connection failed', 'danger');
                break;

            case 'model_update':
            case 'schedule_update':
            case 'payment_update':
            case 'weather_alert':
                // These are handled by specific change list instances or dashboard
                break;

            default:
                console.log('Unknown message type, dispatching as event:', data.type);
                break;
        }

        // Always trigger custom events for other components to listen
        document.dispatchEvent(new CustomEvent(`admin-ws-${data.type}`, { detail: data }));
    }

    sendInitialDataRequest() {
        this.send({ action: 'request_initial_data' });
    }

    showNotification(title, message, type = 'info') {
        // Don't show notifications on change list pages to avoid spam
        if (window.__IS_CHANGE_LIST__) return;

        const container = document.getElementById('realtime-notifications');
        if (!container) {
            this.createNotificationToast(title, message, type);
            return;
        }

        const notification = document.createElement('div');
        notification.className = `alert alert-${type} alert-dismissible fade show position-fixed`;
        notification.style.cssText = `
            top: 20px; right: 20px; z-index: 9999; min-width: 300px; max-width: 400px;
            animation: slideInRight 0.3s ease-out;
        `;
        notification.innerHTML = `
            <div class="d-flex">
                <div class="flex-grow-1">
                    <strong>${title}</strong>
                    <div class="small opacity-75 mt-1">${message}</div>
                </div>
                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
            </div>
        `;

        container.appendChild(notification);

        // Auto-dismiss
        setTimeout(() => {
            if (notification.parentNode) {
                const bsAlert = bootstrap.Alert.getOrCreateInstance(notification);
                bsAlert.close();
            }
        }, 5000);
    }

    createNotificationToast(title, message, type) {
        const toastContainer = document.getElementById('realtime-notifications');
        if (!toastContainer) {
            const container = document.createElement('div');
            container.id = 'realtime-notifications';
            container.className = 'toast-container position-fixed top-0 end-0 p-3';
            container.style.zIndex = '9999';
            document.body.appendChild(container);
        }

        const toast = document.createElement('div');
        toast.className = `toast align-items-center text-white bg-${type} border-0`;
        toast.role = 'alert';
        toast.innerHTML = `
            <div class="d-flex">
                <div class="toast-body">
                    <strong>${title}</strong><br><small>${message}</small>
                </div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
            </div>
        `;

        const container = document.getElementById('realtime-notifications');
        container.appendChild(toast);

        const bsToast = new bootstrap.Toast(toast);
        bsToast.show();

        toast.addEventListener('hidden.bs.toast', () => {
            if (container.children.length === 0) {
                container.remove();
            }
        });
    }

    createStatusIndicator() {
        // Don't create duplicate indicators on change list pages (they have their own)
        if (document.getElementById('ws-status-indicator') || window.__IS_CHANGE_LIST__) {
            return;
        }

        const indicator = document.createElement('div');
        indicator.id = 'ws-status-indicator';
        indicator.className = 'ws-status ws-disconnected position-fixed';
        indicator.style.cssText = `
            top: 10px; right: 10px; z-index: 99999; padding: 8px 12px;
            border-radius: 20px; font-size: 0.75rem; font-weight: 500;
            background: rgba(239,68,68,0.1); border: 1px solid #ef4444;
            transition: all 0.3s ease; cursor: pointer;
        `;
        indicator.innerHTML = '<i class="fas fa-wifi-slash me-1"></i> Offline';
        indicator.title = 'WebSocket Status - Click to reconnect';

        indicator.addEventListener('click', () => {
            this.reconnect();
        });

        document.body.appendChild(indicator);
        this.statusIndicator = indicator;
    }

    updateStatus(connected) {
        if (this.disabled || !this.statusIndicator) return;

        if (connected) {
            this.statusIndicator.className = 'ws-status ws-connected';
            this.statusIndicator.style.background = 'rgba(16,185,129,0.1)';
            this.statusIndicator.style.borderColor = '#10b981';
            this.statusIndicator.innerHTML = '<i class="fas fa-wifi me-1"></i> Live';
        } else {
            this.statusIndicator.className = 'ws-status ws-disconnected';
            this.statusIndicator.style.background = 'rgba(239,68,68,0.1)';
            this.statusIndicator.style.borderColor = '#ef4444';
            this.statusIndicator.innerHTML = '<i class="fas fa-wifi-slash me-1"></i> Offline';
        }

        // Notify change list components
        document.dispatchEvent(new CustomEvent(connected ? 'admin-ws-connected' : 'admin-ws-disconnected'));
    }

    setupEventListeners() {
        if (this.disabled) return;

        document.addEventListener('visibilitychange', () => {
            if (!document.hidden && !this.isConnected) {
                this.connect();
            }
        });

        window.addEventListener('online', () => this.connect());
        window.addEventListener('offline', () => {
            if (this.ws) this.ws.close();
        });

        window.addEventListener('beforeunload', () => {
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.send({ type: 'leave', user_id: {{ user.id|default:0 }} });
            }
        });
    }

    startPollingFallback() {
        console.log('Starting HTTP polling fallback...');
        setInterval(() => {
            if (!this.isConnected && !this.disabled) {
                fetch('/admin/realtime-data/', {
                    headers: { 'X-Requested-With': 'XMLHttpRequest' }
                })
                .then(response => response.json())
                .then(data => {
                    if (data.error) return;

                    Object.keys(data).forEach(key => {
                        document.dispatchEvent(new CustomEvent(`admin-fallback-${key}`, { detail: data[key] }));
                    });
                })
                .catch(err => console.error('Polling error:', err));
            }
        }, 30000);
    }

    // Event registration methods
    on(event, callback) {
        if (this.disabled) return;
        if (this.callbacks[event]) {
            this.callbacks[event].push(callback);
        }
    }

    off(event, callback) {
        if (this.disabled || !this.callbacks[event]) return;
        this.callbacks[event] = this.callbacks[event].filter(cb => cb !== callback);
    }

    reconnect() {
        if (this.disabled) return;
        this.retryCount = 0;
        if (this.reconnectTimeout) clearTimeout(this.reconnectTimeout);
        if (this.ws) this.ws.close();
        this.connect();
    }
}

// Initialize conditionally
if (!window.__SKIP_DASHBOARD_INIT__) {
    window.adminWS = new AdminWebSocketManager();
    window.AdminWebSocketManager = window.adminWS;
} else {
    console.log('WebSocket manager skipped for change list page');
}

// Auto-initialize with safety checks
document.addEventListener('DOMContentLoaded', () => {
    if (!window.__SKIP_DASHBOARD_INIT__ && window.adminWS && !window.adminWS.isConnected) {
        setTimeout(() => {
            if (window.adminWS && !window.adminWS.disabled) {
                window.adminWS.connect();
            }
        }, 1000);
    }
});

// Global CSS for status indicators (idempotent)
if (!document.querySelector('#ws-global-styles')) {
    const style = document.createElement('style');
    style.id = 'ws-global-styles';
    style.textContent = `
        .ws-status {
            position: fixed;
            top: 10px;
            right: 10px;
            z-index: 99999;
            padding: 8px 12px;
            border-radius: 20px;
            font-size: 0.75rem;
            font-weight: 500;
            transition: all 0.3s ease;
            cursor: pointer;
            border: 1px solid;
        }
        .ws-status:hover { transform: scale(1.05); }
        .ws-status.ws-connected {
            background: rgba(16,185,129,0.1);
            border-color: #10b981;
            color: #10b981;
            animation: pulse-green 2s infinite;
        }
        .ws-status.ws-disconnected {
            background: rgba(239,68,68,0.1);
            border-color: #ef4444;
            color: #ef4444;
        }
        @keyframes pulse-green {
            0%, 100% { box-shadow: 0 0 5px rgba(16,185,129,0.5); }
            50% { box-shadow: 0 0 20px rgba(16,185,129,0.8); }
        }
        @keyframes spin {
            from { transform: rotate(0deg); }
            to { transform: rotate(360deg); }
        }
        .status-indicator {
            display: inline-flex;
            align-items: center;
            gap: 0.5rem;
            padding: 0.375rem 0.75rem;
            border-radius: 1rem;
            font-size: 0.875rem;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.3s ease;
            border: 1px solid transparent;
        }
        .status-indicator.connected {
            background: rgba(34, 197, 94, 0.1);
            border-color: #22c55e;
            color: #22c55e;
        }
        .status-indicator.connected i {
            color: #22c55e;
            animation: pulse 2s infinite;
        }
        .status-indicator.disconnected {
            background: rgba(239, 68, 68, 0.1);
            border-color: #ef4444;
            color: #ef4444;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
    `;
    document.head.appendChild(style);
}