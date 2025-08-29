document.addEventListener('DOMContentLoaded', function () {
    // ---- Preload Images for Slideshow ----
    function preloadImages(slides) {
        slides.forEach(slide => {
            const imgLight = new Image();
            imgLight.src = slide.dataset.srcLight;
            const imgDark = new Image();
            imgDark.src = slide.dataset.srcDark;
        });
    }

    // ---- Date Picker ----
    const formData = JSON.parse(document.getElementById('form-data')?.textContent || '{}');
    if (typeof flatpickr !== 'undefined') {
        flatpickr('#departure-date', {
            minDate: 'today',
            dateFormat: 'Y-m-d',
            defaultDate: formData.date || null,
            onReady: function () {
                this.input.classList.add('bg-var-input-bg', 'text-var-text-color');
            }
        });
    }

    // ---- AOS Animations ----
    if (typeof AOS !== 'undefined') {
        try {
            AOS.init({
                duration: 500,
                easing: 'ease-in-out',
                once: true,
                disable: 'mobile'
            });
        } catch (error) {
            console.warn('AOS init failed:', error);
        }
    }

    // ---- Hero Slideshow ----
    const slides = document.querySelectorAll('.hero-slide');
    const dots = document.querySelectorAll('.hero-nav-dots .dot');
    let currentIndex = 0, slideInterval;

    function showSlide(index) {
        slides.forEach((slide, i) => {
            slide.style.opacity = i === index ? '1' : '0';
            slide.setAttribute('aria-hidden', i !== index);
            if (dots[i]) {
                dots[i].classList.toggle('active', i === index);
                dots[i].setAttribute('aria-selected', i === index);
            }
        });
        currentIndex = index;
    }

    function nextSlide() {
        showSlide((currentIndex + 1) % slides.length);
    }

    if (slides.length) {
        preloadImages(slides);
        function updateSlideImages() {
            const isDarkMode = document.documentElement.classList.contains('dark');
            slides.forEach(slide => {
                const url = isDarkMode ? slide.dataset.srcDark : slide.dataset.srcLight;
                slide.style.backgroundImage = `url('${url}')`; // Trusted URLs only
            });
        }
        updateSlideImages();
        const observer = new MutationObserver(updateSlideImages);
        observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
        dots.forEach((dot, i) => {
            dot.setAttribute('role', 'button');
            dot.addEventListener('click', () => {
                clearInterval(slideInterval);
                showSlide(i);
                slideInterval = setInterval(nextSlide, 8000);
            });
        });
        slides.forEach(slide => {
            slide.addEventListener('mouseenter', () => clearInterval(slideInterval));
            slide.addEventListener('mouseleave', () => slideInterval = setInterval(nextSlide, 8000));
            slide.addEventListener('focusin', () => clearInterval(slideInterval));
            slide.addEventListener('focusout', () => slideInterval = setInterval(nextSlide, 8000));
        });
        showSlide(currentIndex);
        slideInterval = setInterval(nextSlide, 8000);
    }

    // ---- Schedule Sorting ----
    const sortSelect = document.getElementById('sort-by');
    if (sortSelect) {
        sortSelect.addEventListener('change', function () {
            const sortBy = this.value;
            const scheduleList = document.querySelector('.schedule-list');
            const cards = Array.from(scheduleList?.querySelectorAll('.schedule-card') || []);
            if (!cards.length) return;
            cards.sort((a, b) => {
                if (sortBy === 'price') {
                    return parseFloat(a.querySelector('.fare')?.textContent.replace('FJD ', '') || Infinity) -
                           parseFloat(b.querySelector('.fare')?.textContent.replace('FJD ', '') || Infinity);
                } else if (sortBy === 'duration') {
                    return parseDuration(a.querySelector('.duration')?.textContent) -
                           parseDuration(b.querySelector('.duration')?.textContent);
                } else {
                    return new Date(a.querySelector('.departure-time')?.dataset.iso || 0) -
                           new Date(b.querySelector('.departure-time')?.dataset.iso || 0);
                }
            });
            scheduleList.innerHTML = '';
            cards.forEach(card => scheduleList.appendChild(card));
        });
    }

    function parseDuration(text) {
        if (!text) return Infinity;
        const match = text.match(/(\d+)h\s*(\d+)?m?/);
        return match ? parseInt(match[1]) * 60 + (parseInt(match[2]) || 0) : Infinity;
    }

    // ---- Weather ----
    const conditionMap = {
        sunny: '☀️', clear: '☀️',
        cloud: '☁️', overcast: '☁️', 'partly cloudy': '☁️',
        rain: '🌧️', shower: '🌧️',
        thunder: '⛈️', thunderstorm: '⛈️',
        drizzle: '🌦️',
        mist: '🌫️', fog: '🌫️', haze: '🌫️',
        snow: '❄️',
        default: '🌤️'
    };

    function getWeatherIcon(desc) {
        if (!desc) return conditionMap.default;
        const key = Object.keys(conditionMap).find(k => desc.toLowerCase().includes(k));
        return conditionMap[key] || conditionMap.default;
    }

    let latestUpdateTime = null;
    const lastWeatherData = new Map();

    function updateWeatherDisplay(weatherData) {
        if (!Array.isArray(weatherData)) {
            console.error('Weather data is not an array:', weatherData);
            document.querySelectorAll('.schedule-card').forEach(card => {
                updateWeatherCard(card, null);
            });
            return;
        }

        weatherData.forEach(weather => {
            if (weather.route_id && weather.condition && !weather.is_expired && !weather.error) {
                lastWeatherData.set(weather.route_id, {
                    condition: weather.condition,
                    temperature: weather.temperature,
                    wind_speed: weather.wind_speed,
                    precipitation_probability: weather.precipitation_probability,
                    updated_at: weather.updated_at,
                    expires_at: weather.expires_at
                });
            }
            if (weather.updated_at) {
                const weatherTime = new Date(weather.updated_at);
                if (!latestUpdateTime || weatherTime > latestUpdateTime) {
                    latestUpdateTime = weatherTime;
                }
            }
        });

        lastWeatherData.forEach((weather, routeId) => {
            document.querySelectorAll(`.schedule-card[data-route-id="${routeId}"]`).forEach(card => {
                updateWeatherCard(card, weather);
            });
        });
    }

    function updateWeatherCard(card, weather) {
        const els = {
            condition: card.querySelector('.weather-condition'),
            icon: card.querySelector('.weather-icon'),
            temp: card.querySelector('.weather-temp .temp-value'),
            wind: card.querySelector('.weather-wind .wind-value'),
            precip: card.querySelector('.weather-precip .precip-value'),
            windContainer: card.querySelector('.weather-wind')
        };
        if (!Object.values(els).every(el => el)) {
            console.warn('Missing weather elements in card');
            return;
        }
        if (!weather || !weather.condition || (weather.expires_at && new Date(weather.expires_at) < new Date())) {
            els.condition.textContent = 'Weather data unavailable';
            els.condition.classList.remove('warning');
            els.condition.setAttribute('role', 'status');
            els.icon.textContent = conditionMap.default;
            els.temp.textContent = 'N/A';
            els.wind.textContent = 'N/A';
            els.precip.textContent = 'N/A';
            els.windContainer.classList.remove('warning');
        } else {
            const mappedCondition = getWeatherIcon(weather.condition);
            els.condition.textContent = weather.condition;
            els.condition.classList.toggle('warning', weather.wind_speed > 30);
            els.condition.setAttribute('role', weather.wind_speed > 30 ? 'alert' : 'status');
            els.icon.textContent = mappedCondition;
            els.temp.textContent = `${weather.temperature}°C`;
            els.wind.textContent = `${weather.wind_speed} kph`;
            els.precip.textContent = weather.precipitation_probability != null ? `${weather.precipitation_probability}%` : 'N/A';
            els.windContainer.classList.toggle('warning', weather.wind_speed > 30);
            Object.values(els).forEach(el => {
                el.style.opacity = '0';
                requestAnimationFrame(() => {
                    el.style.transition = 'opacity 0.5s ease';
                    el.style.opacity = '1';
                });
            });
        }
    }

    const initialWeatherData = JSON.parse(document.getElementById('weather-data')?.textContent || '[]');
    if (Array.isArray(initialWeatherData) && initialWeatherData.length) {
        initialWeatherData.forEach(weather => {
            weather.is_expired = !weather.condition || (weather.expires_at && new Date(weather.expires_at) < new Date());
        });
        updateWeatherDisplay(initialWeatherData);
    } else {
        document.querySelectorAll('.schedule-card').forEach(card => {
            updateWeatherCard(card, null);
        });
    }

    function fetchWeatherUpdates() {
        const url = latestUpdateTime && !isNaN(latestUpdateTime)
            ? `/api/weather/?since=${latestUpdateTime.toISOString()}`
            : '/api/weather/';
        fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(response => {
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                return response.json();
            })
            .then(data => {
                if (data.error) {
                    updateWeatherDisplay([]);
                } else if (Array.isArray(data.weather) && data.weather.length) {
                    updateWeatherDisplay(data.weather);
                } else {
                    updateWeatherDisplay([]);
                }
            })
            .catch(error => {
                console.error('Weather polling error:', error);
                updateWeatherDisplay([]);
            });
    }

    setTimeout(() => {
        fetchWeatherUpdates();
        setInterval(fetchWeatherUpdates, 60000); // Increased to 60s
    }, 3000);

    // ---- Schedule Polling ----
    function pollScheduleUpdates() {
        fetch('/api/schedules/', { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(r => {
                if (!r.ok) throw new Error(r.statusText);
                return r.json();
            })
            .then(data => {
                const nextDepartureElement = document.getElementById('next-departure-time');
                const now = new Date();
                const schedules = data.schedules
                    .filter(s => s.status === 'scheduled' && new Date(s.departure_time) > now)
                    .sort((a, b) => new Date(a.departure_time) - new Date(b.departure_time));

                if (schedules.length) {
                    const nextDeparture = schedules[0];
                    nextDepartureElement.textContent =
                        `${new Intl.DateTimeFormat('en-FJ', { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: 'numeric', timeZone: 'Pacific/Fiji' }).format(new Date(nextDeparture.departure_time))} - ` +
                        `${nextDeparture.route.departure_port} to ${nextDeparture.route.destination_port}`;
                    nextDepartureElement.dataset.iso = nextDeparture.departure_time;
                    nextDepartureElement.dataset.scheduleId = nextDeparture.id;
                    document.querySelectorAll('.schedule-card').forEach(card =>
                        card.classList.toggle('next-departure', card.dataset.scheduleId == nextDeparture.id));
                } else {
                    nextDepartureElement.textContent = 'No upcoming departures';
                    nextDepartureElement.dataset.iso = '';
                    nextDepartureElement.dataset.scheduleId = '';
                    document.querySelectorAll('.schedule-card').forEach(card => card.classList.remove('next-departure'));
                }

                data.schedules.forEach(schedule => {
                    const card = document.querySelector(`.schedule-card[data-schedule-id="${schedule.id}"]`);
                    if (!card) return;
                    card.querySelector('.status-badge').textContent = schedule.status.charAt(0).toUpperCase() + schedule.status.slice(1);
                    const fareEl = card.querySelector('.fare');
                    fareEl.textContent = schedule.status === 'scheduled' ? `FJD ${schedule.route.base_fare}` : 'Booking Unavailable';
                    const seatCount = card.querySelector('.seat-count');
                    seatCount.textContent = schedule.available_seats;
                    seatCount.classList.toggle('low', schedule.available_seats < 5);
                    const departureTime = card.querySelector('.departure-time');
                    departureTime.dataset.iso = schedule.departure_time;
                    departureTime.textContent = new Intl.DateTimeFormat('en-FJ', { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: 'numeric', timeZone: 'Pacific/Fiji' }).format(new Date(schedule.departure_time));
                });
            })
            .catch(e => {
                console.error('Schedule polling error:', e);
                document.getElementById('next-departure-time').textContent = 'Error loading departures';
            });
    }
    setTimeout(() => {
        pollScheduleUpdates();
        setInterval(pollScheduleUpdates, 30000);
    }, 2000);

    // ---- Testimonials ----
    const testimonials = document.querySelectorAll('.testimonial');
    if (testimonials.length) {
        let idx = 0;
        function showTestimonial(i) {
            testimonials.forEach((t, j) => {
                t.style.opacity = j === i ? '1' : '0';
                t.style.display = j === i ? 'block' : 'none';
                t.style.transition = 'opacity 0.5s ease';
            });
        }
        setInterval(() => { idx = (idx + 1) % testimonials.length; showTestimonial(idx); }, 5000);
        showTestimonial(idx);
    }

    // ---- Map Functions ----
    const mapEl = document.getElementById('fiji-map');

    if (mapEl && typeof L !== 'undefined') {
        try {
            const isMobile = window.matchMedia('(max-width: 768px)').matches;

            const map = L.map('fiji-map', {
                zoomControl: !isMobile,
                preferCanvas: true,
                maxBounds: [[-21.0, 176.0], [-16.0, 181.0]],
                maxBoundsViscosity: 1.0
            }).setView([-17.7, 178.0], 7);

            // Determine map tiles based on theme
            const html = document.documentElement;
            const isDark = html.classList.contains('dark-mode');
            const lightTiles = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';
            const darkTiles =  'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';


            const tileLayer = L.tileLayer(isDark ? darkTiles : lightTiles, {
                attribution: '&copy; OpenStreetMap &copy; CARTO',
                maxZoom: 10,
                minZoom: 6,
                tileSize: 256,
                subdomains: 'abcd',
                errorTileUrl: window.TILE_ERROR_URL || '/static/images/tile-error.png'
            }).addTo(map);

            const clusterGroup = typeof L.MarkerClusterGroup !== 'undefined'
                ? L.markerClusterGroup({
                    disableClusteringAtZoom: 8,
                    spiderfyOnMaxZoom: false,
                    showCoverageOnHover: false
                })
                : L.layerGroup();

            // Helper functions (curved line & gradient)
            function getCurvedLineCoords(start, end, curvature = 0.2) {
                const latOffset = (end[0] - start[0]) * curvature;
                const lngOffset = (end[1] - start[1]) * curvature;
                const midLat = (start[0] + end[0]) / 2 + latOffset;
                const midLng = (start[1] + end[1]) / 2 + lngOffset;
                return [start, [midLat, midLng], end];
            }

            function getGradientColors(startColor, endColor, steps) {
                const start = parseInt(startColor.slice(1), 16);
                const end = parseInt(endColor.slice(1), 16);
                const startR = (start >> 16) & 0xff, startG = (start >> 8) & 0xff, startB = start & 0xff;
                const endR = (end >> 16) & 0xff, endG = (end >> 8) & 0xff, endB = end & 0xff;
                const colors = [];
                for (let i = 0; i <= steps; i++) {
                    const t = i / steps;
                    const r = Math.round(startR + t * (endR - startR));
                    const g = Math.round(startG + t * (endG - startG));
                    const b = Math.round(startB + t * (endB - startB));
                    colors.push(`#${((1 << 24) + (r << 16) + (g << 8) + b).toString(16).slice(1)}`);
                }
                return colors;
            }

            function colorForTier(tier) {
                switch (tier) {
                    case 'major': return ['#ff7f50', '#ff4500'];
                    case 'regional': return ['#1e90ff', '#104e8b'];
                    default: return ['#32cd32', '#228b22'];
                }
            }

            // Fetch and draw routes
            fetch('/bookings/api/routes/', { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
                .then(response => response.ok ? response.json() : Promise.reject(`HTTP ${response.status}`))
                .then(data => {
                    const routes = data.routes || [];
                    const markers = {};
                    const layers = {};

                    routes.forEach(route => {
                        if (!route.schedule_id) return; // only scheduled routes

                        const dep = route.departure_port;
                        const dest = route.destination_port;
                        const tier = route.service_tier || 'local';

                        if (!layers[tier]) layers[tier] = L.layerGroup().addTo(map);

                        // Markers
                        if (!markers[dep.name]) markers[dep.name] = L.marker([dep.lat, dep.lng])
                            .addTo(clusterGroup)
                            .bindPopup(`<b>${sanitizeHTML(dep.name)}</b>`);
                        if (!markers[dest.name]) markers[dest.name] = L.marker([dest.lat, dest.lng])
                            .addTo(clusterGroup)
                            .bindPopup(`<b>${sanitizeHTML(dest.name)}</b>`);

                        const routeCoords = route.waypoints.length ? route.waypoints : getCurvedLineCoords([dep.lat, dep.lng], [dest.lat, dest.lng]);
                        const gradientColors = getGradientColors(colorForTier(tier)[0], colorForTier(tier)[1], routeCoords.length - 1);

                        for (let i = 0; i < routeCoords.length - 1; i++) {
                            L.polyline([routeCoords[i], routeCoords[i + 1]], {
                                color: gradientColors[i],
                                weight: 2,
                                opacity: 0.8
                            }).addTo(layers[tier]);
                        }

                        const midIndex = Math.floor(routeCoords.length / 2);
                        const popupContent = `
                            <b>${sanitizeHTML(dep.name)} → ${sanitizeHTML(dest.name)}</b><br>
                            Distance: ${sanitizeHTML(route.distance_km)} km<br>
                            Duration: ${sanitizeHTML(formatDuration(route.estimated_duration))}<br>
                            Fare: FJD ${sanitizeHTML(route.base_fare)}<br>
                            <a href="{% url 'bookings:book_ticket' %}?schedule_id={{ route.schedule_id }}">Book Now</a>
                        `;
                        L.polyline(routeCoords).on('click', () => {
                            L.popup().setLatLng(routeCoords[midIndex]).setContent(popupContent).openOn(map);
                        });
                    });

                    map.addLayer(clusterGroup);
                    const markerGroup = L.featureGroup(Object.values(markers));
                    map.fitBounds(markerGroup.getBounds().pad(0.2));

                    L.control.layers(null, layers, { collapsed: false }).addTo(map);
                })
                .catch(err => {
                    console.error('Error fetching routes:', err);
                    mapEl.innerHTML = '<p>Failed to load map routes.</p>';
                });

            // Listen for theme changes to update map tiles dynamically
            const observer = new MutationObserver(() => {
                const dark = html.classList.contains('dark-mode');
                const newUrl = dark ? darkTiles : lightTiles;
                tileLayer.setUrl(newUrl);
            });
            observer.observe(html, { attributes: true, attributeFilter: ['class'] });

            setTimeout(() => map.invalidateSize(), 100);

        } catch (err) {
            console.error('Map initialization failed:', err);
            mapEl.innerHTML = '<p>Map failed to load. Please try again later.</p>';
        }
    } else {
        console.warn('Map element or Leaflet not found');
        if (mapEl) mapEl.innerHTML = '<p>Map failed to load. Please try again later.</p>';
    }



    // ---- Utility Functions ----
    function sanitizeHTML(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    function formatDuration(seconds) {
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        return `${hours}h ${minutes}m`;
    }
});