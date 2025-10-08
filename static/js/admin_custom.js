$(document).ready(function() {
    // Prevent duplicate initialization
    if (document.getElementById('chartScript') && window.chartInitialized) return;
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
            chartBg: '#ffffff'
        },
        dark: {
            bookings: { express: '#26a69a', standard: '#4fc3f7', border: '#1e40af' },
            utilization: ['#26a69a', '#4fc3f7', '#81d4fa', '#ffb300', '#b0bec5'],
            revenue: { revenue: { background: 'rgba(38, 166, 154, 0.4)', border: '#26a69a', point: '#e5e7eb' }, bookings: { background: 'rgba(79, 195, 247, 0.4)', border: '#4fc3f7', point: '#e5e7eb' } },
            payment: ['#26a69a', '#ffb300', '#f87171'],
            userGrowth: { background: 'rgba(171, 71, 188, 0.4)', border: '#ab47bc', point: '#e5e7eb' },
            topCustomers: ['#26a69a', '#4fc3f7', '#81d4fa', '#ffb300', '#b0bec5'],
            weather: ['#4fc3f7', '#26a69a', '#81d4fa', '#0288d1', '#b3e5fc'],
            tooltip: { background: '#374151', text: '#ffffff', body: '#e5e7eb', border: '#4b5563' },
            text: '#e5e7eb',
            background: '#1f2937',
            chartBg: '#374151'
        }
    };

    // Initialize theme based on system preference
    const isDarkMode = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const theme = isDarkMode ? colors.dark : colors.light;

    // Cache wrappers
    const wrappers = {
        bookingsChart: document.querySelector('#bookings .chart-wrapper'),
        utilizationChart: document.querySelector('#utilization .chart-wrapper'),
        revenueChart: document.querySelector('#revenue .chart-wrapper'),
        paymentChart: document.querySelector('#payment .chart-wrapper'),
        userGrowthChart: document.querySelector('#user-growth .chart-wrapper'),
        topCustomersChart: document.querySelector('#customers .chart-wrapper')
    };

    // Chart initialization function with dynamic canvas
    function initializeChart(wrapper, type, data, options, chartName) {
        if (!wrapper) {
            console.warn(`Wrapper not found for ${chartName}`);
            return null;
        }
        // Remove existing canvas
        let existingCanvas = wrapper.querySelector('canvas');
        while (existingCanvas) {
            existingCanvas.remove();
            existingCanvas = wrapper.querySelector('canvas');
        }
        if (!data.datasets || data.datasets.length === 0 || !data.labels || data.labels.length === 0) {
            console.warn(`Chart not initialized: ${chartName} - No valid data or labels`);
            const fallback = document.createElement('div');
            fallback.textContent = `No ${chartName} data available`;
            fallback.style.cssText = `
                text-align: center;
                color: ${theme.text};
                font-size: 1rem;
                padding: 2rem;
                height: 100%;
                display: flex;
                align-items: center;
                justify-content: center;
                background-color: ${theme.chartBg};
                border-radius: 8px;
            `;
            wrapper.appendChild(fallback);
            return null;
        }
        // Create and append new canvas dynamically
        const canvas = document.createElement('canvas');
        canvas.id = wrapper.getAttribute('data-chart-id') || chartName.toLowerCase().replace(/\s+/g, '-');
        canvas.style.width = '100%';
        canvas.style.height = '100%'; // Use full height of parent
        canvas.style.backgroundColor = theme.chartBg;
        wrapper.appendChild(canvas);
        const ctx = canvas.getContext('2d');
        if (!ctx) {
            console.warn(`Chart not initialized: ${chartName} - No canvas context`);
            return null;
        }
        const existingChart = Chart.getChart(canvas.id);
        if (existingChart) existingChart.destroy();
        let scales = {};
        if (options.scales) {
            if (options.scales.x) {
                scales.x = {
                    ...options.scales.x,
                    ticks: { ...options.scales.x.ticks || {}, color: theme.text, font: { size: 12 } },
                    title: { ...options.scales.x.title || {}, color: theme.text }
                };
            }
            if (options.scales.y) {
                scales.y = {
                    ...options.scales.y,
                    ticks: { ...options.scales.y.ticks || {}, color: theme.text, font: { size: 12 } },
                    title: { ...options.scales.y.title || {}, color: theme.text }
                };
            }
            if (options.scales.y1) {
                scales.y1 = {
                    ...options.scales.y1,
                    ticks: { ...options.scales.y1.ticks || {}, color: theme.text, font: { size: 12 } },
                    title: { ...options.scales.y1.title || {}, color: theme.text }
                };
            }
        }
        const updatedOptions = {
            ...options,
            scales,
            plugins: {
                ...options.plugins,
                tooltip: {
                    backgroundColor: theme.tooltip.background,
                    titleColor: theme.tooltip.text,
                    bodyColor: theme.tooltip.body,
                    borderColor: theme.tooltip.border,
                    borderWidth: 1,
                    caretSize: 6,
                    cornerRadius: 6,
                    padding: 10
                },
                legend: {
                    ...options.plugins?.legend,
                    labels: { ...options.plugins?.legend?.labels, color: theme.text, font: { size: 14 } }
                },
                title: {
                    ...options.plugins?.title,
                    color: theme.text,
                    font: { size: 16, weight: '600' }
                }
            },
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 500, easing: 'easeOutQuart' }
        };
        const chart = new Chart(ctx, {
            type,
            data,
            options: updatedOptions
        });
        console.log(`${chartName} chart initialized with data:`, data);
        return chart;
    }

    // Cache for chart data and state
    let cachedData = {};
    let currentUtilizationData = [];
    let utilizationChart = null;
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
        if (utilizationData.length === 0) {
            return [];
        }
        if (selectedDay === 'all') {
            const grouped = {};
            utilizationData.forEach(item => {
                const ferry = item.ferry || 'No Data';
                if (!grouped[ferry]) {
                    grouped[ferry] = { sum: 0, count: 0 };
                }
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
        const chartDataKey = chartTypeMap[chartId];
        const chartData = data[chartDataKey] || [];
        const dateRangeText = days === '7' ? 'Last 7 Days' : days === 'all' ? 'All Time' : 'Last 30 Days';

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
                    hoverBorderColor: isDarkMode ? '#0288d1' : '#0277bd'
                }]
            };
            const options = {
                scales: {
                    y: { type: 'linear', beginAtZero: true, ticks: { precision: 0 } },
                    x: { type: 'category', ticks: { maxRotation: 45, minRotation: 45 } }
                },
                plugins: {
                    legend: { position: 'top' },
                    title: { display: true, text: `Top Routes by Bookings (${dateRangeText})` }
                }
            };
            initializeChart(wrappers.bookingsChart, 'bar', bookingsData, options, 'Bookings');
        }

        if (chartId === 'utilizationChart') {
            currentUtilizationData = getUtilizationData(document.querySelector('#utilization .utilization-filter')?.value || 'all');
            const utilizationData = {
                labels: currentUtilizationData.length > 0 ? currentUtilizationData.map(item => item.ferry || 'No Data') : ['No Data'],
                datasets: [{
                    label: 'Utilization (%)',
                    data: currentUtilizationData.length > 0 ? currentUtilizationData.map(item => item.utilization || 0) : [0],
                    backgroundColor: currentUtilizationData.length > 0 ?
                        currentUtilizationData.map((_, i) => theme.utilization[i % theme.utilization.length]) :
                        [theme.utilization[0]],
                    borderWidth: 2
                }]
            };
            const options = {
                indexAxis: 'y',
                scales: {
                    x: { type: 'linear', beginAtZero: true, max: 100, ticks: { precision: 0 } },
                    y: { type: 'category' }
                },
                plugins: {
                    legend: { position: 'top' },
                    title: { display: true, text: `Ferry Utilization (${dateRangeText})` }
                }
            };
            utilizationChart = initializeChart(wrappers.utilizationChart, 'bar', utilizationData, options, 'Utilization');
        }

        if (chartId === 'revenueChart') {
            const revenueDatasets = [
                {
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
                }
            ];
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
            const revenueData = {
                labels: chartData.map(item => item.date || 'No Data'),
                datasets: revenueDatasets
            };
            const options = {
                scales: {
                    x: { type: 'category', ticks: { maxRotation: 45, minRotation: 45 } },
                    y: {
                        type: 'linear',
                        beginAtZero: true,
                        position: 'left',
                        title: { display: true, text: 'Revenue ($)' },
                        ticks: { precision: 0 }
                    }
                },
                plugins: {
                    legend: { position: 'top' },
                    title: { display: true, text: `Revenue and Bookings Over Time (${dateRangeText})` }
                }
            };
            if (bookingsData.length > 0) {
                options.scales.y1 = {
                    type: 'linear',
                    beginAtZero: true,
                    position: 'right',
                    title: { display: true, text: 'Bookings Count' },
                    grid: { drawOnChartArea: false },
                    ticks: { precision: 0 }
                };
            }
            initializeChart(wrappers.revenueChart, 'line', revenueData, options, 'Revenue');
        }

        if (chartId === 'paymentChart') {
            const paymentData = {
                labels: chartData.map(item => item.status || 'No Data'),
                datasets: [{
                    label: 'Payment Status Count',
                    data: chartData.map(item => item.count || 0),
                    backgroundColor: theme.payment,
                    borderWidth: 2,
                    hoverOffset: 20
                }]
            };
            const options = {
                plugins: {
                    legend: { position: 'right' },
                    title: { display: true, text: `Payment Status (${dateRangeText})` }
                },
                onClick: (event, elements) => {
                    if (elements.length > 0) {
                        const index = elements[0].index;
                        const status = paymentData.labels[index].toLowerCase();
                        window.location.href = `/admin/bookings/booking/?payment_status=${encodeURIComponent(status)}`;
                    }
                }
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
                    y: { type: 'linear', beginAtZero: true, ticks: { precision: 0 } },
                    x: { type: 'category', ticks: { maxRotation: 45, minRotation: 45 } }
                },
                plugins: {
                    legend: { position: 'top' },
                    title: { display: true, text: `User Growth (${dateRangeText})` }
                }
            };
            initializeChart(wrappers.userGrowthChart, 'line', userGrowthData, options, 'User Growth');
        }

        if (chartId === 'topCustomersChart') {
            const topCustomersData = {
                labels: chartData.map(item => item.user || 'No Data'),
                datasets: [{
                    label: 'Bookings',
                    data: chartData.map(item => item.count || 0),
                    backgroundColor: theme.topCustomers,
                    borderWidth: 2
                }]
            };
            const options = {
                scales: {
                    y: { type: 'linear', beginAtZero: true, ticks: { precision: 0 } },
                    x: { type: 'category', ticks: { maxRotation: 45, minRotation: 45 } }
                },
                plugins: {
                    legend: { position: 'top' },
                    title: { display: true, text: `Top Customers by Bookings (${dateRangeText})` }
                }
            };
            initializeChart(wrappers.topCustomersChart, 'bar', topCustomersData, options, 'Top Customers');
        }
    }

    // Fetch and update single chart
    function fetchAndUpdateChart(chartId, days) {
        const spinner = document.querySelector(`.refresh-chart[data-chart-id="${chartId}"] i`);
        if (spinner) spinner.classList.add('animate-spin');
        const chartType = chartTypeMap[chartId];
        fetch(`/admin/analytics-data/?days=${days}&chart_type=${chartType}`)
            .then(response => {
                if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
                return response.json();
            })
            .then(data => {
                console.log(`Analytics Data Fetched for ${chartId}:`, data);
                cachedData[chartType] = data[chartType];
                if (chartType === 'revenue_over_time') {
                    cachedData['bookings_over_time'] = data['bookings_over_time'];
                }
                updateChart(chartId, data, days);
                if (spinner) spinner.classList.remove('animate-spin');
            })
            .catch(error => {
                console.error(`Error fetching analytics data for ${chartId}:`, error);
                if (spinner) spinner.classList.remove('animate-spin');
                const wrapper = wrappers[chartId];
                if (wrapper) {
                    const fallback = document.createElement('div');
                    fallback.textContent = 'Error loading chart data';
                    fallback.style.cssText = `
                        text-align: center;
                        color: ${theme.text};
                        font-size: 1rem;
                        padding: 2rem;
                        height: 100%;
                        display: flex;
                        align-items: center;
                        justify-content: center;
                        background-color: ${theme.chartBg};
                        border-radius: 8px;
                    `;
                    wrapper.innerHTML = '';
                    wrapper.appendChild(fallback);
                }
            });
    }

    // Initialize all charts
    function initializeCharts() {
        Object.keys(wrappers).forEach(chartId => {
            fetchAndUpdateChart(chartId, chartDays[chartId]);
        });
    }

    // Initial chart fetch
    initializeCharts();

    // Date Range Filters
    document.querySelectorAll('.date-range-filter').forEach(select => {
        select.addEventListener('change', () => {
            const chartId = select.getAttribute('data-chart-id');
            const days = select.value;
            console.log(`Date Range Changed for ${chartId}: ${days}`);
            chartDays[chartId] = days;
            fetchAndUpdateChart(chartId, days);
        });
    });

    // Chart Refresh Buttons
    document.querySelectorAll('.refresh-chart').forEach(button => {
        button.addEventListener('click', () => {
            const chartId = button.getAttribute('data-chart-id');
            const days = chartDays[chartId] || '30';
            fetchAndUpdateChart(chartId, days);
        });
    });

    // Dismiss Alerts
    function bindDismissAlerts() {
        document.querySelectorAll('.dismiss-alert').forEach(button => {
            button.addEventListener('click', () => {
                const alertBanner = button.parentElement;
                alertBanner.classList.add('opacity-0', 'h-0', 'mb-0');
                setTimeout(() => alertBanner.remove(), 300);
                const alertCount = document.getElementById('alert-count');
                const currentCount = parseInt(alertCount.textContent) - 1;
                alertCount.textContent = currentCount;
                if (currentCount === 0) {
                    const alertsList = document.getElementById('alerts-list');
                    const currentTime = new Date().toLocaleString('en-GB', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: 'short', year: 'numeric' });
                    alertsList.innerHTML = `
                        <div class="alert-banner p-4 rounded-lg mb-3 bg-white dark:bg-[#374151] shadow-md flex items-center border-l-4 border-[#26a69a]" role="alert" aria-live="polite">
                            <span class="font-bold text-base text-[#26a69a] dark:text-[#26a69a]">All systems operational as of ${currentTime}.</span>
                            <span class="text-[#6b7280] dark:text-[#9ca3af] ml-4 font-medium text-sm" aria-label="No details available for operational status">No Details</span>
                        </div>
                    `;
                }
            });
        });
    }
    bindDismissAlerts();

    // Refresh Alerts
    const refreshAlerts = document.getElementById('refresh-alerts');
    if (refreshAlerts) {
        refreshAlerts.addEventListener('click', () => {
            const spinner = document.getElementById('alert-spinner');
            spinner.classList.remove('hidden');
            fetch('/admin/analytics-data/?chart_type=alerts')
                .then(response => {
                    if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
                    return response.json();
                })
                .then(data => {
                    const alertsList = document.getElementById('alerts-list');
                    alertsList.innerHTML = '';
                    data.alerts.forEach(alert => {
                        const div = document.createElement('div');
                        div.className = 'alert-banner p-4 rounded-lg mb-3 bg-white dark:bg-[#374151] shadow-md flex items-center border-l-4 border-[#f87171] transition transform hover:-translate-y-0.5';
                        div.setAttribute('role', 'alert');
                        div.setAttribute('aria-live', 'polite');
                        div.innerHTML = `
                            <span class="font-bold text-base text-[#b91c1c] dark:text-[#f87171] flex-1">${alert.message}</span>
                            ${alert.link ? `<a href="${alert.link}" class="text-[#1e40af] dark:text-[#60a5fa] hover:text-[#2563eb] dark:hover:text-[#93c5fd] ml-4 font-medium text-sm" aria-label="View details for alert: ${alert.message}">Details</a>` : '<span class="text-[#6b7280] dark:text-[#9ca3af] ml-4 font-medium text-sm" aria-label="No details available for alert: ${alert.message}">No Details</span>'}
                            <button class="dismiss-alert ml-4 text-[#b91c1c] dark:text-[#f87171] hover:text-[#991b1b] dark:hover:text-[#ef4444] focus:outline-none focus:ring-2 focus:ring-[#b91c1c] dark:focus:ring-[#f87171]" aria-label="Dismiss alert: ${alert.message}">
                                <i class="fas fa-times"></i>
                            </button>
                        `;
                        alertsList.appendChild(div);
                    });
                    document.getElementById('alert-count').textContent = data.alerts.length;
                    bindDismissAlerts();
                    spinner.classList.add('hidden');
                })
                .catch(error => {
                    console.error('Error refreshing alerts:', error);
                    spinner.classList.add('hidden');
                    const alertsList = document.getElementById('alerts-list');
                    if (alertsList) {
                        alertsList.innerHTML = '<div class="alert-banner p-4 rounded-lg mb-3 bg-white dark:bg-[#374151] shadow-md flex items-center border-l-4 border-[#b91c1c] dark:border-[#f87171]" role="alert" aria-live="polite"><span class="text-base text-[#b91c1c] dark:text-[#f87171]">Failed to load alerts. Please try again.</span></div>';
                    }
                });
        });
    }

    // Refresh Weather Conditions
    const refreshWeather = document.getElementById('refresh-weather');
    if (refreshWeather) {
        refreshWeather.classList.add('btn', 'btn-secondary');
        refreshWeather.addEventListener('click', () => {
            const spinner = document.getElementById('weather-spinner');
            spinner.classList.remove('hidden');
            fetch('/admin/analytics-data/?chart_type=weather_conditions')
                .then(response => {
                    if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
                    return response.json();
                })
                .then(data => {
                    const weatherList = document.querySelector('.weather-conditions .weather-list');
                    weatherList.innerHTML = '';
                    data.weather_conditions.forEach(weather => {
                        const div = document.createElement('div');
                        div.className = 'weather-item py-4 border-b border-gray-300 dark:border-[#4b5563] hover:bg-gray-50/80 dark:hover:bg-[rgba(38,166,154,0.2)] transition duration-300';
                        div.innerHTML = `
                            <span class="weather-date text-base">${new Date(weather.updated_at).toLocaleString('en-GB', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: 'short', year: 'numeric' })}</span>
                            <span class="weather-details text-base ml-4">${weather.port}: ${weather.condition}, ${weather.temperature}°C, Wind ${weather.wind_speed} km/h</span>
                        `;
                        weatherList.appendChild(div);
                    });
                    if (data.weather_conditions.length === 0) {
                        weatherList.innerHTML = '<div class="weather-item py-4 text-base text-[#6b7280] dark:text-[#9ca3af]">No weather data available.</div>';
                    }
                    spinner.classList.add('hidden');
                })
                .catch(error => {
                    console.error('Error refreshing weather:', error);
                    spinner.classList.add('hidden');
                    const weatherList = document.querySelector('.weather-conditions .weather-list');
                    if (weatherList) {
                        weatherList.innerHTML = '<div class="weather-item py-4 text-base text-[#b91c1c] dark:text-[#f87171]">Failed to load weather data. Please try again.</div>';
                    }
                });
        });
    }

    // DataTables for Recent Bookings
    if (typeof $.fn.DataTable !== 'undefined') {
        (function($) {
            const dataTable = $('#recent-bookings-table').DataTable({
                paging: true,
                searching: true,
                ordering: true,
                info: true,
                autoWidth: false,
                responsive: true,
                language: {
                    search: "Filter bookings:",
                    emptyTable: "No recent bookings available."
                },
                pageLength: 5,
                lengthMenu: [5, 10],
                columnDefs: [
                    { width: '10%', targets: 0 },
                    { width: '25%', targets: 1 },
                    { width: '35%', targets: 2, render: (data) => `<span title="${data}">${data}</span>` },
                    { width: '20%', targets: 3 },
                    { width: '10%', targets: 4 }
                ]
            });
            console.log('DataTables initialized successfully.');
        })(jQuery);
    } else {
        console.warn('DataTables library not loaded. Skipping table initialization.');
        const table = document.getElementById('recent-bookings-table');
        if (table) {
            table.style.display = 'none';
            const fallback = document.createElement('div');
            fallback.textContent = 'DataTables failed to load. Table functionality is unavailable.';
            fallback.style.cssText = `color: ${theme.text}; padding: 2rem; background-color: ${theme.background}; border-radius: 8px; text-align: center;`;
            table.parentElement.appendChild(fallback);
        }
    }

    // Export to CSV with error handling
    const exportBookings = document.getElementById('export-bookings');
    if (exportBookings) {
        exportBookings.addEventListener('click', () => {
            const dataElement = document.getElementById('recent-bookings-data');
            if (!dataElement) {
                console.error('Recent bookings data element not found.');
                alert('Error: Booking data not available for export.');
                return;
            }
            try {
                const data = JSON.parse(dataElement.textContent);
                const exportData = Array.isArray(data) ? data : [data];
                const csv = Papa.unparse(exportData.map(item => ({
                    ID: item.id || 'N/A',
                    User: item.user_email || 'N/A',
                    Schedule: item.schedule || 'N/A',
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
                alert('Failed to export bookings. The data may be invalid or missing. Check the console for details.');
            }
        });
    }

    // Initialize Tooltips with Tippy.js
    if (typeof tippy !== 'undefined') {
        tippy('.btn-primary-custom', {
            content: element => element.getAttribute('data-tippy-content'),
            theme: isDarkMode ? 'dark' : 'light',
            placement: 'top',
            animation: 'fade',
            arrow: true,
            role: 'tooltip'
        });
    } else {
        console.warn('Tippy.js library is not loaded. Skipping tooltip initialization.');
    }

    // Utilization Filter
    const utilizationFilter = document.querySelector('#utilization .utilization-filter');
    if (utilizationFilter) {
        utilizationFilter.addEventListener('change', function () {
            const selectedDay = this.value;
            console.log('Utilization Filter Changed:', selectedDay);
            currentUtilizationData = getUtilizationData(selectedDay);
            if (utilizationChart) {
                utilizationChart.data.labels = currentUtilizationData.length > 0 ? currentUtilizationData.map(item => item.ferry || 'No Data') : ['No Data'];
                utilizationChart.data.datasets[0].data = currentUtilizationData.length > 0 ? currentUtilizationData.map(item => item.utilization || 0) : [0];
                utilizationChart.data.datasets[0].backgroundColor = currentUtilizationData.length > 0 ?
                    currentUtilizationData.map((_, i) => theme.utilization[i % theme.utilization.length]) :
                    [theme.utilization[0]];
                const dateRangeText = chartDays.utilizationChart === '7' ? 'Last 7 Days' : chartDays.utilizationChart === 'all' ? 'All Time' : 'Last 30 Days';
                utilizationChart.options.plugins.title.text = selectedDay === 'all' ? `Ferry Utilization (${dateRangeText})` : `Ferry Utilization (${selectedDay}, ${dateRangeText})`;
                utilizationChart.update();
            } else {
                console.warn('Utilization chart not initialized.');
            }
        });
    }
});