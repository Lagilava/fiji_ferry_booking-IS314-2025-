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
                'sunny': '☀︎',
                'clear': '☀︎',
                'partly cloudy': '☁︎⸝⸝',
                'partly_cloudy': '☁︎⸝⸝',
                'cloudy': '☁︎',
                'overcast': '☁︎',
                'cloud': '☁︎',
                'rain': '☂︎',
                'light rain': '☂︎',
                'heavy rain': '☔',
                'shower': '☂︎',
                'thunderstorm': '⚡',
                'thunder': '⚡',
                'drizzle': '☂︎',
                'fog': '〰',
                'mist': '〰',
                'haze': '〰',
                'windy': '〽',
                'snow': '❄︎',
                'sleet': '❄︎',
                'hail': '❄︎'
            };

            const key = condition?.toLowerCase()?.replace(/\s+/g, '_');
            return icons[key] || '☁︎';
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

    // FILTER MANAGER
    class FilterManager {
        constructor() {
            this.isInitialized = false;
            this.init();
        }
        init() {
            if (this.isInitialized) return;
            this.isInitialized = true;
            this.setupControls();
            this.setupThemeListener();
            this.setupFilterSidebar();
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
            const viewAllBtn = document.getElementById('view-all-btn');
            if (viewAllBtn) {
                viewAllBtn.addEventListener('click', (e) => {
                    e.preventDefault();
                    const url = new URL(window.location);
                    ['route', 'date', 'passengers', 'sort'].forEach(param => url.searchParams.delete(param));
                    window.history.replaceState({}, '', url);
                    window.resetSearch();
                    const sortSelect = document.getElementById('sort-by');
                    if (sortSelect) sortSelect.value = 'time';
                    FijiFerry.notificationManager?.show('Showing all available schedules', 'success', 2000);
                });
            }
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
                    if (routeIdInput) {
                        routeIdInput.value = '';
                    }
                    const url = new URL(window.location);
                    ['route', 'date', 'passengers', 'sort'].forEach(param => url.searchParams.delete(param));
                    window.history.replaceState({}, '', url);
                    form.dispatchEvent(new Event('reset', { bubbles: true }));
                    form.dispatchEvent(new Event('input', { bubbles: true }));
                }
                FijiFerry.notificationManager?.show('Search reset! Ready to discover new routes.', 'info', 3000);
            };
            document.addEventListener('keydown', (e) => {
                if ((e.ctrlKey || e.metaKey) && e.key === 'r') {
                    e.preventDefault();
                    window.resetSearch();
                }
            });

            // Infinite scroll + load more button
            const loadMoreBtn = document.getElementById('load-more-schedules');
            if (loadMoreBtn) {
                loadMoreBtn.addEventListener('click', (event) => {
                    event.preventDefault();
                    this.loadMoreSchedules();
                });
            }

            window.addEventListener('scroll', Utils.throttle(() => {
                if (this.isNearBottom() && loadMoreBtn && !this.isLoadingMore && !loadMoreBtn.disabled) {
                    this.loadMoreSchedules();
                }
            }, 250));
        }

        setupFilterSidebar() {
            const priceMin = document.getElementById('price-min');
            const priceMax = document.getElementById('price-max');
            const durationMax = document.getElementById('duration-max');
            const statusInputs = Array.from(document.querySelectorAll('input[name="status-filter"]'));
            const applyBtn = document.getElementById('apply-filters');
            const resetBtn = document.getElementById('reset-filters');
            const filterStatus = document.getElementById('filter-status');

            const runFilters = () => {
                this.applyScheduleFilters();
            };

            if (priceMin) priceMin.addEventListener('input', runFilters);
            if (priceMax) priceMax.addEventListener('input', runFilters);
            if (durationMax) durationMax.addEventListener('change', runFilters);
            statusInputs.forEach(input => input.addEventListener('change', runFilters));

            if (applyBtn) applyBtn.addEventListener('click', runFilters);
            if (resetBtn) resetBtn.addEventListener('click', () => {
                if (priceMin) priceMin.value = '';
                if (priceMax) priceMax.value = '';
                if (durationMax) durationMax.value = '0';
                statusInputs.forEach(input => input.checked = true);
                this.resetAndLoadSchedules();
            });

            this.resetAndLoadSchedules();

            if (filterStatus) {
                filterStatus.textContent = 'Showing all schedules';
            }
            this.updateAppliedBadge();
        }

        applyScheduleFilters() {
            // Use backend rules by reloading schedule pages; keep client message updated.
            this.resetAndLoadSchedules();
            this.updateAppliedBadge();
            const filterStatus = document.getElementById('filter-status');
            const cards = document.querySelectorAll('.schedule-card');
            if (filterStatus) {
                filterStatus.textContent = `${cards.length} schedules loading with current filters...`;
            }
        }

        getCurrentFilterContext() {
            const routeInput = document.getElementById('route')?.value.trim();
            const routeIdInput = document.getElementById('route-id')?.value.trim();
            const dateInput = document.getElementById('departure-date')?.value;
            const priceMin = document.getElementById('price-min')?.value;
            const priceMax = document.getElementById('price-max')?.value;
            const durationMax = document.getElementById('duration-max')?.value;
            const statusInputs = Array.from(document.querySelectorAll('input[name="status-filter"]:checked')).map(el => el.value);

            return JSON.stringify({route: routeInput, route_id: routeIdInput, date: dateInput, priceMin, priceMax, durationMax, status: statusInputs.sort()});
        }

        updateAppliedBadge() {
            const badge = document.getElementById('filter-applied-badge');
            if (!badge) return;

            const route = document.getElementById('route')?.value.trim() || 'all';
            const date = document.getElementById('departure-date')?.value || 'all';
            const statuses = Array.from(document.querySelectorAll('input[name="status-filter"]:checked')).map(el => el.value).sort();
            const statusText = statuses.length > 0 ? statuses.join(',') : 'all';

            badge.textContent = `Applied: route=${route || 'all'} date=${date} status=${statusText}`;
        }

        updateFilterStatus(message) {
            const filterStatus = document.getElementById('filter-status');
            if (!filterStatus) return;
            filterStatus.textContent = message;
        }

        resetAndLoadSchedules() {
            const list = document.getElementById('schedule-list');
            const button = document.getElementById('load-more-schedules');
            if (list) list.innerHTML = '';
            if (button) {
                button.style.display = '';
                button.disabled = false;
                // Reset to a positive value so first paged request always runs
                button.setAttribute('data-remaining', '1');
                const loadMoreText = document.getElementById('load-more-text');
                if (loadMoreText) {
                    loadMoreText.textContent = 'Load More Schedules (loading... )';
                }
            }
            this.currentFilterKey = this.getCurrentFilterContext();
            this.isLoadingMore = false;
            this.currentOffset = 0;
            this.updateAppliedBadge();
            this.updateFilterStatus('Reloading schedules with applied filters...');
            this.loadMoreSchedules();
        }




        isNearBottom() {
            const threshold = 150;
            return (window.innerHeight + window.scrollY) >= (document.body.offsetHeight - threshold);
        }

        updateProgress(total = null) {
            const progressContainer = document.getElementById('schedule-progress-container');
            const progressBar = document.getElementById('schedule-progress');
            const scheduleList = document.getElementById('schedule-list');
            if (!progressContainer || !progressBar || !scheduleList) return;

            const current = document.querySelectorAll('.schedule-card').length;
            const totalCount = total ?? parseInt(scheduleList.getAttribute('data-total') || '0', 10);

            if (!totalCount) {
                progressContainer.classList.add('hidden');
                return;
            }

            const percent = Math.min(100, Math.round((current / totalCount) * 100));
            progressBar.style.width = `${percent}%`;
            progressContainer.classList.remove('hidden');

            if (percent >= 100) {
                setTimeout(() => progressContainer.classList.add('hidden'), 400);
            }
        }

        async loadMoreSchedules() {
            if (this.isLoadingMore) return;
            const list = document.getElementById('schedule-list');
            const button = document.getElementById('load-more-schedules');
            if (!list || !button) return;

            const remaining = parseInt(button.getAttribute('data-remaining') || '0', 10);
            const offset = document.querySelectorAll('.schedule-card').length;

            // Always allow initial fetch (offset 0), because filter state may change from initial totals.
            if (offset > 0 && remaining <= 0) {
                button.classList.add('hidden');
                return;
            }

            this.isLoadingMore = true;
            button.disabled = true;
            button.innerHTML = '<span class="loading-spinner w-4 h-4 border-2 border-gray-300 border-t-blue-500 rounded-full animate-spin" aria-hidden="true"></span><span class="ml-2">Loading more schedules...</span>';
            const progressContainer = document.getElementById('schedule-progress-container');
            const progressBar = document.getElementById('schedule-progress');
            if (progressContainer && progressBar) {
                progressContainer.classList.remove('hidden');
                progressBar.style.width = '0%';
            }

            const currentFilterKey = this.getCurrentFilterContext();
            const limit = 6;
            const params = new URLSearchParams();
            params.set('offset', offset);
            params.set('limit', limit);

            const routeVal = document.getElementById('route')?.value.trim();
            const routeIdVal = document.getElementById('route-id')?.value.trim();
            const dateVal = document.getElementById('departure-date')?.value;
            const durationVal = document.getElementById('duration-max')?.value;
            const priceMinVal = document.getElementById('price-min')?.value;
            const priceMaxVal = document.getElementById('price-max')?.value;
            const statuses = Array.from(document.querySelectorAll('input[name="status-filter"]:checked')).map(i => i.value);

            if (routeVal) params.set('route', routeVal);
            if (routeIdVal) params.set('route_id', routeIdVal);
            if (dateVal) params.set('date', dateVal);
            if (durationVal && durationVal !== '0') params.set('duration_max', durationVal);
            if (priceMinVal) params.set('price_min', priceMinVal);
            if (priceMaxVal) params.set('price_max', priceMaxVal);
            if (statuses.length > 0) params.set('status', statuses.join(','));

            const url = `/bookings/api/paged_bookings/?${params.toString()}`;
            console.log('[FijiFerry] loadMoreSchedules URL', url);

            try {
                const { data, error } = await Utils.useFetch(url);
                console.log('[FijiFerry] loadMoreSchedules response', { data, error });
                if (error) throw error;
                const schedules = data?.schedules || [];
                const total = data?.total ?? null;

                const currentKey = this.getCurrentFilterContext();
                if (!this.currentFilterKey) {
                    this.currentFilterKey = currentKey;
                }

                if (this.currentFilterKey !== currentKey) {
                    // Filter changed while load was in-flight, discard stale results and reload.
                    this.currentFilterKey = currentKey;
                    this.currentOffset = 0;
                    this.resetAndLoadSchedules();
                    return;
                }

                if (schedules.length === 0 && offset === 0) {
                    FijiFerry.notificationManager?.show('No matching schedules found', 'warning', 3500);
                }

                schedules.forEach((schedule) => {
                    const cardHTML = this.renderScheduleCard(schedule);
                    list.insertAdjacentHTML('beforeend', cardHTML);
                });

                const newRemaining = data.remaining ?? Math.max(0, remaining - schedules.length);
                button.setAttribute('data-remaining', newRemaining);
                const text = document.getElementById('load-more-text');
                if (text) {
                    text.textContent = newRemaining > 0 ? `Load More Schedules (${newRemaining} remaining)` : 'All schedules loaded';
                }

                if (newRemaining <= 0 || schedules.length === 0) {
                    button.style.display = 'none';
                }

                this.updateProgress(data.total);

                // Save offset for continued paging behavior
                this.currentOffset = offset + schedules.length;

                logger.log(`Appended ${schedules.length} schedules (remaining ${newRemaining})`);
            } catch (error) {
                logger.error('Load more schedules failed:', error);
                FijiFerry.notificationManager?.show('Could not load more schedules. Please try again.', 'error', 3000);
            } finally {
                this.isLoadingMore = false;
                const progressContainer = document.getElementById('schedule-progress-container');
                if (progressContainer && button && button.style.display === 'none') {
                    progressContainer.classList.add('hidden');
                }
                if (button && button.style.display !== 'none') {
                    button.disabled = false;
                    if (document.getElementById('load-more-text')) {
                        document.getElementById('load-more-text').textContent = `Load More Schedules (${button.getAttribute('data-remaining') || remaining} remaining)`;
                    } else {
                        button.innerHTML = '<i class="fas fa-plus" aria-hidden="true"></i><span style="color: black;">Load More Schedules</span>';
                    }
                }
            }
        }

        renderScheduleCard(schedule) {
            const status = schedule.status || 'scheduled';
            const statusClass = status === 'scheduled' ? 'bg-emerald-100 text-emerald-800' : status === 'delayed' ? 'bg-yellow-100 text-yellow-800' : status === 'cancelled' ? 'bg-red-100 text-red-800' : 'bg-gray-100 text-gray-700';
            const statusIcon = status === 'scheduled' ? 'fa-check-circle' : status === 'delayed' ? 'fa-exclamation-triangle' : status === 'cancelled' ? 'fa-times-circle' : 'fa-clock';
            const price = schedule.base_fare ? `FJD ${Math.round(schedule.base_fare)}` : 'Unavailable';
            const departureTime = new Date(schedule.departure_time).toLocaleString('en-US', { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
            const seats = schedule.available_seats ?? 0;
            const [origin, dest] = (schedule.route || '').split(' to ');

            return `
                <article class="schedule-card transition-all duration-300 hover:shadow-lg hover:-translate-y-1 border border-gray-200 rounded-xl overflow-hidden flex flex-col h-full" data-schedule-id="${schedule.id}" data-route-id="${schedule.route_id || ''}" data-price="${schedule.price ?? 0}" data-duration="${Math.round((schedule.duration ?? 0) * 60)}" data-status="${schedule.status || 'scheduled'}" role="article" aria-label="${schedule.route} departing ${departureTime}">
                    <div class="route-info p-6 flex-grow">
                        <header class="mb-4">
                            <h3 class="text-xl font-bold text-gray-800 font-poppins mb-2">${origin || 'Unknown'} <span class="text-sm text-gray-400" aria-hidden="true">→</span> ${dest || 'Unknown'}</h3>
                            <time class="departure-time text-sm text-gray-600 mb-1" datetime="${schedule.departure_time}">${departureTime}</time>
                            <p class="ferry-name text-sm text-gray-500">${schedule.ferry_name || 'Ferry'}</p>
                        </header>
                        <div class="weather-info flex items-center gap-3 p-3 bg-gray-50 rounded-lg mb-4 border border-gray-100" aria-label="Weather forecast for departure">
                            <div class="weather-icon text-2xl flex-shrink-0" aria-hidden="true">☁︎</div>
                            <div class="weather-details flex-1 min-w-0">
                                <div class="weather-condition font-semibold text-sm text-gray-800">Loading weather...</div>
                                <div class="weather-meta flex gap-4 text-xs text-gray-500 mt-1 flex-wrap">
                                    <span class="weather-temp inline-flex items-center gap-1"><i class="fas fa-thermometer-half text-emerald-500" aria-hidden="true"></i><span>--°C</span></span>
                                    <span class="weather-wind inline-flex items-center gap-1"><i class="fas fa-wind text-blue-500" aria-hidden="true"></i><span>-- kph</span></span>
                                    <span class="weather-precip inline-flex items-center gap-1"><i class="fas fa-cloud-rain text-gray-500" aria-hidden="true"></i><span>--%</span></span>
                                </div>
                            </div>
                        </div>
                        <dl class="schedule-meta grid grid-cols-2 gap-3 mb-4 text-sm text-gray-600">
                            <div class="seats flex items-center gap-2 dt"><dt class="flex-shrink-0"><i class="fas fa-chair text-gray-400" aria-hidden="true"></i></dt><dd class="seats-count font-semibold text-gray-800">${seats}</dd><span class="sr-only">seats available</span></div>
                            <div class="duration flex items-center gap-2 justify-end dt"><dt class="flex-shrink-0"><i class="fas fa-clock text-gray-400" aria-hidden="true"></i></dt><dd>${Math.round(schedule.duration || 0)}m</dd><span class="sr-only">duration</span></div>
                        </dl>
                    </div>
                    <footer class="schedule-footer pt-4 border-t border-gray-200 px-6 pb-6 bg-gray-50 mt-auto">
                        <div class="status-price flex items-center justify-between mb-4">
                            <span class="status-badge inline-flex items-center gap-1 px-3 py-1 rounded-full text-xs font-semibold ${statusClass}"><i class="fas ${statusIcon}" aria-hidden="true"></i><span>${status.replace(/\b\w/g, l=> l.toUpperCase())}</span></span>
                            <span class="price text-lg font-bold text-emerald-600">${price}</span>
                        </div>
                        <a href="/bookings/book/?schedule_id=${schedule.id}" class="book-btn w-full bg-gradient-to-r from-emerald-500 to-teal-500 hover:from-emerald-600 hover:to-teal-600 text-white py-3 px-6 rounded-xl font-semibold shadow-lg hover:shadow-xl transition-all transform hover:-translate-y-1 flex items-center justify-center gap-2 text-center focus:outline-none focus:ring-2 focus:ring-emerald-500/50" aria-label="Book ferry from ${origin} to ${dest} departing ${departureTime}"><i class="fas fa-ticket-alt" aria-hidden="true"></i><span>Book Now (${seats} seats)</span></a>
                    </footer>
                </article>
            `;
        }

        destroy() {
            this.isInitialized = false;
        }
    };

    // MAP MANAGER – ONLY ACTIVE PORTS
    class MapManager {
        constructor() {
            this.map = null;
            this.init();
        }
        async init() {
            const mapContainer = document.getElementById('fiji-map');
            if (!mapContainer) return;
            this.map = L.map('fiji-map').setView([-17.7134, 178.0650], 8);
            L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
                maxZoom: 19,
                attribution: '&copy; OpenStreetMap'
            }).addTo(this.map);
            await this.loadPorts();
        }
        async loadPorts() {
            try {
                const response = await fetch('/bookings/api/routes/');
                if (!response.ok) throw new Error('Ports fetch failed');
                const { routes } = await response.json();

                // Active ports/routes inferred from the rendered schedule cards.
                const activePorts = new Set();
                const activeRoutes = new Set();
                document.querySelectorAll('.schedule-card h3').forEach(h3 => {
                    const [depart, dest] = h3.textContent.split(' to ');
                    if (depart) activePorts.add(depart.trim());
                    if (dest) activePorts.add(dest.trim());
                    if (depart && dest) activeRoutes.add(`${depart.trim()}→${dest.trim()}`);
                });

                const bounds = [];
                const drawnPorts = new Map();   // name -> [lat,lng] (dedupe markers)

                const coord = (p) => {
                    const lat = parseFloat(p.lat), lng = parseFloat(p.lng);
                    return (isNaN(lat) || isNaN(lng)) ? null : [lat, lng];
                };

                // 1) Draw the sea route lines (boat routes), not just ports.
                routes.forEach(route => {
                    const a = coord(route.departure_port);
                    const b = coord(route.destination_port);
                    if (!a || !b) return;
                    const key = `${route.departure_port.name}→${route.destination_port.name}`;
                    const isActive = activeRoutes.has(key);
                    // Use server waypoints if provided, else a straight dep→dest line.
                    const line = (Array.isArray(route.waypoints) && route.waypoints.length >= 2)
                        ? route.waypoints : [a, b];
                    L.polyline(line, {
                        color: isActive ? '#10b981' : '#94a3b8',
                        weight: isActive ? 4 : 2,
                        opacity: isActive ? 0.9 : 0.5,
                        dashArray: isActive ? null : '6,8',
                        lineJoin: 'round',
                    }).addTo(this.map).bindPopup(
                        `<b>${route.departure_port.name} → ${route.destination_port.name}</b>` +
                        (route.base_fare ? `<br>From FJD ${route.base_fare}` : '') +
                        (isActive ? '<br><span style="color:#10b981">● Active today</span>' : ''));
                    bounds.push(a, b);
                    drawnPorts.set(route.departure_port.name, a);
                    drawnPorts.set(route.destination_port.name, b);
                });

                // 2) Draw one marker per unique port (active ones emphasised).
                drawnPorts.forEach((latlng, name) => {
                    if (activePorts.has(name)) {
                        L.circleMarker(latlng, {
                            radius: 8, color: '#10b981', fillColor: '#10b981', fillOpacity: 0.85, weight: 2,
                        }).addTo(this.map).bindPopup(`<b>${name}</b><br>Active schedule`);
                        L.circle(latlng, {
                            radius: 18000, color: '#10b981', fillColor: '#10b981',
                            fillOpacity: 0.12, weight: 0, className: 'pulse-circle',
                        }).addTo(this.map);
                    } else {
                        L.circleMarker(latlng, {
                            radius: 5, color: '#64748b', fillColor: '#cbd5e1', fillOpacity: 0.8, weight: 1,
                        }).addTo(this.map).bindPopup(name);
                    }
                });

                if (bounds.length) {
                    this.map.fitBounds(bounds, { padding: [40, 40], maxZoom: 9 });
                }
                logger.log(`Map loaded – ${routes.length} routes, ${drawnPorts.size} ports`);
            } catch (error) {
                logger.warn('Failed to load ports from API:', error);
                this.addHardcodedPorts();
            }
        }
        addHardcodedPorts() {
            const ports = [
                { name: 'Nadi', lat: -17.7728, lng: 177.3809 },
                { name: 'Suva', lat: -18.1248, lng: 178.3967 },
                { name: 'Denarau', lat: -17.7725, lng: 177.3805 },
                { name: 'Yasawa Islands', lat: -16.9, lng: 177.3 }
            ];
            ports.forEach(port => {
                L.marker([port.lat, port.lng]).addTo(this.map).bindPopup(port.name);
            });
        }
    };

