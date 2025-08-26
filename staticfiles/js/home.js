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
                slide.style.backgroundImage = `url('${isDarkMode ? slide.dataset.srcDark : slide.dataset.srcLight}')`;
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
    const weatherIcons = {
        'Clear': '☀️',
        'Sunny': '☀️',
        'Clouds': '☁️',
        'Rain': '🌧️',
        'Thunderstorm': '⛈️',
        'Drizzle': '🌦️',
        'Mist': '🌫️',
        'Fog': '🌫️',
        'Snow': '❄️',
        'Haze': '🌫️',
        'default': '🌤️'
    };

    function mapWeatherCondition(condition) {
        if (!condition) return 'default';
        const cond = condition.toLowerCase();
        if (cond.includes('sunny') || cond.includes('clear')) return 'Sunny';
        if (cond.includes('cloud') || cond.includes('overcast') || cond.includes('partly cloudy')) return 'Clouds';
        if (cond.includes('rain') || cond.includes('shower')) return 'Rain';
        if (cond.includes('thunder')) return 'Thunderstorm';
        if (cond.includes('drizzle')) return 'Drizzle';
        if (cond.includes('mist') || cond.includes('fog')) return 'Mist';
        if (cond.includes('snow')) return 'Snow';
        if (cond.includes('haze')) return 'Haze';
        return 'default';
    }

    let latestUpdateTime = null;
    const lastWeatherData = new Map();

    function updateWeatherDisplay(weatherData) {
        console.debug('Updating weather display:', weatherData);
        if (!Array.isArray(weatherData)) {
            console.error('Weather data is not an array:', weatherData);
            document.querySelectorAll('.schedule-card').forEach(card => {
                const conditionElement = card.querySelector('.weather-condition');
                const iconElement = card.querySelector('.weather-icon');
                const tempElement = card.querySelector('.weather-temp .temp-value');
                const windElement = card.querySelector('.weather-wind .wind-value');
                const precipElement = card.querySelector('.weather-precip .precip-value');
                if (conditionElement && iconElement && tempElement && windElement && precipElement) {
                    conditionElement.textContent = 'Weather data unavailable';
                    conditionElement.classList.remove('warning');
                    iconElement.textContent = weatherIcons.default;
                    tempElement.textContent = 'N/A';
                    windElement.textContent = 'N/A';
                    precipElement.textContent = 'N/A';
                }
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
            const cards = document.querySelectorAll(`.schedule-card[data-route-id="${routeId}"]`);
            if (!cards.length) {
                console.warn(`No schedule cards found for route_id: ${routeId}`);
                return;
            }
            cards.forEach(card => {
                const conditionElement = card.querySelector('.weather-condition');
                const iconElement = card.querySelector('.weather-icon');
                const tempElement = card.querySelector('.weather-temp .temp-value');
                const windElement = card.querySelector('.weather-wind .wind-value');
                const precipElement = card.querySelector('.weather-precip .precip-value');
                if (!conditionElement || !iconElement || !tempElement || !windElement || !precipElement) {
                    console.warn(`Missing weather elements in card for route_id: ${routeId}`);
                    return;
                }
                const isExpired = !weather.condition ||
                                  (weather.expires_at && new Date(weather.expires_at) < new Date());
                if (isExpired) {
                    conditionElement.textContent = 'Weather data unavailable';
                    conditionElement.classList.remove('warning');
                    iconElement.textContent = weatherIcons.default;
                    tempElement.textContent = 'N/A';
                    windElement.textContent = 'N/A';
                    precipElement.textContent = 'N/A';
                    card.querySelector('.weather-wind').classList.remove('warning');
                } else {
                    const mappedCondition = mapWeatherCondition(weather.condition);
                    conditionElement.textContent = weather.condition;
                    conditionElement.classList.toggle('warning', weather.wind_speed > 30);
                    iconElement.textContent = weatherIcons[mappedCondition] || weatherIcons.default;
                    tempElement.textContent = `${weather.temperature}°C`;
                    windElement.textContent = `${weather.wind_speed} kph`;
                    precipElement.textContent = weather.precipitation_probability != null ? `${weather.precipitation_probability}%` : 'N/A';
                    card.querySelector('.weather-wind').classList.toggle('warning', weather.wind_speed > 30);
                    [conditionElement, iconElement, tempElement, windElement, precipElement].forEach(el => {
                        el.style.opacity = '0';
                        requestAnimationFrame(() => {
                            el.style.transition = 'opacity 0.5s ease';
                            el.style.opacity = '1';
                        });
                    });
                }
            });
        });
    }

    const initialWeatherData = JSON.parse(document.getElementById('weather-data')?.textContent || '[]');
    if (Array.isArray(initialWeatherData) && initialWeatherData.length) {
        console.debug('Initial weather data:', initialWeatherData);
        initialWeatherData.forEach(weather => {
            weather.is_expired = !weather.condition ||
                                 (weather.expires_at && new Date(weather.expires_at) < new Date());
            if (weather.updated_at) {
                const weatherTime = new Date(weather.updated_at);
                if (!latestUpdateTime || weatherTime > latestUpdateTime) {
                    latestUpdateTime = weatherTime;
                }
            }
        });
        updateWeatherDisplay(initialWeatherData);
    } else {
        console.warn('No initial weather data or invalid format');
        document.querySelectorAll('.schedule-card').forEach(card => {
            const conditionElement = card.querySelector('.weather-condition');
            const iconElement = card.querySelector('.weather-icon');
            const tempElement = card.querySelector('.weather-temp .temp-value');
            const windElement = card.querySelector('.weather-wind .wind-value');
            const precipElement = card.querySelector('.weather-precip .precip-value');
            if (conditionElement && iconElement && tempElement && windElement && precipElement) {
                conditionElement.textContent = 'Weather data unavailable';
                conditionElement.classList.remove('warning');
                iconElement.textContent = weatherIcons.default;
                tempElement.textContent = 'N/A';
                windElement.textContent = 'N/A';
                precipElement.textContent = 'N/A';
            }
        });
    }

    function fetchWeatherUpdates() {
        const url = latestUpdateTime && !isNaN(latestUpdateTime)
            ? `/api/weather/?since=${latestUpdateTime.toISOString()}`
            : '/api/weather/';
        fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(response => {
                if (!response.ok) throw new Error(response.statusText);
                return response.json();
            })
            .then(data => {
                console.debug('Received weather data:', data);
                if (data.error) {
                    console.warn('Weather fetch error:', data.error);
                    updateWeatherDisplay([]);
                } else if (Array.isArray(data.weather) && data.weather.length) {
                    updateWeatherDisplay(data.weather);
                } else {
                    console.debug('Weather fetch: no new updates');
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
        setInterval(fetchWeatherUpdates, 30000);
    }, 3000);

    // ---- Schedule Polling ----
    function pollScheduleUpdates() {
        fetch('/api/schedules/', { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(r => { if (!r.ok) throw new Error(r.statusText); return r.json(); })
            .then(data => {
                const nextDepartureElement = document.getElementById('next-departure-time');
                const now = moment().utcOffset('+12:00');
                const schedules = data.schedules
                    .filter(s => s.status === 'scheduled' && moment.utc(s.departure_time).isAfter(now))
                    .sort((a, b) => moment.utc(a.departure_time).diff(moment.utc(b.departure_time)));

                if (schedules.length) {
                    const nextDeparture = schedules[0];
                    nextDepartureElement.textContent =
                        `${moment.utc(nextDeparture.departure_time).format('ddd, MMM D, HH:mm')} - ` +
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
                    card.querySelector('.status-badge').textContent =
                        schedule.status.charAt(0).toUpperCase() + schedule.status.slice(1);
                    const fareEl = card.querySelector('.fare');
                    fareEl.textContent = schedule.status === 'scheduled' ? `FJD ${schedule.route.base_fare}` : 'Booking Unavailable';
                    const seatCount = card.querySelector('.seat-count');
                    seatCount.textContent = schedule.available_seats;
                    seatCount.classList.toggle('low', schedule.available_seats < 5);
                    const departureTime = card.querySelector('.departure-time');
                    departureTime.dataset.iso = schedule.departure_time;
                    departureTime.textContent = moment.utc(schedule.departure_time).format('ddd, MMM D, HH:mm');
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
                t.style.display = j === i ? 'block' : 'none';
                t.style.opacity = j === i ? '1' : '0';
            });
        }
        setInterval(() => { idx = (idx + 1) % testimonials.length; showTestimonial(idx); }, 5000);
        showTestimonial(idx);
    }

    // ---- Map ----
    const mapEl = document.getElementById('fiji-map');
    if (mapEl && typeof L !== 'undefined') {
        try {
            const isMobile = window.matchMedia('(max-width: 768px)').matches;
            const map = L.map('fiji-map', {
                zoomControl: !isMobile,
                preferCanvas: true,
                maxBounds: [
                    [-19.5, 176.0], // Southwest corner (near Fiji)
                    [-16.0, 180.0]  // Northeast corner
                ],
                maxBoundsViscosity: 1.0
            }).setView([-17.7, 178.0], 7);

            const tileLayer = L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
                attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
                maxZoom: 19,
                minZoom: 6,
                tileSize: 256,
                subdomains: 'abcd',
                errorTileUrl: window.TILE_ERROR_URL || '/static/images/tile-error.png' // Fallback to hardcoded URL
            }).addTo(map);

            tileLayer.on('tileerror', function(error, tile) {
                console.warn('Tile load error:', error, 'Tile coords:', tile.coords);
                mapEl.innerHTML = '<p class="text-center text-var-text-color">Map tiles failed to load. Please try again later.</p>';
            });

            const clusterGroup = typeof L.MarkerClusterGroup !== 'undefined'
                ? L.markerClusterGroup({
                    disableClusteringAtZoom: 8,
                    spiderfyOnMaxZoom: false,
                    showCoverageOnHover: false
                })
                : L.layerGroup();

            const destinations = [
                { name: 'Nadi', coords: [-17.7765, 177.4356], url: '/bookings/book/?to_port=nadi' },
                { name: 'Suva', coords: [-18.1416, 178.4419], url: '/bookings/book/?to_port=suva' },
                { name: 'Taveuni', coords: [-16.9892, -179.8797], url: '/bookings/book/?to_port=taveuni' },
                { name: 'Savusavu', coords: [-16.7769, 179.3321], url: '/bookings/book/?to_port=savusavu' }
            ];

            destinations.forEach(dest => {
                const marker = L.marker(dest.coords)
                    .bindPopup(`<b>${dest.name}</b><br><a href="${dest.url}">Book Now</a>`);
                clusterGroup.addLayer(marker);
            });

            map.addLayer(clusterGroup);
            setTimeout(() => map.invalidateSize(), 100);
        } catch (error) {
            console.error('Map initialization failed:', error);
            mapEl.innerHTML = '<p class="text-center text-var-text-color">Map failed to load. Please try again later.</p>';
        }
    } else {
        console.warn('Map element or Leaflet not found');
        if (mapEl) {
            mapEl.innerHTML = '<p class="text-center text-var-text-color">Map failed to load. Please try again later.</p>';
        }
    }
});