document.addEventListener('DOMContentLoaded', function () {
    // Get CSRF token from cookie
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
        return cookieValue;
    }

    const csrftoken = getCookie('csrftoken');
    console.log('CSRF token retrieved:', csrftoken ? 'Present' : 'Missing');

    fetch('/admin/analytics-data/', {
        headers: {
            'X-Requested-With': 'XMLHttpRequest',
            'X-CSRFToken': csrftoken
        }
    })
    .then(response => {
        if (!response.ok) {
            throw new Error('Network response was not ok: ' + response.statusText);
        }
        return response.json();
    })
    .then(data => {
        console.log('Analytics data fetched:', data);

        // Bookings per Route (Bar Chart)
        const bookingsCtx = document.getElementById('bookingsPerRouteChart');
        if (bookingsCtx) {
            if (data.bookings_per_route.length === 0) {
                document.querySelector('#bookingsPerRouteChart + .chart-empty').style.display = 'block';
            } else {
                new Chart(bookingsCtx.getContext('2d'), {
                    type: 'bar',
                    data: {
                        labels: data.bookings_per_route.map(item => item.route),
                        datasets: [{
                            label: 'Bookings',
                            data: data.bookings_per_route.map(item => item.count),
                            backgroundColor: 'rgba(75, 192, 192, 0.6)',
                            borderColor: 'rgba(75, 192, 192, 1)',
                            borderWidth: 1
                        }]
                    },
                    options: {
                        scales: {
                            y: { beginAtZero: true, title: { display: true, text: 'Number of Bookings' } },
                            x: { title: { display: true, text: 'Route' } }
                        },
                        plugins: { legend: { display: false } }
                    }
                });
            }
        } else {
            console.error('Bookings per Route canvas not found');
        }

        // Ferry Utilization (Pie Chart)
        const utilizationCtx = document.getElementById('ferryUtilizationChart');
        if (utilizationCtx) {
            if (data.ferry_utilization.length === 0) {
                document.querySelector('#ferryUtilizationChart + .chart-empty').style.display = 'block';
            } else {
                new Chart(utilizationCtx.getContext('2d'), {
                    type: 'pie',
                    data: {
                        labels: data.ferry_utilization.map(item => item.ferry),
                        datasets: [{
                            label: 'Utilization (%)',
                            data: data.ferry_utilization.map(item => item.utilization),
                            backgroundColor: [
                                'rgba(255, 99, 132, 0.6)',
                                'rgba(54, 162, 235, 0.6)',
                                'rgba(255, 206, 86, 0.6)',
                                'rgba(75, 192, 192, 0.6)',
                                'rgba(153, 102, 255, 0.6)'
                            ]
                        }]
                    },
                    options: {
                        plugins: { legend: { position: 'right' } }
                    }
                });
            }
        } else {
            console.error('Ferry Utilization canvas not found');
        }

        // Revenue Over Time (Line Chart)
        const revenueCtx = document.getElementById('revenueOverTimeChart');
        if (revenueCtx) {
            if (data.revenue_over_time.length === 0) {
                document.querySelector('#revenueOverTimeChart + .chart-empty').style.display = 'block';
            } else {
                new Chart(revenueCtx.getContext('2d'), {
                    type: 'line',
                    data: {
                        labels: data.revenue_over_time.map(item => item.date),
                        datasets: [{
                            label: 'Revenue ($)',
                            data: data.revenue_over_time.map(item => item.revenue),
                            fill: false,
                            borderColor: 'rgba(54, 162, 235, 1)',
                            tension: 0.1
                        }]
                    },
                    options: {
                        scales: {
                            y: { beginAtZero: true, title: { display: true, text: 'Revenue ($)' } },
                            x: { title: { display: true, text: 'Date' } }
                        }
                    }
                });
            }
        } else {
            console.error('Revenue Over Time canvas not found');
        }

        // Hide loading/error messages if charts load successfully
        document.querySelectorAll('.chart-error').forEach(el => el.style.display = 'none');
        document.querySelectorAll('.chart-loading').forEach(el => el.style.display = 'none');
    })
    .catch(error => {
        console.error('Error fetching analytics data:', error);
        document.querySelectorAll('.chart-container').forEach(container => {
            const errorDiv = container.querySelector('.chart-error');
            errorDiv.textContent = 'Error: Failed to load chart data. Check console for details.';
            errorDiv.style.display = 'block';
            container.querySelector('.chart-loading').style.display = 'none';
        });
    });
});