// === SCHEDULE MANAGER – PER-SCHEDULE DB POLLING ===
class ScheduleManager {
    constructor() {
        this.init();
    }

    init() {
        logger.log('ScheduleManager initialized');
        this.updateWeatherDisplay();
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
                    if (iconEl) iconEl.textContent = Utils.getWeatherIcon(data.condition);
                    if (tempEl) tempEl.textContent = `${data.temp || 28}°`;
                });

                // --- Update weather details for this schedule card only ---
                const data = weather || {};
                ['condition', 'icon', 'temp', 'wind', 'precip'].forEach(field => {
                    const el = document.getElementById(`weather-${field}-${id}`);
                    if (!el) return;

                    const value =
                        field === 'icon' ? Utils.getWeatherIcon(data.condition) :
                        field === 'temp' ? `${Math.round(data.temperature ?? data.temp ?? 28)}°C` :
                        field === 'wind' ? `${Math.round(data.wind_speed ?? data.wind ?? 12)} kph` :
                        field === 'precip' ? `${Math.round(data.precipitation_probability ?? data.precip ?? 5)}%` :
                        data.condition || 'Sunny';

                    el.textContent = value;
                });
            }

            logger.log('✅ Weather updated per schedule from DB');
        } catch (error) {
            logger.warn('❌ Weather update failed:', error);
            this.applyFallbackWeather();
        }
    }

    applyFallbackWeather() {
        const fallback = Utils.safeParseJSON('weather-data-fallback', {});
        if (!fallback || !fallback.ports) return;

        // Fallback for port weather
        ['nadi', 'suva'].forEach(port => {
            const data = fallback.ports[port] || {};
            const iconEl = document.getElementById(`${port}-icon`);
            const tempEl = document.getElementById(`${port}-temp`);
            if (iconEl) iconEl.textContent = Utils.getWeatherIcon(data.condition || 'Sunny');
            if (tempEl) tempEl.textContent = `${data.temp || 28}°`;
        });

        // Fallback for each schedule card
        document.querySelectorAll('.schedule-card').forEach(card => {
            const id = card.dataset.scheduleId;
            const data = fallback.current || {};
            ['condition', 'icon', 'temp', 'wind', 'precip'].forEach(field => {
                const el = document.getElementById(`weather-${field}-${id}`);
                if (!el) return;

                const value =
                    field === 'icon' ? Utils.getWeatherIcon(data.condition) :
                    field === 'temp' ? `${data.temp || 28}°C` :
                    field === 'wind' ? `${data.wind || 12} kph` :
                    field === 'precip' ? `${data.precip || 5}%` :
                    data.condition || 'Sunny';

                el.textContent = value;
            });
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