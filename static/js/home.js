document.addEventListener('DOMContentLoaded', function () {
    const isDev = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
    const logger = {
        log: (...args) => isDev && console.log(...args),
        warn: (...args) => isDev && console.warn(...args),
        error: (...args) => console.error(...args)
    };
    // Ensure SITE_URL is defined in your Django template (e.g., http://localhost:8000 or production domain)
    const BASE_URL = SITE_URL || window.location.origin;

    // ---- Utility Functions ----
    function sanitizeHTML(str) {
        return DOMPurify.sanitize(str);
    }

    function formatDuration(seconds) {
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        return `${hours}h ${minutes}m`;
    }

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
                this.input.setAttribute('aria-label', 'Departure Date');
            }
        });
    } else {
        logger.warn('Flatpickr library not loaded');
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
            logger.log('AOS initialized');
        } catch (error) {
            logger.warn('AOS init failed:', error);
        }
    } else {
        logger.warn('AOS library not loaded');
    }

    // ---- Hero Slideshow ----
    const slides = document.querySelectorAll('.hero-slide');
    const dots = document.querySelectorAll('.hero-nav-dots .dot');
    let currentIndex = 0, slideInterval;

    function showSlide(index) {
        requestAnimationFrame(() => {
            slides.forEach((slide, i) => {
                slide.style.opacity = i === index ? '1' : '0';
                slide.setAttribute('aria-hidden', i !== index);
                if (dots[i]) {
                    dots[i].classList.toggle('active', i === index);
                    dots[i].setAttribute('aria-selected', i === index);
                }
            });
            currentIndex = index;
        });
    }

    function nextSlide() {
        showSlide((currentIndex + 1) % slides.length);
    }

    if (slides.length) {
        preloadImages(slides);
        function updateSlideImages() {
            requestAnimationFrame(() => {
                const isDarkMode = document.documentElement.classList.contains('dark');
                slides.forEach(slide => {
                    const url = isDarkMode ? slide.dataset.srcDark : slide.dataset.srcLight;
                    slide.style.backgroundImage = `url('${url}')`;
                });
            });
        }
        updateSlideImages();
        let debounceTimeout;
        const observer = new MutationObserver(() => {
            clearTimeout(debounceTimeout);
            debounceTimeout = setTimeout(updateSlideImages, 100);
        });
        observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
        dots.forEach((dot, i) => {
            dot.setAttribute('role', 'button');
            dot.setAttribute('aria-label', `Slide ${i + 1}`);
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
            requestAnimationFrame(() => {
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
            logger.error('Weather data is not an array:', weatherData);
            document.querySelectorAll('.schedule-card').forEach(card => {
                updateWeatherCard(card, null);
            });
            return;
        }

        requestAnimationFrame(() => {
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
            logger.warn('Missing weather elements in card');
            return;
        }
        requestAnimationFrame(() => {
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
                els.condition.textContent = weather.condition;
                els.condition.classList.toggle('warning', weather.wind_speed > 30);
                els.condition.setAttribute('role', weather.wind_speed > 30 ? 'alert' : 'status');
                els.icon.textContent = getWeatherIcon(weather.condition);
                els.temp.textContent = `${weather.temperature}°C`;
                els.wind.textContent = `${weather.wind_speed} kph`;
                els.precip.textContent = weather.precipitation_probability != null ? `${weather.precipitation_probability}%` : 'N/A';
                els.windContainer.classList.toggle('warning', weather.wind_speed > 30);
            }
            Object.values(els).forEach(el => {
                el.style.transition = 'opacity 0.5s ease';
                el.style.opacity = '1';
            });
        });
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

    function setupWeatherStream(retryCount = 3, delay = 5000) {
        const streamUrl = `${BASE_URL}/bookings/api/weather/stream/`;
        logger.log(`Attempting to connect to weather stream: ${streamUrl}`);
        const source = new EventSource(streamUrl);
        source.onmessage = event => {
            const data = JSON.parse(event.data);
            if (data.weather) updateWeatherDisplay(data.weather);
        };
        source.onerror = err => {
            logger.error('Weather stream error:', err);
            source.close();
            if (navigator.onLine && retryCount > 0) {
                logger.log(`Retrying weather stream (${retryCount} attempts left)...`);
                setTimeout(() => setupWeatherStream(retryCount - 1, delay * 2), delay);
            } else {
                logger.error('Max retries reached for weather stream or offline');
                document.querySelectorAll('.schedule-card').forEach(card => updateWeatherCard(card, null));
            }
        };
    }

    // ---- Schedule Polling ----
    function pollScheduleUpdates(retryCount = 3, delay = 5000) {
        const url = `${BASE_URL}/bookings/api/schedules/`;
        logger.log(`Polling schedules from: ${url}`);
        fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(r => {
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                return r.json();
            })
            .then(data => {
                requestAnimationFrame(() => {
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
                        const statusBadge = card.querySelector('.status-badge');
                        const fareEl = card.querySelector('.fare');
                        const seatCount = card.querySelector('.seat-count');
                        const departureTime = card.querySelector('.departure-time');
                        if (!statusBadge || !fareEl || !seatCount || !departureTime) return;
                        statusBadge.textContent = schedule.status.charAt(0).toUpperCase() + schedule.status.slice(1);
                        fareEl.textContent = schedule.status === 'scheduled' ? `FJD ${schedule.route.base_fare}` : 'Booking Unavailable';
                        seatCount.textContent = schedule.available_seats;
                        seatCount.classList.toggle('low', schedule.available_seats < 5);
                        departureTime.dataset.iso = schedule.departure_time;
                        departureTime.textContent = new Intl.DateTimeFormat('en-FJ', { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: 'numeric', timeZone: 'Pacific/Fiji' }).format(new Date(schedule.departure_time));
                    });
                });
            })
            .catch(e => {
                logger.error('Schedule polling error:', e);
                if (retryCount > 0 && navigator.onLine) {
                    logger.log(`Retrying schedule poll (${retryCount} attempts left)...`);
                    setTimeout(() => pollScheduleUpdates(retryCount - 1, delay * 2), delay);
                } else {
                    logger.error('Max retries reached for schedule polling or offline');
                    document.getElementById('next-departure-time').textContent = 'Unable to load departures. Please try again later.';
                }
            });
    }

    // ---- Testimonials ----
    const testimonials = document.querySelectorAll('.testimonial');
    if (testimonials.length) {
        let idx = 0;
        function showTestimonial(i) {
            requestAnimationFrame(() => {
                testimonials.forEach((t, j) => {
                    t.style.opacity = j === i ? '1' : '0';
                    t.style.display = j === i ? 'block' : 'none';
                    t.style.transition = 'opacity 0.5s ease';
                });
            });
        }
        setInterval(() => { idx = (idx + 1) % testimonials.length; showTestimonial(idx); }, 5000);
        showTestimonial(idx);
    }

    // ---- Map Functions ----
    function initializeMapAndRoutes(retryCount = 3, delay = 5000) {
        const mapEl = document.getElementById('fiji-map');
        if (!mapEl || typeof L === 'undefined') {
            logger.warn('Map element or Leaflet not found');
            if (mapEl) mapEl.innerHTML = '<p>Map failed to load. Please try again later.</p>';
            return;
        }
        try {
            const isMobile = window.matchMedia('(max-width: 768px)').matches;
            const map = L.map('fiji-map', {
                zoomControl: !isMobile,
                preferCanvas: true,
                maxBounds: [[-21.0, 176.0], [-16.0, 181.0]],
                maxBoundsViscosity: 1.0
            }).setView([-17.7, 178.0], 7);

            const html = document.documentElement;
            const tileLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
                maxZoom: 10,
                minZoom: 6,
                tileSize: 256,
                subdomains: 'abc',
                errorTileUrl: window.TILE_ERROR_URL
            }).addTo(map);

            const clusterGroup = typeof L.MarkerClusterGroup !== 'undefined'
                ? L.markerClusterGroup({
                    disableClusteringAtZoom: 8,
                    spiderfyOnMaxZoom: false,
                    showCoverageOnHover: false
                })
                : L.layerGroup();

            function getIconForTier(tier) {
                const color = tier === 'major' ? '#ff4500' : tier === 'regional' ? '#104e8b' : '#228b22';
                return L.divIcon({
                    html: `<div style="background-color: ${color}; width: 12px; height: 12px; border-radius: 50%; border: 2px solid #fff;"></div>`,
                    className: 'custom-marker',
                    iconSize: [12, 12],
                    iconAnchor: [6, 6],
                    popupAnchor: [0, -6]
                });
            }

            const url = `${BASE_URL}/bookings/api/routes/`;
            logger.log(`Fetching routes from: ${url}`);
            fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
                .then(response => {
                    if (!response.ok) throw new Error(`HTTP ${response.status}`);
                    return response.json();
                })
                .then(data => {
                    requestAnimationFrame(() => {
                        const routes = data.routes || [];
                        const markers = {};
                        const layers = {};

                        routes.forEach(route => {
                            if (!route.schedule_id) return;

                            const dep = route.departure_port;
                            const dest = route.destination_port;
                            const tier = route.service_tier || 'remote';

                            if (!layers[tier]) layers[tier] = L.layerGroup().addTo(map);

                            if (!markers[dep.name]) {
                                markers[dep.name] = L.marker([dep.lat, dep.lng], { icon: getIconForTier(tier) })
                                    .addTo(clusterGroup)
                                    .bindTooltip(`
                                        <b>${sanitizeHTML(dep.name)}</b><br>
                                        Route to ${sanitizeHTML(dest.name)}<br>
                                        Distance: ${sanitizeHTML(route.distance_km)} km<br>
                                        Duration: ${sanitizeHTML(formatDuration(route.estimated_duration))}<br>
                                        Fare: FJD ${sanitizeHTML(route.base_fare)}<br>
                                        <a href="/bookings/book/?schedule_id=${route.schedule_id}" aria-label="Book route from ${dep.name} to ${dest.name}">Book Now</a>
                                    `, { direction: 'top', offset: [0, -10] });
                            }
                            if (!markers[dest.name]) {
                                markers[dest.name] = L.marker([dest.lat, dest.lng], { icon: getIconForTier(tier) })
                                    .addTo(clusterGroup)
                                    .bindTooltip(`
                                        <b>${sanitizeHTML(dest.name)}</b><br>
                                        Route from ${sanitizeHTML(dep.name)}<br>
                                        Distance: ${sanitizeHTML(route.distance_km)} km<br>
                                        Duration: ${sanitizeHTML(formatDuration(route.estimated_duration))}<br>
                                        Fare: FJD ${sanitizeHTML(route.base_fare)}<br>
                                        <a href="/bookings/book/?schedule_id=${route.schedule_id}" aria-label="Book route from ${dep.name} to ${dest.name}">Book Now</a>
                                    `, { direction: 'top', offset: [0, -10] });
                            }
                        });

                        map.addLayer(clusterGroup);
                        const markerGroup = L.featureGroup(Object.values(markers));
                        map.fitBounds(markerGroup.getBounds().pad(0.2));

                        L.control.layers(null, layers, { collapsed: false }).addTo(map);
                    });
                })
                .catch(err => {
                    logger.error('Error fetching routes:', err);
                    if (retryCount > 0 && navigator.onLine) {
                        logger.log(`Retrying routes fetch (${retryCount} attempts left)...`);
                        setTimeout(() => initializeMapAndRoutes(retryCount - 1, delay * 2), delay);
                    } else {
                        logger.error('Max retries reached for routes fetch or offline');
                        mapEl.innerHTML = '<p style="color: red;">Unable to load map routes. Please check your connection or try again later.</p>';
                    }
                });

            const observer = new MutationObserver(() => {
                const dark = html.classList.contains('dark');
                tileLayer.setUrl('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png');
            });
            observer.observe(html, { attributes: true, attributeFilter: ['class'] });

            setTimeout(() => map.invalidateSize(), 100);
        } catch (err) {
            logger.error('Map initialization failed:', err);
            mapEl.innerHTML = '<p>Map failed to load. Please try again later.</p>';
        }
    }

    // ---- Check Cancellation Modal ----
    function checkCancellationModal() {
        const modal = document.querySelector('.cancellation-modal');
        if (!modal) {
            logger.warn('Cancellation modal not present on this page');
            return false;
        }
        return true;
    }

    // ---- Initialize Heavy Tasks ----
    setTimeout(() => {
        checkCancellationModal();
        initializeMapAndRoutes();
        setupWeatherStream();
        pollScheduleUpdates();
        setInterval(() => pollScheduleUpdates(), 30000);
    }, 500);
});