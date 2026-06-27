/**
 * Fiji Ferry Booking - Complete Homepage JavaScript
 * Unified implementation for home.html
 * Version: 2.5.0
 *
 * Fixed:
 * • Weather fetched from DATABASE (no SSE stream)
 * • Map shows ONLY ports with active schedules
 * • Robust fallbacks, error handling, no 404s
 */
(function () {
    'use strict';

    // GLOBAL CONFIGURATION
    const FijiFerry = window.FijiFerry || {};
    FijiFerry.config = {
        animationDuration: 600,
        slideshowInterval: 5000,
        testimonialInterval: 7000,
        pollingInterval: 120000,
        weatherUpdateInterval: 120000, // Poll DB every 2 min
        debug: true
    };

    // LOGGER
    const logger = {
        log: (...args) => FijiFerry.config.debug && console.log('[FijiFerry]', ...args),
        warn: (...args) => FijiFerry.config.debug && console.warn('[FijiFerry]', ...args),
        error: (...args) => console.error('[FijiFerry]', ...args)
    };

    // UTILITY FUNCTIONS
    const Utils = {
        safeParseJSON(elementId, defaultValue = {}) {
            try {
                const script = document.getElementById(elementId);
                if (!script) return defaultValue;
                const jsonStr = script.textContent.trim()
                    .replace(/^\s*<\!\[CDATA\[/, '').replace(/\]\]>\s*$/, '');
                return JSON.parse(jsonStr) || defaultValue;
            } catch (error) {
                logger.warn(`Failed to parse ${elementId}:`, error);
                return defaultValue;
            }
        },
        sanitizeHTML(str) {
            const div = document.createElement('div');
            div.textContent = str;
            return div.innerHTML;
        },
        formatDuration(minutes) {
            if (!minutes || isNaN(minutes)) return 'N/A';
            const hours = Math.floor(minutes / 60);
            const mins = minutes % 60;
            return hours > 0 ? `${hours}h ${mins}m` : `${mins}m`;
        },
        formatPrice(price) {
            return price ? `FJD ${parseFloat(price).toFixed(0)}` : 'Price TBD';
        },
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
        },
        throttle(func, limit) {
            let inThrottle;
            return function () {
                const args = arguments;
                const context = this;
                if (!inThrottle) {
                    func.apply(context, args);
                    inThrottle = true;
                    setTimeout(() => inThrottle = false, limit);
                }
            };
        },
        async useFetch(url, options = {}) {
            try {
                const response = await fetch(url, options);
                if (!response.ok) {
                    const errorText = await response.text();
                    throw new Error(`Fetch error ${response.status}: ${errorText}`);
                }
                const data = await response.json();
                return { data, error: null };
            } catch (error) {
                logger.error('useFetch error', error, url);
                return { data: null, error };
            }
        },
        getWeatherIcon(condition) {
            const icons = {
                'sunny': 'fa-sun',
                'clear': 'fa-sun',
                'partly cloudy': 'fa-cloud-sun',
                'partly_cloudy': 'fa-cloud-sun',
                'cloudy': 'fa-cloud',
                'overcast': 'fa-cloud',
                'cloud': 'fa-cloud',
                'rain': 'fa-cloud-rain',
                'light rain': 'fa-cloud-rain',
                'heavy rain': 'fa-cloud-showers-heavy',
                'shower': 'fa-cloud-rain',
                'thunderstorm': 'fa-bolt',
                'thunder': 'fa-bolt',
                'drizzle': 'fa-cloud-rain',
                'fog': 'fa-smog',
                'mist': 'fa-smog',
                'haze': 'fa-smog',
                'windy': 'fa-wind',
                'snow': 'fa-snowflake',
                'sleet': 'fa-snowflake',
                'hail': 'fa-snowflake'
            };

            const key = condition?.toLowerCase()?.replace(/\s+/g, '_');
            const icon = icons[key] || 'fa-cloud';
            return `<i class="fas ${icon}" aria-hidden="true"></i>`;
        },
        getRouteColor(routeId) {
            const colors = ['#10b981', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4', '#84cc16'];
            return colors[routeId % colors.length];
        },
        preloadImages(sources) {
            sources.forEach(src => {
                if (src) {
                    const img = new Image();
                    img.src = src;
                }
            });
        },
        getThemeColor(color, opacity = 1) {
            const root = document.documentElement;
            const theme = root.getAttribute('data-theme') || 'light';
            const colors = {
                primary: theme === 'dark' ? '#34D399' : '#10B981',
                secondary: theme === 'dark' ? '#60A5FA' : '#3B82F6',
                background: theme === 'dark' ? '#0F172A' : '#FFFFFF',
                surface: theme === 'dark' ? '#1E293B' : '#F8FAFC',
                text: theme === 'dark' ? '#F1F5F9' : '#1E293B',
                border: theme === 'dark' ? '#334155' : '#E2E8F0'
            };
            return colors[color] || (theme === 'dark' ? '#94A3B8' : '#6B7280');
        },
        applyTailwindOverrides() {
            const theme = document.documentElement.getAttribute('data-theme') || 'light';
            if (theme === 'dark') {
                const style = document.createElement('style');
                style.textContent = `
                    [data-theme="dark"] .text-gray-800 { color: #F1F5F9 !important; }
                    [data-theme="dark"] .text-gray-700 { color: #E2E8F0 !important; }
                    [data-theme="dark"] .text-gray-600 { color: #CBD5E1 !important; }
                    [data-theme="dark"] .text-gray-500 { color: #94A3B8 !important; }
                    [data-theme="dark"] .text-gray-400 { color: #64748B !important; }
                    [data-theme="dark"] .text-gray-300 { color: #475569 !important; }
                    [data-theme="dark"] .text-gray-200 { color: #334155 !important; }
                    [data-theme="dark"] .text-gray-100 { color: #1E293B !important; }
                    [data-theme="dark"] .bg-white { background-color: #0F172A !important; }
                    [data-theme="dark"] .bg-gray-50 { background-color: #1E293B !important; }
                    [data-theme="dark"] .bg-gray-100 { background-color: #334155 !important; }
                    [data-theme="dark"] .bg-gray-200 { background-color: #475569 !important; }
                    [data-theme="dark"] .border-gray-200 { border-color: #475569 !important; }
                    [data-theme="dark"] .border-gray-100 { border-color: #334155 !important; }
                `;
                document.head.appendChild(style);
            }
        }
    };

    // NOTIFICATION SYSTEM
    class NotificationManager {
        constructor() {
            this.container = null;
            this.notifications = new Map();
            this.init();
        }
        init() {
            this.createContainer();
            this.setupThemeListener();
        }
        setupThemeListener() {
            const observer = new MutationObserver(() => this.updateNotificationsTheme());
            observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
        }
        createContainer() {
            if (this.container) this.container.remove();
            this.container = document.createElement('div');
            this.container.className = 'notification-container fixed top-4 right-4 z-50 space-y-2 max-w-sm w-full sm:w-80';
            document.body.appendChild(this.container);
            this.updateContainerTheme();
        }
        updateContainerTheme() {
            if (!this.container) return;
            const theme = document.documentElement.getAttribute('data-theme') || 'light';
            this.container.style.background = theme === 'dark' ? 'rgba(15, 23, 42, 0.95)' : 'rgba(255, 255, 255, 0.95)';
            this.container.style.backdropFilter = 'blur(20px)';
        }
        updateNotificationsTheme() {
            this.notifications.forEach(({ element }) => {
                if (element && element.parentNode) this.updateNotificationTheme(element);
            });
        }
        updateNotificationTheme(notification) {
            const theme = document.documentElement.getAttribute('data-theme') || 'light';
            const classes = notification.className.split(' ');
            const bgClass = classes.find(cls => cls.includes('bg-'));
            if (bgClass) {
                const color = bgClass.replace('bg-', '');
                const opacity = theme === 'dark' ? 0.15 : 1;
                const rgbaColor = this.hexToRgb(Utils.getThemeColor(color), opacity);
                notification.style.background = `rgba(${rgbaColor})`;
                if (theme === 'dark') {
                    notification.style.color = '#F1F5F9';
                    const closeBtn = notification.querySelector('.notification-close');
                    if (closeBtn) closeBtn.style.color = '#F1F5F9';
                }
            }
        }
        hexToRgb(hex, alpha = 1) {
            const result = /^#?([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i.exec(hex);
            return result ? `${parseInt(result[1], 16)}, ${parseInt(result[2], 16)}, ${parseInt(result[3], 16)}` : '0, 0, 0';
        }
        show(message, type = 'info', duration = 4000, options = {}) {
            // Prefer the global unified toast system (defined in base.html) so
            // notifications look and behave identically on every page.
            if (window.Toast && typeof window.Toast.show === 'function') {
                return window.Toast.show(message, type, { duration, ...options });
            }
            const id = `notification-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`;
            const config = this.getNotificationConfig(type);
            const notification = document.createElement('div');
            notification.id = id;
            notification.className = `
                notification transform translate-x-full transition-transform duration-300 p-4 rounded-xl shadow-2xl max-w-sm
                ${config.bg} ${config.text} border-l-4 ${config.border}
            `;
            notification.setAttribute('role', 'alert');
            notification.setAttribute('aria-live', options.live || 'polite');
            notification.setAttribute('aria-atomic', 'true');
            notification.innerHTML = `
                <div class="notification-content flex items-start gap-3">
                    <span class="notification-icon flex-shrink-0 mt-0.5 text-lg">${config.icon}</span>
                    <div class="notification-message flex-1 min-w-0">
                        <div class="notification-title font-semibold text-sm leading-tight capitalize">${type}</div>
                        <div class="notification-text text-sm leading-relaxed break-words" title="${Utils.sanitizeHTML(message)}">${Utils.sanitizeHTML(message)}</div>
                    </div>
                    <button class="notification-close ml-2 text-current opacity-70 hover:opacity-100 p-1 rounded-full hover:bg-white/20 transition-colors flex-shrink-0"
                            onclick="FijiFerry.notificationManager?.removeNotification('${id}')"
                            aria-label="Dismiss ${type} notification">
                        <i class="fas fa-times text-sm"></i>
                    </button>
                </div>
            `;
            this.container.appendChild(notification);
            this.notifications.set(id, { element: notification, duration, options });
            requestAnimationFrame(() => notification.classList.remove('translate-x-full'));
            if (duration > 0) setTimeout(() => this.removeNotification(id), duration);
            this.updateNotificationTheme(notification);
            return notification;
        }
        getNotificationConfig(type) {
            const configs = {
                success: { icon: 'Check', bg: 'bg-emerald-500', border: 'border-emerald-400', text: 'text-white' },
                error: { icon: 'Cross', bg: 'bg-red-500', border: 'border-red-400', text: 'text-white' },
                warning: { icon: 'Warning', bg: 'bg-amber-500', border: 'border-amber-400', text: 'text-white' },
                info: { icon: 'Info', bg: 'bg-blue-500', border: 'border-blue-400', text: 'text-white' }
            };
            return configs[type] || configs.info;
        }
        removeNotification(id) {
            const notification = document.getElementById(id);
            if (!notification) return;
            notification.classList.add('translate-x-full');
            setTimeout(() => {
                if (notification.parentNode) notification.remove();
                this.notifications.delete(id);
            }, 300);
        }
        closeAll() {
            this.notifications.forEach((_, id) => this.removeNotification(id));
        }
        destroy() {
            this.closeAll();
            if (this.container) this.container.remove();
            this.container = null;
        }
    };

    // HERO MANAGER
    class HeroManager {
        constructor() {
            this.slides = document.querySelectorAll('.hero-slide');
            this.dots = document.querySelectorAll('.hero-nav-dots .dot');
            this.form = document.getElementById('search-form');
            this.currentSlide = 0;
            this.slideInterval = null;
            this.isInitialized = false;
            this.init();
        }
        init() {
            if (this.isInitialized) return;
            this.isInitialized = true;
            logger.log('Initializing HeroManager');
            this.setupSlideshow();
            if (this.form) this.setupForm();
            this.setupThemeListener();
            this.setupQuickSearch();
            if (this.form) this.form.addEventListener('input', () => this.updateState());
        }
        setupThemeListener() {
            const observer = new MutationObserver(() => this.updateTheme());
            observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
        }
        updateTheme() {
            const theme = document.documentElement.getAttribute('data-theme') || 'light';
            logger.log(`Hero theme changed to: ${theme}`);
            this.slides.forEach(slide => {
                const imgSrc = slide.dataset.srcLight;
                if (imgSrc && slide.style.backgroundImage !== `url('${imgSrc}')`) {
                    const img = new Image();
                    img.onload = () => {
                        slide.style.backgroundImage = `url('${imgSrc}')`;
                        logger.log(`Updated slide image to: ${imgSrc}`);
                    };
                    img.src = imgSrc;
                }
            });
        }
        setupSlideshow() {
            if (!this.slides.length) {
                logger.warn('No slides found for hero slideshow');
                return;
            }
            const activeSlide = document.querySelector('.hero-slide.active');
            if (activeSlide) this.currentSlide = Array.from(this.slides).indexOf(activeSlide);
            else if (this.slides[0]) {
                this.slides[0].classList.add('active');
                this.currentSlide = 0;
            }
            if (this.dots[this.currentSlide]) this.dots[this.currentSlide].classList.add('active');
            this.showSlide(this.currentSlide);
            this.startSlideshow();
            const hero = document.querySelector('.hero');
            if (hero) {
                ['mouseenter', 'focusin'].forEach(event => hero.addEventListener(event, () => this.pauseSlideshow()));
                ['mouseleave', 'focusout'].forEach(event => hero.addEventListener(event, () => this.resumeSlideshow()));
            }
            this.updateTheme();
        }
        showSlide(index) {
            if (index < 0 || index >= this.slides.length) return;
            this.slides.forEach((slide, i) => {
                if (i === index) {
                    slide.classList.add('active');
                    slide.style.opacity = '1';
                    slide.style.zIndex = '2';
                } else {
                    slide.classList.remove('active');
                    slide.style.opacity = '0';
                    slide.style.zIndex = '1';
                }
            });
            this.dots.forEach((dot, i) => {
                dot.classList.toggle('active', i === index);
                dot.setAttribute('aria-pressed', (i === index).toString());
                dot.setAttribute('tabindex', i === index ? '0' : '-1');
            });
            this.currentSlide = index;
        }
        startSlideshow() {
            if (this.slideInterval) clearInterval(this.slideInterval);
            if (this.slides.length <= 1) return;
            this.slideInterval = setInterval(() => {
                this.currentSlide = (this.currentSlide + 1) % this.slides.length;
                this.showSlide(this.currentSlide);
            }, FijiFerry.config.slideshowInterval);
        }
        pauseSlideshow() {
            if (this.slideInterval) {
                clearInterval(this.slideInterval);
                this.slideInterval = null;
            }
        }
        resumeSlideshow() {
            if (!this.slideInterval && this.slides.length > 1) this.startSlideshow();
        }
        setupForm() {
            this.form.addEventListener('submit', (e) => {
                if (!this.validate()) {
                    e.preventDefault();
                    FijiFerry.notificationManager?.show('Please fill in all required fields', 'warning');
                }
            });
            const dateInput = document.getElementById('departure-date');
            if (dateInput) {
                dateInput.addEventListener('change', (e) => {
                    const today = new Date().toISOString().split('T')[0];
                    if (e.target.value < today) {
                        e.target.value = today;
                        FijiFerry.notificationManager?.show('Please select a future date', 'warning');
                    }
                });
                if (!dateInput.min) dateInput.min = new Date().toISOString().split('T')[0];
            }
            this.populateForm();
            this.setupRouteSuggestions();
        }
        setupRouteSuggestions() {
            const routeInput = document.getElementById('route');
            const routeIdInput = document.getElementById('route-id');
            const suggestions = document.getElementById('route-suggestions');
            if (!routeInput || !suggestions) return;
            let activeSuggestionIndex = -1;

            routeInput.addEventListener('input', Utils.debounce(async (e) => {
                if (routeIdInput) routeIdInput.value = '';
                const query = e.target.value.toLowerCase().trim();
                if (query.length < 2) {
                    suggestions.classList.add('hidden');
                    routeInput.setAttribute('aria-expanded', 'false');
                    routeInput.removeAttribute('aria-activedescendant');
                    return;
                }
                try {
                    const response = await fetch(`/bookings/api/routes/?q=${encodeURIComponent(query)}`);
                    if (!response.ok) throw new Error('Failed to fetch routes');
                    const { routes } = await response.json();
                    if (routes.length > 0) {
                        activeSuggestionIndex = -1;
                        suggestions.innerHTML = routes.slice(0, 5).map((route, index) => `
                            <div id="route-option-${index}" class="route-suggestion p-3 border-b border-gray-100 hover:bg-gray-50 cursor-pointer transition-colors dark:border-gray-700 dark:hover:bg-gray-800"
                                 role="option" tabindex="-1"
                                 data-value="${route.departure_port.name} to ${route.destination_port.name}"
                                 data-route-id="${route.id}">
                                ${route.departure_port.name} to ${route.destination_port.name}
                            </div>
                        `).join('');
                        suggestions.classList.remove('hidden');
                        routeInput.setAttribute('aria-expanded', 'true');
                        routeInput.removeAttribute('aria-activedescendant');

                        suggestions.querySelectorAll('.route-suggestion').forEach((option, idx) => {
                            option.addEventListener('click', () => {
                                routeInput.value = option.getAttribute('data-value');
                                if (routeIdInput) {
                                    routeIdInput.value = option.getAttribute('data-route-id');
                                }
                                suggestions.classList.add('hidden');
                                routeInput.setAttribute('aria-expanded', 'false');
                                routeInput.removeAttribute('aria-activedescendant');
                                routeInput.focus();
                            });
                            option.addEventListener('keydown', (ev) => {
                                if (ev.key === 'Enter') {
                                    ev.preventDefault();
                                    option.click();
                                }
                            });
                        });
                    } else {
                        suggestions.classList.add('hidden');
                        routeInput.setAttribute('aria-expanded', 'false');
                        routeInput.removeAttribute('aria-activedescendant');
                    }
                } catch (error) {
                    console.warn('Route suggestions failed:', error);
                    suggestions.classList.add('hidden');
                    routeInput.setAttribute('aria-expanded', 'false');
                    routeInput.removeAttribute('aria-activedescendant');
                }
            }, 300));
            document.addEventListener('click', (e) => {
                if (!e.target.closest('#route') && !e.target.closest('#route-suggestions')) {
                    suggestions.classList.add('hidden');
                    routeInput.setAttribute('aria-expanded', 'false');
                    routeInput.removeAttribute('aria-activedescendant');
                }
            });
            routeInput.addEventListener('keydown', (e) => {
                if (e.key === 'Escape') {
                    suggestions.classList.add('hidden');
                    routeInput.setAttribute('aria-expanded', 'false');
                    routeInput.removeAttribute('aria-activedescendant');
                    routeInput.focus();
                }
                const suggestionsList = suggestions.querySelectorAll('.route-suggestion');
                const activeId = routeInput.getAttribute('aria-activedescendant');
                const activeOption = activeId ? document.getElementById(activeId) : null;
                let nextIndex;

                if (e.key === 'ArrowDown' && suggestionsList.length > 0) {
                    e.preventDefault();
                    const currentIndex = activeOption ? Array.from(suggestionsList).indexOf(activeOption) : -1;
                    nextIndex = Math.min(suggestionsList.length - 1, currentIndex + 1);
                    suggestionsList[nextIndex]?.focus();
                    routeInput.setAttribute('aria-activedescendant', suggestionsList[nextIndex]?.id || '');
                } else if (e.key === 'ArrowUp' && suggestionsList.length > 0) {
                    e.preventDefault();
                    const currentIndex = activeOption ? Array.from(suggestionsList).indexOf(activeOption) : suggestionsList.length;
                    nextIndex = Math.max(0, currentIndex - 1);
                    suggestionsList[nextIndex]?.focus();
                    routeInput.setAttribute('aria-activedescendant', suggestionsList[nextIndex]?.id || '');
                } else if (e.key === 'Enter' && activeOption) {
                    e.preventDefault();
                    activeOption.click();
                }
            });
            suggestions.addEventListener('keydown', (e) => {
                const suggestionsList = suggestions.querySelectorAll('.route-suggestion');
                const current = document.activeElement;
                const currentIndex = Array.from(suggestionsList).indexOf(current);
                if (e.key === 'ArrowDown') {
                    e.preventDefault();
                    const nextIndex = (currentIndex + 1) % suggestionsList.length;
                    suggestionsList[nextIndex].focus();
                    routeInput.setAttribute('aria-activedescendant', suggestionsList[nextIndex].id);
                } else if (e.key === 'ArrowUp') {
                    e.preventDefault();
                    const prevIndex = (currentIndex - 1 + suggestionsList.length) % suggestionsList.length;
                    suggestionsList[prevIndex].focus();
                    routeInput.setAttribute('aria-activedescendant', suggestionsList[prevIndex].id);
                } else if (e.key === 'Enter' && current && current.classList.contains('route-suggestion')) {
                    e.preventDefault();
                    current.click();
                } else if (e.key === 'Escape') {
                    suggestions.classList.add('hidden');
                    routeInput.setAttribute('aria-expanded', 'false');
                    routeInput.removeAttribute('aria-activedescendant');
                    routeInput.focus();
                }
            });
        }
        validate() {
            const route = document.getElementById('route')?.value.trim();
            const date = document.getElementById('departure-date')?.value;
            const passengers = document.getElementById('passengers')?.value;
            const today = new Date().toISOString().split('T')[0];
            return route && date && date >= today && passengers && passengers !== '0';
        }
        updateState() {
            const isValid = this.validate();
            const submitBtn = this.form.querySelector('button[type="submit"]');
            const feedback = document.getElementById('form-feedback');
            if (submitBtn) {
                submitBtn.disabled = !isValid;
                submitBtn.classList.toggle('opacity-50', !isValid);
                submitBtn.classList.toggle('cursor-not-allowed', !isValid);
            }
            if (feedback) {
                const theme = document.documentElement.getAttribute('data-theme') || 'light';
                feedback.classList.toggle('hidden', isValid);
                if (isValid) {
                    feedback.innerHTML = '<i class="fas fa-check-circle mr-1"></i>Ready to search!';
                    feedback.classList.add(theme === 'dark' ? 'text-emerald-400' : 'text-emerald-300');
                    feedback.classList.remove('text-red-300', 'text-red-400');
                } else {
                    feedback.innerHTML = '<i class="fas fa-exclamation-triangle mr-1"></i>Please complete all fields';
                    feedback.classList.add(theme === 'dark' ? 'text-red-400' : 'text-red-300');
                    feedback.classList.remove('text-emerald-300', 'text-emerald-400');
                }
            }
        }
        populateForm() {
            try {
                const formData = Utils.safeParseJSON('form-data', {});
                const urlParams = new URLSearchParams(window.location.search);
                const routeInput = document.getElementById('route');
                const routeValue = formData.route || urlParams.get('route') || '';
                if (routeInput && routeValue) {
                    routeInput.value = routeValue;
                    routeInput.dispatchEvent(new Event('input', { bubbles: true }));
                }
                const dateInput = document.getElementById('departure-date');
                const today = new Date().toISOString().split('T')[0];
                const dateValue = formData.date || urlParams.get('date') || today;
                if (dateInput && dateValue >= today) dateInput.value = dateValue;
                const passengerSelect = document.getElementById('passengers');
                const passengerValue = formData.passengers || urlParams.get('passengers') || '1';
                if (passengerSelect && passengerValue) {
                    const option = passengerSelect.querySelector(`[value="${passengerValue}"]`);
                    if (option) passengerSelect.value = passengerValue;
                }
                this.updateState();
            } catch (error) {
                logger.warn('Form population failed:', error);
            }
        }
        setupQuickSearch() {
            document.querySelectorAll('.quick-route, .destination-cta, [data-quick-search]').forEach(link => {
                link.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    const portName = link.dataset.toPort || link.dataset.quickSearch || link.textContent.toLowerCase().replace(/[^a-z0-9]/g, '-').split('-')[0];
                    this.quickSearch(portName);
                });
            });
        }
        quickSearch(portName) {
            if (!portName) return false;
            const routeInput = document.getElementById('route');
            const form = document.getElementById('search-form');
            if (!routeInput || !form) return false;
            routeInput.value = `${portName}-to-destination`;
            const routeIdInput = document.getElementById('route-id');
            if (routeIdInput) routeIdInput.value = '';
            routeInput.dispatchEvent(new Event('input', { bubbles: true }));
            form.scrollIntoView({ behavior: 'smooth', block: 'center' });
            setTimeout(() => { routeInput.focus(); routeInput.select(); }, 300);
            FijiFerry.notificationManager?.show(
                `Searching routes from ${portName.replace(/-/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}`,
                'info', 2500
            );
            return true;
        }
        destroy() {
            this.isInitialized = false;
        }
    };

