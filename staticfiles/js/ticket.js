document.addEventListener('DOMContentLoaded', () => {
    AOS.init({
        duration: 800,
        easing: 'ease-out-quart',
        once: true,
        offset: 80,
    });

    // Apply vibrant animation after AOS
    setTimeout(() => {
        document.querySelectorAll('.passenger-details, .booking-info, .additional-info').forEach(el => {
            el.classList.add('vibrant');
        });
    }, 1000);

    initCountdowns();

    // Initialize maps on page load
    document.querySelectorAll('.route-map').forEach(mapElement => {
        if (mapElement.dataset.mapInit === 'false') {
            initSingleMap(mapElement);
            mapElement.dataset.mapInit = 'true';
        }
    });

    // Ensure map resizes if tab is toggled
    document.querySelectorAll('.nav-tabs .nav-link').forEach(tab => {
        tab.addEventListener('shown.bs.tab', (e) => {
            const targetId = e.target.getAttribute('data-bs-target').slice(1);
            if (targetId.startsWith('overview-')) {
                const mapId = 'map-' + targetId.split('-')[1];
                const mapElement = document.getElementById(mapId);
                if (mapElement && mapElement._leaflet_map) {
                    mapElement._leaflet_map.invalidateSize();
                }
            }
        });
    });

    // Smooth Scroll for Back Button
    document.querySelectorAll('.ticket-action-btn.back').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            window.scrollTo({ top: 0, behavior: 'smooth' });
            setTimeout(() => window.location.href = btn.href, 300);
        });
    });
});

function initCountdowns() {
    document.querySelectorAll('.countdown').forEach(element => {
        const departureTime = new Date(element.dataset.departureTime).getTime();
        const updateCountdown = () => {
            const now = new Date().getTime();
            const distance = departureTime - now;

            if (distance < 0) {
                element.textContent = 'Departure Time Passed';
                element.classList.remove('urgent');
                return;
            }

            const days = Math.floor(distance / (1000 * 60 * 60 * 24));
            const hours = Math.floor((distance % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
            const minutes = Math.floor((distance % (1000 * 60 * 60)) / (1000 * 60));
            const seconds = Math.floor((distance % (1000 * 60)) / 1000);

            element.textContent = `Countdown to Departure: ${days}d ${hours}h ${minutes}m ${seconds}s`;

            // Dynamic color: red if less than 1 hour
            if (distance < 3600000) {  // 1 hour in ms
                element.classList.add('urgent');
            } else {
                element.classList.remove('urgent');
            }
        };

        updateCountdown();
        setInterval(updateCountdown, 1000);
    });
}

function initSingleMap(mapElement) {
    try {
        const departureLat = parseFloat(mapElement.dataset.departureLat);
        const departureLng = parseFloat(mapElement.dataset.departureLng);
        const destinationLat = parseFloat(mapElement.dataset.destinationLat);
        const destinationLng = parseFloat(mapElement.dataset.destinationLng);
        const departurePort = mapElement.dataset.departurePort || 'Departure Port';
        const destinationPort = mapElement.dataset.destinationPort || 'Destination Port';

        const map = L.map(mapElement.id).setView([(departureLat + destinationLat) / 2, (departureLng + destinationLng) / 2], 8);
        mapElement._leaflet_map = map;  // Store for invalidateSize

        // Use default OSM tiles for both themes
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
            maxZoom: 19
        }).addTo(map);

        // Add sea marks
        L.tileLayer('https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png', {
            attribution: '&copy; <a href="http://www.openseamap.org">OpenSeaMap</a> contributors'
        }).addTo(map);

        // Departure marker with ripple
        const depMarker = L.marker([departureLat, departureLng], {
            icon: L.divIcon({
                className: 'custom-marker ripple',
                html: '<i class="fas fa-anchor-circle-check fa-2x text-ocean-teal"></i>',
                iconSize: [32, 32],
                iconAnchor: [16, 32]
            })
        }).addTo(map).bindPopup(`<b>${departurePort}</b><br>Departure Point`);

        // Destination marker with ripple
        const destMarker = L.marker([destinationLat, destinationLng], {
            icon: L.divIcon({
                className: 'custom-marker ripple',
                html: '<i class="fas fa-anchor fa-2x text-nautical-blue"></i>',
                iconSize: [32, 32],
                iconAnchor: [16, 32]
            })
        }).addTo(map).bindPopup(`<b>${destinationPort}</b><br>Destination Point`);

        // Simple animation: Open popups alternately
        let activePopup = 'dep';
        const togglePopups = () => {
            if (activePopup === 'dep') {
                depMarker.openPopup();
                destMarker.closePopup();
                activePopup = 'dest';
            } else {
                destMarker.openPopup();
                depMarker.closePopup();
                activePopup = 'dep';
            }
        };
        togglePopups();
        setInterval(togglePopups, 3000);  // Switch every 3s

        // Fit bounds
        const bounds = L.latLngBounds([[departureLat, departureLng], [destinationLat, destinationLng]]);
        map.fitBounds(bounds, { padding: [50, 50] });

        // Remove loading
        const loading = mapElement.querySelector('.map-loading');
        if (loading) loading.remove();
    } catch (e) {
        console.error('Map initialization error:', e);
        mapElement.innerHTML = '<p class="text-center p-4 text-muted">Map unavailable. Please check coordinates.</p>';
    }
}