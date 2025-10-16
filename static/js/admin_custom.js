document.addEventListener('DOMContentLoaded', function() {
    // Prevent duplicate initialization
    if (document.getElementById('chartScript') && window.chartInitialized) {
        console.log('Dashboard already initialized, skipping.');
        return;
    }
    console.log("Custom admin JS loaded - Initializing enhanced dashboard");
    window.chartInitialized = true;

    // Color schemes
    const colors = {
        light: {
            bookings: { express: '#26a69a', standard: '#4fc3f7', border: '#1e40af' },
            utilization: ['#26a69a', '#4fc3f7', '#81d4fa', '#ffb300', '#e0f7fa'],
            revenue: { revenue: { background: 'rgba(38, 166, 154, 0.3)', border: '#26a69a', point: '#ffffff' }, bookings: { background: 'rgba(79, 195, 247, 0.3)', border: '#4fc3f7', point: '#ffffff' } },
            payment: ['#26a69a', '#ffb300', '#b91c1c'],
            userGrowth: { background: 'rgba(171, 71, 188, 0.3)', border: '#ab47bc', point: '#ffffff' },
            topCustomers: ['#26a69a', '#4fc3f7', '#81d4fa', '#ffb300', '#e0f7fa'],
            weather: ['#4fc3f7', '#26a69a', '#81d4fa', '#0288d1', '#b3e5fc'],
            tooltip: { background: 'rgba(31, 41, 55, 0.9)', text: '#ffffff', body: '#e5e7eb', border: '#1e40af' },
            text: '#1f2937',
            background: '#f8fafc',
            chartBg: '#ffffff',
            warning: '#b91c1c',
            success: '#047857',
            primaryHover: '#2563eb',
            muted: '#6b7280',
            secondaryHover: '#d1d5db'
        },
        dark: {
            bookings: { express: '#26a69a', standard: '#4fc3f7', border: '#60a5fa' },
            utilization: ['#26a69a', '#4fc3f7', '#81d4fa', '#ffb300', '#b0bec5'],
            revenue: { revenue: { background: 'rgba(38, 166, 154, 0.4)', border: '#26a69a', point: '#e5e7eb' }, bookings: { background: 'rgba(79, 195, 247, 0.4)', border: '#4fc3f7', point: '#e5e7eb' } },
            payment: ['#26a69a', '#ffb300', '#f87171'],
            userGrowth: { background: 'rgba(171, 71, 188, 0.4)', border: '#ab47bc', point: '#e5e7eb' },
            topCustomers: ['#26a69a', '#4fc3f7', '#81d4fa', '#ffb300', '#b0bec5'],
            weather: ['#4fc3f7', '#26a69a', '#81d4fa', '#0288d1', '#b3e5fc'],
            tooltip: { background: '#374151', text: '#ffffff', body: '#e5e7eb', border: '#4b5563' },
            text: '#e5e7eb',
            background: '#1f2937',
            chartBg: '#374151',
            warning: '#f87171',
            success: '#10b981',
            primaryHover: '#93c5fd',
            muted: '#9ca3af',
            secondaryHover: '#4b5563'
        }
    };

    // Make colors globally available for qr_scanner.js
    window.colors = colors;

    // Initialize theme
    const isDarkMode = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const theme = isDarkMode ? colors.dark : colors.light;

    // Cache wrappers and chart instances
    const wrappers = {
        bookingsChart: document.querySelector('#bookings .chart-wrapper'),
        utilizationChart: document.querySelector('#utilization .chart-wrapper'),
        revenueChart: document.querySelector('#revenue .chart-wrapper'),
        paymentChart: document.querySelector('#payment .chart-wrapper'),
        userGrowthChart: document.querySelector('#user-growth .chart-wrapper'),
        topCustomersChart: document.querySelector('#customers .chart-wrapper'),
        performanceMetrics: document.querySelector('#performance_metrics'),
        weatherAlerts: document.querySelector('#weather_alerts')
    };
    const charts = {};
    let activeChartId = 'bookingsChart';

    // Log wrapper initialization
    Object.keys(wrappers).forEach(key => {
        console.log(`Wrapper ${key} found: ${!!wrappers[key]}`);
        if (!wrappers[key] && ['performanceMetrics', 'weatherAlerts'].includes(key)) {
            console.error(`Critical widget wrapper missing: ${key}. Check template rendering for ${key === 'performanceMetrics' ? 'bookings/admin_widgets/performance_metrics.html' : 'bookings/admin_widgets/weather_alerts.html'}.`);
        }
    });

    // Get CSRF token
    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        console.log(`CSRF token retrieved: ${cookieValue ? 'Present' : 'Missing'}`);
        return cookieValue;
    }

    // Enhance chart accessibility
    function enhanceChartAccessibility(chart, chartName) {
        if (chart && chart.canvas) {
            chart.canvas.setAttribute('aria-label', `Interactive ${chartName} chart`);
            chart.canvas.setAttribute('role', 'img');
            chart.canvas.setAttribute('tabindex', '0');
            chart.canvas.addEventListener('focus', () => {
                console.log(`${chartName} chart focused`);
            });
        }
    }

    // Clear all charts
    function clearAllCharts() {
        Object.keys(wrappers).forEach(id => {
            if (id.includes('Chart')) {
                const wrapper = wrappers[id];
                if (wrapper) {
                    wrapper.innerHTML = '';
                }
                const chartName = id.replace('Chart', '');
                if (charts[chartName]) {
                    charts[chartName].destroy();
                    delete charts[chartName];
                }
                const tabPane = wrapper?.closest('.tab-pane');
                if (tabPane) {
                    tabPane.classList.remove('show', 'active');
                    tabPane.style.display = 'none';
                    tabPane.style.opacity = '0';
                }
                const tabLink = document.querySelector(`.nav-link[data-bs-target="#${chartName}"]`);
                if (tabLink) tabLink.classList.remove('active');
            }
        });
    }

    // Initialize chart
    function initializeChart(wrapper, type, data, options, chartName) {
        if (!wrapper) {
            console.warn(`Wrapper not found for ${chartName}`);
            return null;
        }
        wrapper.innerHTML = `
            <div class="chart-loading" style="text-align: center; color: ${theme.text}; font-size: 1rem; padding: 2rem; height: 100%; display: flex; align-items: center; justify-content: center; background-color: ${theme.chartBg}; border-radius: 8px;">
                <i class="fas fa-spinner fa-spin"></i> Loading ${chartName}...
            </div>`;
        if (!data.datasets || data.datasets.length === 0 || !data.labels || data.labels.length === 0) {
            console.warn(`Chart not initialized: ${chartName} - No valid data or labels`);
            wrapper.innerHTML = `
                <div style="text-align: center; color: ${theme.text}; font-size: 1rem; padding: 2rem; height: 100%; display: flex; align-items: center; justify-content: center; background-color: ${theme.chartBg}; border-radius: 8px;">
                    No ${chartName} data available
                </div>`;
            return null;
        }
        const canvas = document.createElement('canvas');
        canvas.id = wrapper.getAttribute('data-chart-id') || chartName.toLowerCase().replace(/\s+/g, '-');
        canvas.style.width = '100%';
        canvas.style.height = '100%';
        canvas.style.minHeight = '400px';
        canvas.style.maxHeight = '450px';
        canvas.style.backgroundColor = theme.chartBg;
        wrapper.innerHTML = '';
        wrapper.appendChild(canvas);
        const ctx = canvas.getContext('2d');
        if (!ctx) {
            console.warn(`Chart not initialized: ${chartName} - No canvas context`);
            return null;
        }
        const existingChart = Chart.getChart(canvas.id);
        if (existingChart) existingChart.destroy();

        // Create a deep copy of options to avoid mutation issues
        const updatedOptions = JSON.parse(JSON.stringify(options));

        // Update scales with theme
        if (updatedOptions.scales) {
            Object.keys(updatedOptions.scales).forEach(scaleKey => {
                if (updatedOptions.scales[scaleKey]) {
                    updatedOptions.scales[scaleKey].ticks = {
                        ...updatedOptions.scales[scaleKey].ticks,
                        color: theme.text,
                        font: { size: 12 }
                    };
                    if (updatedOptions.scales[scaleKey].title) {
                        updatedOptions.scales[scaleKey].title.color = theme.text;
                    }
                }
            });
        }

        // Update plugins with theme
        if (!updatedOptions.plugins) updatedOptions.plugins = {};
        updatedOptions.plugins.tooltip = {
            backgroundColor: theme.tooltip.background,
            titleColor: theme.tooltip.text,
            bodyColor: theme.tooltip.body,
            borderColor: theme.tooltip.border,
            borderWidth: 1,
            caretSize: 6,
            cornerRadius: 6,
            padding: 10
        };
        if (updatedOptions.plugins.legend) {
            updatedOptions.plugins.legend.labels = {
                ...updatedOptions.plugins.legend.labels,
                color: theme.text,
                font: { size: 14 }
            };
        }
        if (updatedOptions.plugins.title) {
            updatedOptions.plugins.title.color = theme.text;
            updatedOptions.plugins.title.font = { size: 16, weight: '600' };
        }

        // Set responsive options
        updatedOptions.responsive = true;
        updatedOptions.maintainAspectRatio = false;
        updatedOptions.animation = { duration: 500, easing: 'easeOutQuart' };

        const chart = new Chart(ctx, { type, data, options: updatedOptions });
        charts[chartName] = chart;

        // Add resize observer
        const resizeObserver = new ResizeObserver(() => {
            if (chartName !== activeChartId.replace('Chart', '')) return;
            console.log(`Wrapper dimensions for ${chartName}: width=${wrapper.offsetWidth}px, height=${wrapper.offsetHeight}px`);
            canvas.width = Math.max(wrapper.offsetWidth, 800);
            canvas.height = Math.min(Math.max(wrapper.offsetHeight, 400), 450);
            chart.resize();
            console.log(`Chart ${chartName} resized due to container change`);
        });
        resizeObserver.observe(wrapper);
        enhanceChartAccessibility(chart, chartName);
        console.log(`${chartName} chart initialized with data:`, data);
        return chart;
    }

    // Debounce function
    function debounce(func, wait) {
        let timeout;
        return function(...args) {
            clearTimeout(timeout);
            timeout = setTimeout(() => func(...args), wait);
        };
    }

    // Fetch widget data
    window.fetchWidgetData = function(url, widget, retries = 3, delay = 2000) {
        if (!widget) {
            console.error(`Widget element not found for URL: ${url}.`);
            return;
        }
        const widgetId = widget.id || 'unknown';
        console.log(`Fetching widget data for ${widgetId} from: ${url}`);
        const spinner = widget.querySelector('.fa-sync-alt');
        if (spinner) spinner.classList.remove('hidden');
        const csrfToken = getCookie('csrftoken');
        if (!csrfToken) {
            console.error(`CSRF token not found for ${url}`);
            widget.innerHTML = `<p style="color: ${theme.warning}; text-align: center;">Error: CSRF token missing.</p>`;
            if (spinner) spinner.classList.add('hidden');
            return;
        }
        fetch(url, {
            method: 'GET',
            headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': csrfToken }
        })
        .then(response => {
            console.log(`Response status for ${url}: ${response.status}`);
            if (!response.ok) throw new Error(`HTTP error! Status: ${response.status}`);
            return response.json();
        })
        .then(data => {
            console.log(`Widget data fetched for ${widgetId}:`, data);
            updateWidgetContent(widget, data);
            if (spinner) spinner.classList.add('hidden');
            reattachRefreshListeners();
        })
        .catch(error => {
            console.error(`Error fetching widget data for ${widgetId}:`, error);
            if (retries > 0) {
                console.warn(`Retrying fetch for ${url} in ${delay}ms... (${retries} retries left)`);
                setTimeout(() => window.fetchWidgetData(url, widget, retries - 1, delay * 1.5), delay);
            } else {
                widget.innerHTML = `<p style="color: ${theme.warning}; text-align: center;">Error loading widget: ${error.message}.</p>`;
                if (spinner) spinner.classList.add('hidden');
            }
        });
    };

    // Parse alert message function
    function parseAlertMessage(message) {
        if (!message || typeof message !== 'string') {
            return { condition: 'N/A', port: 'Unknown', wind_speed: null, precipitation_probability: null, temperature: null };
        }
        const alertPrefix = 'WEATHER ALERT: ';
        if (!message.startsWith(alertPrefix)) {
            return { condition: 'N/A', port: 'Unknown', wind_speed: null, precipitation_probability: null, temperature: null };
        }
        let content = message.substring(alertPrefix.length);
        const parenIndex = content.indexOf('(');
        let desc, details;
        if (parenIndex !== -1) {
            desc = content.substring(0, parenIndex).trim();
            details = content.substring(parenIndex + 1, content.length - 1).trim();
        } else {
            desc = content.trim();
            details = '';
        }
        const atIndex = desc.indexOf(' at ');
        let condition = 'N/A', port = 'Unknown';
        if (atIndex !== -1) {
            condition = desc.substring(0, atIndex).trim();
            port = desc.substring(atIndex + 4).trim();
        } else {
            condition = desc;
        }
        let wind_speed = null, precipitation_probability = null;
        if (details) {
            const parts = details.split(',');
            parts.forEach(part => {
                part = part.trim();
                if (part.startsWith('Wind:')) {
                    const val = part.substring(5).trim().replace('km/h', '');
                    wind_speed = parseFloat(val);
                } else if (part.startsWith('Precip:')) {
                    const val = part.substring(7).trim().replace('%', '');
                    precipitation_probability = parseFloat(val);
                }
            });
        }
        return {
            condition,
            port,
            wind_speed,
            precipitation_probability,
            temperature: null
        };
    }

    // Update widget content
    function updateWidgetContent(widget, data) {
        if (!widget) {
            console.error('Widget element is null during update');
            return;
        }

        const widgetId = widget.id;
        console.log(`Updating widget content for ${widgetId}:`, data);

        try {
            if (widgetId === 'performance_metrics') {
                widget.innerHTML = `
                    <div class="section-header">
                        <h3 class="section-title">Performance Metrics</h3>
                        <button id="refresh-performance-metrics" class="btn btn-secondary" aria-label="Refresh performance metrics">
                            <i class="fas fa-sync-alt hidden" id="performance-metrics-spinner"></i> Refresh
                        </button>
                    </div>
                    <div class="stats-grid">
                        <div class="stat-item">
                            <h3 class="stat-number" id="total-bookings" aria-label="Total bookings">${data.total_bookings || 0}</h3>
                            <p class="stat-label">Total Bookings</p>
                        </div>
                        <div class="stat-item">
                            <h3 class="stat-number" id="active-ferries" aria-label="Active ferries">${data.active_ferries || 0}</h3>
                            <p class="stat-label">Active Ferries</p>
                        </div>
                        <div class="stat-item">
                            <h3 class="stat-number" id="pending-payments" aria-label="Pending payments">${data.pending_payments || 0}</h3>
                            <p class="stat-label">Pending Payments</p>
                        </div>
                    </div>
                    <small class="text-muted">Updated: ${data.updated_at ? new Date(data.updated_at).toLocaleString() : 'N/A'}</small>
                `;
            } else if (widgetId === 'weather_alerts') {
                let alertsHtml = `
                    <div class="section-header">
                        <h3 class="section-title">Weather Alerts</h3>
                        <button id="refresh-weather-alerts" class="btn btn-secondary" aria-label="Refresh weather alerts" data-tippy-content="Refresh weather alerts">
                            <i class="fas fa-sync-alt hidden" id="weather-alerts-spinner"></i> Refresh
                        </button>
                    </div>
                    <div class="weather-alerts-list" aria-live="polite" style="
                        max-height: 320px;
                        overflow-y: auto;
                        scrollbar-width: thin;
                        scrollbar-color: ${theme.muted} ${theme.chartBg};
                        background: ${theme.chartBg};
                        border: 1px solid ${theme.border};
                        border-radius: 8px;
                        animation: fadeIn 0.5s ease-out;
                    ">
                `;

                // Merge both possible alert arrays
                const alerts = Array.isArray(data.weather_alerts) && data.weather_alerts.length > 0
                    ? data.weather_alerts
                    : (Array.isArray(data.data) ? data.data : []);

                if (alerts.length > 0) {
                    alertsHtml += '<ul class="list-group" style="list-style: none; padding: 0; margin: 0;">';
                    alerts.forEach(alert => {
                        let port = 'Unknown';
                        let condition = 'N/A';
                        let wind_speed = null;
                        let precipitation_probability = null;
                        let temperature = null;

                        // Check if direct fields or need parsing
                        if (alert.message) {
                            const parsed = parseAlertMessage(alert.message);
                            port = parsed.port;
                            condition = parsed.condition;
                            wind_speed = parsed.wind_speed;
                            precipitation_probability = parsed.precipitation_probability;
                            temperature = parsed.temperature;
                        } else {
                            // Direct fields (weather_conditions format)
                            port = alert.port || 'Unknown';
                            condition = alert.condition || 'N/A';
                            wind_speed = alert.wind_speed;
                            precipitation_probability = alert.precipitation_probability;
                            temperature = alert.temperature;
                        }

                        const wind = wind_speed !== null ? wind_speed.toFixed(1) : 'N/A';
                        const temp = temperature !== null ? temperature.toFixed(1) : 'N/A';
                        const precip = precipitation_probability !== null ? precipitation_probability.toFixed(0) : 'N/A';

                        let badgeHtml = '';
                        if (alert.severity === 'high') {
                            badgeHtml = `<span class="badge bg-danger" style="
                                background: ${theme.warning};
                                color: #ffffff;
                                padding: 0.4rem 0.8rem;
                                border-radius: 6px;
                                font-weight: 500;
                            ">High Risk</span>`;
                        } else if (alert.severity === 'medium') {
                            badgeHtml = `<span class="badge bg-warning" style="
                                background: #ffb300;
                                color: #000000;
                                padding: 0.4rem 0.8rem;
                                border-radius: 6px;
                                font-weight: 500;
                            ">Medium Risk</span>`;
                        } else if (alert.warning) {
                            badgeHtml = `<span class="badge bg-danger" style="
                                background: ${theme.warning};
                                color: #ffffff;
                                padding: 0.4rem 0.8rem;
                                border-radius: 6px;
                                font-weight: 500;
                            ">${alert.warning}</span>`;
                        }

                        alertsHtml += `
                            <li class="list-group-item weather-alert-item" style="
                                padding: 1rem;
                                border-bottom: 1px solid ${theme.border};
                                color: ${theme.text};
                                font-size: 0.95rem;
                                transition: background 0.2s ease, transform 0.2s ease;
                                animation: fadeIn 0.5s ease-out;
                            ">
                                <strong>${port}</strong>: ${condition}
                                (Wind: ${wind} km/h, Temp: ${temp}°C, Precip: ${precip}%)
                                ${badgeHtml}
                            </li>`;
                    });
                    alertsHtml += '</ul>';
                } else {
                    alertsHtml += `<div class="weather-alert-item" style="
                        padding: 1rem;
                        color: ${theme.text};
                        font-size: 0.95rem;
                        animation: fadeIn 0.5s ease-out;
                    ">No critical weather alerts at this time.</div>`;
                }

                alertsHtml += `</div>
                    <small class="text-muted last-updated" style="
                        color: ${theme.muted};
                        font-size: 0.85rem;
                        margin-top: 1rem;
                        display: block;
                        text-align: right;
                    ">
                        Last updated: <span id="weather-last-updated">${data.timestamp || data.updated_at ? new Date(data.timestamp || data.updated_at).toLocaleString() : 'N/A'}</span>
                    </small>`;

                widget.innerHTML = alertsHtml;

                // Hover effect for alert items
                widget.querySelectorAll('.weather-alert-item').forEach(item => {
                    item.addEventListener('mouseenter', () => {
                        item.style.background = theme.secondaryHover;
                        item.style.transform = 'translateX(5px)';
                    });
                    item.addEventListener('mouseleave', () => {
                        item.style.background = 'none';
                        item.style.transform = 'none';
                    });
                });

                // Scrollbar style for WebKit
                const alertList = widget.querySelector('.weather-alerts-list');
                if (alertList) {
                    alertList.style.setProperty('--webkit-scrollbar-width', '8px');
                    alertList.style.setProperty('--webkit-scrollbar-thumb-background', theme.muted);
                    alertList.style.setProperty('--webkit-scrollbar-thumb-border-radius', '4px');
                }
            }
        } catch (error) {
            console.error(`Error updating widget content for ${widgetId}:`, error);
            widget.innerHTML = `<p style="color: ${theme.warning}; text-align: center;">Error rendering widget: ${error.message}.</p>`;
        }
    }

    // Reattach refresh button listeners
    function reattachRefreshListeners() {
        const refreshPerformance = document.getElementById('refresh-performance-metrics');
        if (refreshPerformance) {
            refreshPerformance.removeEventListener('click', refreshPerformanceHandler);
            refreshPerformance.addEventListener('click', refreshPerformanceHandler);
        }
        const refreshWeather = document.getElementById('refresh-weather-alerts');
        if (refreshWeather) {
            refreshWeather.removeEventListener('click', refreshWeatherHandler);
            refreshWeather.addEventListener('click', refreshWeatherHandler);
        }
    }

    function refreshPerformanceHandler() {
        const spinner = document.getElementById('performance-metrics-spinner');
        if (spinner) spinner.classList.remove('hidden');
        const widget = document.getElementById('performance_metrics');
        if (widget) {
            window.fetchWidgetData('/admin/widget-data/performance_metrics/', widget);
        } else {
            console.error('Performance metrics widget not found for refresh.');
        }
        setTimeout(() => {
            if (spinner) spinner.classList.add('hidden');
        }, 1000);
    }

    function refreshWeatherHandler() {
        const spinner = document.getElementById('weather-alerts-spinner');
        if (spinner) spinner.classList.remove('hidden');
        const widget = document.getElementById('weather_alerts');
        if (widget) {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ action: 'refresh_weather' }));
            } else {
                console.warn('WebSocket not connected. Fetching weather alerts via HTTP.');
                window.fetchWidgetData('/admin/widget-data/weather_alerts/', widget);
            }
        } else {
            console.error('Weather alerts widget not found for refresh.');
        }
        setTimeout(() => {
            if (spinner) spinner.classList.add('hidden');
        }, 1000);
    }

    // WebSocket handling with retry logic
    let ws = null;
    let wsRetryCount = 0;
    const maxRetries = 5;
    const baseRetryDelay = 5000;

    function initializeWebSocket() {
        if (wsRetryCount >= maxRetries) {
            console.error('Max WebSocket retries reached. Falling back to HTTP polling.');
            document.querySelectorAll('.jazzmin-widget').forEach(widget => {
                const url = widget.getAttribute('data-widget-url');
                if (url) window.fetchWidgetData(url, widget);
            });
            setInterval(() => {
                const widget = document.getElementById('weather_alerts');
                if (widget) window.fetchWidgetData('/admin/widget-data/weather_alerts/', widget);
            }, 60000);
            return;
        }

        const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
        const wsUrl = `${protocol}://${window.location.host}/ws/admin/dashboard/`;
        ws = new WebSocket(wsUrl);

        ws.onopen = () => {
            console.log('WebSocket connected to admin dashboard');
            wsRetryCount = 0;
            ws.send(JSON.stringify({ action: 'refresh_weather' }));
        };

        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                console.log('WebSocket message received:', data);

                if (data.type === 'weather_alerts') {
                    const weatherWidget = document.getElementById('weather_alerts');
                    if (weatherWidget) updateWidgetContent(weatherWidget, data);

                } else if (data.type === 'booking_updates') {
                    const dataElement = document.getElementById('recent-bookings-data');
                    if (dataElement && data.data && Array.isArray(data.data)) {
                        dataElement.textContent = JSON.stringify(data.data);
                        if (typeof window.jQuery.fn.DataTable !== 'undefined') {
                            const table = window.jQuery('#recent-bookings-table').DataTable();
                            table.clear();
                            data.data.forEach(booking => {
                                table.row.add([
                                    booking.id || 'N/A',
                                    booking.user_email || 'N/A',
                                    `<span title="${booking.route || 'N/A'}">${booking.route || 'N/A'}</span>`,
                                    booking.booking_date ? new Date(booking.booking_date).toLocaleString('en-GB', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: 'short', year: 'numeric' }) : 'N/A',
                                    `<span data-status="${booking.status || 'N/A'}">${booking.status || 'N/A'}</span>`
                                ]).draw();
                            });
                            console.log('Recent bookings table updated via WebSocket.');
                        }
                    }

                } else if (data.type === 'schedule_update') {
                    // Handle schedule updates
                    const row = document.querySelector(`#schedule-${data.schedule_id}`);
                    if (row) {
                        const seatsElem = row.querySelector('.available-seats');
                        const statusElem = row.querySelector('.status');
                        if (seatsElem) seatsElem.textContent = data.available_seats;
                        if (statusElem) statusElem.textContent = data.status;
                    }

                    // Optionally update dashboard charts
                    if (window.updateDashboard) {
                        window.updateDashboard('ferry_utilization', data);
                    }

                    console.log('Schedule updated via WebSocket:', data);

                } else {
                    console.warn('Unknown WebSocket message type:', data.type);
                }
            } catch (e) {
                console.error('Error parsing WebSocket message:', e);
            }
        };


        ws.onclose = (event) => {
            console.log(`WebSocket disconnected: Code ${event.code}, Reason: ${event.reason}`);
            wsRetryCount++;
            console.log(`Reconnecting in ${baseRetryDelay * (wsRetryCount + 1)}ms... (${wsRetryCount}/${maxRetries})`);
            setTimeout(initializeWebSocket, baseRetryDelay * (wsRetryCount + 1));
        };

        ws.onerror = (error) => {
            console.error('WebSocket error:', error);
        };
    }

    // Cache for chart data and state
    let cachedData = {};
    const chartDays = {
        bookingsChart: '30',
        utilizationChart: 'all',
        revenueChart: '30',
        paymentChart: '30',
        userGrowthChart: '30',
        topCustomersChart: '30'
    };

    // Map chartId to backend chart_type
    const chartTypeMap = {
        bookingsChart: 'bookings_per_route',
        utilizationChart: 'ferry_utilization',
        revenueChart: 'revenue_over_time',
        paymentChart: 'payment_status',
        userGrowthChart: 'user_growth',
        topCustomersChart: 'top_customers'
    };

    // Helper function to get filtered/averaged utilization data
    function getUtilizationData(selectedDay) {
        const utilizationData = cachedData.ferry_utilization || [];
        if (utilizationData.length === 0) return [];
        if (selectedDay === 'all') {
            const grouped = {};
            utilizationData.forEach(item => {
                const ferry = item.ferry || 'No Data';
                if (!grouped[ferry]) grouped[ferry] = { sum: 0, count: 0 };
                grouped[ferry].sum += item.utilization || 0;
                grouped[ferry].count += 1;
            });
            const result = Object.keys(grouped).map(ferry => ({
                ferry,
                utilization: grouped[ferry].count > 0 ? grouped[ferry].sum / grouped[ferry].count : 0
            }));
            console.log(`Processed Utilization Data (All Days):`, result);
            return result;
        } else {
            const filtered = utilizationData.filter(item => item.day_of_week === selectedDay);
            console.log(`Processed Utilization Data (${selectedDay}):`, filtered);
            return filtered;
        }
    }

    // Update single chart
    function updateChart(chartId, data, days) {
        if (chartId !== activeChartId) {
            console.log(`Skipping update for ${chartId} as it is not the active chart`);
            return;
        }
        console.log(`Updating chart ${chartId} with days: ${days}`);
        const chartDataKey = chartTypeMap[chartId];
        const chartData = data[chartDataKey] || [];
        const dateRangeText = days === '7' ? 'Last 7 Days' : days === 'all' ? 'All Time' : 'Last 30 Days';
        const isAllTime = days === 'all';
        const dataLength = chartData.length;
        const barPercentage = dataLength > 20 ? 0.1 : dataLength > 10 ? 0.2 : 0.3;
        const categoryPercentage = dataLength > 20 ? 0.5 : dataLength > 10 ? 0.6 : 0.7;

        if (chartId === 'bookingsChart') {
            const bookingsData = {
                labels: chartData.slice(0, 10).map(item => item.route || 'No Data'),
                datasets: [{
                    label: 'Bookings Count',
                    data: chartData.slice(0, 10).map(item => item.count || 0),
                    backgroundColor: chartData.slice(0, 10).map(item => theme.bookings[item.route_type || 'standard']),
                    borderColor: theme.bookings.border,
                    borderWidth: 2,
                    hoverBackgroundColor: chartData.slice(0, 10).map(item => theme.bookings[item.route_type || 'standard']),
                    hoverBorderColor: isDarkMode ? '#0288d1' : '#0277bd',
                    barPercentage,
                    categoryPercentage
                }]
            };
            const options = {
                scales: {
                    y: { type: 'linear', beginAtZero: true, ticks: { precision: 0 }, title: { display: true, text: 'Number of Bookings' }, padding: 20 },
                    x: { type: 'category', ticks: { maxRotation: 45, minRotation: 45, autoSkip: isAllTime, maxTicksLimit: 12 }, title: { display: true, text: 'Routes' }, padding: 20 }
                },
                plugins: { legend: { position: 'top' }, title: { display: true, text: `Top Routes by Bookings (${dateRangeText})` } },
                layout: { padding: { top: 20, bottom: 20, left: 20, right: 20 } }
            };
            initializeChart(wrappers.bookingsChart, 'bar', bookingsData, options, 'Bookings');
        }

        if (chartId === 'utilizationChart') {
            const utilizationData = {
                labels: getUtilizationData(document.querySelector('#utilization .utilization-filter')?.value || 'all').map(item => item.ferry || 'No Data'),
                datasets: [{
                    label: 'Utilization (%)',
                    data: getUtilizationData(document.querySelector('#utilization .utilization-filter')?.value || 'all').map(item => item.utilization || 0),
                    backgroundColor: getUtilizationData(document.querySelector('#utilization .utilization-filter')?.value || 'all').map((_, i) => theme.utilization[i % theme.utilization.length]),
                    borderWidth: 2,
                    barPercentage,
                    categoryPercentage
                }]
            };
            const options = {
                indexAxis: 'y',
                scales: {
                    x: { type: 'linear', beginAtZero: true, max: 100, ticks: { precision: 0 }, title: { display: true, text: 'Utilization (%)' }, padding: 20 },
                    y: { type: 'category', ticks: { autoSkip: isAllTime, maxTicksLimit: 12 }, title: { display: true, text: 'Ferries' }, padding: 20 }
                },
                plugins: { legend: { position: 'top' }, title: { display: true, text: `Ferry Utilization (${dateRangeText})` } },
                layout: { padding: { top: 20, bottom: 20, left: 20, right: 20 } }
            };
            initializeChart(wrappers.utilizationChart, 'bar', utilizationData, options, 'Utilization');
        }

        if (chartId === 'revenueChart') {
            const revenueDatasets = [{
                label: 'Revenue ($)',
                data: chartData.map(item => item.revenue || 0),
                fill: true,
                backgroundColor: theme.revenue.revenue.background,
                borderColor: theme.revenue.revenue.border,
                tension: 0.3,
                pointRadius: 4,
                pointHoverRadius: 6,
                pointBackgroundColor: theme.revenue.revenue.point,
                pointBorderColor: theme.revenue.revenue.border,
                pointHoverBackgroundColor: theme.revenue.revenue.border,
                yAxisID: 'y'
            }];
            const bookingsData = data.bookings_over_time || [];
            if (bookingsData.length > 0) {
                revenueDatasets.push({
                    label: 'Bookings Count',
                    data: bookingsData.map(item => item.count || 0),
                    fill: false,
                    borderColor: theme.revenue.bookings.border,
                    tension: 0.3,
                    pointRadius: 4,
                    pointHoverRadius: 6,
                    pointBackgroundColor: theme.revenue.bookings.point,
                    pointBorderColor: theme.revenue.bookings.border,
                    pointHoverBackgroundColor: theme.revenue.bookings.border,
                    yAxisID: 'y1'
                });
            }
            const revenueData = { labels: chartData.map(item => item.date || 'No Data'), datasets: revenueDatasets };
            const options = {
                scales: {
                    x: { type: 'category', ticks: { maxRotation: 45, minRotation: 45, autoSkip: isAllTime, maxTicksLimit: 12 }, title: { display: true, text: 'Date' }, padding: 20 },
                    y: { type: 'linear', beginAtZero: true, position: 'left', title: { display: true, text: 'Revenue ($)' }, ticks: { precision: 0 }, padding: 20 },
                    ...(bookingsData.length > 0 ? { y1: { type: 'linear', beginAtZero: true, position: 'right', title: { display: true, text: 'Bookings Count' }, grid: { drawOnChartArea: false }, ticks: { precision: 0 }, padding: 20 } } : {})
                },
                plugins: { legend: { position: 'top' }, title: { display: true, text: `Revenue and Bookings Over Time (${dateRangeText})` } },
                layout: { padding: { top: 20, bottom: 20, left: 20, right: 20 } }
            };
            initializeChart(wrappers.revenueChart, 'line', revenueData, options, 'Revenue');
        }

        if (chartId === 'paymentChart') {
            const paymentData = {
                labels: chartData.map(item => item.status || 'No Data'),
                datasets: [{ label: 'Payment Status Count', data: chartData.map(item => item.count || 0), backgroundColor: theme.payment, borderWidth: 2, hoverOffset: 20 }]
            };
            const options = {
                plugins: {
                    legend: { position: 'right' },
                    title: { display: true, text: `Payment Status (${dateRangeText})` },
                    onClick: (event, elements) => {
                        if (elements.length > 0) {
                            const index = elements[0].index;
                            const status = paymentData.labels[index].toLowerCase();
                            window.location.href = `/admin/bookings/booking/?payment_status=${encodeURIComponent(status)}`;
                        }
                    }
                },
                layout: { padding: { top: 20, bottom: 20, left: 20, right: 20 } }
            };
            initializeChart(wrappers.paymentChart, 'pie', paymentData, options, 'Payment');
        }

        if (chartId === 'userGrowthChart') {
            const userGrowthData = {
                labels: chartData.map(item => item.date || 'No Data'),
                datasets: [{
                    label: 'New Users',
                    data: chartData.map(item => item.count || 0),
                    fill: true,
                    backgroundColor: theme.userGrowth.background,
                    borderColor: theme.userGrowth.border,
                    tension: 0.3,
                    pointRadius: 4,
                    pointHoverRadius: 6,
                    pointBackgroundColor: theme.userGrowth.point,
                    pointBorderColor: theme.userGrowth.border,
                    pointHoverBackgroundColor: theme.userGrowth.border
                }]
            };
            const options = {
                scales: {
                    y: { type: 'linear', beginAtZero: true, ticks: { precision: 0 }, title: { display: true, text: 'New Users' }, padding: 20 },
                    x: { type: 'category', ticks: { maxRotation: 45, minRotation: 45, autoSkip: isAllTime, maxTicksLimit: 12 }, title: { display: true, text: 'Date' }, padding: 20 }
                },
                plugins: { legend: { position: 'top' }, title: { display: true, text: `User Growth (${dateRangeText})` } },
                layout: { padding: { top: 20, bottom: 20, left: 20, right: 20 } }
            };
            initializeChart(wrappers.userGrowthChart, 'line', userGrowthData, options, 'User Growth');
        }

        if (chartId === 'topCustomersChart') {
            const topCustomersData = {
                labels: chartData.map(item => item.user || 'No Data'),
                datasets: [{ label: 'Bookings', data: chartData.slice(0, 10).map(item => item.count || 0), backgroundColor: theme.topCustomers, borderWidth: 2, barPercentage, categoryPercentage }]
            };
            const options = {
                scales: {
                    y: { type: 'linear', beginAtZero: true, ticks: { precision: 0 }, title: { display: true, text: 'Number of Bookings' }, padding: 20 },
                    x: { type: 'category', ticks: { maxRotation: 45, minRotation: 45, autoSkip: isAllTime, maxTicksLimit: 12 }, title: { display: true, text: 'Customers' }, padding: 20 }
                },
                plugins: { legend: { position: 'top' }, title: { display: true, text: `Top Customers by Bookings (${dateRangeText})` } },
                layout: { padding: { top: 20, bottom: 20, left: 20, right: 20 } }
            };
            initializeChart(wrappers.topCustomersChart, 'bar', topCustomersData, options, 'Top Customers');
        }
    }

    // Fetch and update single chart
    const debouncedFetchAndUpdateChart = debounce((chartId, days, retries = 3, delay = 2000) => {
        if (chartId !== activeChartId) {
            console.log(`Skipping fetch for ${chartId} as it is not the active chart`);
            return;
        }

        // Ensure we have valid values
        if (!chartId || !chartTypeMap[chartId]) {
            console.error(`Invalid chart ID: ${chartId}`);
            return;
        }

        const chartType = chartTypeMap[chartId];
        const daysValue = days || chartDays[chartId] || '30';

        console.log(`Fetching chart data for ${chartId}: ${chartType}, days: ${daysValue}, retries: ${retries}`);
        const spinner = document.querySelector(`.refresh-chart[data-chart-id="${chartId}"] i`);
        if (spinner) spinner.classList.add('animate-spin');

        // Find the correct wrapper based on chart ID
        let wrapper;
        if (chartId === 'userGrowthChart') {
            wrapper = document.querySelector('#user-growth .chart-wrapper');
        } else if (chartId === 'topCustomersChart') {
            wrapper = document.querySelector('#customers .chart-wrapper');
        } else {
            wrapper = document.querySelector(`#${chartId.replace('Chart', '')} .chart-wrapper`);
        }

        if (!wrapper) {
            console.error(`Chart wrapper not found for ${chartId} during fetch.`);
            if (spinner) spinner.classList.remove('animate-spin');
            return;
        }
        wrappers[chartId] = wrapper; // Update wrapper in case DOM changed
        fetch(`/admin/analytics-data/?days=${daysValue}&chart_type=${chartType}`, {
            headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': getCookie('csrftoken') }
        })
        .then(response => {
            console.log(`Response status for ${chartId}: ${response.status}`);
            if (!response.ok) throw new Error(`HTTP error! Status: ${response.status}`);
            return response.json();
        })
        .then(data => {
            console.log(`Analytics Data Fetched for ${chartId}:`, data);
            cachedData[chartType] = data[chartType];
            if (chartType === 'revenue_over_time') cachedData['bookings_over_time'] = data['bookings_over_time'];
            updateChart(chartId, data, daysValue);
            if (spinner) spinner.classList.remove('animate-spin');
        })
        .catch(error => {
            console.error(`Error fetching analytics data for ${chartId}:`, error);
            if (retries > 0) {
                console.warn(`Retrying fetch for ${chartId} in ${delay}ms... (${retries} retries left)`);
                setTimeout(() => debouncedFetchAndUpdateChart(chartId, daysValue, retries - 1, delay * 1.5), delay);
            } else {
                if (spinner) spinner.classList.remove('animate-spin');
                wrapper.innerHTML = `<div style="text-align: center; color: ${theme.warning}; font-size: 1rem; padding: 2rem; height: 100%; display: flex; align-items: center; justify-content: center; background-color: ${theme.chartBg}; border-radius: 8px;">Error loading chart data: ${error.message}</div>`;
            }
        });
    }, 300);

    // Initialize charts
    function initializeCharts() {
        console.log('Initializing charts');
        const activeTab = document.querySelector('.tab-pane.show.active');
        activeChartId = activeTab ? `${activeTab.id}Chart` : 'bookingsChart';

        // Fix the chart ID mapping for special cases
        if (activeChartId === 'user-growthChart') {
            activeChartId = 'userGrowthChart';
        } else if (activeChartId === 'customersChart') {
            activeChartId = 'topCustomersChart';
        }

        console.log(`Active chart ID: ${activeChartId}`);

        // Clear all charts
        clearAllCharts();

        // Initialize active chart
        let wrapper;
        if (activeChartId === 'userGrowthChart') {
            wrapper = document.querySelector('#user-growth .chart-wrapper');
        } else if (activeChartId === 'topCustomersChart') {
            wrapper = document.querySelector('#customers .chart-wrapper');
        } else {
            wrapper = document.querySelector(`#${activeChartId.replace('Chart', '')} .chart-wrapper`);
        }

        if (!wrapper) {
            console.error(`Wrapper not found for ${activeChartId}`);
            return;
        }
        wrappers[activeChartId] = wrapper; // Update wrapper
        const tabPane = wrapper.closest('.tab-pane');
        const tabLink = document.querySelector(`.nav-link[data-bs-target="#${activeChartId.replace('Chart', '')}"]`);
        if (tabPane) {
            tabPane.classList.add('show', 'active');
            tabPane.style.display = 'block';
            tabPane.style.opacity = '1';
        }
        if (tabLink) {
            tabLink.classList.add('active');
        } else {
            console.warn(`Tab link not found for ${activeChartId}`);
        }
        debouncedFetchAndUpdateChart(activeChartId, chartDays[activeChartId]);
    }

    // Handle tab changes
    function initializeChartsOnTabShown() {
        document.querySelectorAll('.nav-tabs .nav-link').forEach(tab => {
            tab.addEventListener('shown.bs.tab', (e) => {
                const targetId = e.target.getAttribute('data-bs-target').replace('#', '');
                // Fix the chart ID mapping
                let chartId;
                if (targetId === 'user-growth') {
                    chartId = 'userGrowthChart';
                } else if (targetId === 'customers') {
                    chartId = 'topCustomersChart';
                } else {
                    chartId = `${targetId}Chart`;
                }

                console.log(`Tab ${targetId} shown, displaying chart ${chartId}`);

                // Clear all charts
                clearAllCharts();

                // Re-query wrapper to ensure DOM availability
                let wrapper;
                if (chartId === 'userGrowthChart') {
                    wrapper = document.querySelector('#user-growth .chart-wrapper');
                } else if (chartId === 'topCustomersChart') {
                    wrapper = document.querySelector('#customers .chart-wrapper');
                } else {
                    wrapper = document.querySelector(`#${targetId} .chart-wrapper`);
                }

                if (!wrapper) {
                    console.error(`Chart wrapper not found for ${chartId}`);
                    return;
                }
                wrappers[chartId] = wrapper; // Update wrapper
                const tabPane = wrapper.closest('.tab-pane');
                const tabLink = document.querySelector(`.nav-link[data-bs-target="#${targetId}"]`);
                if (tabPane) {
                    tabPane.classList.add('show', 'active');
                    tabPane.style.display = 'block';
                    tabPane.style.opacity = '1';
                }
                if (tabLink) {
                    tabLink.classList.add('active');
                } else {
                    console.warn(`Tab link not found for ${chartId}`);
                }
                activeChartId = chartId;
                debouncedFetchAndUpdateChart(chartId, chartDays[chartId]);
            });
        });
    }

    // Initialize DataTables
    function initializeDataTables(retries = 10, delay = 1500) {
        if (typeof window.jQuery.fn.DataTable === 'undefined') {
            if (retries > 0) {
                console.warn(`DataTables not loaded. Retrying in ${delay}ms... (${retries} retries left)`);
                setTimeout(() => initializeDataTables(retries - 1, delay * 1.5), delay);
                return;
            } else {
                console.error('DataTables failed to load.');
                const table = document.getElementById('recent-bookings-table');
                if (table) {
                    table.style.display = 'none';
                    const fallback = document.createElement('div');
                    fallback.textContent = 'Error loading bookings table.';
                    fallback.style.cssText = `color: ${theme.warning}; padding: 2rem; background-color: ${theme.background}; border-radius: 8px; text-align: center;`;
                    table.parentElement.appendChild(fallback);
                }
                return;
            }
        }
        const dataElement = document.getElementById('recent-bookings-data');
        if (!dataElement) {
            console.error('Recent bookings data element not found.');
            return;
        }
        try {
            const data = JSON.parse(dataElement.textContent);
            (function($) {
                $('#recent-bookings-table').DataTable({
                    paging: true,
                    searching: true,
                    ordering: true,
                    info: true,
                    autoWidth: false,
                    responsive: true,
                    language: { search: "Filter bookings:", emptyTable: "No recent bookings available." },
                    pageLength: 5,
                    lengthMenu: [5, 10],
                    data: data,
                    columns: [
                        { data: 'id', defaultContent: 'N/A' },
                        { data: 'user_email', defaultContent: 'N/A' },
                        { data: 'route', defaultContent: 'N/A', render: data => `<span title="${data}">${data}</span>` },
                        { data: 'booking_date', defaultContent: 'N/A', render: data => data ? new Date(data).toLocaleString('en-GB', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: 'short', year: 'numeric' }) : 'N/A' },
                        { data: 'status', defaultContent: 'N/A', render: data => `<span data-status="${data}">${data}</span>` }
                    ],
                    columnDefs: [
                        { width: '10%', targets: 0 },
                        { width: '25%', targets: 1 },
                        { width: '35%', targets: 2 },
                        { width: '20%', targets: 3 },
                        { width: '10%', targets: 4 }
                    ]
                });
                console.log('DataTables initialized successfully.');
            })(window.jQuery);
        } catch (error) {
            console.error('Error initializing DataTables:', error);
        }
    }

    // Lazy load widgets
    function lazyLoadWidgets() {
        const widgets = [
            { id: 'performance_metrics', url: '/admin/widget-data/performance_metrics/' },
            { id: 'weather_alerts', url: '/admin/widget-data/weather_alerts/' }
        ];
        widgets.forEach(widget => {
            const element = document.getElementById(widget.id);
            if (element) {
                console.log(`Loading widget: ${widget.id}`);
                window.fetchWidgetData(widget.url, element);
            } else {
                console.error(`Widget element not found: ${widget.id}.`);
            }
        });
    }

    // Initialize dashboard
    function initializeDashboard() {
        console.log('Initializing dashboard');
        lazyLoadWidgets();
        initializeDataTables();
        if (typeof bootstrap !== 'undefined') {
            initializeChartsOnTabShown();
            initializeCharts();
        } else {
            console.warn('Bootstrap not loaded. Retrying chart initialization.');
            setTimeout(initializeCharts, 2000);
        }
        initializeWebSocket();
    }

    // Date Range Filters
    document.querySelectorAll('.date-range-filter').forEach(select => {
        select.addEventListener('change', () => {
            const chartId = select.getAttribute('data-chart-id');
            const days = select.value;
            console.log(`Date Range Changed for ${chartId}: ${days}`);
            chartDays[chartId] = days;
            if (chartId === activeChartId) debouncedFetchAndUpdateChart(chartId, days);
        });
    });

    // Utilization Filter
    document.querySelectorAll('.utilization-filter').forEach(select => {
        select.addEventListener('change', () => {
            if (activeChartId === 'utilizationChart') {
                console.log(`Utilization filter changed to: ${select.value}`);
                debouncedFetchAndUpdateChart('utilizationChart', chartDays.utilizationChart);
            }
        });
    });

    // Chart Refresh Buttons
    document.querySelectorAll('.refresh-chart').forEach(button => {
        button.addEventListener('click', () => {
            const chartId = button.getAttribute('data-chart-id');
            const days = chartDays[chartId] || '30';
            console.log(`Refresh button clicked for ${chartId}, days: ${days}`);
            if (chartId === activeChartId) debouncedFetchAndUpdateChart(chartId, days);
        });
    });

    // Export to CSV
    const exportBookings = document.getElementById('export-bookings');
    if (exportBookings) {
        exportBookings.addEventListener('click', () => {
            const dataElement = document.getElementById('recent-bookings-data');
            if (!dataElement) {
                console.error('Recent bookings data element not found.');
                alert('Error: Booking data not available.');
                return;
            }
            try {
                const data = JSON.parse(dataElement.textContent);
                const exportData = Array.isArray(data) ? data : [data];
                const csv = Papa.unparse(exportData.map(item => ({
                    ID: item.id || 'N/A',
                    User: item.user_email || 'N/A',
                    Route: item.route || 'N/A',
                    Date: item.booking_date ? new Date(item.booking_date).toLocaleString('en-GB', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: 'short', year: 'numeric' }) : 'N/A',
                    Status: item.status || 'N/A'
                })));
                const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
                const url = URL.createObjectURL(blob);
                const link = document.createElement('a');
                link.href = url;
                link.setAttribute('download', 'recent_bookings.csv');
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
            } catch (error) {
                console.error('Error exporting bookings to CSV:', error.message);
                alert('Failed to export bookings.');
            }
        });
    }

    // Initialize Tooltips with Tippy.js
    if (typeof tippy !== 'undefined') {
        tippy('.btn-primary-custom, .btn-secondary, .refresh-chart, #scan-qr-code', {
            content: element => element.getAttribute('data-tippy-content') || 'Action',
            theme: isDarkMode ? 'dark' : 'light',
            placement: 'top',
            animation: 'fade',
            arrow: true,
            role: 'tooltip'
        });
    } else {
        console.warn('Tippy.js not loaded.');
    }

    // Update dashboard after form submission
    function updateDashboardAfterSave(model, objectId) {
        const updateMap = {
            'booking': ['recent_bookings', 'bookings_per_route', 'revenue_over_time', 'payment_status', 'top_customers'],
            'schedule': ['ferry_utilization'],
            'maintenancelog': ['fleet_status'],
            'weathercondition': ['weather_alerts'],
            'payment': ['payment_status'],
            'user': ['user_growth', 'top_customers'],
            'ticket': ['recent_bookings']
        };
        const sectionsToUpdate = updateMap[model.toLowerCase()] || [];
        console.log(`Updating dashboard for ${model} change, sections: ${sectionsToUpdate}`);

        sectionsToUpdate.forEach(section => {
            if (section === 'recent_bookings') {
                fetch('/admin/analytics-data/?chart_type=recent_bookings', {
                    headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': getCookie('csrftoken') }
                })
                .then(response => response.json())
                .then(data => {
                    const dataElement = document.getElementById('recent-bookings-data');
                    if (dataElement) dataElement.textContent = JSON.stringify(data.recent_bookings);
                    if (typeof window.jQuery.fn.DataTable !== 'undefined') {
                        const table = window.jQuery('#recent-bookings-table').DataTable();
                        table.clear();
                        data.recent_bookings.forEach(booking => {
                            table.row.add([
                                booking.id || 'N/A',
                                booking.user_email || 'N/A',
                                `<span title="${booking.route || 'N/A'}">${booking.route || 'N/A'}</span>`,
                                booking.booking_date ? new Date(booking.booking_date).toLocaleString('en-GB', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: 'short', year: 'numeric' }) : 'N/A',
                                `<span data-status="${booking.status || 'N/A'}">${booking.status || 'N/A'}</span>`
                            ]).draw();
                        });
                    }
                })
                .catch(error => console.error('Error updating recent bookings:', error));
            } else if (section === 'weather_alerts') {
                const widget = document.getElementById('weather_alerts');
                if (widget) window.fetchWidgetData('/admin/widget-data/weather_alerts/', widget);
            } else if (section === 'fleet_status') {
                fetch('/admin/analytics-data/?chart_type=fleet_status', {
                    headers: { 'X-Requested-With': 'XMLHttpRequest', 'X-CSRFToken': getCookie('csrftoken') }
                })
                .then(response => response.json())
                .then(data => console.log('Fleet status updated:', data.fleet_status))
                .catch(error => console.error('Error updating fleet status:', error));
            } else {
                const chartId = Object.keys(chartTypeMap).find(key => chartTypeMap[key] === section);
                if (chartId && chartId === activeChartId) debouncedFetchAndUpdateChart(chartId, chartDays[chartId] || '30');
            }
        });

        const perfWidget = document.getElementById('performance_metrics');
        if (perfWidget) window.fetchWidgetData('/admin/widget-data/performance_metrics/', perfWidget);
    }

    if (window.location.pathname.includes('/admin/bookings/') || window.location.pathname.includes('/admin/accounts/')) {
        const changeForm = document.getElementById('booking_form') ||
                          document.getElementById('schedule_form') ||
                          document.getElementById('maintenancelog_form') ||
                          document.getElementById('weathercondition_form') ||
                          document.getElementById('payment_form') ||
                          document.getElementById('user_form') ||
                          document.getElementById('ticket_form');
        if (changeForm) {
            changeForm.addEventListener('submit', function(e) {
                e.preventDefault();
                const formData = new FormData(changeForm);
                const model = changeForm.id.replace('_form', '');
                const objectId = window.location.pathname.split('/').slice(-2)[0];
                fetch(changeForm.action, {
                    method: 'POST',
                    body: formData,
                    headers: { 'X-CSRFToken': formData.get('csrfmiddlewaretoken') }
                })
                .then(response => {
                    if (response.ok) {
                        console.log(`${model} form submitted successfully`);
                        setTimeout(() => updateDashboardAfterSave(model, objectId), 500);
                    } else {
                        console.error('Form submission failed:', response.status);
                        alert('Form submission failed.');
                    }
                })
                .catch(error => {
                    console.error('Error submitting form:', error);
                    alert('Error submitting form.');
                });
            });
        }
    }

    // Initialize dashboard
    initializeDashboard();
});