// FILTER MANAGER – refined with auto‑apply + live updates
    class FilterManager {
        constructor() {
            this.isInitialized = false;
            this.isLoadingMore = false;
            this.currentFilterKey = null;
            this.currentOffset = 0;
            this.hasServerContent = false;
            this.init();
        }

        init() {
            if (this.isInitialized) return;
            this.isInitialized = true;
            logger.log('FilterManager initialised');
            this.setupControls();
            this.setupThemeListener();
            this.setupFilterSidebar();
            // Auto‑apply filters on page load if any inputs have values
            this.autoApplyOnLoad();
        }

        autoApplyOnLoad() {
            // Check if any filter input has a non‑default value
            const priceMin = document.getElementById('price-min')?.value;
            const priceMax = document.getElementById('price-max')?.value;
            const durationMax = document.getElementById('duration-max')?.value;
            const statuses = document.querySelectorAll('input[name="status-filter"]:checked');
            const hasFilters = priceMin || priceMax || (durationMax && durationMax !== '0') || statuses.length < 3;

            if (hasFilters) {
                // Small delay to ensure DOM is ready
                setTimeout(() => {
                    this.applyClientSideFilters();
                    this.updateAppliedBadge();
                }, 100);
            }
        }

        setupThemeListener() {
            const observer = new MutationObserver(() => this.updateTheme());
            observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
        }

        updateTheme() {
            const theme = document.documentElement.getAttribute('data-theme') || 'light';
            const filters = document.querySelector('.schedule-filters');
            if (filters) {
                filters.style.background = theme === 'dark' ? 'rgba(30, 41, 59, 0.8)' : 'rgba(255, 255, 255, 0.8)';
                filters.style.backdropFilter = 'blur(10px)';
                filters.style.borderColor = theme === 'dark' ? '#475569' : '#E5E7EB';
            }
            const sortSelect = document.getElementById('sort-by');
            if (sortSelect) {
                sortSelect.style.background = theme === 'dark' ? 'rgb(30, 41, 59)' : 'white';
                sortSelect.style.borderColor = theme === 'dark' ? '#475569' : '#D1D5DB';
                sortSelect.style.color = Utils.getThemeColor('text');
            }
        }

        setupControls() {
            // View All button
            const viewAllBtn = document.getElementById('view-all-btn');
            if (viewAllBtn) {
                viewAllBtn.addEventListener('click', (e) => {
                    e.preventDefault();
                    this.clearFilterInputs();
                    this.reloadFromAPI();
                    FijiFerry.notificationManager?.show('Showing all available schedules', 'success', 2000);
                });
            }

            // Global reset function
            window.resetSearch = () => {
                const form = document.getElementById('search-form');
                if (form) {
                    form.reset();
                    const dateInput = document.getElementById('departure-date');
                    const today = new Date().toISOString().split('T')[0];
                    if (dateInput) {
                        dateInput.value = today;
                        dateInput.min = today;
                    }
                    const routeIdInput = document.getElementById('route-id');
                    if (routeIdInput) routeIdInput.value = '';
                }
                this.clearFilterInputs();
                this.reloadFromAPI();
                FijiFerry.notificationManager?.show('Search reset! Ready to discover new routes.', 'info', 3000);
            };

            // Ctrl+R shortcut
            document.addEventListener('keydown', (e) => {
                if ((e.ctrlKey || e.metaKey) && e.key === 'r') {
                    e.preventDefault();
                    window.resetSearch();
                }
            });

            // Load More button
            const loadMoreBtn = document.getElementById('load-more-schedules');
            if (loadMoreBtn) {
                loadMoreBtn.addEventListener('click', (e) => {
                    e.preventDefault();
                    this.loadMoreSchedules();
                });
            }

            // Infinite scroll
            window.addEventListener('scroll', Utils.throttle(() => {
                if (this.isNearBottom() && loadMoreBtn && !this.isLoadingMore && !loadMoreBtn.disabled) {
                    this.loadMoreSchedules();
                }
            }, 250));
        }

        clearFilterInputs() {
            const priceMin = document.getElementById('price-min');
            const priceMax = document.getElementById('price-max');
            const durationMax = document.getElementById('duration-max');
            if (priceMin) priceMin.value = '';
            if (priceMax) priceMax.value = '';
            if (durationMax) durationMax.value = '0';
            document.querySelectorAll('input[name="status-filter"]').forEach(i => {
                i.checked = true;
            });
        }

        setupFilterSidebar() {
            const priceMin = document.getElementById('price-min');
            const priceMax = document.getElementById('price-max');
            const durationMax = document.getElementById('duration-max');
            const statusInputs = Array.from(document.querySelectorAll('input[name="status-filter"]'));
            const applyBtn = document.getElementById('apply-filters');
            const resetBtn = document.getElementById('reset-filters');

            // ─── LIVE FILTERING: apply on every input change ───
            const liveFilter = () => {
                this.applyClientSideFilters();
                this.updateAppliedBadge();
                this.updateNoResultsMessage();
            };

            const debouncedLiveFilter = Utils.debounce(liveFilter, 250);

            if (priceMin) priceMin.addEventListener('input', debouncedLiveFilter);
            if (priceMax) priceMax.addEventListener('input', debouncedLiveFilter);
            if (durationMax) durationMax.addEventListener('change', liveFilter);
            statusInputs.forEach(input => input.addEventListener('change', liveFilter));

            // ─── Apply button (kept for clarity, but now redundant) ───
            if (applyBtn) {
                applyBtn.addEventListener('click', () => {
                    liveFilter();
                    const visibleCount = document.querySelectorAll('.schedule-card:not([style*="display: none"])').length;
                    FijiFerry.notificationManager?.show(
                        `${visibleCount} schedule${visibleCount !== 1 ? 's' : ''} match your filters`,
                        'info', 2000
                    );
                });
            }

            // ─── Reset button ───
            if (resetBtn) {
                resetBtn.addEventListener('click', () => {
                    this.clearFilterInputs();
                    this.showAllCards();
                    this.updateAppliedBadge();
                    this.updateFilterStatus('Showing all schedules');
                    this.hideNoResultsMessage();
                    FijiFerry.notificationManager?.show('Filters cleared', 'info', 2000);
                });
            }

            // ─── Sort dropdown ───
            const sortSelect = document.getElementById('sort-by');
            if (sortSelect) {
                sortSelect.addEventListener('change', () => {
                    this.sortVisibleCards(sortSelect.value);
                });
            }

            // ─── Detect server‑rendered content ───
            const list = document.getElementById('schedule-list');
            if (list) {
                const serverCards = list.querySelectorAll('.schedule-card');
                this.hasServerContent = serverCards.length > 0;
                logger.log(`Found ${serverCards.length} server‑rendered schedule cards`);
            }

            // ─── Enrich cards with data attributes ───
            this.enrichServerCards();

            // ─── Initial UI state ───
            this.updateAppliedBadge();
            this.updateFilterStatus(
                this.hasServerContent
                    ? `Showing ${document.querySelectorAll('.schedule-card').length} schedules`
                    : 'No schedules loaded'
            );
            this.hideNoResultsMessage();
        }

        /**
         * Ensure every card has the data‑attributes needed for filtering.
         */
        enrichServerCards() {
            document.querySelectorAll('.schedule-card').forEach(card => {
                if (!card.hasAttribute('data-price')) {
                    const priceEl = card.querySelector('.price');
                    const priceText = priceEl ? priceEl.textContent : '';
                    const priceNum = parseFloat(priceText.replace(/[^0-9.]/g, '')) || 0;
                    card.setAttribute('data-price', priceNum);
                }
                if (!card.hasAttribute('data-duration')) {
                    const durationEl = card.querySelector('.duration dd');
                    const durationText = durationEl ? durationEl.textContent : '0';
                    const hours = parseFloat(durationText) || 0;
                    card.setAttribute('data-duration', Math.round(hours * 3600));
                }
                if (!card.hasAttribute('data-status')) {
                    const statusEl = card.querySelector('.status-badge');
                    const statusText = statusEl ? statusEl.textContent.trim().toLowerCase() : 'scheduled';
                    card.setAttribute('data-status', statusText);
                }
                if (!card.hasAttribute('data-time-slot')) {
                    const timeEl = card.querySelector('.departure-time');
                    if (timeEl && timeEl.getAttribute('datetime')) {
                        const d = new Date(timeEl.getAttribute('datetime'));
                        card.setAttribute('data-time-slot', d.getHours());
                    } else {
                        card.setAttribute('data-time-slot', '0');
                    }
                }
            });
        }

        /**
         * Core filter function: hides/shows cards based on sidebar values.
         * Returns the number of visible cards.
         */
        applyClientSideFilters() {
            const priceMin = parseFloat(document.getElementById('price-min')?.value) || 0;
            const priceMax = parseFloat(document.getElementById('price-max')?.value) || Infinity;
            const durationMax = parseFloat(document.getElementById('duration-max')?.value) || 0; // 0 = any
            const checkedStatuses = Array.from(
                document.querySelectorAll('input[name="status-filter"]:checked')
            ).map(el => el.value);

            let visibleCount = 0;
            let totalCount = 0;

            document.querySelectorAll('.schedule-card').forEach(card => {
                totalCount++;
                const cardPrice = parseFloat(card.getAttribute('data-price')) || 0;
                const cardDuration = parseFloat(card.getAttribute('data-duration')) || 0; // seconds
                const cardStatus = (card.getAttribute('data-status') || 'scheduled').toLowerCase();

                let show = true;

                // Price filter
                if (cardPrice < priceMin || cardPrice > priceMax) show = false;

                // Duration filter (0 = any)
                if (durationMax > 0) {
                    const durationHours = cardDuration / 3600;
                    if (durationHours > durationMax) show = false;
                }

                // Status filter
                if (checkedStatuses.length > 0 && !checkedStatuses.includes(cardStatus)) show = false;

                card.style.display = show ? '' : 'none';
                if (show) visibleCount++;
            });

            this.updateFilterStatus(`Showing ${visibleCount} of ${totalCount} schedules`);
            return visibleCount;
        }

        /**
         * Show a "no results" message if 0 cards are visible.
         */
        updateNoResultsMessage() {
            const visible = document.querySelectorAll('.schedule-card:not([style*="display: none"])').length;
            let noResultsEl = document.getElementById('no-results-message');

            if (visible === 0) {
                if (!noResultsEl) {
                    const list = document.getElementById('schedule-list');
                    if (list) {
                        noResultsEl = document.createElement('li');
                        noResultsEl.id = 'no-results-message';
                        noResultsEl.className = 'col-span-full text-center py-12';
                        noResultsEl.innerHTML = `
                            <div class="empty-state">
                                <i class="fas fa-search text-5xl text-gray-300 mb-4" aria-hidden="true"></i>
                                <h4 class="text-xl font-semibold text-gray-700 mb-2">No schedules match your filters</h4>
                                <p class="text-gray-500 text-sm">Try adjusting your price, duration, or status filters.</p>
                                <button onclick="document.getElementById('reset-filters')?.click()"
                                        class="mt-4 bg-gray-100 hover:bg-gray-200 text-gray-700 px-4 py-2 rounded-lg text-sm font-medium transition-all">
                                    Clear filters
                                </button>
                            </div>
                        `;
                        list.appendChild(noResultsEl);
                    }
                } else {
                    noResultsEl.style.display = '';
                }
            } else {
                if (noResultsEl) noResultsEl.style.display = 'none';
            }
        }

        hideNoResultsMessage() {
            const el = document.getElementById('no-results-message');
            if (el) el.style.display = 'none';
        }

        showAllCards() {
            document.querySelectorAll('.schedule-card').forEach(card => {
                card.style.display = '';
            });
            this.hideNoResultsMessage();
        }

        sortVisibleCards(sortBy) {
            const list = document.getElementById('schedule-list');
            if (!list) return;

            const cards = Array.from(list.querySelectorAll('.schedule-card:not([style*="display: none"])'));
            if (cards.length === 0) return;

            cards.sort((a, b) => {
                switch (sortBy) {
                    case 'price': {
                        const pa = parseFloat(a.getAttribute('data-price')) || 0;
                        const pb = parseFloat(b.getAttribute('data-price')) || 0;
                        return pa - pb;
                    }
                    case 'duration': {
                        const da = parseFloat(a.getAttribute('data-duration')) || 0;
                        const db = parseFloat(b.getAttribute('data-duration')) || 0;
                        return da - db;
                    }
                    case 'time':
                    default: {
                        const ta = parseInt(a.getAttribute('data-time-slot')) || 0;
                        const tb = parseInt(b.getAttribute('data-time-slot')) || 0;
                        return ta - tb;
                    }
                }
            });

            // Re‑append in sorted order
            cards.forEach(card => list.appendChild(card));
            logger.log(`Sorted ${cards.length} cards by ${sortBy}`);
        }

        updateAppliedBadge() {
            const badge = document.getElementById('filter-applied-badge');
            if (!badge) return;

            const route = document.getElementById('route')?.value.trim() || 'all';
            const date = document.getElementById('departure-date')?.value || 'all';
            const priceMin = document.getElementById('price-min')?.value || '';
            const priceMax = document.getElementById('price-max')?.value || '';
            const durationMax = document.getElementById('duration-max')?.value || 'any';
            const statuses = Array.from(
                document.querySelectorAll('input[name="status-filter"]:checked')
            ).map(el => el.value).sort();
            const statusText = statuses.length > 0 ? statuses.join(',') : 'all';

            let parts = [`route: ${route}`, `date: ${date}`];
            if (priceMin) parts.push(`price ≥ ${priceMin}`);
            if (priceMax) parts.push(`price ≤ ${priceMax}`);
            if (durationMax !== '0') parts.push(`≤ ${durationMax}h`);
            parts.push(`status: ${statusText}`);

            badge.textContent = `Applied: ${parts.join(' • ')}`;
        }

        updateFilterStatus(message) {
            const el = document.getElementById('filter-status');
            if (el) el.textContent = message;
        }

        isNearBottom() {
            return window.innerHeight + window.scrollY >= document.body.offsetHeight - 150;
        }

        updateProgress(total) {
            const container = document.getElementById('schedule-progress-container');
            const bar = document.getElementById('schedule-progress');
            const list = document.getElementById('schedule-list');
            if (!container || !bar || !list) return;

            const current = list.querySelectorAll('.schedule-card').length;
            const totalInt = total ?? parseInt(list.getAttribute('data-total') || '0', 10);

            if (!totalInt) {
                container.classList.add('hidden');
                return;
            }

            const percent = Math.min(100, Math.round((current / totalInt) * 100));
            bar.style.width = `${percent}%`;
            container.classList.remove('hidden');

            if (percent >= 100) {
                setTimeout(() => container.classList.add('hidden'), 400);
            }
        }

        // ─── API‑based loading (preserved from original) ───

        reloadFromAPI() {
            const list = document.getElementById('schedule-list');
            const button = document.getElementById('load-more-schedules');

            if (list) list.innerHTML = '';
            if (button) {
                button.style.display = '';
                button.disabled = false;
                button.setAttribute('data-remaining', '1');
            }

            this.hasServerContent = false;
            this.currentFilterKey = this.getCurrentFilterContext();
            this.currentOffset = 0;
            this.isLoadingMore = false;

            this.loadMoreSchedules();
        }

        getCurrentFilterContext() {
            const route = document.getElementById('route')?.value.trim() || '';
            const routeId = document.getElementById('route-id')?.value.trim() || '';
            const date = document.getElementById('departure-date')?.value || '';
            const priceMin = document.getElementById('price-min')?.value || '';
            const priceMax = document.getElementById('price-max')?.value || '';
            const durationMax = document.getElementById('duration-max')?.value || '0';
            const statuses = Array.from(
                document.querySelectorAll('input[name="status-filter"]:checked')
            ).map(el => el.value).sort();

            return JSON.stringify({
                route, route_id: routeId, date, priceMin, priceMax, durationMax, status: statuses
            });
        }

        async loadMoreSchedules() {
            if (this.isLoadingMore) return;

            const list = document.getElementById('schedule-list');
            const button = document.getElementById('load-more-schedules');
            if (!list || !button) return;

            const remaining = parseInt(button.getAttribute('data-remaining') || '0', 10);
            const offset = list.querySelectorAll('.schedule-card').length;

            if (offset > 0 && remaining <= 0) {
                button.classList.add('hidden');
                return;
            }

            this.isLoadingMore = true;
            button.disabled = true;
            const origHTML = button.innerHTML;
            button.innerHTML = `<span class="loading-spinner w-4 h-4 border-2 border-gray-300 border-t-blue-500 rounded-full animate-spin inline-block" aria-hidden="true"></span><span class="ml-2">Loading...</span>`;

            // Show progress
            const progressContainer = document.getElementById('schedule-progress-container');
            const progressBar = document.getElementById('schedule-progress');
            if (progressContainer && progressBar) {
                progressContainer.classList.remove('hidden');
                progressBar.style.width = '0%';
            }

            // Build params
            const params = new URLSearchParams({ offset, limit: 6 });
            const routeVal = document.getElementById('route')?.value.trim();
            const routeIdVal = document.getElementById('route-id')?.value.trim();
            const dateVal = document.getElementById('departure-date')?.value;
            const durationVal = document.getElementById('duration-max')?.value;
            const priceMinVal = document.getElementById('price-min')?.value;
            const priceMaxVal = document.getElementById('price-max')?.value;
            const statuses = Array.from(
                document.querySelectorAll('input[name="status-filter"]:checked')
            ).map(i => i.value);

            if (routeVal) params.set('route', routeVal);
            if (routeIdVal) params.set('route_id', routeIdVal);
            if (dateVal) params.set('date', dateVal);
            if (durationVal && durationVal !== '0') params.set('duration_max', durationVal);
            if (priceMinVal) params.set('price_min', priceMinVal);
            if (priceMaxVal) params.set('price_max', priceMaxVal);
            if (statuses.length > 0) params.set('status', statuses.join(','));

            const url = `/bookings/api/paged_bookings/?${params.toString()}`;
            logger.log('loadMoreSchedules URL:', url);

            try {
                const { data, error } = await Utils.useFetch(url);
                if (error) throw error;

                const schedules = data?.schedules || [];
                const total = data?.total ?? 0;

                if (schedules.length === 0 && offset === 0) {
                    list.innerHTML = this.renderEmptyState();
                    button.style.display = 'none';
                    this.updateFilterStatus('No matching schedules found');
                    return;
                }

                schedules.forEach(schedule => {
                    const html = this.renderScheduleCard(schedule);
                    list.insertAdjacentHTML('beforeend', html);
                });

                const newRemaining = data.remaining ?? Math.max(0, total - offset - schedules.length);
                button.setAttribute('data-remaining', String(newRemaining));

                if (newRemaining <= 0 || schedules.length < 6) {
                    button.style.display = 'none';
                }

                this.updateProgress(total);
                this.updateFilterStatus(`Showing ${list.querySelectorAll('.schedule-card').length} of ${total} schedules`);
                this.enrichServerCards(); // Ensure new cards have data attrs

                // Re‑apply filters to newly loaded cards
                this.applyClientSideFilters();

                logger.log(`Loaded ${schedules.length} schedules (remaining: ${newRemaining})`);
            } catch (error) {
                logger.error('loadMoreSchedules failed:', error);
                if (list.querySelectorAll('.schedule-card').length === 0) {
                    list.innerHTML = this.renderErrorState(error.message);
                }
                FijiFerry.notificationManager?.show('Could not load schedules. Please try again.', 'error', 3000);
            } finally {
                this.isLoadingMore = false;
                if (button && button.style.display !== 'none') {
                    button.disabled = false;
                    const remaining = button.getAttribute('data-remaining') || '0';
                    button.innerHTML = `<i class="fas fa-plus" aria-hidden="true"></i><span id="load-more-text" style="color:black">Load More Schedules (${remaining} remaining)</span>`;
                }
                if (progressContainer && button?.style.display === 'none') {
                    progressContainer.classList.add('hidden');
                }
            }
        }

        renderEmptyState() { /* ... unchanged ... */ }
        renderErrorState(message) { /* ... unchanged ... */ }
        renderScheduleCard(schedule) { /* ... unchanged ... */ }

        destroy() {
            this.isInitialized = false;
        }
    }

    // MAP MANAGER – ONLY ACTIVE PORTS
    class MapManager {
        constructor() {
            this.map = null;
            this.init();
        }

        async init() {
            const mapContainer = document.getElementById('fiji-map');
            if (!mapContainer) return;

            this.isTouch = window.matchMedia('(hover: none), (pointer: coarse)').matches;

            this.map = L.map('fiji-map', {
                scrollWheelZoom: false,
                dragging: !this.isTouch,
                tap: false,
                zoomControl: false,
            }).setView([-17.7134, 178.0650], 8);

            // ESRI Ocean basemap — deep blue ocean, perfect for a ferry service
            L.tileLayer(
                'https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}',
                { maxZoom: 13, attribution: 'Tiles &copy; Esri &mdash; Sources: GEBCO, NOAA, CHS, OSU, UNH, CSUMB, National Geographic, DeLorme, NAVTEQ, Esri' }
            ).addTo(this.map);

            // Ocean reference overlay (labels on top of the ocean basemap)
            L.tileLayer(
                'https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Reference/MapServer/tile/{z}/{y}/{x}',
                { maxZoom: 13, opacity: 0.7 }
            ).addTo(this.map);

            // Zoom control — bottom right, away from the legend
            L.control.zoom({ position: 'bottomright' }).addTo(this.map);

            this.setupInteractionGate(mapContainer);
            await this.loadPorts();
        }

        createPortIcon(name) {
            const boatSvg = `<svg viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">
                <path d="M3 13h18l-2 6H5L3 13z" fill="white"/>
                <path d="M5 13L7 7h10l2 6" fill="rgba(255,255,255,0.6)"/>
                <rect x="11" y="3" width="2" height="5" fill="white"/>
                <path d="M11 3 L7 8 L11 8 Z" fill="white"/>
            </svg>`;

            return L.divIcon({
                html: `<div class="port-pin">
                    <div class="port-pin__rings">
                        <div class="port-pin__ring"></div>
                        <div class="port-pin__ring"></div>
                    </div>
                    <div class="port-pin__dot">${boatSvg}</div>
                    <div class="port-pin__label">${name}</div>
                </div>`,
                className: '',
                iconSize: [30, 60],
                iconAnchor: [15, 15],
                popupAnchor: [0, -20],
            });
        }

        // ── Sea-lane waypoints for known Fiji ferry corridors ──────────────────
        // Each key is a canonical sorted pair "A|B" (port names lowercased, sorted).
        // Waypoints trace the actual sea lane: curves around Viti Levu, through
        // Bligh Water, along the Yasawa Chain, across the Koro Sea, etc.
        // No straight lines through land.
        getSeaLaneWaypoints(nameA, nameB) {
            const key = [nameA, nameB]
                .map(n => n.toLowerCase().trim())
                .sort()
                .join('|');

            const lanes = {
                // Suva ↔ Lautoka — overnight ferry, goes SOUTH around Viti Levu
                'lautoka|suva': [
                    [-18.1248, 178.3967],  // Suva
                    [-18.28,   178.22],    // clears Suva Barrier Reef heading SW
                    [-18.50,   177.95],    // south of Beqa Island, open ocean
                    [-18.55,   177.65],    // rounding southwest tip of Viti Levu
                    [-18.35,   177.50],    // Coral Coast heading NW
                    [-18.05,   177.42],    // Viti Levu Bay
                    [-17.6154, 177.4510],  // Lautoka
                ],
                // Suva ↔ Natovi — short hop along northeast coast of Viti Levu
                'natovi|suva': [
                    [-18.1248, 178.3967],
                    [-17.96,   178.46],
                    [-17.80,   178.48],
                    [-17.6590, 178.4850],  // Natovi
                ],
                // Natovi ↔ Nabouwalu — crosses Bligh Water from NE Viti Levu to S Vanua Levu
                'nabouwalu|natovi': [
                    [-17.6590, 178.4850],  // Natovi
                    [-17.46,   178.55],
                    [-17.22,   178.60],
                    [-17.02,   178.66],
                    [-16.9910, 178.6920],  // Nabouwalu
                ],
                // Lautoka ↔ Nabouwalu — northwest coast then cross to Vanua Levu
                'lautoka|nabouwalu': [
                    [-17.6154, 177.4510],  // Lautoka
                    [-17.38,   177.55],    // north past Ba
                    [-17.12,   177.85],    // Bligh Water, heading east
                    [-17.00,   178.20],
                    [-16.9910, 178.6920],  // Nabouwalu
                ],
                // Denarau ↔ Yasawa Islands — north up the Yasawa Chain (Bligh Water)
                'denarau|yasawa islands': [
                    [-17.7725, 177.3805],  // Port Denarau
                    [-17.52,   177.22],    // clear Mamanuca Group heading NNW
                    [-17.18,   177.28],    // entering Yasawa passage
                    [-16.95,   177.35],    // Yasawa Islands
                ],
                // Denarau ↔ Yasawa (alternate name)
                'denarau|yasawa': [
                    [-17.7725, 177.3805],
                    [-17.52,   177.22],
                    [-17.18,   177.28],
                    [-16.95,   177.35],
                ],
                // Denarau / Nadi ↔ Mamanuca Islands
                'denarau|mamanuca islands': [
                    [-17.7725, 177.3805],
                    [-17.70,   177.22],
                    [-17.65,   177.12],
                ],
                // Suva ↔ Savusavu (Vanua Levu) — northeast through Koro Sea
                'savusavu|suva': [
                    [-18.1248, 178.3967],  // Suva
                    [-17.88,   178.62],    // out through Bau Waters
                    [-17.60,   178.82],    // Koro Sea
                    [-17.30,   179.00],
                    [-17.00,   179.18],
                    [-16.78,   179.32],
                    [-16.7763, 179.3413],  // Savusavu
                ],
                // Suva ↔ Levuka (Ovalau Island) — east across Koro Sea
                'levuka|suva': [
                    [-18.1248, 178.3967],
                    [-17.95,   178.58],
                    [-17.78,   178.72],
                    [-17.6798, 178.8370],  // Levuka
                ],
                // Suva ↔ Koro Island
                'koro island|suva': [
                    [-18.1248, 178.3967],
                    [-17.80,   178.75],
                    [-17.55,   179.00],
                    [-17.3165, 179.4170],  // Koro Island
                ],
                // Suva ↔ Taveuni (far northeast)
                'suva|taveuni': [
                    [-18.1248, 178.3967],
                    [-17.70,   178.80],
                    [-17.35,   179.20],
                    [-17.00,   179.60],
                    [-16.80,   179.85],
                    [-16.8000, 179.9700],  // Taveuni
                ],
                // Savusavu ↔ Taveuni (short hop, north Vanua Levu coast)
                'savusavu|taveuni': [
                    [-16.7763, 179.3413],
                    [-16.78,   179.55],
                    [-16.80,   179.78],
                    [-16.8000, 179.9700],
                ],
                // Nabouwalu ↔ Savusavu (east along Vanua Levu south coast)
                'nabouwalu|savusavu': [
                    [-16.9910, 178.6920],
                    [-16.92,   178.90],
                    [-16.85,   179.05],
                    [-16.80,   179.20],
                    [-16.7763, 179.3413],
                ],
                // Lautoka ↔ Suva via south coast (direct booking option)
                'lautoka|suva (south)': [
                    [-17.6154, 177.4510],
                    [-18.05,   177.42],
                    [-18.35,   177.50],
                    [-18.55,   177.65],
                    [-18.50,   177.95],
                    [-18.28,   178.22],
                    [-18.1248, 178.3967],
                ],
            };

            return lanes[key] || null;
        }

        // Fallback: generate a gentle curved arc that bows away from land.
        // We add two intermediate points offset perpendicular to the direct line,
        // biased toward open ocean (south/west in Fiji's case).
        buildCurvedArc(fromLatLng, toLatLng) {
            const [lat1, lng1] = fromLatLng;
            const [lat2, lng2] = toLatLng;
            const midLat = (lat1 + lat2) / 2;
            const midLng = (lng1 + lng2) / 2;

            // Perpendicular offset: rotates the midpoint away from land
            const dLat = lat2 - lat1;
            const dLng = lng2 - lng1;
            const len = Math.sqrt(dLat * dLat + dLng * dLng);
            // Push midpoint 25% of route length to the south (open ocean in Fiji)
            const offsetFactor = 0.25;
            const perpLat = -dLng / len * offsetFactor;
            const perpLng =  dLat / len * offsetFactor;

            const q1Lat = (lat1 + midLat) / 2 + perpLat;
            const q1Lng = (lng1 + midLng) / 2 + perpLng;
            const q3Lat = (midLat + lat2) / 2 + perpLat;
            const q3Lng = (midLng + lng2) / 2 + perpLng;

            // Sample 10 points along a quadratic Bezier through the offset midpoint
            const cx = midLat + perpLat;
            const cy = midLng + perpLng;
            const pts = [];
            for (let t = 0; t <= 1; t += 0.1) {
                const u = 1 - t;
                const lat = u * u * lat1 + 2 * u * t * cx + t * t * lat2;
                const lng = u * u * lng1 + 2 * u * t * cy + t * t * lng2;
                pts.push([lat, lng]);
            }
            return pts;
        }

        createPopupHtml(name, routeCount) {
            const bookUrl = `/bookings/book/?port=${encodeURIComponent(name)}`;
            return `<div class="map-popup">
                <div class="map-popup__name">
                    <span class="popup-dot"></span>${name}
                </div>
                <div class="map-popup__meta">${routeCount} active route${routeCount !== 1 ? 's' : ''} today</div>
                <a href="/bookings/book/" class="map-popup__book">
                    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M5 12h14M12 5l7 7-7 7"/></svg>
                    Book a ferry
                </a>
            </div>`;
        }

        setupInteractionGate(mapContainer) {
            if (!document.getElementById('map-gate-styles')) {
                const style = document.createElement('style');
                style.id = 'map-gate-styles';
                style.textContent = `
                  #fiji-map { position: relative; }
                  .map-interaction-gate {
                    position: absolute; inset: 0; z-index: 1000;
                    display: flex; align-items: center; justify-content: center;
                    background: rgba(10,22,40,0.22); cursor: pointer;
                    transition: opacity .25s ease; text-align: center; padding: 1rem;
                  }
                  .map-interaction-gate.is-hidden { opacity: 0; pointer-events: none; }
                  .map-gate-inner {
                    display: inline-flex; align-items: center; gap: .6rem;
                    background: rgba(15,23,42,.88); color: #f0f9ff;
                    padding: .75rem 1.25rem; border-radius: 999px; font-weight: 700;
                    font-size: .9rem; box-shadow: 0 8px 28px rgba(0,0,0,.35);
                    border: 1px solid rgba(16,185,129,.35); max-width: 90%;
                    backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);
                  }
                  .map-gate-icon { font-size: 1.1rem; }
                `;
                document.head.appendChild(style);
            }

            const overlay = document.createElement('div');
            overlay.className = 'map-interaction-gate';
            overlay.setAttribute('role', 'button');
            overlay.setAttribute('tabindex', '0');
            overlay.setAttribute('aria-label', 'Activate map interaction');
            overlay.innerHTML = `<span class="map-gate-inner">
                <span class="map-gate-icon">🗺️</span>
                <span>${this.isTouch ? 'Tap to explore the map' : 'Click to interact · scroll to zoom'}</span>
            </span>`;
            mapContainer.appendChild(overlay);

            const enable = () => {
                this.map.scrollWheelZoom.enable();
                if (this.isTouch) this.map.dragging.enable();
                overlay.classList.add('is-hidden');
            };
            const disable = () => {
                this.map.scrollWheelZoom.disable();
                if (this.isTouch) this.map.dragging.disable();
                overlay.classList.remove('is-hidden');
            };

            overlay.addEventListener('click', enable);
            overlay.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); enable(); }
            });

            if (this.isTouch) {
                document.addEventListener('touchstart', (e) => {
                    if (!mapContainer.contains(e.target)) disable();
                }, { passive: true });
            } else {
                mapContainer.addEventListener('mouseleave', disable);
            }
        }

        async loadPorts() {
            try {
                const response = await fetch('/bookings/api/routes/');
                if (!response.ok) throw new Error('Routes fetch failed');
                const { routes } = await response.json();

                // Collect active port coordinates from rendered schedule cards
                const activeRouteIds = new Set();
                document.querySelectorAll('.schedule-card[data-route-id]').forEach(card => {
                    const rid = (card.dataset.routeId || '').trim();
                    if (rid) activeRouteIds.add(rid);
                });

                const coord = (p) => {
                    const lat = parseFloat(p.lat), lng = parseFloat(p.lng);
                    return (isNaN(lat) || isNaN(lng)) ? null : [lat, lng];
                };

                // Map: port name → { latlng, routeCount }
                const activePorts = new Map();
                const drawnRoutes = new Set();   // "A|B" keys to avoid duplicates

                routes.forEach(route => {
                    if (!activeRouteIds.has(String(route.id))) return;
                    [route.departure_port, route.destination_port].forEach(port => {
                        if (!port) return;
                        const c = coord(port);
                        if (!c) return;
                        const existing = activePorts.get(port.name);
                        if (existing) { existing.routeCount++; }
                        else { activePorts.set(port.name, { latlng: c, routeCount: 1 }); }
                    });

                    // Draw sea-lane route between the two ports
                    const dep = route.departure_port, dst = route.destination_port;
                    if (!dep || !dst) return;
                    const cDep = coord(dep), cDst = coord(dst);
                    if (!cDep || !cDst) return;

                    const routeKey = [dep.name, dst.name].map(n => n.toLowerCase().trim()).sort().join('|');
                    if (drawnRoutes.has(routeKey)) return;
                    drawnRoutes.add(routeKey);

                    const waypoints = this.getSeaLaneWaypoints(dep.name, dst.name)
                        || this.buildCurvedArc(cDep, cDst);

                    // Outer glow line
                    L.polyline(waypoints, {
                        color: '#10b981', weight: 6, opacity: 0.12,
                        className: 'route-glow',
                    }).addTo(this.map);

                    // Animated dashed route line
                    L.polyline(waypoints, {
                        color: '#10b981', weight: 2.5, opacity: 0.85,
                        dashArray: '10 7',
                        className: 'route-animated',
                    }).addTo(this.map);
                });

                const bounds = [];
                activePorts.forEach(({ latlng, routeCount }, name) => {
                    L.marker(latlng, { icon: this.createPortIcon(name) })
                        .addTo(this.map)
                        .bindPopup(this.createPopupHtml(name, routeCount), {
                            maxWidth: 220, className: 'map-popup-wrap',
                        });
                    bounds.push(latlng);
                });

                // Update "Active ports" stat counter
                const portsEl = document.getElementById('active-ports-count');
                if (portsEl) {
                    portsEl.setAttribute('data-count', activePorts.size);
                    portsEl.textContent = activePorts.size;
                }

                if (bounds.length) {
                    this.map.fitBounds(bounds, { padding: [60, 60], maxZoom: 9 });
                } else {
                    this.map.setView([-17.7134, 178.0650], 8);
                }

                logger.log(`Map loaded – ${activePorts.size} active port(s)`);
            } catch (error) {
                logger.warn('Failed to load ports from API:', error);
                this.addHardcodedPorts();
            }
        }

        addHardcodedPorts() {
            const ports = [
                { name: 'Denarau',    lat: -17.7725, lng: 177.3805 },
                { name: 'Suva',       lat: -18.1248, lng: 178.3967 },
                { name: 'Lautoka',    lat: -17.6154, lng: 177.4510 },
                { name: 'Natovi',     lat: -17.6590, lng: 178.4850 },
                { name: 'Nabouwalu',  lat: -16.9910, lng: 178.6920 },
                { name: 'Savusavu',   lat: -16.7763, lng: 179.3413 },
                { name: 'Yasawa Islands', lat: -16.95, lng: 177.35 },
            ];
            const routePairs = [
                ['Suva', 'Lautoka'],
                ['Suva', 'Natovi'],
                ['Natovi', 'Nabouwalu'],
                ['Denarau', 'Yasawa Islands'],
                ['Suva', 'Savusavu'],
            ];
            const portMap = Object.fromEntries(ports.map(p => [p.name, [p.lat, p.lng]]));
            const bounds = [];

            routePairs.forEach(([a, b]) => {
                const cA = portMap[a], cB = portMap[b];
                if (!cA || !cB) return;
                const waypoints = this.getSeaLaneWaypoints(a, b) || this.buildCurvedArc(cA, cB);
                L.polyline(waypoints, { color: '#10b981', weight: 6, opacity: 0.12, className: 'route-glow' }).addTo(this.map);
                L.polyline(waypoints, { color: '#10b981', weight: 2.5, opacity: 0.85, dashArray: '10 7', className: 'route-animated' }).addTo(this.map);
            });

            ports.forEach(port => {
                L.marker([port.lat, port.lng], { icon: this.createPortIcon(port.name) })
                    .addTo(this.map)
                    .bindPopup(this.createPopupHtml(port.name, 1), { maxWidth: 220 });
                bounds.push([port.lat, port.lng]);
            });
            if (bounds.length) this.map.fitBounds(bounds, { padding: [60, 60], maxZoom: 9 });
        }
    };

