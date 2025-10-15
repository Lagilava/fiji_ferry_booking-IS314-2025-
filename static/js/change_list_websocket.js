// change_list_websocket.js - Integrates with global adminWS for change lists
(function() {
    'use strict';

    document.addEventListener('DOMContentLoaded', function() {
        // Prevent duplicate initialization
        if (window.changeListWS) {
            console.log('ChangeList WebSocket already initialized');
            return;
        }

        console.log('🛠️ Initializing ChangeList WebSocket integration...');

        // Wait for global WS and jQuery to be available
        function initializeWhenReady() {
            if (!window.adminWS || typeof jQuery === 'undefined') {
                setTimeout(initializeWhenReady, 500);
                return;
            }

            class ChangeListIntegration {
                constructor() {
                    this.model = window.WEBSOCKET_CONFIG?.model || 'unknown';
                    this.app_label = window.WEBSOCKET_CONFIG?.app_label || 'unknown';
                    this.selectedIds = new Set();
                    this.currentFilters = {};
                    this.statusElement = null;
                    this.setup();
                }

                setup() {
                    console.log(`📡 ChangeList WS for ${this.app_label}.${this.model}`);

                    // Register with global WS for model-specific messages
                    if (window.adminWS.on) {
                        window.adminWS.on('message', (data) => this.handleMessage(data));
                    }

                    // Listen for model-specific custom events
                    ['model_update', 'full_sync', 'activity', 'selection_change'].forEach(type => {
                        document.addEventListener(`admin-ws-${type}`, (e) => {
                            const data = e.detail;
                            if (data.app_label === this.app_label && data.model === this.model) {
                                this.handleMessage({ type, ...data });
                            }
                        });
                    });

                    this.setupUI();
                    this.monitorSelections();
                    this.monitorFilters();

                    // Initial sync after short delay
                    setTimeout(() => this.requestSync(), 1500);
                }

                handleMessage(data) {
                    console.log(`📨 ChangeList [${this.model}]:`, data.type);

                    switch (data.type) {
                        case 'model_update':
                            this.handleModelUpdate(data);
                            break;
                        case 'full_sync':
                            this.handleFullSync(data);
                            break;
                        case 'activity':
                            this.handleActivity(data);
                            break;
                        case 'selection_change':
                            this.handleSelectionChange(data);
                            break;
                        case 'connection_confirmed':
                            this.requestSync();
                            break;
                    }
                }

                handleModelUpdate(data) {
                    console.log(`🔄 ${data.action} on ${data.objects?.length || 1} items`);

                    // Add data-object-id to existing rows if missing
                    document.querySelectorAll('#result_list tbody tr').forEach(row => {
                        if (!row.dataset.objectId && row.querySelector('input[name="_selected_action"]')) {
                            const checkbox = row.querySelector('input[name="_selected_action"]');
                            if (checkbox && checkbox.value) {
                                row.dataset.objectId = checkbox.value;
                            }
                        }
                    });

                    data.objects?.forEach(obj => {
                        let row = document.querySelector(`tr[data-object-id="${obj.id}"]`);

                        if (data.action === 'create') {
                            if (!row) {
                                this.insertNewRow(obj);
                                this.showNotification('➕ New', `${this.model} #${obj.id} created`);
                            }
                        } else if (data.action === 'update') {
                            if (row) {
                                this.updateRow(row, obj);
                                row.classList.add('table-warning', 'updated-row');
                                setTimeout(() => row.classList.remove('table-warning', 'updated-row'), 3000);
                                this.showNotification('✏️ Updated', `${this.model} #${obj.id} modified`);
                            }
                        } else if (data.action === 'delete') {
                            if (row) {
                                row.style.transition = 'opacity 0.5s ease';
                                row.style.opacity = '0';
                                setTimeout(() => {
                                    if (row) row.remove();
                                    this.showNotification('🗑️ Deleted', `${this.model} #${obj.id} removed`);
                                }, 500);
                            }
                        }
                    });

                    const resultsContainer = document.getElementById('results-container');
                    if (resultsContainer) {
                        resultsContainer.classList.add('updated');
                        setTimeout(() => resultsContainer.classList.remove('updated'), 1000);
                    }
                }

                insertNewRow(obj) {
                    const table = document.querySelector('#result_list');
                    if (!table) return;

                    const tbody = table.querySelector('tbody');
                    if (!tbody) return;

                    const row = document.createElement('tr');
                    row.dataset.objectId = obj.id;
                    row.className = 'table-success updated-row';

                    // Add checkbox cell
                    const checkboxCell = document.createElement('td');
                    checkboxCell.className = 'action-checkbox';
                    checkboxCell.innerHTML = `<input type="checkbox" class="action-select" value="${obj.id}" name="_selected_action">`;
                    row.appendChild(checkboxCell);

                    // Add data cells
                    const fields = obj.fields || {};
                    Object.entries(fields).forEach(([key, value]) => {
                        const cell = document.createElement('td');
                        cell.className = `field-${key}`;
                        cell.textContent = value || 'N/A';
                        row.appendChild(cell);
                    });

                    // Add action cell
                    const actionCell = document.createElement('td');
                    actionCell.className = 'field-__recent_actions';
                    actionCell.innerHTML = `<a href="/admin/${this.app_label}/${this.model}/${obj.id}/change/" class="viewsalinks">Change</a>`;
                    row.appendChild(actionCell);

                    tbody.insertBefore(row, tbody.firstChild);

                    // Add selection handler
                    const checkbox = checkboxCell.querySelector('.action-select');
                    if (checkbox) {
                        checkbox.addEventListener('change', (e) => {
                            this.handleSelection(e.target.checked, obj.id);
                        });
                    }
                }

                updateRow(row, obj) {
                    const cells = row.querySelectorAll('td:not(.action-checkbox):not(.field-__recent_actions)');
                    const fields = obj.fields || {};

                    Object.entries(fields).forEach(([key, value], index) => {
                        if (cells[index]) {
                            cells[index].textContent = value || 'N/A';
                            cells[index].classList.add('updated-cell');
                            setTimeout(() => cells[index].classList.remove('updated-cell'), 2000);
                        }
                    });
                }

                handleFullSync(data) {
                    console.log(`🔄 Full sync: ${data.objects?.length || 0} items`);
                    this.showNotification('🔄 Synced', `${data.total_count || 0} items refreshed`);
                    this.updateCounts(data);
                }

                handleActivity(data) {
                    this.addActivityItem({
                        timestamp: new Date().toLocaleTimeString(),
                        user: data.user || 'System',
                        action: data.action,
                        target: data.target || `${this.model} #${data.id || 'unknown'}`,
                        details: data.details
                    });
                }

                handleSelectionChange(data) {
                    data.selected?.forEach(id => {
                        const checkbox = document.querySelector(`input.action-select[value="${id}"]`);
                        if (checkbox && !checkbox.checked) {
                            checkbox.checked = true;
                            checkbox.closest('tr')?.classList.add('table-info');
                            setTimeout(() => checkbox.closest('tr')?.classList.remove('table-info'), 1000);
                            this.selectedIds.add(id);
                        }
                    });
                    this.updateExportButton();
                }

                setupUI() {
                    // Status indicator
                    const statusEl = document.getElementById('ws-indicator');
                    if (statusEl) {
                        this.statusElement = statusEl;
                        if (window.adminWS?.isConnected) {
                            statusEl.className = 'status-indicator connected';
                            statusEl.innerHTML = '<i class="fas fa-circle"></i> Live';
                        }
                        statusEl.addEventListener('click', () => {
                            if (window.adminWS) window.adminWS.reconnect();
                            this.requestSync();
                        });
                    }

                    // Export button
                    const exportBtn = document.getElementById('export-selection');
                    if (exportBtn) {
                        exportBtn.addEventListener('click', () => this.exportSelected());
                    }

                    // Refresh button
                    const refreshBtn = document.getElementById('ws-refresh');
                    if (refreshBtn) {
                        refreshBtn.addEventListener('click', (e) => {
                            e.preventDefault();
                            this.requestSync();
                            const icon = refreshBtn.querySelector('i');
                            icon.classList.add('fa-spin');
                            setTimeout(() => icon.classList.remove('fa-spin'), 1000);
                        });
                    }

                    // Activity toggle
                    const activityToggle = document.getElementById('activity-toggle');
                    if (activityToggle) {
                        activityToggle.addEventListener('click', this.toggleActivity.bind(this));
                    }

                    // Listen for global WS connection changes
                    document.addEventListener('admin-ws-connected', () => {
                        if (this.statusElement) {
                            this.statusElement.className = 'status-indicator connected';
                            this.statusElement.innerHTML = '<i class="fas fa-circle"></i> Live';
                        }
                        this.requestSync();
                    });

                    document.addEventListener('admin-ws-disconnected', () => {
                        if (this.statusElement) {
                            this.statusElement.className = 'status-indicator disconnected';
                            this.statusElement.innerHTML = '<i class="fas fa-circle"></i> Offline';
                        }
                    });
                }

                monitorSelections() {
                    document.addEventListener('change', (e) => {
                        if (e.target.matches('.action-select')) {
                            this.handleSelection(e.target.checked, e.target.value);
                        }
                    }, true); // Use capture phase for dynamic elements
                }

                handleSelection(checked, id) {
                    if (checked) {
                        this.selectedIds.add(id);
                    } else {
                        this.selectedIds.delete(id);
                    }

                    this.updateExportButton();

                    // Broadcast to other clients
                    if (window.adminWS?.send) {
                        window.adminWS.send({
                            type: 'selection_change',
                            model: this.model,
                            app_label: this.app_label,
                            selected: Array.from(this.selectedIds)
                        });
                    }
                }

                monitorFilters() {
                    let currentUrl = window.location.href;
                    const urlCheckInterval = setInterval(() => {
                        if (window.location.href !== currentUrl) {
                            currentUrl = window.location.href;
                            this.currentFilters = this.parseFiltersFromUrl();
                            setTimeout(() => this.requestSync(), 500);
                        }
                    }, 1000);

                    // Watch search input
                    const searchInput = document.querySelector('#searchbar input, input[name="q"]');
                    if (searchInput) {
                        searchInput.addEventListener('input', this.debounce(() => {
                            this.requestSync();
                        }, 800));
                    }

                    // Cleanup
                    window.addEventListener('beforeunload', () => clearInterval(urlCheckInterval));
                }

                parseFiltersFromUrl() {
                    const params = new URLSearchParams(window.location.search);
                    const filters = {};
                    params.forEach((value, key) => {
                        if (!['p', 'o'].includes(key) && value) {
                            filters[key] = value;
                        }
                    });

                    const searchInput = document.querySelector('#searchbar input, input[name="q"]');
                    if (searchInput?.value) {
                        filters.q = searchInput.value;
                    }

                    return filters;
                }

                requestSync() {
                    if (!window.adminWS?.isConnected) {
                        console.warn('Global WS not connected, sync delayed');
                        return;
                    }

                    window.adminWS.send({
                        type: 'request_changelist_sync',
                        model: this.model,
                        app_label: this.app_label,
                        filters: this.parseFiltersFromUrl()
                    });

                    this.showNotification('🔄 Syncing...', `Refreshing ${this.model} data...`);
                }

                updateExportButton() {
                    const count = this.selectedIds.size;
                    const btn = document.getElementById('export-selection');
                    if (btn) {
                        btn.disabled = count === 0;
                        btn.innerHTML = `<i class="fas fa-download"></i> Export ${count || 'Selected'}`;
                        btn.title = count ? `Export ${count} selected items` : 'Select items to export';
                    }
                }

                async exportSelected() {
                    if (this.selectedIds.size === 0) {
                        this.showNotification('❌ No Selection', 'Please select items to export', 'warning');
                        return;
                    }

                    const csrfToken = document.querySelector('[name=csrfmiddlewaretoken]');
                    if (!csrfToken) {
                        this.showNotification('❌ CSRF Error', 'Cannot export without security token', 'danger');
                        return;
                    }

                    try {
                        this.showNotification('📤 Exporting...', `${this.selectedIds.size} items...`);

                        const response = await fetch(`/admin/${this.app_label}/${this.model}/export/`, {
                            method: 'POST',
                            headers: {
                                'X-CSRFToken': csrfToken.value,
                                'Content-Type': 'application/json',
                            },
                            body: JSON.stringify({
                                ids: Array.from(this.selectedIds),
                                format: 'csv'
                            })
                        });

                        if (response.ok) {
                            const blob = await response.blob();
                            const contentType = response.headers.get('content-type');
                            let filename = `${this.model}_export_${Date.now()}.csv`;

                            const disposition = response.headers.get('content-disposition');
                            if (disposition && disposition.indexOf('attachment') !== -1) {
                                const matches = /filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/.exec(disposition);
                                if (matches != null && matches[1]) {
                                    filename = matches[1].replace(/['"]/g, '');
                                }
                            }

                            const url = URL.createObjectURL(blob);
                            const a = document.createElement('a');
                            a.href = url;
                            a.download = filename;
                            document.body.appendChild(a);
                            a.click();
                            document.body.removeChild(a);
                            URL.revokeObjectURL(url);

                            this.showNotification('✅ Export Complete', `${this.selectedIds.size} items exported`, 'success');
                        } else {
                            const errorText = await response.text();
                            throw new Error(`Export failed: ${response.status} ${errorText}`);
                        }
                    } catch (error) {
                        console.error('Export failed:', error);
                        this.showNotification('❌ Export Failed', error.message, 'danger');
                    }
                }

                addActivityItem(activity) {
                    const container = document.getElementById('activity-feed-content');
                    if (!container) return;

                    const empty = container.querySelector('.activity-empty');
                    if (empty) empty.style.display = 'none';

                    const item = document.createElement('div');
                    item.className = 'activity-item p-2 border-bottom small';
                    item.innerHTML = `
                        <div class="d-flex justify-content-between align-items-start">
                            <div class="flex-grow-1">
                                <div class="d-flex justify-content-between mb-1">
                                    <span class="fw-bold text-primary">${activity.action}</span>
                                    <small class="text-muted">${activity.timestamp}</small>
                                </div>
                                <div class="text-sm">${activity.target}</div>
                                ${activity.details ? `<small class="text-muted mt-1 d-block">${activity.details}</small>` : ''}
                            </div>
                            <span class="badge bg-secondary ms-2">${activity.user}</span>
                        </div>
                    `;

                    container.insertBefore(item, container.firstChild);

                    // Limit to 15 items
                    const items = container.querySelectorAll('.activity-item');
                    if (items.length > 15) {
                        items[items.length - 1].remove();
                    }
                }

                toggleActivity() {
                    const content = document.getElementById('activity-feed-content');
                    const toggle = document.getElementById('activity-toggle');
                    const icon = toggle?.querySelector('i');

                    if (content.style.display === 'none' || !content.style.display) {
                        content.style.display = 'block';
                        if (icon) icon.className = 'fas fa-minus';
                    } else {
                        content.style.display = 'none';
                        if (icon) icon.className = 'fas fa-plus';
                    }
                }

                updateCounts(data) {
                    const countElements = document.querySelectorAll('.results-count, [data-result-count]');
                    countElements.forEach(el => {
                        if (data.total_count !== undefined) {
                            el.textContent = data.total_count.toLocaleString();
                        }
                    });
                }

                showNotification(title, message, type = 'info') {
                    if (window.adminWS?.showNotification) {
                        window.adminWS.showNotification(title, message, type);
                    } else {
                        // Fallback notification
                        const notification = document.createElement('div');
                        notification.className = `alert alert-${type} alert-dismissible fade show position-fixed`;
                        notification.style.cssText = `
                            top: 20px; right: 20px; z-index: 9999; min-width: 300px; max-width: 400px;
                        `;
                        notification.innerHTML = `
                            <div class="d-flex">
                                <div class="flex-grow-1">
                                    <strong>${title}</strong>
                                    <div class="small opacity-75 mt-1">${message}</div>
                                </div>
                                <button type="button" class="btn-close" onclick="this.parentElement.parentElement.remove()"></button>
                            </div>
                        `;
                        document.body.appendChild(notification);
                        setTimeout(() => notification.remove(), 5000);
                    }
                }

                debounce(func, wait) {
                    let timeout;
                    return function executedFunction(...args) {
                        const later = () => {
                            clearTimeout(timeout);
                            func(...args);
                        };
                        clearTimeout(timeout);
                        timeout = setTimeout(later, wait);
                    };
                }
            }

            // Initialize
            window.changeListWS = new ChangeListIntegration();
            console.log('✅ ChangeList WebSocket integration complete');
        }

        initializeWhenReady();
    });
})();