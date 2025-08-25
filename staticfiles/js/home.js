document.addEventListener('DOMContentLoaded', function () {
    // Initialize Flatpickr for date picker
    const formData = JSON.parse(document.getElementById('form-data')?.textContent || '{}');
    flatpickr('#departure-date', {
        minDate: 'today',
        dateFormat: 'Y-m-d',
        defaultDate: formData.date || document.getElementById('departure-date').value || null
    });

    // Initialize AOS
    if (typeof AOS !== 'undefined') {
        try {
            AOS.init({
                duration: 800,
                easing: 'ease-in-out',
                once: true,
                mirror: false,
                anchorPlacement: 'top-bottom',
                offset: 100,
                disable: 'mobile'
            });
        } catch (error) {
            console.warn('AOS initialization failed, proceeding without animations:', error);
        }
    }

    // Hero Slideshow
    const heroContainer = document.querySelector('.hero-slideshow');
    if (!heroContainer) {
        console.error('Hero slideshow container not found.');
        return;
    }
    const slides = document.querySelectorAll('.hero-slide');
    const dots = document.querySelectorAll('.hero-nav-dots .dot');
    if (!slides || slides.length === 0) {
        console.error('No hero slides found.');
        return;
    }

    let currentIndex = 0;
    let slideInterval;
    let isTransitioning = false;
    let lastScrollPosition = 0;
    let ticking = false;
    const isMobile = window.matchMedia('(max-width: 768px)').matches;

    function handleParallax() {
        if (isMobile) return;
        const scrollPosition = window.pageYOffset;
        slides.forEach(slide => {
            slide.style.setProperty('--translate-y', `${scrollPosition * 0.1}px`);
        });
        ticking = false;
    }

    const styleSheet = document.createElement('style');
    styleSheet.textContent = `
        .hero-slide {
            transform: scale(1.1) translateY(var(--translate-y, 0));
            will-change: transform, opacity;
        }
        @media (max-width: 768px) {
            .hero-slide {
                transform: scale(1);
            }
        }
    `;
    document.head.appendChild(styleSheet);

    if (!isMobile) {
        window.addEventListener('scroll', function () {
            lastScrollPosition = window.pageYOffset;
            if (!ticking) {
                window.requestAnimationFrame(handleParallax);
                ticking = true;
            }
        }, { passive: true });
    }

    function preloadImages() {
        slides.forEach((slide, index) => {
            const bgImage = slide.dataset.src;
            if (bgImage) {
                if (index <= 1) {
                    slide.style.backgroundImage = `url(${bgImage})`;
                    slide.removeAttribute('data-src');
                    slide.style.opacity = index === 0 ? '1' : '0';
                } else {
                    const observer = new IntersectionObserver((entries, obs) => {
                        entries.forEach(entry => {
                            if (entry.isIntersecting) {
                                const lazySlide = entry.target;
                                if (lazySlide.dataset.src && !lazySlide.style.backgroundImage) {
                                    lazySlide.style.backgroundImage = `url(${lazySlide.dataset.src})`;
                                    lazySlide.removeAttribute('data-src');
                                    lazySlide.style.opacity = '0';
                                    requestAnimationFrame(() => {
                                        lazySlide.style.opacity = '1';
                                        lazySlide.style.transition = 'opacity 0.3s ease';
                                    });
                                    obs.unobserve(lazySlide);
                                }
                            }
                        });
                    }, { rootMargin: '300px', threshold: 0.1 });
                    observer.observe(slide);
                }
            }
        });
    }

    function showSlide(index) {
        if (isTransitioning || index === currentIndex) return;
        isTransitioning = true;
        slides.forEach((slide, i) => {
            slide.style.setProperty('--opacity', i === index ? '1' : '0');
            slide.style.setProperty('--scale', i === index ? '1' : '1.1');
            slide.setAttribute('aria-hidden', i !== index);
            if (dots[i]) {
                dots[i].classList.toggle('active', i === index);
                dots[i].setAttribute('aria-selected', i === index);
            }
        });
        currentIndex = index;
        setTimeout(() => {
            isTransitioning = false;
        }, 700);
    }

    const slideStyles = document.createElement('style');
    slideStyles.textContent = `
        .hero-slide {
            opacity: var(--opacity, 1);
            transform: scale(var(--scale, 1)) translateY(var(--translate-y, 0));
            transition: opacity 0.7s ease, transform 0.7s ease;
        }
        @media (max-width: 768px) {
            .hero-slide {
                transform: scale(var(--scale, 1));
            }
        }
    `;
    document.head.appendChild(slideStyles);

    function nextSlide() {
        if (isTransitioning) return;
        const nextIndex = (currentIndex + 1) % slides.length;
        showSlide(nextIndex);
    }

    function prevSlide() {
        if (isTransitioning) return;
        const prevIndex = (currentIndex - 1 + slides.length) % slides.length;
        showSlide(prevIndex);
    }

    dots.forEach((dot, i) => {
        dot.setAttribute('role', 'button');
        dot.setAttribute('aria-label', `Go to slide ${i + 1}`);
        dot.addEventListener('click', () => {
            clearInterval(slideInterval);
            showSlide(i);
            slideInterval = setInterval(nextSlide, 6000);
        });
        dot.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                clearInterval(slideInterval);
                showSlide(i);
                slideInterval = setInterval(nextSlide, 6000);
            }
        });
    });

    let touchStartX = 0;
    let touchEndX = 0;

    heroContainer.addEventListener('touchstart', e => {
        touchStartX = e.changedTouches[0].screenX;
    }, { passive: true });

    heroContainer.addEventListener('touchend', e => {
        touchEndX = e.changedTouches[0].screenX;
        const swipeThreshold = 50;
        if (touchStartX - touchEndX > swipeThreshold) {
            clearInterval(slideInterval);
            nextSlide();
            slideInterval = setInterval(nextSlide, 6000);
        } else if (touchEndX - touchStartX > swipeThreshold) {
            clearInterval(slideInterval);
            prevSlide();
            slideInterval = setInterval(nextSlide, 6000);
        }
    }, { passive: true });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'ArrowRight') {
            clearInterval(slideInterval);
            nextSlide();
            slideInterval = setInterval(nextSlide, 6000);
        } else if (e.key === 'ArrowLeft') {
            clearInterval(slideInterval);
            prevSlide();
            slideInterval = setInterval(nextSlide, 6000);
        }
    }, { passive: true });

    heroContainer.addEventListener('mouseenter', () => {
        clearInterval(slideInterval);
    }, { passive: true });

    heroContainer.addEventListener('mouseleave', () => {
        slideInterval = setInterval(nextSlide, 6000);
    }, { passive: true });

    try {
        preloadImages();
        showSlide(currentIndex);
        slideInterval = setInterval(nextSlide, 6000);
    } catch (error) {
        console.error('Slideshow initialization failed:', error);
    }

    let resizeTimeout;
    window.addEventListener('resize', () => {
        clearTimeout(resizeTimeout);
        resizeTimeout = setTimeout(() => {
            slides.forEach(slide => {
                slide.style.transition = 'none';
                requestAnimationFrame(() => {
                    slide.style.transition = 'opacity 0.7s ease, transform 0.7s ease';
                });
            });
        }, 100);
    }, { passive: true });

    slides.forEach(slide => {
        slide.setAttribute('tabindex', '-1');
        slide.setAttribute('aria-hidden', 'true');
    });
    slides[currentIndex].setAttribute('aria-hidden', 'false');

    // Schedule Sorting
    const sortSelect = document.getElementById('sort-by');
    if (sortSelect) {
        sortSelect.addEventListener('change', function () {
            const sortBy = this.value;
            const scheduleList = document.querySelector('.schedule-list');
            const cards = Array.from(scheduleList.querySelectorAll('.schedule-card'));
            cards.sort((a, b) => {
                if (sortBy === 'price') {
                    const fareA = parseFloat(a.querySelector('.fare').textContent.replace('FJD ', '') || Infinity);
                    const fareB = parseFloat(b.querySelector('.fare').textContent.replace('FJD ', '') || Infinity);
                    return fareA - fareB;
                } else if (sortBy === 'duration') {
                    const durA = a.querySelector('.duration').textContent.includes('Not Available') ? Infinity : parseDuration(a.querySelector('.duration').textContent);
                    const durB = b.querySelector('.duration').textContent.includes('Not Available') ? Infinity : parseDuration(b.querySelector('.duration').textContent);
                    return durA - durB;
                } else {
                    const timeA = new Date(a.querySelector('.departure-time').dataset.iso);
                    const timeB = new Date(b.querySelector('.departure-time').dataset.iso);
                    return timeA - timeB;
                }
            });
            scheduleList.innerHTML = '';
            cards.forEach(card => scheduleList.appendChild(card));
        });
    }

    function parseDuration(text) {
        const match = text.match(/(\d+)h\s*(\d+)?m?/);
        if (!match) return Infinity;
        const hours = parseInt(match[1]) || 0;
        const minutes = parseInt(match[2]) || 0;
        return hours * 60 + minutes;
    }

    // Schedule Updates Polling
    function pollScheduleUpdates() {
        fetch('/get_schedule_updates/', {
            method: 'GET',
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
            },
        })
        .then(response => {
            if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
            return response.json();
        })
        .then(data => {
            const nextDepartureElement = document.getElementById('next-departure-time');
            const now = moment().utcOffset('+12:00'); // Fiji time (UTC+12)
            const schedules = data.schedules
                .filter(s => s.status === 'scheduled' && moment(s.departure_time).isAfter(now))
                .sort((a, b) => moment(a.departure_time).diff(moment(b.departure_time)));

            if (schedules.length > 0) {
                const nextDeparture = schedules[0];
                nextDepartureElement.textContent = `${moment(nextDeparture.departure_time).format('ddd, MMM D, HH:mm')} - ${nextDeparture.route.departure_port} to ${nextDeparture.route.destination_port}`;
                nextDepartureElement.dataset.iso = nextDeparture.departure_time;
                nextDepartureElement.dataset.scheduleId = nextDeparture.id;
                document.querySelectorAll('.schedule-card').forEach(card => {
                    card.classList.toggle('next-departure', card.dataset.scheduleId == nextDeparture.id);
                });
            } else {
                nextDepartureElement.textContent = 'No upcoming departures';
                nextDepartureElement.dataset.iso = '';
                nextDepartureElement.dataset.scheduleId = '';
                document.querySelectorAll('.schedule-card').forEach(card => {
                    card.classList.remove('next-departure');
                });
            }

            // Update schedule cards
            data.schedules.forEach(schedule => {
                const card = document.querySelector(`.schedule-card[data-schedule-id="${schedule.id}"]`);
                if (card) {
                    const statusBadge = card.querySelector('.status-badge');
                    statusBadge.textContent = schedule.status.charAt(0).toUpperCase() + schedule.status.slice(1);
                    statusBadge.className = `status-badge status-${schedule.status} ${
                        schedule.status === 'scheduled' ? 'bg-green-100 text-green-800 dark:bg-green-800 dark:text-green-100' :
                        schedule.status === 'cancelled' ? 'bg-red-100 text-red-800 dark:bg-red-800 dark:text-red-100' :
                        'bg-orange-100 text-orange-800 dark:bg-orange-800 dark:text-orange-100'
                    }`;
                    const fareElement = card.querySelector('.fare');
                    fareElement.textContent = schedule.status === 'scheduled' ? `FJD ${schedule.route.base_fare}` : 'Booking Unavailable';
                    fareElement.className = `fare ${
                        schedule.status !== 'scheduled' ? 'fare-unavailable text-red-600 dark:text-red-400' : 'text-blue-600 dark:text-blue-400'
                    }`;
                    const seatCount = card.querySelector('.seat-count');
                    seatCount.textContent = schedule.available_seats;
                    seatCount.classList.toggle('low', schedule.available_seats < 5);
                    const departureTime = card.querySelector('.departure-time');
                    departureTime.dataset.iso = schedule.departure_time;
                    departureTime.textContent = moment(schedule.departure_time).format('D, MMM d, HH:mm');
                }
            });
        })
        .catch(error => {
            console.error('Schedule polling error:', error);
            document.getElementById('next-departure-time').textContent = 'Error loading departures';
            document.querySelectorAll('.schedule-card').forEach(card => {
                card.classList.remove('next-departure');
            });
        });
    }

    // Initialize with server-rendered next departure
    const nextDepartureElement = document.getElementById('next-departure-time');
    if (nextDepartureElement.dataset.scheduleId) {
        document.querySelectorAll('.schedule-card').forEach(card => {
            card.classList.toggle('next-departure', card.dataset.scheduleId == nextDepartureElement.dataset.scheduleId);
        });
    }
    setInterval(pollScheduleUpdates, 10000);
    pollScheduleUpdates();

    // Weather Updates via SSE
    function startWeatherStream() {
        const eventSource = new EventSource('/weather/stream/');
        eventSource.onopen = function() {
            console.log('SSE weather stream connected');
        };
        eventSource.onmessage = function(event) {
            try {
                const data = JSON.parse(event.data);
                if (!data.weather && !data.error) {
                    throw new Error('Invalid weather data format');
                }
                if (data.error) {
                    console.warn('Weather data error:', data.error);
                    document.querySelectorAll('.weather-condition').forEach(el => {
                        el.textContent = 'Weather data unavailable';
                        el.classList.remove('warning');
                    });
                    return;
                }
                data.weather.forEach(weather => {
                    const cards = document.querySelectorAll(`.schedule-card[data-route-id="${weather.route_id}"]`);
                    cards.forEach(card => {
                        const conditionElement = card.querySelector('.weather-condition');
                        if (weather.error || !weather.condition) {
                            conditionElement.textContent = 'Weather data unavailable';
                            conditionElement.classList.remove('warning');
                        } else {
                            const waveInfo = weather.wave_height ? `, Waves ${weather.wave_height}m` : '';
                            conditionElement.textContent = `${weather.condition}, ${weather.temperature}°C, Wind ${weather.wind_speed}kph${waveInfo}`;
                            const isWarning = weather.wind_speed > 30 || (weather.wave_height && weather.wave_height > 2);
                            conditionElement.classList.toggle('warning', isWarning);
                            conditionElement.style.transition = 'opacity 0.3s ease';
                            conditionElement.style.opacity = '0';
                            requestAnimationFrame(() => {
                                conditionElement.style.opacity = '1';
                            });
                        }
                    });
                });
            } catch (error) {
                console.error('SSE weather data parse error:', error);
                document.querySelectorAll('.weather-condition').forEach(el => {
                    el.textContent = 'Weather data unavailable';
                    el.classList.remove('warning');
                });
            }
        };
        eventSource.onerror = function() {
            console.warn('SSE weather stream error, retrying in 5 seconds...');
            document.querySelectorAll('.weather-condition').forEach(el => {
                el.textContent = 'Weather data temporarily unavailable';
                el.classList.remove('warning');
            });
            eventSource.close();
            setTimeout(startWeatherStream, 5000);
        };
    }
    startWeatherStream();

    // Testimonial Slider
    const testimonials = document.querySelectorAll('.testimonial');
    if (testimonials.length > 0) {
        let testimonialIndex = 0;
        function showTestimonial(index) {
            testimonials.forEach((t, i) => {
                t.style.display = i === index ? 'block' : 'none';
                t.style.opacity = i === index ? '1' : '0';
            });
        }
        function nextTestimonial() {
            testimonialIndex = (testimonialIndex + 1) % testimonials.length;
            showTestimonial(testimonialIndex);
        }
        showTestimonial(testimonialIndex);
        setInterval(nextTestimonial, 5000);
    }
});