// === SCHEDULE MANAGER – PER-SCHEDULE DB POLLING ===
    class ScheduleManager {
        constructor() {
            this.init();
        }

        init() {
            logger.log('ScheduleManager initialized');
            // Paint server-rendered weather immediately so the strips are never
            // blank, then refresh live from the DB/API.
            this.renderInitialWeather();
            this.updateWeatherDisplay();
            // Live, real-time refresh of seats/status + weather, like the admin
            // dashboard. Lightweight polling against read-only endpoints.
            this.startLiveUpdates();
        }

        startLiveUpdates() {
            const SCHEDULE_MS = 45000;
            const WEATHER_MS = (FijiFerry.config && FijiFerry.config.weatherUpdateInterval) || 120000;

            this.pollScheduleUpdates();
            this._scheduleTimer = setInterval(() => this.pollScheduleUpdates(), SCHEDULE_MS);
            this._weatherTimer = setInterval(() => this.updateWeatherDisplay(), WEATHER_MS);

            // Refresh as soon as the tab regains focus.
            document.addEventListener('visibilitychange', () => {
                if (!document.hidden) { this.pollScheduleUpdates(); this.updateWeatherDisplay(); }
            });
        }

        async pollScheduleUpdates() {
            try {
                const res = await fetch('/bookings/api/bookings/updates/?limit=50', {
                    headers: { 'X-Requested-With': 'XMLHttpRequest' }
                });
                if (!res.ok) return;
                const data = await res.json();
                const live = {};
                (data.schedules || []).forEach(s => { live[String(s.id)] = s; });

                document.querySelectorAll('.schedule-card[data-schedule-id]').forEach(card => {
                    const id = String(card.dataset.scheduleId);
                    const info = live[id];
                    const seatsEl = card.querySelector('.seats-count');

                    if (!info) {
                        // Disappeared from the active feed → sold out / cancelled / departed.
                        if (card.dataset.status !== 'unavailable') {
                            card.dataset.status = 'unavailable';
                            card.classList.add('is-unavailable');
                            if (seatsEl) seatsEl.textContent = '0';
                            const route = card.querySelector('.bp-port-name')?.textContent?.trim();
                            if (window.Toast) window.Toast.info(
                                `A departure${route ? ' from ' + route : ''} is no longer available.`);
                        }
                        return;
                    }

                    // Update seat count live; toast when a sailing gets tight.
                    if (seatsEl) {
                        const prev = parseInt(seatsEl.textContent, 10);
                        if (!Number.isNaN(prev) && info.available_seats !== prev) {
                            seatsEl.textContent = info.available_seats;
                            if (info.available_seats > 0 && info.available_seats <= 5 && prev > 5 && window.Toast) {
                                window.Toast.warning(`Only ${info.available_seats} seats left on a ${info.route} sailing!`);
                            }
                        }
                    }
                    if (info.status && card.dataset.status !== info.status) {
                        card.dataset.status = info.status;
                    }
                });
                logger.log('Schedule cards refreshed from live feed');
            } catch (e) {
                logger.warn('Live schedule poll failed:', e);
            }
        }

        // Populate each schedule card's weather strip from the data the server
        // already embedded (schedule-weather-data), before any network call.
        renderInitialWeather() {
            const list = Utils.safeParseJSON('schedule-weather-data', []);
            if (!Array.isArray(list)) return;
            list.forEach(w => {
                const id = w.schedule_id;
                if (id == null) return;
                this.paintCard(id, {
                    condition: w.condition,
                    temperature: w.temperature,
                    wind_speed: w.wind_speed,
                    precipitation_probability: w.precipitation_probability,
                });
            });
        }

        // Shared painter so initial + live + fallback all render identically.
        paintCard(id, data) {
            data = data || {};
            ['condition', 'icon', 'temp', 'wind', 'precip'].forEach(field => {
                const el = document.getElementById(`weather-${field}-${id}`);
                if (!el) return;
                const value =
                    field === 'icon' ? Utils.getWeatherIcon(data.condition) :
                    field === 'temp' ? `${Math.round(data.temperature ?? data.temp ?? 28)}°C` :
                    field === 'wind' ? `${Math.round(data.wind_speed ?? data.wind ?? 12)} kph` :
                    field === 'precip' ? `${Math.round(data.precipitation_probability ?? data.precip ?? 5)}%` :
                    data.condition || 'Sunny';
                if (field === 'icon') el.innerHTML = value; else el.textContent = value;
            });
        }

        async updateWeatherDisplay() {
            try {
                const scheduleCards = Array.from(document.querySelectorAll('.schedule-card'));
                if (scheduleCards.length === 0) return;

                // === Update each schedule card individually ===
                for (const card of scheduleCards) {
                    const id = card.dataset.scheduleId;
                    if (!id) continue;

                    // Fetch weather for this schedule_id
                    const response = await fetch(`/bookings/api/weather/conditions/?schedule_id=${id}`);
                    if (!response.ok) throw new Error(`Weather fetch failed for schedule ${id}`);
                    const { weather } = await response.json();

                    // --- Update port weather (for dashboard top icons) ---
                    ['nadi', 'suva'].forEach(port => {
                        const data = weather?.ports?.[port] || {};
                        const iconEl = document.getElementById(`${port}-icon`);
                        const tempEl = document.getElementById(`${port}-temp`);
                        if (iconEl) iconEl.innerHTML = Utils.getWeatherIcon(data.condition);
                        if (tempEl) tempEl.textContent = `${data.temp || 28}°`;
                    });

                    // --- Update weather details for this schedule card only ---
                    if (weather) this.paintCard(id, weather);
                }

                logger.log('Weather updated per schedule from DB');
            } catch (error) {
                logger.warn('Weather update failed:', error);
                this.applyFallbackWeather();
            }
        }

        applyFallbackWeather() {
            // NOTE: the template emits this under id "weather-data".
            const fallback = Utils.safeParseJSON('weather-data', {});
            if (!fallback) return;

            // Fallback for port weather (top icons, if present)
            ['nadi', 'suva'].forEach(port => {
                const data = (fallback.ports && fallback.ports[port]) || {};
                const iconEl = document.getElementById(`${port}-icon`);
                const tempEl = document.getElementById(`${port}-temp`);
                if (iconEl) iconEl.innerHTML = Utils.getWeatherIcon(data.condition || 'Sunny');
                if (tempEl) tempEl.textContent = `${data.temp || 28}°`;
            });

            // Fallback for each schedule card uses the current-conditions block.
            const current = fallback.current || {};
            document.querySelectorAll('.schedule-card').forEach(card => {
                this.paintCard(card.dataset.scheduleId, current);
            });

            logger.log('Applied fallback weather');
        }
    }

    // TESTIMONIAL MANAGER
    class TestimonialManager {
        constructor() {
            this.testimonials = document.querySelectorAll('.testimonial');
            this.current = 0;
            this.interval = null;
            this.init();
        }
        init() {
            this.startRotation();
        }
        startRotation() {
            this.interval = setInterval(() => {
                this.testimonials.forEach(t => t.classList.remove('active'));
                this.current = (this.current + 1) % this.testimonials.length;
                this.testimonials[this.current].classList.add('active');
            }, FijiFerry.config.testimonialInterval);
        }
        pauseAutoRotate() {
            clearInterval(this.interval);
        }
        resumeAutoRotate() {
            this.startRotation();
        }
    };

    // MAIN INITIALIZATION
    class HomepageManager {
        constructor() {
            this.components = new Map();
            this.isInitialized = false;
        }
        init() {
            if (this.isInitialized) return;
            this.isInitialized = true;
            Utils.applyTailwindOverrides();
            this.components.set('notifications', new NotificationManager());
            this.components.set('hero', new HeroManager());
            this.components.set('filters', new FilterManager());
            setTimeout(() => {
                if (document.getElementById('fiji-map')) {
                    this.components.set('map', new MapManager());
                }
            }, 200);
            setTimeout(() => {
                this.components.set('schedules', new ScheduleManager());
                this.components.set('testimonials', new TestimonialManager());
            }, 300);
            this.setupGlobalListeners();
            this.startBackgroundTasks();
            window.FijiFerry = FijiFerry;
            FijiFerry.homepage = this;
            FijiFerry.notificationManager = this.components.get('notifications');
            logger.log('Homepage initialized v2.5.0');
        }
        setupGlobalListeners() {
            document.addEventListener('keydown', (e) => {
                if (['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName)) return;
                if (e.key === 'Escape') this.components.get('notifications')?.closeAll?.();
                if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
                    e.preventDefault();
                    document.getElementById('route')?.focus();
                }
                if ((e.ctrlKey || e.metaKey) && e.key === 'r') {
                    e.preventDefault();
                    window.resetSearch();
                }
            });
            window.addEventListener('online', () => {
                FijiFerry.notificationManager?.show('Connection restored', 'success', 3000);
            });
            window.addEventListener('offline', () => {
                FijiFerry.notificationManager?.show('Connection lost', 'warning', 5000);
            });
        }
        startBackgroundTasks() {
            const liveFerryCount = document.getElementById('live-ferry-count');
            const onScheduleCount = document.getElementById('on-schedule-count');
            if (liveFerryCount && onScheduleCount) {
                // Real values from the server (data-count); fall back to 0.
                const ferries = parseInt(liveFerryCount.dataset.count, 10) || 0;
                const onSchedule = parseInt(onScheduleCount.dataset.count, 10) || 0;
                this.animateCounter(liveFerryCount, ferries, 1500);
                this.animateCounter(onScheduleCount, onSchedule, 1500);
            }
            const heroSlides = document.querySelectorAll('.hero-slide');
            if (heroSlides.length > 0) {
                const heroImages = Array.from(heroSlides).map(slide => slide.dataset.srcLight).filter(Boolean);
                Utils.preloadImages(heroImages);
            }
        }
        animateCounter(element, target, duration) {
            let start = 0;
            const increment = target / (duration / 16);
            const timer = setInterval(() => {
                start += increment;
                if (start >= target) {
                    start = target;
                    clearInterval(timer);
                }
                element.textContent = Math.floor(start);
            }, 16);
        }
        pauseAll() {
            this.components.get('hero')?.pauseSlideshow?.();
            this.components.get('testimonials')?.pauseAutoRotate?.();
        }
        resumeAll() {
            this.components.get('hero')?.resumeSlideshow?.();
            this.components.get('testimonials')?.resumeAutoRotate?.();
        }
        destroy() {
            this.components.forEach(comp => comp.destroy?.());
            this.components.clear();
            this.isInitialized = false;
        }
    };

    // GLOBAL FUNCTIONS
    window.saveSchedule = (id) => console.log(`Save schedule ${id}`);
    window.shareSchedule = (id) => console.log(`Share schedule ${id}`);

    // Delegate clicks for buttons that use data-schedule-id instead of inline onclick
    document.addEventListener('click', (e) => {
        const saveBtn = e.target.closest('.js-save-schedule');
        if (saveBtn) { window.saveSchedule(saveBtn.dataset.scheduleId); return; }
        const shareBtn = e.target.closest('.js-share-schedule');
        if (shareBtn) { window.shareSchedule(shareBtn.dataset.scheduleId); }
    });
    window.scrollToSchedules = () => {
        document.getElementById('schedules-section')?.scrollIntoView({ behavior: 'smooth' });
    };

    // INITIALIZATION
    let initAttempted = false;
    function initialize() {
        if (initAttempted) return;
        initAttempted = true;
        const initWithDelay = () => {
            Utils.applyTailwindOverrides();
            FijiFerry.homepage = new HomepageManager();
            FijiFerry.homepage.init();
        };
        if (window.requestIdleCallback) {
            requestIdleCallback(initWithDelay, { timeout: 200 });
        } else {
            setTimeout(initWithDelay, 100);
        }
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initialize);
    } else {
        initialize();
    }
    window.addEventListener('load', () => {
        if (!initAttempted) initialize();
    });
    window.addEventListener('beforeunload', () => {
        if (FijiFerry.homepage?.destroy) FijiFerry.homepage.destroy();
    });
    window.FijiFerry = FijiFerry;
    window.Utils = Utils;
})();
