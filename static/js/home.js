/**
 * Fiji Ferry Booking - Complete Homepage JavaScript
 * Unified implementation for home.html
 * Version: 2.3.1
 * Fixed: Dark mode compatibility, map initialization, hero slideshow, conflicts
 */

(function() {
    'use strict';

    // 🌟 GLOBAL CONFIGURATION
    const FijiFerry = window.FijiFerry || {};
    FijiFerry.config = {
        animationDuration: 600,
        slideshowInterval: 5000,
        testimonialInterval: 7000,
        pollingInterval: 120000, // 2 minutes
        weatherUpdateInterval: 300000, // 5 minutes
        debug: window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
    };

    // 🛠️ LOGGER
    const logger = {
        log: (...args) => FijiFerry.config.debug && console.log('[FijiFerry]', ...args),
        warn: (...args) => FijiFerry.config.debug && console.warn('[FijiFerry]', ...args),
        error: (...args) => console.error('[FijiFerry]', ...args)
    };

    // 🔧 UTILITY FUNCTIONS
    const Utils = {
        safeParseJSON(elementId, defaultValue = {}) {
            try {
                const script = document.getElementById(elementId);
                if (!script) return defaultValue;

                let jsonStr = script.textContent.trim();
                jsonStr = jsonStr.replace(/^\s*<\!\[CDATA\[/, '').replace(/\]\]>\s*$/, '');

                const parsed = JSON.parse(jsonStr);
                return parsed || defaultValue;
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

        parseDuration(text) {
            if (!text) return Infinity;
            const match = text.match(/(\d+)h?\s*(\d+)?m?/i);
            return match ? parseInt(match[1]) * 60 + (parseInt(match[2]) || 0) : Infinity;
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
            return function() {
                const args = arguments;
                const context = this;
                if (!inThrottle) {
                    func.apply(context, args);
                    inThrottle = true;
                    setTimeout(() => inThrottle = false, limit);
                }
            };
        },

        getWeatherIcon(condition) {
            const icons = {
                'sunny': '☀️', 'clear': '☀️', 'partly cloudy': '⛅', 'partly_cloudy': '⛅',
                'cloudy': '☁️', 'overcast': '☁️', 'cloud': '☁️',
                'rain': '🌧️', 'light rain': '🌦️', 'heavy rain': '🌧️', 'shower': '🌧️',
                'thunderstorm': '⛈️', 'thunder': '⛈️', 'drizzle': '🌦️',
                'fog': '🌫️', 'mist': '🌫️', 'haze': '🌫️',
                'windy': '💨'
            };
            const key = condition?.toLowerCase().replace(/\s+/g, '_');
            return icons[key] || '🌤️';
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

        getCSRFToken() {
            return document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
                   document.cookie.match(/csrftoken=([^;]+)/)?.[1];
        },

        // Animation easing functions
        easeOutCubic(t) {
            return 1 - Math.pow(1 - t, 3);
        },

        easeOutQuart(t) {
            return 1 - (--t) * t * t * t;
        },

        // Theme-aware color getter
        getThemeColor(color, opacity = 1) {
            const root = document.documentElement;
            const theme = root.getAttribute('data-theme') || 'light';
            const colors = {
                primary: theme === 'dark' ? '#34D399' : '#10B981',
                secondary: theme === 'dark' ? '#60A5FA' : '#3B82F6',
                background: theme === 'dark' ? '#0F172A' : '#FFFFFF',
                surface: theme === 'dark' ? '#1E293B' : '#F8FAFC',
                text: theme === 'dark' ? '#F1F5F9' : '#1E293B',
                border: theme === 'dark' ? '#334155' : '#E2E8F0',
                gray800: theme === 'dark' ? '#F1F5F9' : '#1E293B',
                gray600: theme === 'dark' ? '#CBD5E1' : '#4B5563',
                gray500: theme === 'dark' ? '#94A3B8' : '#6B7280',
                gray400: theme === 'dark' ? '#64748B' : '#9CA3AF',
                gray300: theme === 'dark' ? '#475569' : '#D1D5DB',
                gray200: theme === 'dark' ? '#334155' : '#E5E7EB',
                gray100: theme === 'dark' ? '#1E293B' : '#F3F4F6',
                white: theme === 'dark' ? '#0F172A' : '#FFFFFF'
            };
            return colors[color] || (theme === 'dark' ? '#94A3B8' : '#6B7280');
        },

        // Override Tailwind colors for dark mode
        applyTailwindOverrides() {
            const theme = document.documentElement.getAttribute('data-theme') || 'light';
            if (theme === 'dark') {
                // Force Tailwind classes to use dark mode colors
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
                    [data-theme="dark"] .bg-gray-50 { background-color: #1E293B !important; }
                    [data-theme="dark"] .bg-gray-800 { background-color: #1E293B !important; }
                    [data-theme="dark"] .border-gray-200 { border-color: #475569 !important; }
                    [data-theme="dark"] .border-gray-100 { border-color: #334155 !important; }
                    [data-theme="dark"] .border-gray-300 { border-color: #475569 !important; }
                    [data-theme="dark"] .bg-gray-50 { background-color: #1E293B !important; }
                    [data-theme="dark"] .bg-gray-100 { background-color: #334155 !important; }
                `;
                document.head.appendChild(style);
            }
        }
    };

    // 🔔 NOTIFICATION SYSTEM (Enhanced for dark mode)
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
            const observer = new MutationObserver(() => {
                this.updateNotificationsTheme();
            });
            observer.observe(document.documentElement, {
                attributes: true,
                attributeFilter: ['data-theme']
            });
        }

        createContainer() {
            // Remove existing container if present
            if (this.container) {
                this.container.remove();
            }

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
                if (element && element.parentNode) {
                    this.updateNotificationTheme(element);
                }
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

                // Update text colors for dark mode
                if (theme === 'dark') {
                    notification.style.color = '#F1F5F9';
                    const closeBtn = notification.querySelector('.notification-close');
                    if (closeBtn) {
                        closeBtn.style.color = '#F1F5F9';
                    }
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

            // Animate in
            requestAnimationFrame(() => {
                notification.classList.remove('translate-x-full');
            });

            // Auto-remove
            if (duration > 0) {
                setTimeout(() => this.removeNotification(id), duration);
            }

            // Focus management
            if (options.focusable !== false) {
                const closeBtn = notification.querySelector('.notification-close');
                if (closeBtn) {
                    closeBtn.focus();
                    closeBtn.addEventListener('blur', () => {
                        // Keep notification visible on blur
                    });
                }
            }

            // Update theme immediately
            this.updateNotificationTheme(notification);
            return notification;
        }

        getNotificationConfig(type) {
            const configs = {
                success: {
                    icon: '✅',
                    bg: 'bg-emerald-500',
                    border: 'border-emerald-400',
                    text: 'text-white'
                },
                error: {
                    icon: '❌',
                    bg: 'bg-red-500',
                    border: 'border-red-400',
                    text: 'text-white'
                },
                warning: {
                    icon: '⚠️',
                    bg: 'bg-amber-500',
                    border: 'border-amber-400',
                    text: 'text-white'
                },
                info: {
                    icon: 'ℹ️',
                    bg: 'bg-blue-500',
                    border: 'border-blue-400',
                    text: 'text-white'
                }
            };
            return configs[type] || configs.info;
        }

        removeNotification(id) {
            const notification = document.getElementById(id);
            if (!notification) return;

            notification.classList.add('translate-x-full');
            setTimeout(() => {
                if (notification.parentNode) {
                    notification.remove();
                }
                this.notifications.delete(id);
            }, 300);
        }

        closeAll() {
            this.notifications.forEach((_, id) => {
                this.removeNotification(id);
            });
        }

        destroy() {
            this.closeAll();
            if (this.container) {
                this.container.remove();
                this.container = null;
            }
        }
    }

    // 🎬 HERO MANAGER (Fixed slideshow)
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
            this.setupNavigation();
            this.setupThemeListener();
        }

        setupThemeListener() {
            const observer = new MutationObserver(() => {
                this.updateTheme();
            });
            observer.observe(document.documentElement, {
                attributes: true,
                attributeFilter: ['data-theme']
            });
        }

        updateTheme() {
            const theme = document.documentElement.getAttribute('data-theme') || 'light';
            logger.log(`Hero theme changed to: ${theme}`);

            this.slides.forEach(slide => {
                const imgSrc = theme === 'dark' ? slide.dataset.srcDark : slide.dataset.srcLight;
                if (imgSrc && slide.style.backgroundImage !== `url('${imgSrc}')`) {
                    // Preload image before changing
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

            logger.log(`Found ${this.slides.length} slides, initializing slideshow`);

            // Set initial active slide
            const activeSlide = document.querySelector('.hero-slide.active');
            if (activeSlide) {
                this.currentSlide = Array.from(this.slides).indexOf(activeSlide);
            } else if (this.slides[0]) {
                this.slides[0].classList.add('active');
                this.currentSlide = 0;
            }

            // Initialize dots
            if (this.dots[this.currentSlide]) {
                this.dots[this.currentSlide].classList.add('active');
            }

            // Set initial slide
            this.showSlide(this.currentSlide);

            // Start auto-advance
            this.startSlideshow();

            // Pause on hover/focus
            const hero = document.querySelector('.hero');
            if (hero) {
                const pauseEvents = ['mouseenter', 'focusin'];
                const resumeEvents = ['mouseleave', 'focusout'];

                pauseEvents.forEach(event => {
                    hero.addEventListener(event, () => {
                        this.pauseSlideshow();
                        logger.log('Slideshow paused');
                    });
                });

                resumeEvents.forEach(event => {
                    hero.addEventListener(event, () => {
                        this.resumeSlideshow();
                        logger.log('Slideshow resumed');
                    });
                });
            }

            // Update theme for initial load
            this.updateTheme();
        }

        showSlide(index) {
            if (index < 0 || index >= this.slides.length) {
                logger.warn(`Invalid slide index: ${index}`);
                return;
            }

            logger.log(`Showing slide ${index}`);

            // Update slide visibility with smooth transition
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

            // Update navigation dots
            this.dots.forEach((dot, i) => {
                dot.classList.toggle('active', i === index);
                dot.setAttribute('aria-pressed', (i === index).toString());
                dot.setAttribute('tabindex', i === index ? '0' : '-1');
            });

            this.currentSlide = index;
        }

        startSlideshow() {
            // Clear existing interval
            if (this.slideInterval) {
                clearInterval(this.slideInterval);
                this.slideInterval = null;
            }

            // Only start if we have multiple slides
            if (this.slides.length <= 1) {
                logger.log('Single slide, no slideshow needed');
                return;
            }

            logger.log(`Starting slideshow with ${this.slides.length} slides`);
            this.slideInterval = setInterval(() => {
                this.currentSlide = (this.currentSlide + 1) % this.slides.length;
                this.showSlide(this.currentSlide);
            }, FijiFerry.config.slideshowInterval);
        }

        pauseSlideshow() {
            if (this.slideInterval) {
                clearInterval(this.slideInterval);
                this.slideInterval = null;
                logger.log('Slideshow paused');
            }
        }

        resumeSlideshow() {
            if (!this.slideInterval && this.slides.length > 1) {
                this.startSlideshow();
                logger.log('Slideshow resumed');
            }
        }

        setupForm() {
            logger.log('Setting up hero form');

            // Form validation
            this.form.addEventListener('submit', (e) => {
                if (!this.validateForm()) {
                    e.preventDefault();
                    const notificationManager = FijiFerry.notificationManager || new NotificationManager();
                    notificationManager.show('Please fill in all required fields', 'warning');
                    return false;
                }

                // Add loading state to submit button
                const submitBtn = this.form.querySelector('button[type="submit"]');
                if (submitBtn) {
                    this.addLoadingState(submitBtn, 'Searching ferries...');
                }
            });

            // Date validation
            const dateInput = document.getElementById('departure-date');
            if (dateInput) {
                dateInput.addEventListener('change', (e) => {
                    const today = new Date().toISOString().split('T')[0];
                    if (e.target.value < today) {
                        e.target.value = today;
                        const notificationManager = FijiFerry.notificationManager || new NotificationManager();
                        notificationManager.show('Please select a future date', 'warning');
                    }
                });

                // Set minimum date if not set
                if (!dateInput.min) {
                    dateInput.min = today;
                }
            }

            // Auto-populate form from data
            this.populateForm();

            // Setup route suggestions
            this.setupRouteSuggestions();
        }

        setupRouteSuggestions() {
            const routeInput = document.getElementById('route');
            const suggestions = document.getElementById('route-suggestions');

            if (!routeInput || !suggestions) return;

            routeInput.addEventListener('input', Utils.debounce((e) => {
                const query = e.target.value.toLowerCase().trim();
                if (query.length < 2) {
                    suggestions.classList.add('hidden');
                    return;
                }

                const datalist = document.getElementById('routes');
                if (!datalist) return;

                const options = Array.from(datalist.querySelectorAll('option'));
                const matches = options.filter(opt =>
                    opt.value.toLowerCase().includes(query) ||
                    (opt.dataset.display && opt.dataset.display.toLowerCase().includes(query))
                ).slice(0, 5);

                if (matches.length > 0) {
                    suggestions.innerHTML = matches.map(opt => `
                        <div class="route-suggestion p-3 border-b border-gray-100 hover:bg-gray-50 cursor-pointer transition-colors dark:border-gray-700 dark:hover:bg-gray-800"
                             onclick="document.getElementById('route').value='${opt.value}'; document.getElementById('route-suggestions').classList.add('hidden');"
                             onkeydown="if(event.key==='Enter'){document.getElementById('route').value='${opt.value}'; document.getElementById('route-suggestions').classList.add('hidden');}"
                             role="option" tabindex="0"
                             data-display="${opt.dataset.display || opt.textContent}">
                            ${opt.dataset.display || opt.textContent}
                        </div>
                    `).join('');
                    suggestions.classList.remove('hidden');
                    suggestions.querySelector('.route-suggestion')?.focus();
                } else {
                    suggestions.classList.add('hidden');
                }
            }, 300));

            // Hide suggestions on outside click
            document.addEventListener('click', (e) => {
                if (!e.target.closest('#route') && !e.target.closest('#route-suggestions')) {
                    suggestions.classList.add('hidden');
                }
            });

            // Hide on Escape key
            routeInput.addEventListener('keydown', (e) => {
                if (e.key === 'Escape') {
                    suggestions.classList.add('hidden');
                    routeInput.focus();
                }
                if (e.key === 'ArrowDown' && !suggestions.classList.contains('hidden')) {
                    e.preventDefault();
                    suggestions.querySelector('.route-suggestion')?.focus();
                }
            });

            // Keyboard navigation for suggestions
            suggestions.addEventListener('keydown', (e) => {
                const suggestionsList = suggestions.querySelectorAll('.route-suggestion');
                const current = document.activeElement;
                const currentIndex = Array.from(suggestionsList).indexOf(current);

                if (e.key === 'ArrowDown') {
                    e.preventDefault();
                    const nextIndex = (currentIndex + 1) % suggestionsList.length;
                    suggestionsList[nextIndex].focus();
                } else if (e.key === 'ArrowUp') {
                    e.preventDefault();
                    const prevIndex = (currentIndex - 1 + suggestionsList.length) % suggestionsList.length;
                    suggestionsList[prevIndex].focus();
                } else if (e.key === 'Enter' && current && current.classList.contains('route-suggestion')) {
                    e.preventDefault();
                    current.click();
                } else if (e.key === 'Escape') {
                    suggestions.classList.add('hidden');
                    routeInput.focus();
                }
            });
        }

        validateForm() {
            const route = document.getElementById('route')?.value.trim();
            const date = document.getElementById('departure-date')?.value;
            const passengers = document.getElementById('passengers')?.value;
            const today = new Date().toISOString().split('T')[0];

            return route && date && date >= today && passengers && passengers !== '0';
        }

        populateForm() {
            try {
                const formData = Utils.safeParseJSON('form-data', {});
                const urlParams = new URLSearchParams(window.location.search);

                // Route
                const routeInput = document.getElementById('route');
                const routeValue = formData.route || urlParams.get('route') || '';
                if (routeInput && routeValue) {
                    routeInput.value = routeValue;
                    routeInput.dispatchEvent(new Event('input', { bubbles: true }));
                }

                // Date
                const dateInput = document.getElementById('departure-date');
                const today = new Date().toISOString().split('T')[0];
                const dateValue = formData.date || urlParams.get('date') || today;
                if (dateInput && dateValue >= today) {
                    dateInput.value = dateValue;
                }

                // Passengers
                const passengerSelect = document.getElementById('passengers');
                const passengerValue = formData.passengers || urlParams.get('passengers') || '1';
                if (passengerSelect && passengerValue) {
                    const option = passengerSelect.querySelector(`[value="${passengerValue}"]`);
                    if (option) {
                        passengerSelect.value = passengerValue;
                    }
                }

                // Trigger validation update
                this.updateState();
                logger.log('Form populated successfully');
            } catch (error) {
                logger.warn('Form population failed:', error);
            }
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
                feedback.classList.toggle('hidden', isValid);
                const theme = document.documentElement.getAttribute('data-theme') || 'light';
                if (isValid) {
                    feedback.classList.add(theme === 'dark' ? 'text-emerald-400' : 'text-emerald-300');
                    feedback.classList.remove('text-red-300', 'text-red-400');
                    feedback.innerHTML = '✓ Ready to search!';
                } else {
                    feedback.classList.add(theme === 'dark' ? 'text-red-400' : 'text-red-300');
                    feedback.classList.remove('text-emerald-300', 'text-emerald-400');
                    feedback.innerHTML = '⚠️ Please complete all fields';
                }
            }
        }

        addLoadingState(element, text = 'Loading...') {
            const originalHTML = element.innerHTML;
            const originalClasses = element.className;

            element.innerHTML = `<i class="fas fa-spinner fa-spin mr-2"></i>${text}`;
            element.disabled = true;
            element.className = originalClasses + ' opacity-75 cursor-not-allowed';
            element.dataset.originalHTML = originalHTML;

            // Restore after timeout or form success
            setTimeout(() => {
                if (element.dataset.originalHTML) {
                    element.innerHTML = element.dataset.originalHTML;
                    element.disabled = false;
                    element.className = originalClasses;
                    delete element.dataset.originalHTML;
                }
            }, 5000); // 5 second timeout
        }

        setupNavigation() {
            this.dots.forEach((dot, index) => {
                // Skip if dot doesn't exist
                if (!dot) return;

                ['click', 'keydown'].forEach(eventType => {
                    dot.addEventListener(eventType, (e) => {
                        if (eventType === 'keydown' && (e.key !== 'Enter' && e.key !== ' ')) return;
                        if (eventType === 'keydown') {
                            e.preventDefault();
                        }

                        this.pauseSlideshow();
                        this.showSlide(index);
                        this.resumeSlideshow();

                        logger.log(`Navigated to slide ${index}`);
                    });
                });

                // Focus management
                dot.addEventListener('focus', () => {
                    dot.style.outline = '2px solid #10B981';
                    dot.style.outlineOffset = '2px';
                });

                dot.addEventListener('blur', () => {
                    dot.style.outline = 'none';
                });
            });
        }

        destroy() {
            this.pauseSlideshow();
            this.isInitialized = false;
            logger.log('HeroManager destroyed');
        }
    }

    // 📊 STATS MANAGER
    class StatsManager {
        constructor() {
            this.stats = document.querySelectorAll('.stat-number[data-target]');
            this.animated = new Set();
            this.isInitialized = false;
            this.init();
        }

        init() {
            if (this.isInitialized) return;
            this.isInitialized = true;

            if (!this.stats.length) {
                logger.log('No stats elements found');
                return;
            }

            logger.log(`Found ${this.stats.length} stats elements`);

            const observer = new IntersectionObserver((entries) => {
                entries.forEach(entry => {
                    if (entry.isIntersecting && !this.animated.has(entry.target)) {
                        this.animateStat(entry.target);
                        this.animated.add(entry.target);
                        logger.log(`Animating stat: ${entry.target.dataset.target}`);
                    }
                });
            }, {
                threshold: 0.7,
                rootMargin: '0px 0px -100px 0px'
            });

            this.stats.forEach(stat => observer.observe(stat));
            this.setupThemeListener();
        }

        setupThemeListener() {
            const observer = new MutationObserver(() => {
                this.updateStatsTheme();
            });
            observer.observe(document.documentElement, {
                attributes: true,
                attributeFilter: ['data-theme']
            });
        }

        updateStatsTheme() {
            const theme = document.documentElement.getAttribute('data-theme') || 'light';
            this.stats.forEach(stat => {
                const parent = stat.closest('.stat-item');
                if (parent) {
                    const originalColor = stat.dataset.originalColor;
                    if (originalColor) {
                        stat.style.color = originalColor;
                    } else {
                        // Store original color for theme switching
                        if (!stat.dataset.originalColor) {
                            stat.dataset.originalColor = stat.style.color || window.getComputedStyle(stat).color;
                        }
                        stat.style.color = Utils.getThemeColor('text');
                    }
                }

                // Update stat labels
                const label = parent.querySelector('.stat-label');
                if (label) {
                    label.style.color = Utils.getThemeColor('text-secondary');
                }
            });
        }

        animateStat(statElement) {
            const target = parseFloat(statElement.dataset.target);
            const unit = statElement.dataset.unit || '';
            let current = 0;
            const duration = 2000;
            const startTime = performance.now();

            // Store original color before animation
            if (!statElement.dataset.originalColor) {
                statElement.dataset.originalColor = statElement.style.color || window.getComputedStyle(statElement).color;
            }

            const updateNumber = (currentTime) => {
                const elapsed = currentTime - startTime;
                const progress = Math.min(elapsed / duration, 1);
                const easeProgress = Utils.easeOutQuart(progress);

                current = target * easeProgress;
                statElement.textContent = Math.floor(current) + (target > 100 && !unit ? '%' : unit);

                // Update color during animation for visual effect
                const theme = document.documentElement.getAttribute('data-theme') || 'light';
                statElement.style.color = theme === 'dark' ? '#10B981' : '#059669';

                if (progress < 1) {
                    requestAnimationFrame(updateNumber);
                } else {
                    // Reset to theme color
                    statElement.style.color = Utils.getThemeColor('text');
                    statElement.textContent = target + (target > 100 && !unit ? '%' : unit);
                }
            };

            requestAnimationFrame(updateNumber);
        }

        destroy() {
            this.animated.clear();
            this.isInitialized = false;
        }
    }

    // 🗺️ MAP MANAGER (Fixed - Compatible with template loading)
    class MapManager {
        constructor() {
            this.map = null;
            this.markers = null;
            this.isInitialized = false;
            this.init();
        }

        init() {
            const mapEl = document.getElementById('fiji-map');
            if (!mapEl) {
                logger.warn('Map element not found');
                return;
            }

            logger.log('MapManager initialized, waiting for Leaflet...');
            this.waitForLeaflet(mapEl);
        }

        waitForLeaflet(mapEl, maxAttempts = 50) {
            let attempts = 0;

            const checkLeaflet = () => {
                attempts++;

                if (typeof L !== 'undefined') {
                    logger.log('Leaflet loaded, initializing map');
                    this.initializeMap(mapEl);
                    return;
                }

                if (attempts >= maxAttempts) {
                    logger.error('Leaflet failed to load after maximum attempts');
                    this.showMapError(mapEl);
                    return;
                }

                logger.log(`Waiting for Leaflet... (attempt ${attempts}/${maxAttempts})`);
                setTimeout(checkLeaflet, 100);
            };

            checkLeaflet();
        }

        initializeMap(mapEl) {
            if (this.isInitialized) {
                logger.log('Map already initialized, skipping');
                return;
            }
            this.isInitialized = true;

            try {
                logger.log('Creating Leaflet map instance');

                const isMobile = window.matchMedia('(max-width: 768px)').matches;
                const theme = document.documentElement.getAttribute('data-theme') || 'light';

                // Create map instance
                this.map = L.map(mapEl.id, {
                    center: [-17.6797, 178.0330], // Fiji geographic center
                    zoom: 8,
                    zoomControl: !isMobile,
                    minZoom: 6,
                    maxZoom: 14,
                    maxBounds: [[-21.0, 176.0], [-16.0, 181.0]], // Fiji bounds
                    maxBoundsViscosity: 1.0,
                    preferCanvas: true,
                    scrollWheelZoom: isMobile ? false : 'center',
                    attributionControl: false,
                    zoomAnimation: true,
                    fadeAnimation: true,
                    markerZoomAnimation: true
                });

                logger.log(`Map created with center: ${this.map.getCenter()}, zoom: ${this.map.getZoom()}`);

                // Add theme-aware tile layer
                this.addBaseLayers();

                // Add Fiji ports with static data (no API dependency)
                this.addFijiPorts();

                // Setup interactive controls
                this.setupControls();

                // Setup theme change listener
                this.setupThemeListener();

                // Fit bounds after all layers are added
                setTimeout(() => {
                    if (this.markers && this.markers.getLayers().length > 0) {
                        this.map.fitBounds(this.markers.getBounds().pad(0.2));
                        logger.log('Map bounds fitted to ports');
                    } else {
                        // Fallback bounds for Fiji
                        this.map.fitBounds([[-18.0, 177.0], [-17.0, 179.0]]);
                    }
                }, 500);

                logger.log('Map initialization complete');
            } catch (error) {
                logger.error('Map initialization failed:', error);
                this.showMapError(mapEl);
            }
        }

        addBaseLayers() {
            const theme = document.documentElement.getAttribute('data-theme') || 'light';
            logger.log(`Adding base layers for theme: ${theme}`);

            let tileUrl, attribution;

            if (theme === 'dark') {
                // Dark theme - use CartoDB dark tiles for better contrast
                tileUrl = 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png';
                attribution = '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors © <a href="https://carto.com/attributions">CARTO</a>';
            } else {
                // Light theme - standard OpenStreetMap tiles
                tileUrl = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
                attribution = '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';
            }

            // Add tile layer to map
            const tileLayer = L.tileLayer(tileUrl, {
                attribution: attribution,
                maxZoom: 18,
                minZoom: 6,
                detectRetina: true,
                opacity: theme === 'dark' ? 0.95 : 1.0
            });

            tileLayer.addTo(this.map);
            logger.log(`Added tile layer: ${tileUrl}`);

            // Add zoom control
            L.control.zoom({
                position: 'topright',
                zoomInTitle: 'Zoom in',
                zoomOutTitle: 'Zoom out'
            }).addTo(this.map);

            // Add scale control
            L.control.scale({
                position: 'bottomleft',
                metric: true,
                imperial: false,
                maxWidth: 200
            }).addTo(this.map);

            // Add attribution control with custom styling
            const attributionControl = L.control.attribution({
                position: 'bottomright',
                prefix: false
            });
            attributionControl.addTo(this.map);

            // Style attribution for theme
            const attributionContainer = attributionControl.getContainer();
            if (attributionContainer) {
                attributionContainer.style.padding = '2px 6px';
                attributionContainer.style.background = theme === 'dark' ? 'rgba(15, 23, 42, 0.8)' : 'rgba(255, 255, 255, 0.8)';
                attributionContainer.style.borderRadius = '4px';
                attributionContainer.style.fontSize = '12px';
                attributionContainer.style.color = theme === 'dark' ? '#E2E8F0' : '#64748B';
            }
        }

        addFijiPorts() {
            logger.log('Adding Fiji port markers');

            // Create layer group for markers
            this.markers = L.layerGroup();

            // Static Fiji ports data (reliable, no API dependency)
            const ports = [
                {
                    coords: [-17.755, 177.443],
                    name: 'Nadi International Airport',
                    type: 'major',
                    description: 'Main international gateway and ferry hub',
                    routes: ['Denarau Marina', 'Mamanuca Islands', 'Yasawa Islands'],
                    iconColor: '#EF4444'
                },
                {
                    coords: [-18.141, 178.425],
                    name: 'Suva Harbor',
                    type: 'major',
                    description: "Fiji's capital city main port",
                    routes: ['Nadi', 'Lautoka', 'Levuka', 'Vanua Levu'],
                    iconColor: '#3B82F6'
                },
                {
                    coords: [-17.759, 177.376],
                    name: 'Denarau Marina',
                    type: 'tourist',
                    description: 'Luxury resort and yacht marina gateway',
                    routes: ['Nadi', 'Mamanuca Islands', 'Malolo Lailai'],
                    iconColor: '#F59E0B'
                },
                {
                    coords: [-17.200, 177.000],
                    name: 'Yasawa Islands (Gateway)',
                    type: 'tourist',
                    description: 'Remote paradise island chain entry point',
                    routes: ['Denarau', 'Nadi', 'Port Denarau'],
                    iconColor: '#8B5CF6'
                },
                {
                    coords: [-17.717, 177.450],
                    name: 'Lautoka Wharf',
                    type: 'regional',
                    description: 'Sugar City regional ferry terminal',
                    routes: ['Suva', 'Viti Levu Coast', 'Momi Bay'],
                    iconColor: '#10B981'
                },
                {
                    coords: [-17.833, 178.167],
                    name: 'Nausori International',
                    type: 'regional',
                    description: 'Eastern Viti Levu domestic hub',
                    routes: ['Suva', 'Levuka', 'Lomaiviti Group'],
                    iconColor: '#06B6D4'
                }
            ];

            ports.forEach((port, index) => {
                // Create custom animated marker icon
                const icon = L.divIcon({
                    html: `
                        <div style="
                            position: relative;
                            width: 20px;
                            height: 20px;
                        ">
                            <div style="
                                background: ${port.iconColor};
                                width: 12px;
                                height: 12px;
                                border-radius: 50%;
                                border: 3px solid white;
                                box-shadow: 0 2px 8px rgba(0,0,0,0.3);
                                position: absolute;
                                top: 4px;
                                left: 4px;
                                transition: all 0.3s ease;
                                animation: pulse-marker 2s infinite;
                            "></div>
                            <div style="
                                position: absolute;
                                top: 0;
                                left: 0;
                                width: 20px;
                                height: 20px;
                                border: 2px solid ${port.iconColor};
                                border-radius: 50%;
                                opacity: 0.4;
                                animation: pulse-ring 2s infinite;
                            "></div>
                        </div>
                    `,
                    className: 'port-marker',
                    iconSize: [20, 20],
                    iconAnchor: [10, 10],
                    popupAnchor: [0, -10]
                });

                // Create marker instance
                const marker = L.marker(port.coords, { icon });
                marker.addTo(this.markers);

                // Enhanced interactive popup
                const popupContent = `
                    <div style="min-width: 220px; padding: 16px; font-family: 'Inter', sans-serif;">
                        <div style="display: flex; align-items: center; gap: 8px; margin-bottom: 8px;">
                            <div style="
                                background: ${port.iconColor};
                                width: 12px;
                                height: 12px;
                                border-radius: 50%;
                                border: 2px solid white;
                                flex-shrink: 0;
                            "></div>
                            <h3 style="margin: 0; font-size: 16px; font-weight: 600; color: ${port.iconColor};">
                                ${port.name}
                            </h3>
                        </div>
                        <p style="margin: 0 0 12px 0; font-size: 14px; color: #666; line-height: 1.5;">
                            ${port.description}
                        </p>
                        <div style="margin-bottom: 12px; font-size: 13px; color: #888;">
                            <strong style="color: #333;">Routes:</strong><br>
                            <span style="color: #666;">${port.routes.join(', ')}</span>
                        </div>
                        <div style="text-align: center; margin-top: 12px;">
                            <button onclick="FijiFerry?.homepage?.components?.get('form')?.quickSearch('${port.name.toLowerCase().replace(/ /g, '-')}'); L.DomEvent.stopPropagation(event);"
                                    style="
                                        background: linear-gradient(135deg, ${port.iconColor} 0%, ${this.lightenColor(port.iconColor, 20)});
                                        color: white;
                                        border: none;
                                        padding: 8px 16px;
                                        border-radius: 6px;
                                        cursor: pointer;
                                        font-size: 13px;
                                        font-weight: 500;
                                        transition: all 0.2s ease;
                                        width: 100%;
                                    "
                                    onmouseover="this.style.transform='translateY(-1px)'; this.style.boxShadow='0 4px 12px rgba(0,0,0,0.15)';"
                                    onmouseout="this.style.transform='translateY(0)'; this.style.boxShadow='none';">
                                <i class="fas fa-search mr-1"></i>
                                View Schedules
                            </button>
                        </div>
                    </div>
                `;

                marker.bindPopup(popupContent, {
                    maxWidth: 280,
                    minWidth: 220,
                    className: 'custom-popup port-popup',
                    closeButton: true,
                    autoClose: true,
                    closeOnEscapeKey: true,
                    keepInView: true
                });

                // Add click handler for quick search (outside popup)
                marker.on('click', (e) => {
                    // Prevent popup if clicking marker directly
                    L.DomEvent.stopPropagation(e.originalEvent);

                    const notificationManager = FijiFerry.notificationManager || new NotificationManager();
                    notificationManager.show(`Loading schedules for ${port.name}...`, 'info', 2000);

                    // Trigger form search
                    const formManager = FijiFerry.homepage?.components?.get('form');
                    if (formManager && formManager.quickSearch) {
                        formManager.quickSearch(port.name.toLowerCase().replace(/ /g, '-'));
                    }

                    // Scroll to form
                    const form = document.getElementById('search-form');
                    if (form) {
                        form.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    }
                });

                // Add hover effect
                marker.on('mouseover', () => {
                    if (this.map) {
                        this.map.setZoomAround(port.coords, this.map.getZoom() + 0.5, { animate: true });
                    }
                });

                marker.on('mouseout', () => {
                    if (this.map) {
                        this.map.setZoomAround(port.coords, this.map.getZoom() - 0.5, { animate: true });
                    }
                });
            });

            // Add all markers to map
            this.markers.addTo(this.map);
            logger.log(`Successfully added ${ports.length} port markers`);

            // Add CSS animations for marker effects
            if (!document.getElementById('marker-animations')) {
                const style = document.createElement('style');
                style.id = 'marker-animations';
                style.textContent = `
                    @keyframes pulse-marker {
                        0%, 100% { transform: scale(1); opacity: 1; }
                        50% { transform: scale(1.1); opacity: 0.7; }
                    }
                    @keyframes pulse-ring {
                        0% { transform: scale(0.8); opacity: 0.5; }
                        50% { transform: scale(1.2); opacity: 0.2; }
                        100% { transform: scale(1.4); opacity: 0; }
                    }
                    .port-marker {
                        cursor: pointer !important;
                    }
                    .custom-popup .leaflet-popup-content-wrapper {
                        background: #ffffff;
                        border-radius: 8px;
                        box-shadow: 0 10px 30px rgba(0,0,0,0.1);
                        border: 1px solid #e5e7eb;
                    }
                    [data-theme="dark"] .custom-popup .leaflet-popup-content-wrapper {
                        background: #1e293b;
                        color: #f1f5f9;
                        border-color: #334155;
                        box-shadow: 0 10px 30px rgba(0,0,0,0.3);
                    }
                    .custom-popup .leaflet-popup-content {
                        margin: 0;
                        font-family: 'Inter', sans-serif;
                    }
                    .custom-popup .leaflet-popup-tip {
                        background: #ffffff;
                        box-shadow: 0 2px 8px rgba(0,0,0,0.1);
                    }
                    [data-theme="dark"] .custom-popup .leaflet-popup-tip {
                        background: #1e293b;
                        box-shadow: 0 2px 8px rgba(0,0,0,0.3);
                    }
                `;
                document.head.appendChild(style);
            }
        }

        setupControls() {
            logger.log('Setting up map controls');

            const legendItems = document.querySelectorAll('.legend-item');
            legendItems.forEach((item, index) => {
                // Skip if item doesn't exist
                if (!item) return;

                // Make legend interactive
                item.addEventListener('click', (e) => {
                    e.preventDefault();
                    item.classList.toggle('active');

                    // Visual feedback
                    const type = item.dataset.type;
                    const isActive = item.classList.contains('active');
                    item.style.background = isActive ? 'rgba(16, 185, 129, 0.1)' : 'transparent';

                    const notificationManager = FijiFerry.notificationManager || new NotificationManager();
                    notificationManager.show(
                        `${type.charAt(0).toUpperCase() + type.slice(1)} layer ${isActive ? 'enabled' : 'disabled'}`,
                        'info',
                        1500
                    );
                });

                // Keyboard accessibility
                item.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        item.click();
                    }
                });

                // Focus styling
                item.addEventListener('focus', () => {
                    item.style.outline = '2px solid #10B981';
                    item.style.outlineOffset = '2px';
                });

                item.addEventListener('blur', () => {
                    item.style.outline = 'none';
                });

                // ARIA attributes
                item.setAttribute('role', 'button');
                item.setAttribute('tabindex', '0');
                item.setAttribute('aria-pressed', 'false');
            });

            // Add fullscreen control if supported
            if (this.map && document.fullscreenEnabled !== undefined) {
                const fullscreenBtn = L.control({ position: 'topright' });
                fullscreenBtn.onAdd = (map) => {
                    const div = L.DomUtil.create('div', 'leaflet-bar leaflet-control leaflet-control-custom fullscreen-control');
                    div.innerHTML = '<i class="fas fa-expand"></i>';
                    div.style.cssText = `
                        background: rgba(255, 255, 255, 0.8);
                        width: 30px; height: 30px;
                        line-height: 30px; text-align: center;
                        cursor: pointer; border-radius: 4px;
                        font-size: 14px; color: #333;
                        box-shadow: 0 1px 5px rgba(0,0,0,0.4);
                        transition: all 0.2s ease;
                    `;

                    div.addEventListener('click', (e) => {
                        L.DomEvent.stopPropagation(e);
                        if (!document.fullscreenElement) {
                            map.getContainer().requestFullscreen().catch(err => {
                                logger.error('Fullscreen failed:', err);
                            });
                        } else {
                            document.exitFullscreen();
                        }
                    });

                    div.addEventListener('mouseenter', () => {
                        div.style.background = 'rgba(255, 255, 255, 0.95)';
                        div.style.transform = 'scale(1.05)';
                    });

                    div.addEventListener('mouseleave', () => {
                        div.style.background = 'rgba(255, 255, 255, 0.8)';
                        div.style.transform = 'scale(1)';
                    });

                    return div;
                };
                fullscreenBtn.addTo(this.map);
            }

            // Add locate control
            if (navigator.geolocation) {
                const locateBtn = L.control({ position: 'topright' });
                locateBtn.onAdd = (map) => {
                    const div = L.DomUtil.create('div', 'leaflet-bar leaflet-control leaflet-control-custom locate-control');
                    div.innerHTML = '<i class="fas fa-location-arrow"></i>';
                    div.style.cssText = `
                        background: rgba(255, 255, 255, 0.8);
                        width: 30px; height: 30px;
                        line-height: 30px; text-align: center;
                        cursor: pointer; border-radius: 4px;
                        font-size: 14px; color: #333;
                        box-shadow: 0 1px 5px rgba(0,0,0,0.4);
                        transition: all 0.2s ease;
                        margin-top: 5px;
                    `;

                    div.addEventListener('click', (e) => {
                        L.DomEvent.stopPropagation(e);
                        div.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';

                        navigator.geolocation.getCurrentPosition(
                            (position) => {
                                const latlng = [position.coords.latitude, position.coords.longitude];
                                map.setView(latlng, 10);
                                div.innerHTML = '<i class="fas fa-location-arrow"></i>';

                                // Add temporary marker
                                L.marker(latlng).addTo(map)
                                    .bindPopup('Your Location')
                                    .openPopup();

                                const notificationManager = FijiFerry.notificationManager || new NotificationManager();
                                notificationManager.show('Showing your location on the map', 'success', 2000);
                            },
                            (error) => {
                                div.innerHTML = '<i class="fas fa-location-arrow"></i>';
                                logger.error('Geolocation error:', error);
                                const notificationManager = FijiFerry.notificationManager || new NotificationManager();
                                notificationManager.show('Unable to get your location', 'warning', 3000);
                            },
                            { timeout: 10000 }
                        );
                    });

                    return div;
                };
                locateBtn.addTo(this.map);
            }
        }

        setupThemeListener() {
            const observer = new MutationObserver(() => {
                if (this.map) {
                    logger.log('Map theme change detected, updating layers');
                    this.addBaseLayers(); // Re-add tile layers for new theme

                    // Update attribution styling
                    const attributionControl = this.map.attributionControl;
                    if (attributionControl) {
                        const container = attributionControl.getContainer();
                        const theme = document.documentElement.getAttribute('data-theme') || 'light';
                        if (container) {
                            container.style.color = theme === 'dark' ? '#E2E8F0' : '#64748B';
                            container.style.background = theme === 'dark' ? 'rgba(15, 23, 42, 0.8)' : 'rgba(255, 255, 255, 0.8)';
                            container.style.borderRadius = '4px';
                            container.style.padding = '2px 6px';
                        }
                    }

                    // Update marker colors if needed
                    this.updateMarkerTheme();
                }
            });

            observer.observe(document.documentElement, {
                attributes: true,
                attributeFilter: ['data-theme']
            });
        }

        updateMarkerTheme() {
            const theme = document.documentElement.getAttribute('data-theme') || 'light';
            if (this.markers) {
                this.markers.eachLayer(marker => {
                    // Update marker styling based on theme
                    const icon = marker.options.icon;
                    if (icon && icon.options && icon.options.html) {
                        // Recreate marker with theme-appropriate styling
                        const newIcon = L.divIcon({
                            html: icon.options.html.replace(/border:\s*2px\s*solid\s*#fff/g,
                                `border: 2px solid ${theme === 'dark' ? '#1E293B' : '#fff'}`),
                            className: icon.options.className,
                            iconSize: icon.options.iconSize,
                            iconAnchor: icon.options.iconAnchor
                        });
                        marker.setIcon(newIcon);
                    }
                });
            }
        }

        showMapError(container) {
            logger.error('Showing map error state');
            container.innerHTML = `
                <div class="p-8 text-center rounded-lg border" style="
                    background: linear-gradient(135deg, #fef2f2 0%, #fee2e2 100%);
                    border: 2px solid #fecaca;
                    color: #dc2626;
                    box-shadow: 0 4px 12px rgba(239, 68, 68, 0.15);
                ">
                    <div style="font-size: 4rem; margin-bottom: 1rem; line-height: 1;">🗺️</div>
                    <h3 style="margin: 0 0 0.75rem 0; font-size: 1.5rem; font-weight: 700; color: #b91c1c;">Map Loading Issue</h3>
                    <p style="margin: 0 0 1.5rem 0; line-height: 1.6; font-size: 1rem; color: #991b1b;">
                        Unable to load the interactive Fiji map. This could be due to a network issue or browser compatibility problem.
                    </p>
                    <div style="display: flex; gap: 1rem; justify-content: center; flex-wrap: wrap; margin-top: 1rem;">
                        <button onclick="location.reload()"
                                style="
                                    background: linear-gradient(135deg, #10b981 0%, #059669 100%);
                                    color: white;
                                    border: none;
                                    padding: 0.875rem 1.75rem;
                                    border-radius: 8px;
                                    cursor: pointer;
                                    font-weight: 600;
                                    font-size: 0.95rem;
                                    transition: all 0.2s ease;
                                    box-shadow: 0 4px 12px rgba(16, 185, 129, 0.3);
                                "
                                onmouseover="this.style.transform='translateY(-2px)'; this.style.boxShadow='0 6px 16px rgba(16, 185, 129, 0.4)';"
                                onmouseout="this.style.transform='translateY(0)'; this.style.boxShadow='0 4px 12px rgba(16, 185, 129, 0.3)';">
                            🔄 Try Again
                        </button>
                        <button onclick="FijiFerry?.homepage?.components?.get('form')?.quickSearch('nadi'); this.closest('.p-8').parentElement.remove();"
                                style="
                                    background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
                                    color: white;
                                    border: none;
                                    padding: 0.875rem 1.75rem;
                                    border-radius: 8px;
                                    cursor: pointer;
                                    font-weight: 600;
                                    font-size: 0.95rem;
                                    transition: all 0.2s ease;
                                    box-shadow: 0 4px 12px rgba(59, 130, 246, 0.3);
                                "
                                onmouseover="this.style.transform='translateY(-2px)'; this.style.boxShadow='0 6px 16px rgba(59, 130, 246, 0.4)';"
                                onmouseout="this.style.transform='translateY(0)'; this.style.boxShadow='0 4px 12px rgba(59, 130, 246, 0.3)';">
                            🏝️ Browse Routes
                        </button>
                    </div>
                    <div style="margin-top: 1.5rem; padding-top: 1rem; border-top: 1px solid #fecaca; font-size: 0.875rem; color: #991b1b;">
                        <i class="fas fa-info-circle mr-1"></i>
                        Try refreshing the page or checking your internet connection.
                    </div>
                </div>
            `;
        }

        handleResize() {
            if (this.map) {
                // Debounced resize to prevent layout thrashing
                clearTimeout(this.resizeTimeout);
                this.resizeTimeout = setTimeout(() => {
                    this.map.invalidateSize({ animate: false, pan: false });
                    logger.log('Map resized');
                }, 250);
            }
        }

        destroy() {
            if (this.map) {
                this.map.remove();
                this.map = null;
            }
            this.isInitialized = false;
            this.markers = null;
            logger.log('MapManager destroyed');
        }

        lightenColor(hex, percent) {
            // Helper function to lighten hex colors for gradients
            const num = parseInt(hex.replace("#", ""), 16);
            const amt = Math.round(2.55 * percent);
            const R = (num >> 16) + amt;
            const G = (num >> 8 & 0x00FF) + amt;
            const B = (num & 0x0000FF) + amt;
            return "#" + (0x1000000 + (R < 255 ? R < 1 ? 0 : R : 255) * 0x10000 +
                (G < 255 ? G < 1 ? 0 : G : 255) * 0x100 +
                (B < 255 ? B < 1 ? 0 : B : 255)).toString(16).slice(1);
        }
    }

    // 🚤 SCHEDULE MANAGER (Enhanced for dark mode)
    class ScheduleManager {
        constructor(serverData = {}) {
            this.cards = new Map();
            this.serverData = serverData;
            this.isInitialized = false;
            this.init();
        }

        init() {
            if (this.isInitialized) return;
            this.isInitialized = true;

            logger.log('Initializing ScheduleManager');
            this.cacheScheduleCards();
            this.setupEventListeners();
            this.updateWeatherDisplay();
            this.setupThemeListener();
        }

        setupThemeListener() {
            const observer = new MutationObserver(() => {
                logger.log('Schedule theme change detected');
                this.updateCardsTheme();
            });
            observer.observe(document.documentElement, {
                attributes: true,
                attributeFilter: ['data-theme']
            });
        }

        updateCardsTheme() {
            const theme = document.documentElement.getAttribute('data-theme') || 'light';
            logger.log(`Updating ${this.cards.size} schedule cards for theme: ${theme}`);

            this.cards.forEach((card) => {
                if (!card || !card.parentNode) return;

                // Update card base styling
                card.classList.toggle('dark-mode', theme === 'dark');

                // Route info section
                const routeInfo = card.querySelector('.route-info');
                if (routeInfo) {
                    routeInfo.classList.toggle('dark-mode', theme === 'dark');
                    routeInfo.style.background = theme === 'dark' ? '#1E293B' : 'white';
                    routeInfo.style.color = theme === 'dark' ? '#F1F5F9' : '#1E293B';
                }

                // Schedule footer
                const scheduleFooter = card.querySelector('.schedule-footer');
                if (scheduleFooter) {
                    scheduleFooter.classList.toggle('dark-mode', theme === 'dark');
                    scheduleFooter.style.background = theme === 'dark' ? '#334155' : '#F9FAFB';
                    scheduleFooter.style.borderColor = theme === 'dark' ? '#475569' : '#E5E7EB';
                }

                // Weather info section
                const weatherInfo = card.querySelector('.weather-info');
                if (weatherInfo) {
                    weatherInfo.classList.toggle('dark-mode', theme === 'dark');
                    if (theme === 'dark') {
                        weatherInfo.style.background = 'linear-gradient(135deg, #1E3A8A 0%, #1E40AF 100%)';
                        weatherInfo.style.borderColor = '#1E40AF';
                        weatherInfo.style.color = '#E2E8F0';
                    } else {
                        weatherInfo.style.background = 'linear-gradient(135deg, #EFF6FF 0%, #DBEAFE 100%)';
                        weatherInfo.style.borderColor = '#BFDBFE';
                        weatherInfo.style.color = '#1E293B';
                    }
                }

                // Update text colors for all text elements
                const textElements = card.querySelectorAll('.text-gray-800, .text-gray-600, .text-gray-500, .text-gray-400, .text-gray-300, .text-gray-200, .text-gray-100');
                textElements.forEach(el => {
                    const classList = el.className;
                    if (classList.includes('text-gray-800')) {
                        el.style.color = Utils.getThemeColor('gray800');
                    } else if (classList.includes('text-gray-600')) {
                        el.style.color = Utils.getThemeColor('gray600');
                    } else if (classList.includes('text-gray-500')) {
                        el.style.color = Utils.getThemeColor('gray500');
                    } else if (classList.includes('text-gray-400')) {
                        el.style.color = Utils.getThemeColor('gray400');
                    } else if (classList.includes('text-gray-300')) {
                        el.style.color = Utils.getThemeColor('gray300');
                    } else if (classList.includes('text-gray-200')) {
                        el.style.color = Utils.getThemeColor('gray200');
                    } else if (classList.includes('text-gray-100')) {
                        el.style.color = Utils.getThemeColor('gray100');
                    }
                });

                // Update status badges
                const statusBadges = card.querySelectorAll('.status-badge');
                statusBadges.forEach(badge => {
                    const themeClass = theme === 'dark' ? 'dark-mode' : '';
                    badge.classList.toggle('dark-mode', theme === 'dark');

                    // Update badge colors based on status
                    const status = badge.textContent.toLowerCase().trim();
                    if (status.includes('scheduled')) {
                        badge.style.background = theme === 'dark' ? 'rgba(16, 185, 129, 0.2)' : '#D1FAE5';
                        badge.style.color = theme === 'dark' ? '#34D399' : '#10B981';
                    } else if (status.includes('delayed')) {
                        badge.style.background = theme === 'dark' ? 'rgba(245, 158, 11, 0.2)' : '#FEF3C7';
                        badge.style.color = theme === 'dark' ? '#FBBF24' : '#D97706';
                    } else if (status.includes('cancelled')) {
                        badge.style.background = theme === 'dark' ? 'rgba(239, 68, 68, 0.2)' : '#FEE2E2';
                        badge.style.color = theme === 'dark' ? '#FCA5A5' : '#EF4444';
                    }
                });

                // Update price styling
                const priceEl = card.querySelector('.price');
                if (priceEl) {
                    priceEl.style.color = Utils.getThemeColor('text');
                }

                // Update quick action buttons
                const quickBtns = card.querySelectorAll('.quick-btn');
                quickBtns.forEach(btn => {
                    const isDark = theme === 'dark';
                    btn.classList.toggle('dark-mode', isDark);

                    if (btn.querySelector('i.far.fa-heart')) {
                        // Save button
                        btn.style.background = isDark ? '#374151' : '#F3F4F6';
                        btn.style.color = isDark ? '#D1D5DB' : '#6B7280';
                        btn.onmouseover = () => btn.style.background = isDark ? '#4B5563' : '#E5E7EB';
                        btn.onmouseout = () => btn.style.background = isDark ? '#374151' : '#F3F4F6';
                    } else if (btn.querySelector('i.fas.fa-share-alt')) {
                        // Share button
                        btn.style.background = isDark ? '#1E40AF' : '#DBEAFE';
                        btn.style.color = isDark ? '#93C5FD' : '#2563EB';
                        btn.onmouseover = () => btn.style.background = isDark ? '#1D4ED8' : '#BFDBFE';
                        btn.onmouseout = () => btn.style.background = isDark ? '#1E40AF' : '#DBEAFE';
                    }
                });

                // Update book button
                const bookBtn = card.querySelector('.book-btn');
                if (bookBtn) {
                    bookBtn.style.background = 'linear-gradient(135deg, #10B981 0%, #059669 100%)';
                    bookBtn.onmouseover = () => bookBtn.style.background = 'linear-gradient(135deg, #059669 0%, #047857 100%)';
                    bookBtn.onmouseout = () => bookBtn.style.background = 'linear-gradient(135deg, #10B981 0%, #059669 100%)';
                }
            });
        }

        cacheScheduleCards() {
            this.cards.clear();
            document.querySelectorAll('.schedule-card').forEach(card => {
                const id = card.dataset.scheduleId;
                if (id) {
                    this.cards.set(id, card);
                }
            });
            logger.log(`Cached ${this.cards.size} schedule cards`);
        }

        setupEventListeners() {
            logger.log('Setting up schedule event listeners');

            // Sorting functionality
            const sortSelect = document.getElementById('sort-by');
            if (sortSelect) {
                sortSelect.addEventListener('change', (e) => {
                    logger.log(`Sorting schedules by: ${e.target.value}`);
                    this.sortSchedules(e.target.value);
                });
            }

            // Quick action delegation (for both existing and dynamically added cards)
            document.addEventListener('click', (e) => {
                const saveBtn = e.target.closest('[onclick*="saveSchedule"], .quick-btn:has(i.fa-heart)');
                if (saveBtn) {
                    e.preventDefault();
                    e.stopPropagation();
                    const scheduleId = e.target.closest('.schedule-card')?.dataset.scheduleId;
                    if (scheduleId) {
                        this.toggleSave(scheduleId, saveBtn);
                    }
                    return;
                }

                const shareBtn = e.target.closest('[onclick*="shareSchedule"], .quick-btn:has(i.fa-share-alt)');
                if (shareBtn) {
                    e.preventDefault();
                    e.stopPropagation();
                    const scheduleId = e.target.closest('.schedule-card')?.dataset.scheduleId;
                    if (scheduleId) {
                        this.shareSchedule(scheduleId);
                    }
                    return;
                }

                // Load more button
                const loadMoreBtn = e.target.closest('#load-more-schedules');
                if (loadMoreBtn) {
                    e.preventDefault();
                    this.loadMoreSchedules();
                }
            }, { passive: false });

            // Schedule card hover effects
            document.addEventListener('mouseenter', (e) => {
                const card = e.target.closest('.schedule-card');
                if (card && !card.classList.contains('hovered')) {
                    card.classList.add('hovered');
                    // Add subtle glow effect
                    card.style.boxShadow = '0 20px 40px rgba(0,0,0,0.1)';
                }
            }, true);

            document.addEventListener('mouseleave', (e) => {
                const card = e.target.closest('.schedule-card');
                if (card) {
                    card.classList.remove('hovered');
                    card.style.boxShadow = '';
                }
            }, true);
        }

        sortSchedules(sortBy) {
            const container = document.getElementById('schedule-list');
            if (!container || !this.cards.size) {
                logger.warn('Cannot sort: no container or cards found');
                return;
            }

            logger.log(`Sorting ${this.cards.size} cards by: ${sortBy}`);

            const cards = Array.from(this.cards.values()).filter(card => card.parentNode);
            if (!cards.length) return;

            cards.sort((a, b) => {
                switch(sortBy) {
                    case 'price':
                        const priceA = parseFloat(a.dataset.price || 999);
                        const priceB = parseFloat(b.dataset.price || 999);
                        return priceA - priceB;
                    case 'duration':
                        const aDuration = a.querySelector('.duration dd')?.textContent || '0h';
                        const bDuration = b.querySelector('.duration dd')?.textContent || '0h';
                        const durationA = this.parseDuration(aDuration);
                        const durationB = this.parseDuration(bDuration);
                        return durationA - durationB;
                    case 'time':
                    default:
                        const aTime = new Date(a.querySelector('.departure-time')?.getAttribute('datetime') || Date.now()).getTime();
                        const bTime = new Date(b.querySelector('.departure-time')?.getAttribute('datetime') || Date.now()).getTime();
                        return aTime - bTime;
                }
            });

            // Clear container and re-append with animation
            container.style.transition = 'none';
            container.innerHTML = '';

            cards.forEach((card, index) => {
                container.appendChild(card);
                card.style.opacity = '0';
                card.style.transform = 'translateY(20px) scale(0.98)';
                card.style.transition = 'all 0.4s cubic-bezier(0.4, 0, 0.2, 1)';

                requestAnimationFrame(() => {
                    card.style.opacity = '1';
                    card.style.transform = 'translateY(0) scale(1)';
                });

                // Stagger animation
                setTimeout(() => {}, index * 75);
            });

            // Update URL without page reload
            const url = new URL(window.location);
            if (sortBy !== 'time') {
                url.searchParams.set('sort', sortBy);
            } else {
                url.searchParams.delete('sort');
            }
            window.history.replaceState({}, '', url);

            const notificationManager = FijiFerry.notificationManager || new NotificationManager();
            notificationManager.show(`Sorted by ${sortBy.replace('_', ' ')}`, 'info', 1500);

            // Update sort select display
            const sortSelect = document.getElementById('sort-by');
            if (sortSelect) {
                Array.from(sortSelect.options).forEach(option => {
                    option.selected = option.value === sortBy;
                });
            }

            logger.log(`Sorting complete: ${sortBy}`);
        }

        parseDuration(text) {
            if (!text) return Infinity;
            // Handle both "2h" and "2h 30m" formats
            const hoursMatch = text.match(/(\d+)h/i);
            const minutesMatch = text.match(/(\d+)m/i);
            const hours = hoursMatch ? parseInt(hoursMatch[1]) : 0;
            const minutes = minutesMatch ? parseInt(minutesMatch[1]) : 0;
            return hours * 60 + minutes;
        }

        toggleSave(scheduleId, button) {
            if (!button) {
                logger.warn('No button element provided for toggleSave');
                return;
            }

            const icon = button.querySelector('i');
            if (!icon) {
                logger.warn('No icon found in save button');
                return;
            }

            const isSaved = icon.classList.contains('fas');
            const theme = document.documentElement.getAttribute('data-theme') || 'light';

            if (isSaved) {
                // Remove from favorites
                icon.classList.remove('fas', 'text-red-500');
                icon.classList.add('far');
                button.title = 'Save to favorites';
                button.setAttribute('aria-label', 'Save this schedule to favorites');

                const notificationManager = FijiFerry.notificationManager || new NotificationManager();
                notificationManager.show('Removed from favorites ❤️', 'info', 2000);

                logger.log(`Schedule ${scheduleId} removed from favorites`);
            } else {
                // Add to favorites
                icon.classList.remove('far');
                icon.classList.add('fas', 'text-red-500');
                button.title = 'Remove from favorites';
                button.setAttribute('aria-label', 'Remove this schedule from favorites');

                const notificationManager = FijiFerry.notificationManager || new NotificationManager();
                notificationManager.show('Added to favorites ❤️', 'success', 2000);

                logger.log(`Schedule ${scheduleId} added to favorites`);
            }

            // Update button styling for theme
            button.style.background = theme === 'dark' ? '#374151' : '#F3F4F6';
            button.onmouseover = () => {
                button.style.background = theme === 'dark' ? '#4B5563' : '#E5E7EB';
            };
            button.onmouseout = () => {
                button.style.background = theme === 'dark' ? '#374151' : '#F3F4F6';
            };
        }

        shareSchedule(scheduleId) {
            const card = this.cards.get(scheduleId);
            if (!card) {
                logger.warn(`Schedule card not found: ${scheduleId}`);
                return;
            }

            const routeName = card.querySelector('h3')?.textContent?.trim() || 'Ferry Schedule';
            const time = card.querySelector('.departure-time')?.textContent?.trim() || '';
            const price = card.querySelector('.price')?.textContent?.trim() || '';

            const shareData = {
                title: `Fiji Ferry: ${routeName}`,
                text: `${routeName} - ${time}${price ? ` (${price})` : ''}`,
                url: `${window.location.origin}/bookings/book/?schedule_id=${scheduleId}`
            };

            logger.log(`Sharing schedule ${scheduleId}:`, shareData);

            if (navigator.share && navigator.canShare && navigator.canShare(shareData)) {
                navigator.share(shareData)
                    .then(() => logger.log('Schedule shared successfully'))
                    .catch((error) => {
                        logger.warn('Share failed, falling back to copy:', error);
                        this.copyToClipboard(shareData.url, 'Schedule link copied to clipboard!');
                    });
            } else {
                // Fallback to clipboard
                this.copyToClipboard(shareData.url, 'Schedule link copied to clipboard!');
            }
        }

        copyToClipboard(text, message = 'Copied to clipboard!') {
            if (!text) {
                logger.warn('No text provided for clipboard copy');
                return;
            }

            navigator.clipboard.writeText(text)
                .then(() => {
                    const notificationManager = FijiFerry.notificationManager || new NotificationManager();
                    notificationManager.show(message, 'success', 2000);
                    logger.log('Text copied to clipboard:', text.substring(0, 50) + '...');
                })
                .catch((error) => {
                    logger.warn('Clipboard API failed:', error);
                    // Fallback to execCommand
                    const textArea = document.createElement('textarea');
                    textArea.value = text;
                    textArea.style.position = 'fixed';
                    textArea.style.left = '-999999px';
                    textArea.style.top = '-999999px';
                    document.body.appendChild(textArea);
                    textArea.focus();
                    textArea.select();

                    try {
                        const successful = document.execCommand('copy');
                        document.body.removeChild(textArea);

                        if (successful) {
                            const notificationManager = FijiFerry.notificationManager || new NotificationManager();
                            notificationManager.show(message, 'success', 2000);
                            logger.log('Fallback copy successful');
                        } else {
                            throw new Error('execCommand failed');
                        }
                    } catch (err) {
                        document.body.removeChild(textArea);
                        logger.error('Copy failed completely:', err);
                        const notificationManager = FijiFerry.notificationManager || new NotificationManager();
                        notificationManager.show('Unable to copy to clipboard', 'error', 3000);
                    }
                });
        }

        async loadMoreSchedules() {
            const loadMoreBtn = document.getElementById('load-more-schedules');
            if (!loadMoreBtn) {
                logger.warn('Load more button not found');
                return;
            }

            logger.log('Load more button clicked');

            const originalText = loadMoreBtn.innerHTML;
            const loadingIndicator = document.querySelector('.loading-indicator');
            const container = loadMoreBtn.closest('.load-more');

            // Update button state
            loadMoreBtn.innerHTML = '<i class="fas fa-spinner fa-spin mr-2"></i>Loading more schedules...';
            loadMoreBtn.disabled = true;
            loadMoreBtn.style.opacity = '0.7';
            loadMoreBtn.style.cursor = 'not-allowed';

            if (loadingIndicator) {
                loadingIndicator.classList.remove('hidden');
            }

            try {
                // Simulate API call with progressive enhancement
                logger.log('Fetching more schedules...');

                // In production, replace with actual API call:
                // const response = await fetch(`/api/schedules/?limit=6&offset=${this.cards.size}&${new URLSearchParams(window.location.search)}`);
                // const data = await response.json();

                // For now, generate mock data
                await new Promise(resolve => setTimeout(resolve, 1200 + Math.random() * 800));
                const newSchedules = this.generateMockSchedules(3 + Math.floor(Math.random() * 3));

                if (newSchedules.length === 0) {
                    // No more schedules
                    loadMoreBtn.innerHTML = '<i class="fas fa-check-circle mr-2 text-emerald-500"></i>All schedules loaded';
                    loadMoreBtn.style.opacity = '0.6';
                    loadMoreBtn.disabled = true;

                    setTimeout(() => {
                        if (container) {
                            container.style.opacity = '0';
                            container.style.transition = 'opacity 0.3s ease';
                            setTimeout(() => container.remove(), 300);
                        }
                    }, 2000);

                    const notificationManager = FijiFerry.notificationManager || new NotificationManager();
                    notificationManager.show('All available schedules loaded!', 'success', 2500);

                    return;
                }

                // Render new schedules
                const scheduleList = document.getElementById('schedule-list');
                if (scheduleList) {
                    this.renderSchedules(newSchedules, scheduleList);
                }

                // Update load more button
                const remainingEl = loadMoreBtn.querySelector('span:last-child');
                if (remainingEl) {
                    const currentRemaining = parseInt(remainingEl.textContent.match(/\((\d+) remaining\)/)?.[1] || 0);
                    const newRemaining = Math.max(0, currentRemaining - newSchedules.length);

                    if (newRemaining > 0) {
                        loadMoreBtn.innerHTML = `<i class="fas fa-plus mr-2"></i>Load More Schedules (${newRemaining} remaining)`;
                    } else {
                        loadMoreBtn.innerHTML = '<i class="fas fa-check-circle mr-2 text-emerald-500"></i>All schedules loaded';
                        loadMoreBtn.style.opacity = '0.6';
                        loadMoreBtn.disabled = true;

                        setTimeout(() => {
                            if (container) {
                                container.remove();
                            }
                        }, 3000);
                    }
                }

                const notificationManager = FijiFerry.notificationManager || new NotificationManager();
                notificationManager.show(`${newSchedules.length} more schedules loaded!`, 'success', 2000);

                logger.log(`Loaded ${newSchedules.length} more schedules`);

            } catch (error) {
                logger.error('Load more failed:', error);

                loadMoreBtn.innerHTML = originalText;
                loadMoreBtn.disabled = false;
                loadMoreBtn.style.opacity = '1';
                loadMoreBtn.style.cursor = 'pointer';

                if (loadingIndicator) {
                    loadingIndicator.classList.add('hidden');
                }

                const notificationManager = FijiFerry.notificationManager || new NotificationManager();
                notificationManager.show('Failed to load more schedules. Please try again.', 'error', 4000);
            }
        }

        generateMockSchedules(count) {
            // Generate realistic mock data
            const routes = [
                'Nadi → Denarau Marina',
                'Denarau → Malolo Lailai',
                'Suva → Levuka',
                'Lautoka → Yasawa Islands',
                'Nadi → Mamanuca Islands'
            ];
            const times = ['09:15 AM', '11:30 AM', '02:45 PM', '04:20 PM', '06:50 PM', '08:15 PM'];
            const ferryNames = ['Fiji Sun', 'Pacific Explorer', 'Yasawa Princess', 'Nadi Express', 'Coral Discovery'];
            const prices = [25, 45, 35, 60, 28, 52, 38, 67];
            const durations = ['45m', '1h 15m', '2h 30m', '4h', '1h 45m', '3h 20m'];

            return Array.from({ length: count }, (_, i) => ({
                id: `mock-${Date.now()}-${i}`,
                route: routes[i % routes.length],
                departure_time: new Date(Date.now() + (i + 3) * 7200000).toISOString(), // 2 hours apart
                time: times[i % times.length],
                ferry: ferryNames[i % ferryNames.length],
                price: prices[i % prices.length],
                base_fare: prices[i % prices.length],
                available_seats: Math.floor(Math.random() * 20) + 5,
                seats: Math.floor(Math.random() * 20) + 5,
                duration: durations[i % durations.length],
                estimated_duration: Math.floor(Math.random() * 240) + 30, // 30-270 minutes
                status: 'scheduled',
                route_id: `mock-route-${i}`,
                departure_port: { name: routes[i % routes.length].split(' → ')[0] },
                destination_port: { name: routes[i % routes.length].split(' → ')[1] }
            }));
        }

        renderSchedules(schedules, container) {
            if (!container) {
                logger.warn('No container provided for rendering schedules');
                return;
            }

            logger.log(`Rendering ${schedules.length} schedules`);

            schedules.forEach((schedule, index) => {
                const card = this.createScheduleCard(schedule);
                if (!card) {
                    logger.warn(`Failed to create card for schedule ${schedule.id}`);
                    return;
                }

                // Insert with animation
                container.appendChild(card);
                this.cards.set(schedule.id, card);

                // Animate entrance
                card.style.opacity = '0';
                card.style.transform = 'translateY(30px) scale(0.95)';
                card.style.transition = 'all 0.5s cubic-bezier(0.4, 0, 0.2, 1)';

                requestAnimationFrame(() => {
                    card.style.opacity = '1';
                    card.style.transform = 'translateY(0) scale(1)';
                });

                // Stagger animations
                setTimeout(() => {}, index * 150);

                // Setup event listeners for new card
                this.setupNewCardListeners(card);

                logger.log(`Rendered schedule card: ${schedule.id}`);
            });

            // Update total count display
            this.updateScheduleCount();
        }

        createScheduleCard(schedule) {
            const theme = document.documentElement.getAttribute('data-theme') || 'light';
            const isDark = theme === 'dark';

            const div = document.createElement('div');
            div.className = `schedule-card transition-all duration-300 hover:shadow-lg hover:-translate-y-1 border rounded-xl overflow-hidden ${
                isDark ? 'dark-mode border-gray-700 bg-gray-800' : 'border-gray-200 bg-white'
            }`;
            div.dataset.scheduleId = schedule.id;
            div.dataset.routeId = schedule.route_id || 'mock';
            div.dataset.timeSlot = schedule.timeSlot || 'daytime';
            div.dataset.price = schedule.price || schedule.base_fare || 35;

            // Generate realistic departure time display
            const departureDateTime = new Date(schedule.departure_time || Date.now());
            const formattedDate = departureDateTime.toLocaleDateString('en-FJ', {
                weekday: 'short',
                month: 'short',
                day: 'numeric'
            });
            const formattedTime = departureDateTime.toLocaleTimeString('en-FJ', {
                hour: 'numeric',
                minute: '2-digit',
                hour12: true
            });

            div.innerHTML = `
                <div class="route-info p-6 ${isDark ? 'dark-mode' : ''}" style="background: ${isDark ? '#1E293B' : 'white'}; color: ${isDark ? '#F1F5F9' : '#1E293B'};">
                    <header class="mb-4">
                        <h3 class="text-xl font-bold mb-2 ${isDark ? 'text-gray-100' : 'text-gray-800'} font-poppins" id="schedule-${schedule.id}-title">
                            ${Utils.sanitizeHTML(schedule.route?.departure_port?.name || schedule.route?.split(' → ')[0] || 'Nadi')}
                            <span class="text-sm ${isDark ? 'text-gray-400' : 'text-gray-400'}" aria-hidden="true">→</span>
                            ${Utils.sanitizeHTML(schedule.route?.destination_port?.name || schedule.route?.split(' → ')[1] || 'Denarau')}
                        </h3>
                        <time class="departure-time text-sm ${isDark ? 'text-gray-300' : 'text-gray-600'} mb-1"
                              datetime="${departureDateTime.toISOString()}"
                              aria-label="Departure time: ${formattedDate} at ${formattedTime}">
                            ${formattedDate}, ${formattedTime}
                        </time>
                        <p class="ferry-name text-sm ${isDark ? 'text-gray-400' : 'text-gray-500'}">${schedule.ferry || 'Fiji Express'}</p>
                    </header>

                    <!-- Weather Info -->
                    <div class="weather-info flex items-center gap-3 p-3 rounded-lg mb-4 border ${isDark ? 'dark-mode border-gray-700 bg-gray-800' : 'border-gray-100 bg-gray-50'}"
                         style="${isDark ? 'background: linear-gradient(135deg, #1E3A8A 0%, #1E40AF 100%); border-color: #1E40AF; color: #E2E8F0;' : 'background: linear-gradient(135deg, #EFF6FF 0%, #DBEAFE 100%); border-color: #BFDBFE; color: #1E293B;'}"
                         aria-label="Weather forecast for departure">
                        <div class="weather-icon text-2xl flex-shrink-0" aria-hidden="true" id="weather-icon-${schedule.id}">🌤️</div>
                        <div class="weather-details flex-1 min-w-0">
                            <div class="weather-condition font-semibold text-sm truncate ${isDark ? 'text-gray-200' : 'text-gray-800'}"
                                 id="weather-condition-${schedule.id}" role="status" aria-live="polite">
                                Loading weather...
                            </div>
                            <div class="weather-meta flex gap-4 text-xs ${isDark ? 'text-gray-400' : 'text-gray-500'} mt-1 flex-wrap">
                                <span class="weather-temp inline-flex items-center gap-1" id="weather-temp-${schedule.id}" aria-label="Temperature">
                                    <i class="fas fa-thermometer-half ${isDark ? 'text-emerald-400' : 'text-emerald-500'}" aria-hidden="true"></i>
                                    <span>28°C</span>
                                </span>
                                <span class="weather-wind inline-flex items-center gap-1" id="weather-wind-${schedule.id}" aria-label="Wind speed">
                                    <i class="fas fa-wind ${isDark ? 'text-blue-400' : 'text-blue-500'}" aria-hidden="true"></i>
                                    <span>12 kph</span>
                                </span>
                                <span class="weather-precip inline-flex items-center gap-1" id="weather-precip-${schedule.id}" aria-label="Precipitation chance">
                                    <i class="fas fa-cloud-rain ${isDark ? 'text-gray-500' : 'text-gray-500'}" aria-hidden="true"></i>
                                    <span>5%</span>
                                </span>
                            </div>
                        </div>
                    </div>

                    <!-- Schedule Details -->
                    <dl class="schedule-meta grid grid-cols-2 gap-3 mb-4 text-sm ${isDark ? 'text-gray-300' : 'text-gray-600'}">
                        <div class="seats flex items-center gap-2">
                            <dt class="flex-shrink-0">
                                <i class="fas fa-chair ${isDark ? 'text-gray-500' : 'text-gray-400'}" aria-hidden="true"></i>
                            </dt>
                            <dd class="seats-count font-semibold ${isDark ? 'text-gray-100' : 'text-gray-800'}">${schedule.available_seats || schedule.seats || 12}</dd>
                            <span class="sr-only">seats available</span>
                        </div>
                        <div class="duration flex items-center gap-2 justify-end">
                            <dt class="flex-shrink-0">
                                <i class="fas fa-clock ${isDark ? 'text-gray-500' : 'text-gray-400'}" aria-hidden="true"></i>
                            </dt>
                            <dd>${schedule.duration || Utils.formatDuration(schedule.estimated_duration || 120)}</dd>
                            <span class="sr-only">estimated duration</span>
                        </div>
                    </dl>
                </div>

                <!-- Status & Price Footer -->
                <footer class="schedule-footer pt-4 border-t ${isDark ? 'dark-mode border-gray-700' : 'border-gray-200'} px-6 pb-6 ${isDark ? 'bg-gray-800' : 'bg-gray-50'}">
                    <div class="status-price flex items-center justify-between mb-4">
                        <span class="status-badge inline-flex items-center gap-1 px-3 py-1 rounded-full text-xs font-semibold ${
                            schedule.status === 'scheduled' ?
                            (isDark ? 'bg-emerald-900 text-emerald-300' : 'bg-emerald-100 text-emerald-800') :
                            schedule.status === 'delayed' ?
                            (isDark ? 'bg-amber-900 text-amber-300' : 'bg-amber-100 text-amber-800') :
                            schedule.status === 'cancelled' ?
                            (isDark ? 'bg-red-900 text-red-300' : 'bg-red-100 text-red-800') :
                            (isDark ? 'bg-gray-800 text-gray-300' : 'bg-gray-100 text-gray-700')
                        }">
                            <i class="fas ${
                                schedule.status === 'scheduled' ? 'fa-check-circle text-emerald-500' :
                                schedule.status === 'delayed' ? 'fa-exclamation-triangle text-amber-500' :
                                schedule.status === 'cancelled' ? 'fa-times-circle text-red-500' :
                                'fa-clock text-gray-500'
                            }" aria-hidden="true"></i>
                            <span aria-label="Schedule status: ${schedule.status}">${schedule.status ? schedule.status.charAt(0).toUpperCase() + schedule.status.slice(1) : 'Unknown'}</span>
                        </span>
                        ${
                            (schedule.base_fare || schedule.price) && schedule.status === 'scheduled' ?
                            `<span class="price text-lg font-bold ${isDark ? 'text-emerald-400' : 'text-emerald-600'}" aria-label="Fare: FJD ${schedule.base_fare || schedule.price}">
                                ${Utils.formatPrice(schedule.base_fare || schedule.price)}
                            </span>` :
                            `<span class="price text-sm ${isDark ? 'text-gray-400' : 'text-gray-500'} font-medium" aria-label="Booking unavailable">Unavailable</span>`
                        }
                    </div>

                    <!-- Action Buttons -->
                    <div class="action-buttons space-y-3">
                        ${
                            schedule.status === 'scheduled' && (schedule.available_seats || schedule.seats) > 0 ?
                            `<a href="/bookings/book/?schedule_id=${schedule.id}"
                               class="book-btn w-full bg-gradient-to-r from-emerald-500 to-teal-500 hover:from-emerald-600 hover:to-teal-600 text-white py-3 px-6 rounded-xl font-semibold shadow-lg hover:shadow-xl transition-all transform hover:-translate-y-1 flex items-center justify-center gap-2 text-center focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
                               aria-label="Book ferry from ${schedule.route?.departure_port?.name || 'Nadi'} to ${schedule.route?.destination_port?.name || 'Denarau'} departing ${formattedDate} at ${formattedTime} (${schedule.available_seats || schedule.seats} seats available)">
                                <i class="fas fa-ticket-alt" aria-hidden="true"></i>
                                <span>Book Now (${schedule.available_seats || schedule.seats} seats)</span>
                            </a>` :
                            schedule.available_seats === 0 || schedule.seats === 0 ?
                            `<button class="unavailable-btn w-full bg-gray-300 ${isDark ? 'dark-mode:bg-gray-600' : ''} text-gray-600 dark-mode:text-gray-400 py-3 px-6 rounded-xl font-semibold cursor-not-allowed opacity-60 flex items-center justify-center gap-2" disabled aria-label="This departure is sold out">
                                <i class="fas fa-chair" aria-hidden="true"></i>
                                <span>Sold Out</span>
                            </button>` :
                            `<button class="cancelled-btn w-full bg-gradient-to-r from-red-500 to-rose-500 ${isDark ? 'dark-mode:from-red-600 dark-mode:to-rose-600' : ''} text-white py-3 px-6 rounded-xl font-semibold flex items-center justify-center gap-2" disabled aria-label="This departure is ${schedule.status} and cannot be booked">
                                <i class="fas fa-times-circle" aria-hidden="true"></i>
                                <span>${schedule.status ? schedule.status.charAt(0).toUpperCase() + schedule.status.slice(1) : 'Unavailable'}</span>
                            </button>
                        }

                        <!-- Quick Actions -->
                        <div class="quick-actions flex gap-2 justify-center pt-3 ${isDark ? 'bg-gray-800 dark-mode:bg-gray-800' : 'bg-white/50'} rounded-lg p-2" role="group" aria-label="Quick actions for schedule ${schedule.id}">
                            <button class="quick-btn ${isDark ? 'dark-mode:bg-gray-700 dark-mode:text-gray-300 dark-mode:hover:bg-gray-600' : 'bg-gray-100 hover:bg-gray-200 text-gray-700'} px-3 py-1 rounded-lg text-xs transition-all flex items-center gap-1 focus:outline-none focus:ring-2 focus:ring-gray-500/50"
                                    onclick="FijiFerry?.homepage?.components?.get('schedules')?.toggleSave('${schedule.id}', this)"
                                    aria-label="Save this schedule to favorites"
                                    title="Save to favorites">
                                <i class="far fa-heart" aria-hidden="true"></i>
                                <span class="sr-only">Save</span>
                            </button>
                            <button class="quick-btn ${isDark ? 'dark-mode:bg-blue-900 dark-mode:text-blue-300 dark-mode:hover:bg-blue-800' : 'bg-blue-100 hover:bg-blue-200 text-blue-700'} px-3 py-1 rounded-lg text-xs transition-all flex items-center gap-1 focus:outline-none focus:ring-2 focus:ring-blue-500/50"
                                    onclick="FijiFerry?.homepage?.components?.get('schedules')?.shareSchedule('${schedule.id}')"
                                    aria-label="Share this schedule"
                                    title="Share schedule">
                                <i class="fas fa-share-alt" aria-hidden="true"></i>
                                <span class="sr-only">Share</span>
                            </button>
                        </div>
                    </div>
                </footer>
            `;

            return div;
        }

        setupNewCardListeners(card) {
            if (!card) return;

            // Add click listeners for quick action buttons
            const saveBtn = card.querySelector('.quick-btn[onclick*="toggleSave"]');
            const shareBtn = card.querySelector('.quick-btn[onclick*="shareSchedule"]');

            if (saveBtn && !saveBtn.dataset.listenerAdded) {
                saveBtn.dataset.listenerAdded = 'true';
                saveBtn.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    const scheduleId = card.dataset.scheduleId;
                    this.toggleSave(scheduleId, saveBtn);
                });
            }

            if (shareBtn && !shareBtn.dataset.listenerAdded) {
                shareBtn.dataset.listenerAdded = 'true';
                shareBtn.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    const scheduleId = card.dataset.scheduleId;
                    this.shareSchedule(scheduleId);
                });
            }

            // Add book button analytics
            const bookBtn = card.querySelector('.book-btn');
            if (bookBtn && !bookBtn.dataset.listenerAdded) {
                bookBtn.dataset.listenerAdded = 'true';
                bookBtn.addEventListener('click', (e) => {
                    const scheduleId = card.dataset.scheduleId;
                    logger.log(`Book button clicked for schedule: ${scheduleId}`);
                    // Add analytics tracking here if needed
                });
            }
        }

        updateScheduleCount() {
            const viewAllBtn = document.getElementById('view-all-btn');
            if (viewAllBtn && this.cards.size > 0) {
                const countSpan = viewAllBtn.querySelector('span:last-child');
                if (countSpan) {
                    countSpan.textContent = `(${this.cards.size})`;
                }
            }
        }

        updateWeatherDisplay() {
            logger.log('Updating weather display');
            try {
                const weatherData = Utils.safeParseJSON('weather-data', {});

                // Update port weather cards
                if (weatherData.ports) {
                    ['nadi', 'suva'].forEach(portKey => {
                        const portData = weatherData.ports[portKey];
                        if (portData) {
                            const tempEl = document.getElementById(`${portKey}-temp`);
                            const iconEl = document.getElementById(`${portKey}-icon`);
                            const conditionEl = document.getElementById(`port-${portKey}-weather`);

                            if (tempEl) {
                                tempEl.textContent = `${Math.round(portData.temp)}°`;
                            }
                            if (iconEl) {
                                iconEl.textContent = Utils.getWeatherIcon(portData.condition);
                            }
                            if (conditionEl) {
                                conditionEl.textContent = portData.condition || 'Sunny';
                            }
                        }
                    });
                }

                // Update individual schedule weather
                this.cards.forEach((card, scheduleId) => {
                    const weatherIcon = document.getElementById(`weather-icon-${scheduleId}`);
                    const conditionEl = document.getElementById(`weather-condition-${scheduleId}`);
                    const tempEl = document.getElementById(`weather-temp-${scheduleId}`);
                    const windEl = document.getElementById(`weather-wind-${scheduleId}`);
                    const precipEl = document.getElementById(`weather-precip-${scheduleId}`);

                    if (weatherIcon && conditionEl) {
                        const theme = document.documentElement.getAttribute('data-theme') || 'light';
                        const conditions = [
                            {
                                icon: Utils.getWeatherIcon('partly cloudy'),
                                condition: 'Partly Cloudy',
                                temp: 28 + Math.floor(Math.random() * 3) - 1,
                                wind: 8 + Math.floor(Math.random() * 8),
                                precip: 5 + Math.floor(Math.random() * 15),
                                color: Utils.getThemeColor('text')
                            },
                            {
                                icon: Utils.getWeatherIcon('sunny'),
                                condition: 'Sunny',
                                temp: 30 + Math.floor(Math.random() * 2),
                                wind: 5 + Math.floor(Math.random() * 6),
                                precip: Math.floor(Math.random() * 3),
                                color: Utils.getThemeColor('text')
                            },
                            {
                                icon: Utils.getWeatherIcon('cloudy'),
                                condition: 'Mostly Cloudy',
                                temp: 26 + Math.floor(Math.random() * 3),
                                wind: 12 + Math.floor(Math.random() * 10),
                                precip: 20 + Math.floor(Math.random() * 30),
                                color: Utils.getThemeColor('text')
                            }
                        ];

                        const randomCondition = conditions[Math.floor(Math.random() * conditions.length)];

                        // Update weather icon
                        weatherIcon.textContent = randomCondition.icon;

                        // Update condition with smooth transition
                        conditionEl.style.transition = 'all 0.3s ease';
                        conditionEl.textContent = randomCondition.condition;
                        conditionEl.style.color = randomCondition.color;

                        // Update temperature
                        if (tempEl) {
                            const tempSpan = tempEl.querySelector('span');
                            if (tempSpan) {
                                tempSpan.textContent = `${randomCondition.temp}°C`;
                            }
                        }

                        // Update wind
                        if (windEl) {
                            const windSpan = windEl.querySelector('span');
                            if (windSpan) {
                                windSpan.textContent = `${randomCondition.wind} kph`;
                            }
                        }

                        // Update precipitation
                        if (precipEl) {
                            const precipSpan = precipEl.querySelector('span');
                            if (precipSpan) {
                                precipSpan.textContent = `${randomCondition.precip}%`;
                            }
                        }

                        // Weather warnings and styling
                        const weatherInfo = card.querySelector('.weather-info');
                        const isSevere = randomCondition.precip > 50 || randomCondition.wind > 30;

                        if (isSevere) {
                            conditionEl.classList.add('text-red-600', 'font-bold');
                            if (weatherInfo) {
                                weatherInfo.classList.add('border-red-200', 'bg-red-50');
                                if (theme === 'dark') {
                                    weatherInfo.classList.add('border-red-800', 'bg-red-900/20');
                                    conditionEl.style.color = '#FCA5A5';
                                }
                            }
                        } else {
                            conditionEl.classList.remove('text-red-600', 'font-bold');
                            if (weatherInfo) {
                                weatherInfo.classList.remove(
                                    'border-red-200', 'bg-red-50',
                                    'border-red-800', 'bg-red-900/20'
                                );
                                conditionEl.style.color = randomCondition.color;
                            }
                        }

                        // Add ARIA live region update
                        conditionEl.setAttribute('aria-live', isSevere ? 'assertive' : 'polite');
                    }
                });

                logger.log('Weather display updated');

            } catch (error) {
                logger.error('Weather update failed:', error);
            }
        }

        showNotification(message, type = 'info', duration = 4000) {
            const notificationManager = FijiFerry.notificationManager || new NotificationManager();
            notificationManager.show(message, type, duration);
        }

        destroy() {
            this.isInitialized = false;
            logger.log('ScheduleManager destroyed');
        }
    }

    // 💬 TESTIMONIAL MANAGER (Enhanced)
    class TestimonialManager {
        constructor() {
            this.testimonials = document.querySelectorAll('.testimonial');
            this.dots = document.querySelectorAll('.testimonial-dot');
            this.prevBtn = document.querySelector('.testimonial-prev');
            this.nextBtn = document.querySelector('.testimonial-next');
            this.currentIndex = 0;
            this.autoInterval = null;
            this.isInitialized = false;
            this.init();
        }

        init() {
            if (this.isInitialized) return;
            this.isInitialized = true;

            logger.log(`Initializing TestimonialManager with ${this.testimonials.length} testimonials`);

            if (!this.testimonials.length) {
                logger.warn('No testimonials found');
                return;
            }

            // Set initial state
            this.showTestimonial(0);
            this.startAutoRotate();

            // Navigation buttons
            if (this.prevBtn) {
                this.prevBtn.addEventListener('click', () => this.prev());
                this.prevBtn.setAttribute('aria-label', 'Previous testimonial');
            }

            if (this.nextBtn) {
                this.nextBtn.addEventListener('click', () => this.next());
                this.nextBtn.setAttribute('aria-label', 'Next testimonial');
            }

            // Dot navigation
            this.dots.forEach((dot, index) => {
                if (!dot) return;

                dot.setAttribute('role', 'button');
                dot.setAttribute('tabindex', index === 0 ? '0' : '-1');
                dot.setAttribute('aria-label', `Go to testimonial ${index + 1}`);
                dot.setAttribute('aria-controls', `testimonial-${index + 1}`);

                dot.addEventListener('click', () => {
                    this.goTo(index);
                    logger.log(`Navigated to testimonial ${index}`);
                });

                dot.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        this.goTo(index);
                    }
                    if (e.key === 'ArrowLeft' && index > 0) {
                        e.preventDefault();
                        this.prev();
                    }
                    if (e.key === 'ArrowRight' && index < this.dots.length - 1) {
                        e.preventDefault();
                        this.next();
                    }
                });

                // Focus management
                dot.addEventListener('focus', () => {
                    dot.style.outline = '2px solid #10B981';
                    dot.style.outlineOffset = '2px';
                });

                dot.addEventListener('blur', () => {
                    dot.style.outline = 'none';
                });
            });

            // Pause/resume on hover
            const container = document.querySelector('.testimonials-container');
            if (container) {
                const pauseEvents = ['mouseenter', 'focusin'];
                const resumeEvents = ['mouseleave', 'focusout'];

                pauseEvents.forEach(event => {
                    container.addEventListener(event, () => {
                        this.pauseAutoRotate();
                        logger.log('Testimonials paused');
                    });
                });

                resumeEvents.forEach(event => {
                    container.addEventListener(event, () => {
                        this.resumeAutoRotate();
                        logger.log('Testimonials resumed');
                    });
                });
            }

            this.setupThemeListener();
            this.setupProgressBar();
        }

        setupThemeListener() {
            const observer = new MutationObserver(() => {
                logger.log('Testimonial theme change detected');
                this.updateTheme();
            });
            observer.observe(document.documentElement, {
                attributes: true,
                attributeFilter: ['data-theme']
            });
        }

        updateTheme() {
            const theme = document.documentElement.getAttribute('data-theme') || 'light';
            logger.log(`Updating testimonials theme to: ${theme}`);

            this.testimonials.forEach(testimonial => {
                const card = testimonial.querySelector('.testimonial-card');
                if (card) {
                    card.classList.toggle('dark-mode', theme === 'dark');
                    card.style.background = theme === 'dark' ? '#1E293B' : 'white';
                    card.style.borderColor = theme === 'dark' ? '#334155' : '#E5E7EB';
                    card.style.color = theme === 'dark' ? '#F1F5F9' : '#1E293B';
                }

                const quoteMark = testimonial.querySelector('.quote-mark');
                if (quoteMark) {
                    quoteMark.style.color = theme === 'dark' ? '#334155' : '#F3F4F6';
                }

                const testimonialText = testimonial.querySelector('.testimonial-text');
                if (testimonialText) {
                    testimonialText.style.color = theme === 'dark' ? '#E2E8F0' : '#6B7280';
                }

                const authorSection = testimonial.querySelector('.testimonial-author');
                if (authorSection) {
                    const gradientClass = testimonial.dataset.gradient || 'from-emerald-50 to-teal-50';
                    const darkGradient = gradientClass.replace(/from-(\w+)-50 to-(\w+)-50/,
                        `from-$1-900 to-$2-900`
                    ).replace('from-emerald-50 to-teal-50', 'from-emerald-900 to-teal-900')
                     .replace('from-blue-50 to-indigo-50', 'from-blue-900 to-indigo-900')
                     .replace('from-purple-50 to-pink-50', 'from-purple-900 to-pink-900');

                    authorSection.style.background = theme === 'dark' ?
                        `linear-gradient(135deg, ${darkGradient})` :
                        `linear-gradient(135deg, ${gradientClass})`;

                    authorSection.style.borderColor = theme === 'dark' ?
                        'rgba(16, 185, 129, 0.3)' :
                        'rgba(16, 185, 129, 0.2)';
                }

                const authorName = testimonial.querySelector('.author-name');
                if (authorName) {
                    authorName.style.color = theme === 'dark' ? '#F1F5F9' : '#1E293B';
                }

                const authorRole = testimonial.querySelector('.author-role');
                if (authorRole) {
                    authorRole.style.color = theme === 'dark' ? '#CBD5E1' : '#6B7280';
                }

                const authorRating = testimonial.querySelector('.author-rating');
                if (authorRating) {
                    authorRating.style.color = theme === 'dark' ? '#FBBF24' : '#F59E0B';
                }

                const authorAvatar = testimonial.querySelector('.author-avatar');
                if (authorAvatar) {
                    const gradientClass = testimonial.dataset.gradient || 'from-emerald-400 to-teal-500';
                    const darkGradient = gradientClass.replace(/from-(\w+)-400 to-(\w+)-500/,
                        `from-$1-500 to-$2-600`
                    );
                    authorAvatar.style.background = theme === 'dark' ?
                        `linear-gradient(135deg, ${darkGradient})` :
                        `linear-gradient(135deg, ${gradientClass})`;
                }
            });

            // Update controls
            const controls = document.querySelector('.testimonial-controls');
            if (controls) {
                controls.style.background = theme === 'dark' ?
                    'rgba(30, 41, 59, 0.9)' :
                    'rgba(255, 255, 255, 0.9)';
                controls.style.backdropFilter = 'blur(20px)';
                controls.style.borderColor = theme === 'dark' ? '#475569' : '#E5E7EB';
            }

            // Update dots
            this.dots.forEach((dot, index) => {
                if (dot) {
                    dot.style.background = theme === 'dark' ? '#475569' : '#D1D5DB';
                    if (dot.classList.contains('active')) {
                        dot.style.background = theme === 'dark' ? '#10B981' : '#10B981';
                    }
                }
            });

            // Update progress bar
            const progressBar = document.querySelector('.testimonial-progress .bg-emerald-500');
            if (progressBar) {
                progressBar.style.background = theme === 'dark' ? '#10B981' : '#10B981';
            }
        }

        setupProgressBar() {
            const progressContainer = document.querySelector('.testimonial-progress');
            if (!progressContainer || this.testimonials.length === 0) return;

            const progressBar = progressContainer.querySelector('div');
            if (!progressBar) return;

            let animationStart = null;
            const duration = FijiFerry.config.testimonialInterval;

            function animateProgress(currentTime) {
                if (!animationStart) animationStart = currentTime;
                const elapsed = currentTime - animationStart;
                const progress = Math.min((elapsed / duration) * 100, 100);

                progressBar.style.width = `${progress}%`;

                if (progress < 100) {
                    requestAnimationFrame(animateProgress);
                } else {
                    animationStart = null;
                }
            }

            // Start animation loop
            const animateLoop = () => {
                requestAnimationFrame(animateProgress);
                setTimeout(animateLoop, duration);
            };
            animateLoop();
        }

        showTestimonial(index) {
            if (index < 0 || index >= this.testimonials.length) {
                logger.warn(`Invalid testimonial index: ${index}`);
                return;
            }

            logger.log(`Showing testimonial ${index}`);

            // Update testimonial visibility
            this.testimonials.forEach((testimonial, i) => {
                if (i === index) {
                    testimonial.classList.add('active');
                    testimonial.style.opacity = '1';
                    testimonial.style.display = 'block';
                    testimonial.style.zIndex = '2';
                    testimonial.setAttribute('aria-hidden', 'false');
                } else {
                    testimonial.classList.remove('active');
                    testimonial.style.opacity = '0';
                    testimonial.style.display = 'none';
                    testimonial.style.zIndex = '1';
                    testimonial.setAttribute('aria-hidden', 'true');
                }
            });

            // Update navigation dots
            this.dots.forEach((dot, i) => {
                if (dot) {
                    dot.classList.toggle('active', i === index);
                    dot.setAttribute('aria-pressed', (i === index).toString());
                    dot.setAttribute('tabindex', i === index ? '0' : '-1');

                    // Visual feedback
                    const theme = document.documentElement.getAttribute('data-theme') || 'light';
                    dot.style.background = i === index ?
                        Utils.getThemeColor('primary') :
                        Utils.getThemeColor('gray300');
                }
            });

            this.currentIndex = index;
        }

        next() {
            this.goTo((this.currentIndex + 1) % this.testimonials.length);
        }

        prev() {
            this.goTo((this.currentIndex - 1 + this.testimonials.length) % this.testimonials.length);
        }

        goTo(index) {
            this.showTestimonial(index);
            this.resetAutoRotate();
        }

        startAutoRotate() {
            // Clear existing interval
            this.pauseAutoRotate();

            if (this.testimonials.length <= 1) {
                logger.log('Single testimonial, no auto-rotate needed');
                return;
            }

            logger.log(`Starting auto-rotate (${this.testimonials.length} testimonials)`);
            this.autoInterval = setInterval(() => {
                this.next();
            }, FijiFerry.config.testimonialInterval);
        }

        pauseAutoRotate() {
            if (this.autoInterval) {
                clearInterval(this.autoInterval);
                this.autoInterval = null;
                logger.log('Auto-rotate paused');
            }
        }

        resetAutoRotate() {
            this.pauseAutoRotate();
            // Resume after delay to allow user interaction
            setTimeout(() => {
                this.startAutoRotate();
            }, 10000);
        }

        resumeAutoRotate() {
            if (!this.autoInterval && this.testimonials.length > 1) {
                this.startAutoRotate();
            }
        }

        destroy() {
            this.pauseAutoRotate();
            this.isInitialized = false;
            logger.log('TestimonialManager destroyed');
        }
    }

    // 📝 FORM MANAGER (Enhanced)
    class FormManager {
        constructor() {
            this.isInitialized = false;
            this.init();
        }

        init() {
            if (this.isInitialized) return;
            this.isInitialized = true;

            logger.log('Initializing FormManager');
            this.setupValidation();
            this.setupQuickSearch();
            this.setupThemeListener();
        }

        setupThemeListener() {
            const observer = new MutationObserver(() => {
                logger.log('Form theme change detected');
                this.updateFormTheme();
            });
            observer.observe(document.documentElement, {
                attributes: true,
                attributeFilter: ['data-theme']
            });
        }

        updateFormTheme() {
            const theme = document.documentElement.getAttribute('data-theme') || 'light';
            const form = document.getElementById('search-form');
            if (!form) return;

            logger.log(`Updating form theme to: ${theme}`);

            // Update booking widget
            const bookingWidget = form.closest('.booking-widget');
            if (bookingWidget) {
                if (theme === 'dark') {
                    bookingWidget.style.background = 'rgba(30, 41, 59, 0.8)';
                    bookingWidget.style.backdropFilter = 'blur(20px)';
                    bookingWidget.style.borderColor = 'rgba(71, 85, 105, 0.5)';
                } else {
                    bookingWidget.style.background = 'rgba(255, 255, 255, 0.1)';
                    bookingWidget.style.backdropFilter = 'blur(20px)';
                    bookingWidget.style.borderColor = 'rgba(255, 255, 255, 0.2)';
                }
            }

            // Update form inputs
            const inputs = form.querySelectorAll('input, select');
            inputs.forEach(input => {
                const isDark = theme === 'dark';

                if (isDark) {
                    input.style.background = 'rgba(30, 41, 59, 0.8)';
                    input.style.borderColor = '#475569';
                    input.style.color = '#F1F5F9';
                    input.style.caretColor = '#F1F5F9';

                    // Update placeholder for dark mode
                    if (input.placeholder) {
                        input.setAttribute('data-placeholder', input.placeholder);
                        input.placeholder = '';
                        const placeholder = document.createElement('span');
                        placeholder.className = 'absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none text-gray-400 transition-colors';
                        placeholder.textContent = input.dataset.placeholder;
                        placeholder.id = `placeholder-${input.id}`;
                        input.parentNode.insertBefore(placeholder, input);
                    }
                } else {
                    input.style.background = 'rgba(255, 255, 255, 0.1)';
                    input.style.borderColor = 'rgba(255, 255, 255, 0.3)';
                    input.style.color = 'white';
                    input.style.caretColor = 'white';

                    // Restore placeholder for light mode
                    const placeholder = document.getElementById(`placeholder-${input.id}`);
                    if (placeholder) {
                        placeholder.remove();
                        input.placeholder = input.dataset.placeholder || '';
                    }
                }

                // Focus states
                input.style.transition = 'all 0.2s ease';
            });

            // Update labels
            const labels = form.querySelectorAll('label');
            labels.forEach(label => {
                label.style.color = theme === 'dark' ? '#E2E8F0' : 'rgba(255, 255, 255, 0.9)';
            });

            // Update feedback
            const feedback = document.getElementById('form-feedback');
            if (feedback) {
                feedback.style.color = theme === 'dark' ? 'rgba(241, 245, 249, 0.7)' : 'rgba(255, 255, 255, 0.7)';
            }

            // Update buttons
            const buttons = form.querySelectorAll('button, .search-button, .book-now-button');
            buttons.forEach(btn => {
                const isDark = theme === 'dark';

                if (btn.classList.contains('search-button')) {
                    btn.style.background = isDark ?
                        'linear-gradient(135deg, #10B981 0%, #059669 100%)' :
                        'linear-gradient(135deg, #10B981 0%, #059669 100%)';
                } else if (btn.classList.contains('book-now-button')) {
                    btn.style.background = isDark ?
                        'linear-gradient(135deg, #F59E0B 0%, #D97706 100%)' :
                        'linear-gradient(135deg, #F59E0B 0%, #D97706 100%)';
                } else {
                    btn.style.color = theme === 'dark' ? '#F1F5F9' : 'white';
                }

                // Hover effects
                btn.onmouseover = () => {
                    btn.style.transform = 'translateY(-1px)';
                    btn.style.boxShadow = isDark ?
                        '0 4px 12px rgba(0,0,0,0.3)' :
                        '0 4px 12px rgba(0,0,0,0.15)';
                };

                btn.onmouseout = () => {
                    btn.style.transform = 'translateY(0)';
                    btn.style.boxShadow = '';
                };
            });
        }

        setupValidation() {
            const form = document.getElementById('search-form');
            if (!form) {
                logger.warn('Search form not found');
                return;
            }

            logger.log('Setting up form validation');

            // Form submission validation
            form.addEventListener('submit', (e) => {
                if (!this.validate()) {
                    e.preventDefault();
                    this.showError();
                    return false;
                }

                logger.log('Form submitted successfully');
            });

            // Real-time validation on input/change
            ['input', 'change'].forEach(eventType => {
                form.addEventListener(eventType, Utils.debounce(() => {
                    this.updateState();
                }, 300));
            });

            // Initial validation state
            this.updateState();
        }

        validate() {
            const routeInput = document.getElementById('route');
            const dateInput = document.getElementById('departure-date');
            const passengerSelect = document.getElementById('passengers');

            if (!routeInput || !dateInput || !passengerSelect) {
                logger.warn('Validation elements not found');
                return false;
            }

            const route = routeInput.value.trim();
            const date = dateInput.value;
            const passengers = passengerSelect.value;
            const today = new Date().toISOString().split('T')[0];

            const isValid = route && date && date >= today && passengers && passengers !== '0';

            // Update form class for styling
            form.classList.toggle('form-invalid', !isValid);

            logger.log(`Form validation: ${isValid ? 'Valid' : 'Invalid'} (route: ${!!route}, date: ${date >= today}, passengers: ${!!passengers})`);
            return isValid;
        }

        updateState() {
            const isValid = this.validate();
            const submitBtn = this.form?.querySelector('button[type="submit"]');
            const feedback = document.getElementById('form-feedback');

            if (submitBtn) {
                submitBtn.disabled = !isValid;
                submitBtn.classList.toggle('opacity-50', !isValid);
                submitBtn.classList.toggle('cursor-not-allowed', !isValid);
                submitBtn.setAttribute('aria-disabled', (!isValid).toString());
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

        showError() {
            logger.log('Showing form validation error');
            const notificationManager = FijiFerry.notificationManager || new NotificationManager();
            notificationManager.show('Please select a route, date, and number of passengers', 'warning', 4000);

            // Focus first invalid field
            const firstInvalid = this.form?.querySelector('input:invalid, select:invalid');
            if (firstInvalid) {
                firstInvalid.focus();
                firstInvalid.scrollIntoView({
                    behavior: 'smooth',
                    block: 'center',
                    inline: 'nearest'
                });

                // Add temporary highlight
                firstInvalid.style.transition = 'all 0.2s ease';
                firstInvalid.style.borderColor = '#EF4444';
                firstInvalid.style.boxShadow = '0 0 0 3px rgba(239, 68, 68, 0.1)';

                setTimeout(() => {
                    firstInvalid.style.borderColor = '';
                    firstInvalid.style.boxShadow = '';
                }, 2000);
            }

            // Also show inline error
            const feedback = document.getElementById('form-feedback');
            if (feedback) {
                feedback.classList.remove('hidden');
                feedback.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }
        }

        setupQuickSearch() {
            logger.log('Setting up quick search functionality');

            // Quick route links
            document.querySelectorAll('.quick-route, .destination-cta, [data-quick-search]').forEach(link => {
                link.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();

                    const portName = link.dataset.toPort ||
                                   link.dataset.quickSearch ||
                                   link.textContent.toLowerCase().replace(/[^a-z0-9]/g, '-').split('-')[0];

                    if (this.quickSearch(portName)) {
                        logger.log(`Quick search initiated for: ${portName}`);
                    }
                });
            });

            // Map marker clicks (if map is available)
            document.addEventListener('click', (e) => {
                if (e.target.closest('.leaflet-marker-icon')) {
                    // Handle map marker clicks
                    const portName = e.target.closest('.leaflet-marker-pane').dataset.portName;
                    if (portName && this.quickSearch(portName.toLowerCase())) {
                        logger.log(`Map marker quick search: ${portName}`);
                    }
                }
            });
        }

        quickSearch(portName) {
            if (!portName) {
                logger.warn('No port name provided for quick search');
                return false;
            }

            const routeInput = document.getElementById('route');
            const form = document.getElementById('search-form');
            const datalist = document.getElementById('routes');

            if (!routeInput || !form) {
                logger.warn('Form elements not found for quick search');
                return false;
            }

            logger.log(`Performing quick search for: ${portName}`);

            // Find matching route in datalist
            let matchingOption = null;
            if (datalist) {
                matchingOption = Array.from(datalist.querySelectorAll('option')).find(opt =>
                    opt.value.includes(portName) ||
                    opt.dataset.display?.toLowerCase().includes(portName) ||
                    opt.textContent.toLowerCase().includes(portName)
                );
            }

            // Set route value
            if (matchingOption) {
                routeInput.value = matchingOption.value;
                logger.log(`Found matching route: ${matchingOption.value}`);
            } else {
                // Fallback to simple format
                routeInput.value = `${portName}-to-destination`;
                logger.log(`Using fallback route format: ${routeInput.value}`);
            }

            // Trigger input event for validation
            routeInput.dispatchEvent(new Event('input', { bubbles: true }));

            // Scroll to form smoothly
            form.scrollIntoView({
                behavior: 'smooth',
                block: 'center',
                inline: 'nearest'
            });

            // Focus route input
            setTimeout(() => {
                routeInput.focus();
                routeInput.select();
            }, 300);

            // Show confirmation
            const notificationManager = FijiFerry.notificationManager || new NotificationManager();
            notificationManager.show(
                `Searching routes from ${portName.replace(/-/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}`,
                'info',
                2500
            );

            return true;
        }

        destroy() {
            this.isInitialized = false;
            logger.log('FormManager destroyed');
        }
    }

    // 🔍 FILTER MANAGER
    class FilterManager {
        constructor() {
            this.isInitialized = false;
            this.init();
        }

        init() {
            if (this.isInitialized) return;
            this.isInitialized = true;

            logger.log('Initializing FilterManager');
            this.setupControls();
            this.setupThemeListener();
        }

        setupThemeListener() {
            const observer = new MutationObserver(() => {
                this.updateTheme();
            });
            observer.observe(document.documentElement, {
                attributes: true,
                attributeFilter: ['data-theme']
            });
        }

        updateTheme() {
            const theme = document.documentElement.getAttribute('data-theme') || 'light';
            const filters = document.querySelector('.schedule-filters');
            if (filters) {
                if (theme === 'dark') {
                    filters.style.background = 'rgba(30, 41, 59, 0.8)';
                    filters.style.backdropFilter = 'blur(10px)';
                    filters.style.borderColor = '#475569';
                } else {
                    filters.style.background = 'rgba(255, 255, 255, 0.8)';
                    filters.style.backdropFilter = 'blur(10px)';
                    filters.style.borderColor = '#E5E7EB';
                }
            }

            const sortSelect = document.getElementById('sort-by');
            if (sortSelect) {
                sortSelect.style.background = theme === 'dark' ? 'rgb(30, 41, 59)' : 'white';
                sortSelect.style.borderColor = theme === 'dark' ? '#475569' : '#D1D5DB';
                sortSelect.style.color = Utils.getThemeColor('text');
            }

            const viewAllBtn = document.getElementById('view-all-btn');
            if (viewAllBtn) {
                viewAllBtn.style.background = theme === 'dark' ?
                    'linear-gradient(135deg, #10B981 0%, #059669 100%)' :
                    'linear-gradient(135deg, #10B981 0%, #059669 100%)';
            }
        }

        setupControls() {
            // View all button - reset filters
            const viewAllBtn = document.getElementById('view-all-btn');
            if (viewAllBtn) {
                viewAllBtn.addEventListener('click', (e) => {
                    e.preventDefault();
                    logger.log('View all clicked - resetting filters');

                    // Clear URL parameters
                    const url = new URL(window.location);
                    ['route', 'date', 'passengers', 'sort'].forEach(param => {
                        url.searchParams.delete(param);
                    });

                    // Update URL without reload
                    window.history.replaceState({}, '', url);

                    // Reset form
                    window.resetSearch();

                    // Reset sort select
                    const sortSelect = document.getElementById('sort-by');
                    if (sortSelect) {
                        sortSelect.value = 'time';
                    }

                    const notificationManager = FijiFerry.notificationManager || new NotificationManager();
                    notificationManager.show('Showing all available schedules', 'success', 2000);
                });

                // Add hover effects
                viewAllBtn.addEventListener('mouseenter', () => {
                    viewAllBtn.style.transform = 'translateY(-1px)';
                });

                viewAllBtn.addEventListener('mouseleave', () => {
                    viewAllBtn.style.transform = 'translateY(0)';
                });
            }

            // Expose reset function globally for template compatibility
            window.resetSearch = () => {
                const formManager = FijiFerry.homepage?.components?.get('form');
                if (formManager) {
                    // Use form manager's reset
                    const form = document.getElementById('search-form');
                    if (form) {
                        form.reset();

                        // Reset date to today
                        const dateInput = document.getElementById('departure-date');
                        const today = new Date().toISOString().split('T')[0];
                        if (dateInput) {
                            dateInput.value = today;
                            dateInput.min = today;
                        }

                        // Clear URL parameters
                        const url = new URL(window.location);
                        ['route', 'date', 'passengers', 'sort'].forEach(param => {
                            url.searchParams.delete(param);
                        });
                        window.history.replaceState({}, '', url);

                        // Trigger events
                        form.dispatchEvent(new Event('reset', { bubbles: true }));
                        form.dispatchEvent(new Event('input', { bubbles: true }));

                        logger.log('Search reset via form manager');
                    }
                } else {
                    // Direct fallback implementation
                    const form = document.getElementById('search-form');
                    if (form) {
                        form.reset();

                        const dateInput = document.getElementById('departure-date');
                        const today = new Date().toISOString().split('T')[0];
                        if (dateInput) {
                            dateInput.value = today;
                            dateInput.min = today;
                        }

                        // Clear URL parameters
                        const url = new URL(window.location);
                        ['route', 'date', 'passengers', 'sort'].forEach(param => {
                            url.searchParams.delete(param);
                        });
                        window.history.replaceState({}, '', url);

                        // Trigger events
                        form.dispatchEvent(new Event('reset', { bubbles: true }));
                        form.dispatchEvent(new Event('input', { bubbles: true }));

                        logger.log('Search reset via fallback');
                    }
                }

                // Show confirmation
                const notificationManager = FijiFerry.notificationManager || new NotificationManager();
                notificationManager.show('Search reset! Discover new routes. ✨', 'info', 3000);
            };

            // Setup keyboard shortcuts
            document.addEventListener('keydown', (e) => {
                // Ctrl/Cmd + R for reset search
                if ((e.ctrlKey || e.metaKey) && e.key === 'r') {
                    e.preventDefault();
                    window.resetSearch();
                }
            });
        }

        destroy() {
            this.isInitialized = false;
            logger.log('FilterManager destroyed');
        }
    }

    // 🌟 MAIN INITIALIZATION (Fixed conflicts)
    class HomepageManager {
        constructor() {
            this.components = new Map();
            this.isInitialized = false;
            logger.log('HomepageManager constructor called');
        }

        init() {
            if (this.isInitialized) {
                logger.log('Homepage already initialized, skipping');
                return;
            }
            this.isInitialized = true;

            logger.log('Initializing Fiji Ferry Homepage v2.3.1');

            // Apply Tailwind overrides for dark mode
            Utils.applyTailwindOverrides();

            // Parse context data
            try {
                window.FijiFerryData = {
                    formData: Utils.safeParseJSON('form-data', {}),
                    weatherData: Utils.safeParseJSON('weather-data', {})
                };
                logger.log('Context data parsed successfully');
            } catch (error) {
                logger.warn('Context parsing failed:', error);
                window.FijiFerryData = { formData: {}, weatherData: {} };
            }

            // Initialize components in dependency order
            logger.log('Initializing components...');

            // Core components first
            this.components.set('notifications', new NotificationManager());
            this.components.set('hero', new HeroManager());
            this.components.set('stats', new StatsManager());
            this.components.set('form', new FormManager());
            this.components.set('filters', new FilterManager());

            // Map component (can fail gracefully)
            setTimeout(() => {
                if (document.getElementById('fiji-map')) {
                    logger.log('Map element found, initializing MapManager');
                    this.components.set('map', new MapManager());
                } else {
                    logger.log('No map element found, skipping MapManager');
                }
            }, 200);

            // Schedule and testimonial components
            setTimeout(() => {
                this.components.set('schedules', new ScheduleManager());
                this.components.set('testimonials', new TestimonialManager());
            }, 300);

            // Setup global event listeners
            this.setupGlobalListeners();

            // Start background tasks
            this.startBackgroundTasks();

            // Expose globally for debugging and template compatibility
            window.FijiFerry = FijiFerry;
            FijiFerry.homepage = this;
            FijiFerry.notificationManager = this.components.get('notifications');

            if (FijiFerry.config.debug) {
                window.Utils = Utils;
                logger.log('Debug mode enabled - check console for detailed logs');
                logger.log('Available components:', Array.from(this.components.keys()));
            }

            logger.log('Homepage initialization complete');
        }

        setupGlobalListeners() {
            logger.log('Setting up global event listeners');

            // Smooth scrolling for anchor links (excluding nav links)
            document.querySelectorAll('a[href^="#"]:not([data-nav-link])').forEach(anchor => {
                anchor.addEventListener('click', (e) => {
                    e.preventDefault();
                    const targetId = anchor.getAttribute('href').substring(1);
                    const target = document.getElementById(targetId);
                    if (target) {
                        target.scrollIntoView({
                            behavior: 'smooth',
                            block: 'start',
                            inline: 'nearest'
                        });
                        logger.log(`Smooth scroll to: ${targetId}`);
                    }
                });
            });

            // Navbar link highlighting and navigation
            document.querySelectorAll('[data-nav-link]').forEach(link => {
                link.addEventListener('click', (e) => {
                    // Remove active class from all nav links
                    document.querySelectorAll('[data-nav-link]').forEach(l => {
                        l.classList.remove('active');
                        l.style.background = '';
                    });

                    // Add active class to clicked link
                    link.classList.add('active');

                    // Add visual feedback
                    link.style.background = 'rgba(16, 185, 129, 0.1)';
                    setTimeout(() => {
                        link.style.background = '';
                    }, 200);

                    logger.log(`Nav link clicked: ${link.textContent.trim()}`);
                });

                // Keyboard navigation support
                link.addEventListener('keydown', (e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        link.click();
                    }
                });
            });

            // Global keyboard shortcuts
            document.addEventListener('keydown', (e) => {
                const isInputFocused = ['INPUT', 'TEXTAREA', 'SELECT'].includes(document.activeElement.tagName);

                if (isInputFocused) return;

                // Escape key - close notifications, dropdowns, modals
                if (e.key === 'Escape') {
                    this.components.get('notifications')?.closeAll?.();

                    // Close dropdowns
                    const dropdowns = document.querySelectorAll('.dropdown.open');
                    dropdowns.forEach(dropdown => {
                        dropdown.classList.remove('open');
                        const btn = dropdown.querySelector('.dropdown-btn');
                        if (btn) {
                            btn.setAttribute('aria-expanded', 'false');
                            btn.querySelector('.fa-chevron-down')?.style.setProperty('transform', 'rotate(0deg)');
                        }
                    });

                    // Close mobile menu
                    const mobileMenu = document.getElementById('mobile-menu');
                    if (mobileMenu?.classList.contains('open')) {
                        mobileMenu.classList.remove('open');
                        document.getElementById('hamburger-btn')?.classList.remove('open');
                        document.body.style.overflow = '';
                    }

                    logger.log('Escape key pressed - global cleanup');
                }

                // Ctrl/Cmd + K - focus search
                if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
                    e.preventDefault();
                    const routeInput = document.getElementById('route');
                    if (routeInput) {
                        routeInput.focus();
                        routeInput.select();
                        logger.log('Search focused via shortcut');
                    }
                }

                // Ctrl/Cmd + R - reset search
                if ((e.ctrlKey || e.metaKey) && e.key === 'r') {
                    e.preventDefault();
                    window.resetSearch();
                    logger.log('Search reset via shortcut');
                }
            });

            // Window resize handler
            let resizeTimeout;
            window.addEventListener('resize', () => {
                clearTimeout(resizeTimeout);
                resizeTimeout = setTimeout(() => {
                    this.components.forEach(component => {
                        if (component.handleResize) {
                            component.handleResize();
                        }
                    });

                    // Update mobile class
                    document.body.classList.toggle('is-mobile', window.innerWidth < 768);

                    logger.log(`Window resized to: ${window.innerWidth}x${window.innerHeight}`);
                }, 250);
            });

            // Online/offline status
            window.addEventListener('online', () => {
                logger.log('🌐 Connection restored');
                const notificationManager = this.components.get('notifications');
                notificationManager?.show('✅ Connection restored - all features available', 'success', 3000);
            });

            window.addEventListener('offline', () => {
                logger.warn('🌐 Connection lost');
                const notificationManager = this.components.get('notifications');
                notificationManager?.show('⚠️ Connection lost - some features may be limited', 'warning', 5000);
            });

            // Page visibility change
            document.addEventListener('visibilitychange', () => {
                if (document.hidden) {
                    logger.log('Page hidden - pausing animations');
                    this.pauseAll();
                } else {
                    logger.log('Page visible - resuming animations');
                    this.resumeAll();
                }
            });

            // Global error handling
            window.addEventListener('error', (e) => {
                if (e.filename && (e.filename.includes('fiji-ferry') || e.filename.includes('home.js'))) {
                    logger.error('🚨 FijiFerry JavaScript Error:', e.error || e.message);
                    logger.error('Stack trace:', e.error?.stack);

                    const notificationManager = this.components.get('notifications');
                    if (notificationManager) {
                        notificationManager.show(
                            '⚠️ An unexpected error occurred. Please refresh the page to continue.',
                            'error',
                            0 // Don't auto-dismiss
                        );
                    }
                }
            });

            // Prevent double initialization
            if (document.readyState === 'loading') {
                document.removeEventListener('DOMContentLoaded', this.init);
            }
        }

        startBackgroundTasks() {
            logger.log('Starting background tasks');

            // Weather updates (if weather data available)
            if (window.FijiFerryData && window.FijiFerryData.weatherData) {
                const scheduleManager = this.components.get('schedules');
                if (scheduleManager) {
                    const weatherUpdate = () => {
                        scheduleManager.updateWeatherDisplay();
                    };

                    // Initial update
                    weatherUpdate();

                    // Periodic updates
                    setInterval(weatherUpdate, FijiFerry.config.weatherUpdateInterval);
                    logger.log(`Weather updates scheduled every ${FijiFerry.config.weatherUpdateInterval/1000}s`);
                }
            }

            // Stats animation trigger (if stats exist)
            const statItems = document.querySelectorAll('.stat-item');
            if (statItems.length > 0) {
                const statsManager = this.components.get('stats');
                if (statsManager) {
                    setTimeout(() => {
                        statItems.forEach(item => {
                            item.classList.add('animate');
                        });
                        logger.log(`Triggered animation for ${statItems.length} stat items`);
                    }, 1000);
                }
            }

            // Live ferry count animation
            const liveFerryCount = document.getElementById('live-ferry-count');
            const onScheduleCount = document.getElementById('on-schedule-count');
            if (liveFerryCount && onScheduleCount) {
                // Animate from 0 to target values
                this.animateCounter(liveFerryCount, 3, 1500);
                this.animateCounter(onScheduleCount, 2, 1500);
                logger.log('Live ferry counters animated');
            }

            // Preload hero images
            const heroSlides = document.querySelectorAll('.hero-slide');
            if (heroSlides.length > 0) {
                const heroImages = Array.from(heroSlides).map(slide =>
                    slide.dataset.srcLight || slide.dataset.srcDark
                ).filter(Boolean);
                Utils.preloadImages(heroImages);
                logger.log(`Preloaded ${heroImages.length} hero images`);
            }

            // Setup periodic cleanup
            setInterval(() => {
                // Clean up any orphaned elements
                const orphanedCards = document.querySelectorAll('.schedule-card:not([data-schedule-id])');
                orphanedCards.forEach(card => card.remove());

                // Update any stale weather data
                const scheduleManager = this.components.get('schedules');
                if (scheduleManager) {
                    scheduleManager.updateWeatherDisplay();
                }
            }, 300000); // Every 5 minutes
        }

        animateCounter(element, target, duration) {
            if (!element || isNaN(target)) {
                logger.warn('Invalid counter animation parameters');
                return;
            }

            let start = parseFloat(element.textContent) || 0;
            const increment = target / (duration / 16); // ~60fps
            const startTime = performance.now();

            const timer = setInterval(() => {
                const elapsed = performance.now() - startTime;
                start += increment;

                if (start >= target) {
                    start = target;
                    clearInterval(timer);
                }

                element.textContent = Math.floor(start);
            }, 16);

            setTimeout(() => {
                if (timer) clearInterval(timer);
                element.textContent = target;
            }, duration);
        }

        pauseAll() {
            logger.log('Pausing all animations');
            this.components.get('hero')?.pauseSlideshow?.();
            this.components.get('testimonials')?.pauseAutoRotate?.();
        }

        resumeAll() {
            logger.log('Resuming all animations');
            this.components.get('hero')?.resumeSlideshow?.();
            this.components.get('testimonials')?.resumeAutoRotate?.();
        }

        handleResize() {
            this.components.forEach((component, name) => {
                if (component.handleResize) {
                    try {
                        component.handleResize();
                        logger.log(`Resize handled for: ${name}`);
                    } catch (error) {
                        logger.warn(`Resize failed for ${name}:`, error);
                    }
                }
            });
        }

        destroy() {
            logger.log('Destroying HomepageManager');

            this.components.forEach((component, name) => {
                try {
                    if (component.destroy) {
                        component.destroy();
                        logger.log(`Destroyed component: ${name}`);
                    }
                } catch (error) {
                    logger.warn(`Failed to destroy ${name}:`, error);
                }
            });

            this.components.clear();
            this.isInitialized = false;
        }
    }

    // 🎯 GLOBAL FUNCTIONS (Template compatibility)
    window.saveSchedule = function(scheduleId) {
        logger.log(`Global saveSchedule called for: ${scheduleId}`);

        const scheduleManager = FijiFerry.homepage?.components?.get('schedules');
        if (scheduleManager && scheduleManager.toggleSave) {
            const button = event?.target?.closest('button');
            scheduleManager.toggleSave(scheduleId, button);
            return;
        }

        // Fallback implementation
        const button = event?.target?.closest('button');
        if (button) {
            const icon = button.querySelector('i');
            if (icon) {
                const isSaved = icon.classList.contains('fas');
                if (isSaved) {
                    icon.classList.remove('fas', 'text-red-500');
                    icon.classList.add('far');
                    console.log(`✓ Schedule ${scheduleId} removed from favorites (fallback)`);
                } else {
                    icon.classList.remove('far');
                    icon.classList.add('fas', 'text-red-500');
                    console.log(`♥ Schedule ${scheduleId} added to favorites (fallback)`);
                }
                return;
            }
        }

        console.warn(`⚠️ Could not toggle save state for schedule ${scheduleId}`);
    };

    window.shareSchedule = function(scheduleId) {
        logger.log(`Global shareSchedule called for: ${scheduleId}`);

        const scheduleManager = FijiFerry.homepage?.components?.get('schedules');
        if (scheduleManager && scheduleManager.shareSchedule) {
            scheduleManager.shareSchedule(scheduleId);
            return;
        }

        // Fallback implementation
        const url = `${window.location.origin}/bookings/book/?schedule_id=${scheduleId}`;
        if (navigator.share) {
            navigator.share({
                title: 'Fiji Ferry Booking',
                text: 'Check out this ferry schedule!',
                url: url
            }).catch(error => {
                console.warn('Share failed:', error);
                navigator.clipboard.writeText(url).then(() => {
                    console.log('✓ Schedule link copied to clipboard (fallback)');
                }).catch(() => {
                    console.error('❌ Could not copy schedule link');
                });
            });
        } else {
            navigator.clipboard.writeText(url).then(() => {
                console.log('✓ Schedule link copied to clipboard (fallback)');
            }).catch(error => {
                console.error('❌ Could not copy schedule link:', error);
            });
        }
    };

    window.scrollToSchedules = function() {
        logger.log('Global scrollToSchedules called');
        const schedulesSection = document.getElementById('schedules-section');
        if (schedulesSection) {
            schedulesSection.scrollIntoView({
                behavior: 'smooth',
                block: 'start',
                inline: 'nearest'
            });
            console.log('✓ Scrolled to schedules section');
        } else {
            console.warn('❌ Schedules section not found');
        }
    };

    window.resetSearch = function() {
        logger.log('Global resetSearch called');

        const formManager = FijiFerry.homepage?.components?.get('form');
        if (formManager) {
            // Use form manager's reset functionality
            const form = document.getElementById('search-form');
            if (form) {
                form.reset();

                // Reset date to today
                const dateInput = document.getElementById('departure-date');
                const today = new Date().toISOString().split('T')[0];
                if (dateInput) {
                    dateInput.value = today;
                    dateInput.min = today;
                }

                // Clear URL parameters
                const url = new URL(window.location);
                ['route', 'date', 'passengers', 'sort'].forEach(param => {
                    url.searchParams.delete(param);
                });
                window.history.replaceState({}, '', url);

                // Trigger validation events
                form.dispatchEvent(new Event('reset', { bubbles: true }));
                form.dispatchEvent(new Event('input', { bubbles: true }));

                console.log('✓ Search reset via FormManager');
            }
        } else {
            // Direct fallback implementation
            const form = document.getElementById('search-form');
            if (form) {
                form.reset();

                const dateInput = document.getElementById('departure-date');
                const today = new Date().toISOString().split('T')[0];
                if (dateInput) {
                    dateInput.value = today;
                    dateInput.min = today;
                }

                // Clear URL parameters
                const url = new URL(window.location);
                ['route', 'date', 'passengers', 'sort'].forEach(param => {
                    url.searchParams.delete(param);
                });
                window.history.replaceState({}, '', url);

                // Trigger events
                form.dispatchEvent(new Event('reset', { bubbles: true }));
                form.dispatchEvent(new Event('input', { bubbles: true }));

                console.log('✓ Search reset via fallback');
            } else {
                console.warn('❌ Search form not found for reset');
            }
        }

        // Show confirmation notification
        const notificationManager = FijiFerry.notificationManager || new NotificationManager();
        notificationManager.show('🔍 Search reset! Ready to discover new routes.', 'info', 3000);
    };

    // 🚀 INITIALIZATION (Fixed to prevent conflicts)
    let initializationAttempted = false;
    let initializationTimeout = null;

    function initializeHomepage() {
        if (initializationAttempted) {
            logger.log('Homepage initialization already attempted');
            return;
        }
        initializationAttempted = true;

        clearTimeout(initializationTimeout);

        logger.log('Starting homepage initialization sequence...');

        // Wait for DOM to be fully ready and delay slightly for external scripts
        const initWithDelay = () => {
            // Apply Tailwind dark mode overrides
            Utils.applyTailwindOverrides();

            // Create and initialize main manager
            FijiFerry.homepage = new HomepageManager();

            // Log completion
            logger.log('🚀 Fiji Ferry Homepage v2.3.1 initialized successfully');
            logger.log(`📊 Components loaded: ${FijiFerry.homepage.components.size}`);
            logger.log(`🎨 Current theme: ${document.documentElement.getAttribute('data-theme') || 'light'}`);
            logger.log(`📱 Device: ${window.innerWidth <= 768 ? 'mobile' : 'desktop'}`);
        };

        // Use requestIdleCallback if available, otherwise setTimeout
        if (window.requestIdleCallback) {
            requestIdleCallback(initWithDelay, { timeout: 200 });
        } else {
            setTimeout(initWithDelay, 100);
        }
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initializeHomepage);
        logger.log('DOM loading, will initialize when ready');
    } else {
        initializeHomepage();
        logger.log('DOM ready, initializing immediately');
    }

    // Also try to initialize after window load (for edge cases)
    window.addEventListener('load', () => {
        if (!initializationAttempted) {
            logger.log('Window loaded, performing late initialization');
            initializeHomepage();
        }
    });

    // Cleanup on page unload
    window.addEventListener('beforeunload', () => {
        logger.log('Page unloading, cleaning up...');
        if (FijiFerry.homepage && FijiFerry.homepage.destroy) {
            try {
                FijiFerry.homepage.destroy();
            } catch (error) {
                logger.warn('Cleanup failed:', error);
            }
        }
    });

    // Handle page visibility changes
    document.addEventListener('visibilitychange', () => {
        if (FijiFerry.homepage) {
            if (document.hidden) {
                FijiFerry.homepage.pauseAll();
            } else {
                FijiFerry.homepage.resumeAll();
            }
        }
    });

    // Expose for debugging
    if (FijiFerry.config.debug) {
        console.log('🔧 Fiji Ferry Debug Mode Enabled');
        console.log('📋 Available utilities:', Object.keys(Utils));
        console.log('🎛️ Global functions:', ['saveSchedule', 'shareSchedule', 'scrollToSchedules', 'resetSearch']);
        console.log('🌐 Config:', FijiFerry.config);
    }

    // Export for external access
    window.FijiFerry = FijiFerry;
    window.Utils = Utils;

})();