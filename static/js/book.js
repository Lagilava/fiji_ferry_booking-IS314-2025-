/**
 * book.js - Complete Fiji Ferry Booking System
 * Multi-step form with passenger management, validation, and Stripe integration
 * Enhanced with add-on display, improved summary styling, schedule freshness checks,
 * and real-time departure warnings (15-minute window).
 * Now with FULL URL param support, auto-select schedule, scroll, and Quick Book sync
 */

'use strict';

// Global config fallback
window.bookingConfig = window.bookingConfig || { formData: {}, addOns: [] };
window.urls = window.urls || {};

// Ensure validation utilities exist
window.validationUtils = window.validationUtils || {
    displayBackendErrors: (errors) => {
        document.querySelectorAll('.error-message').forEach(el => {
            el.textContent = '';
            el.classList.remove('show');
        });
        const messagesDiv = document.querySelector('.messages');
        if (messagesDiv) messagesDiv.innerHTML = '';
        errors.forEach(error => {
            if (error.field === 'general') {
                if (messagesDiv) {
                    const alertDiv = document.createElement('div');
                    alertDiv.className = 'alert alert-error';
                    alertDiv.textContent = error.message;
                    messagesDiv.appendChild(alertDiv);
                } else {
                    alert(error.message);
                }
            } else {
                const errorElement = document.getElementById(`error-${error.field}`);
                if (errorElement) {
                    errorElement.textContent = error.message;
                    errorElement.classList.add('show');
                }
            }
        });
    },
    toggleButtonLoading: (btn, loading) => {
        btn.disabled = loading;
        btn.setAttribute('aria-busy', loading.toString());
        const spinner = btn.querySelector('.loading-spinner, .spinner');
        if (spinner) spinner.style.display = loading ? 'inline-block' : 'none';
    },
    validateStep: async (step, formData) => {
        return { valid: true, errors: [] };
    },
    validateFile: async (file) => {
        const allowedTypes = ['image/jpeg', 'image/jpg', 'image/png', 'application/pdf'];
        const maxSize = 2.5 * 1024 * 1024; // 2.5MB
        if (!allowedTypes.includes(file.type)) {
            return { valid: false, error: 'Invalid file type. Please upload PDF, JPG, or PNG.' };
        }
        if (file.size > maxSize) {
            return { valid: false, error: 'File too large. Maximum 2.5MB allowed.' };
        }
        return { valid: true };
    }
};

// CRITICAL: Expose initializeBookingSystem globally FIRST
window.initializeBookingSystem = function initializeBookingSystem() {
    console.log('initializeBookingSystem called');

    // Prevent double initialization
    if (window.bookingSystemActive) {
        console.warn('Booking system already active');
        return;
    }
    window.bookingSystemActive = true;

    // Ensure URLs are set with fallbacks
    window.urls = window.urls || {};
    if (!window.urls.createCheckoutSession) {
        window.urls.createCheckoutSession = '/bookings/api/create_checkout_session/';
    }
    if (!window.urls.getPricing) {
        window.urls.getPricing = '/bookings/api/pricing/';
    }
    if (!window.urls.getActiveSchedules) {
        window.urls.getActiveSchedules = '/bookings/api/bookings/';
    }

    console.log('URLs configured:', window.urls);

    // DOM Elements
    const elements = {
        form: document.getElementById('booking-form'),
        stepsContainer: document.querySelector('.steps'),
        progressBar: document.getElementById('progress-bar'),
        progressBarFill: document.getElementById('progress-bar-fill'),
        scheduleSelect: document.getElementById('schedule_id'),
        guestEmail: document.getElementById('guest_email'),
        adultsInput: document.getElementById('adults'),
        childrenInput: document.getElementById('children'),
        infantsInput: document.getElementById('infants'),
        vehicleCheckbox: document.getElementById('add_vehicle'),
        vehicleFields: document.getElementById('vehicle-fields'),
        cargoCheckbox: document.getElementById('add_cargo'),
        cargoFields: document.getElementById('cargo-fields'),
        privacyCheckbox: document.getElementById('privacy_consent'),
        submitBtn: document.getElementById('submit-booking'),
        bookingSummary: document.getElementById('booking-summary'),
        passengerTemplate: document.getElementById('passenger-field-template'),
        currentStepInput: document.getElementById('current-step'),
        weatherInfo: document.getElementById('weather-info')
    };

    // Validate core elements
    if (!elements.form) {
        console.error('Booking form not found');
        return false;
    }

    console.log('Core elements found');

    // State management
    let appState = {
        currentStep: parseInt(elements.currentStepInput?.value) || 1,
        totalPassengers: { adults: 1, children: 0, infants: 0 },
        formData: window.bookingConfig.formData || {},
        isSubmitting: false,
        activeSchedulesMap: {}, // id -> schedule
        // Departure warning timers/ids
        departureWarn: {
            thresholdMs: 15 * 60 * 1000, // 15 minutes
            preWarnTimeoutId: null,
            countdownIntervalId: null,
            currentScheduleId: null
        }
    };

    // Validation utilities
    const validation = window.validationUtils;

    // Utility Functions
    const utils = {
        saveToSession() {
            try {
                const formData = new FormData(elements.form);
                const dataObj = Object.fromEntries(formData);
                dataObj.step = appState.currentStep;
                dataObj.timestamp = Date.now();
                // also persist add-ons selections if present
                if (appState.formData?.addOnsSelected) {
                    dataObj.addOnsSelected = appState.formData.addOnsSelected;
                }
                sessionStorage.setItem('ferryBookingData', JSON.stringify(dataObj));
                console.log('Form data saved');
            } catch (error) {
                console.warn('Failed to save session data:', error);
            }
        },

        loadFromSession() {
            try {
                const saved = sessionStorage.getItem('ferryBookingData');
                if (saved) {
                    const data = JSON.parse(saved);
                    appState.formData = { ...appState.formData, ...data };
                    appState.currentStep = parseInt(data.step) || 1;
                }
            } catch (error) {
                console.warn('Failed to load session data:', error);
            }
        },

        updateProgress(step) {
            if (elements.progressBarFill) {
                const percentage = (step / 4) * 100;
                elements.progressBarFill.style.width = `${percentage}%`;
                elements.progressBarFill.classList.remove('step-1-fill', 'step-2-fill', 'step-3-fill', 'step-4-fill');
                elements.progressBarFill.classList.add(`step-${step}-fill`);
            }

            elements.stepsContainer?.querySelectorAll('.step').forEach((stepEl, index) => {
                const stepNum = index + 1;
                stepEl.classList.toggle('active', stepNum === step);
                stepEl.classList.toggle('completed', stepNum < step);
                stepEl.setAttribute('aria-current', stepNum === step ? 'step' : 'false');
            });
        },

        getCsrfToken() {
            return window.csrfToken || document.querySelector('input[name=csrfmiddlewaretoken]')?.value || '';
        },

        async apiRequest(endpoint, options = {}) {
            const defaults = {
                method: 'POST',
                headers: {
                    'X-CSRFToken': utils.getCsrfToken(),
                    'X-Requested-With': 'XMLHttpRequest'
                },
                ...options
            };

            try {
                console.log(`API Request: ${endpoint}`);
                const response = await fetch(endpoint, defaults);
                if (!response.ok) {
                    const errorText = await response.text();
                    console.error(`API Error ${response.status}:`, errorText);
                    throw new Error(`HTTP ${response.status}: ${errorText}`);
                }
                return await response.json();
            } catch (error) {
                console.error('API request failed:', error);
                throw error;
            }
        },

        debounce(fn, delay) {
            let timeout;
            return function(...args) {
                clearTimeout(timeout);
                timeout = setTimeout(() => fn.apply(this, args), delay);
            };
        },

        /** ----------------- ADDONS PERSISTENCE HELPERS ----------------- */

        /**
         * Collect add-on selections from the DOM.
         * Recognizes inputs ending with "_quantity" or elements marked with [data-addon].
         * Attempts to read label and unit price from nearby DOM or data-attributes.
         */
        collectAddOnsSelected() {
            const entries = [];
            const qInputs = elements.form.querySelectorAll(
                'input[name$="_quantity"], select[name$="_quantity"], [data-addon]'
            );

            qInputs.forEach(input => {
                const isDataset = input.hasAttribute('data-addon');
                const name = isDataset ? input.getAttribute('data-addon') : input.name;
                if (!name) return;

                const quantityVal = isDataset ? input.getAttribute('data-quantity') : input.value;
                const qty = parseInt((quantityVal || '0'), 10);
                if (!Number.isFinite(qty) || qty <= 0) return;

                const root = input.closest('[data-addon-root]') || input.closest('.addon-row') || input.parentElement;
                const label =
                    (root?.querySelector('[data-addon-label]')?.textContent ||
                     input.getAttribute('data-addon-label') ||
                     name).trim();

                const unitStr =
                    root?.querySelector('[data-addon-price]')?.textContent ||
                    input.getAttribute('data-addon-price') ||
                    input.dataset?.price ||
                    '';

                const parsedUnit = Number.parseFloat((String(unitStr).match(/[\d.]+/) || [0])[0]) || 0;

                entries.push({
                    id: name.replace(/_quantity$/, ''),
                    label,
                    quantity: qty,
                    unitPrice: parsedUnit,
                    amount: (qty * parsedUnit)
                });
            });

            return entries;
        },

        /**
         * Save collected add-ons into appState and sessionStorage
         * to survive navigation and reloads.
         */
        saveAddOnsToState() {
            const selected = utils.collectAddOnsSelected();
            appState.formData = appState.formData || {};
            appState.formData.addOnsSelected = selected;

            const current = JSON.parse(sessionStorage.getItem('ferryBookingData') || '{}');
            current.addOnsSelected = selected;
            sessionStorage.setItem('ferryBookingData', JSON.stringify(current));

            return selected;
        }
        /** -------------------------------------------------------------- */
    };

    /* ====================== SCHEDULE FRESHNESS & WARNINGS ===================== */

    function ensureWarningContainers() {
        const select = elements.scheduleSelect;
        if (!select) return { expired: null, warning: null };

        let expiredNote = document.getElementById('schedule-expired-note');
        if (!expiredNote) {
            expiredNote = document.createElement('div');
            expiredNote.id = 'schedule-expired-note';
            expiredNote.style.display = 'none';
            expiredNote.className = 'mt-2 p-3 rounded border border-red-200 bg-red-50 text-red-700 text-sm';
            select.parentElement.appendChild(expiredNote);
        }

        let warningNote = document.getElementById('schedule-warning-note');
        if (!warningNote) {
            warningNote = document.createElement('div');
            warningNote.id = 'schedule-warning-note';
            warningNote.style.display = 'none';
            warningNote.className = 'mt-2 p-3 rounded border border-amber-200 bg-amber-50 text-amber-800 text-sm';
            select.parentElement.appendChild(warningNote);
        }

        return { expired: expiredNote, warning: warningNote };
    }

    function showExpiredScheduleNotice(msg = 'This departure is no longer available. Please choose another schedule.') {
        const { expired } = ensureWarningContainers();
        if (!expired) return;
        expired.textContent = msg;
        expired.style.display = 'block';

        // Also surface via your existing error renderer
        window.validationUtils?.displayBackendErrors?.([
            { field: 'general', message: msg }
        ]);
    }

    function clearExpiredScheduleNotice() {
        const expired = document.getElementById('schedule-expired-note');
        if (expired) {
            expired.style.display = 'none';
            expired.textContent = '';
        }
    }

    function showDepartureWarningBanner(remainingMs) {
        const { warning } = ensureWarningContainers();
        if (!warning) return;

        const mins = Math.max(0, Math.floor(remainingMs / 60000));
        const secs = Math.max(0, Math.floor((remainingMs % 60000) / 1000));
        warning.innerHTML = `
            <strong>Heads up:</strong> This departure leaves in <strong>${String(mins).padStart(2,'0')}:${String(secs).padStart(2,'0')}</strong>.
            Please complete your booking soon.
        `;
        warning.style.display = 'block';
    }

    function clearDepartureWarningBanner() {
        const warning = document.getElementById('schedule-warning-note');
        if (warning) {
            warning.style.display = 'none';
            warning.textContent = '';
        }
    }

    function clearDepartureTimers() {
        if (appState.departureWarn.preWarnTimeoutId) {
            clearTimeout(appState.departureWarn.preWarnTimeoutId);
            appState.departureWarn.preWarnTimeoutId = null;
        }
        if (appState.departureWarn.countdownIntervalId) {
            clearInterval(appState.departureWarn.countdownIntervalId);
            appState.departureWarn.countdownIntervalId = null;
        }
    }

    async function refreshActiveSchedulesIfNeeded() {
        try {
            const res = await utils.apiRequest(window.urls.getActiveSchedules || '/bookings/api/bookings/', { method: 'GET' });
            const list = res.schedules || [];
            appState.activeSchedulesMap = {};
            list.forEach(s => { appState.activeSchedulesMap[String(s.id)] = s; });
            return list;
        } catch(e) {
            console.warn('Could not refresh schedules:', e);
            return null;
        }
    }

    /**
     * Validate the selected schedule is still valid & in the future.
     * Returns true if OK, false if invalid/expired (and informs the user).
     */
    async function ensureSelectedScheduleIsFresh() {
        const select = elements.scheduleSelect;
        const selectedId = select?.value;
        if (!selectedId) return false;

        // Local cache check
        let s = appState.activeSchedulesMap[String(selectedId)];
        if (!s) {
            await refreshActiveSchedulesIfNeeded();
            s = appState.activeSchedulesMap[String(selectedId)];
        }
        if (!s) {
            showExpiredScheduleNotice('This departure is no longer available. Please choose another schedule.');
            return false;
        }

        // Status + time check
        const now = Date.now();
        const depMs = new Date(s.departure_time).getTime();
        if ((s.status && s.status !== 'scheduled') || isNaN(depMs) || depMs <= now) {
            showExpiredScheduleNotice('This departure has already left. Please choose another schedule.');
            return false;
        }

        // If previously shown, clear the banner
        clearExpiredScheduleNotice();
        return true;
    }

    /**
     * Set up a timed warning that starts at 15 minutes before departure.
     * - If already within 15 minutes, show live countdown immediately.
     * - If more than 15 minutes away, schedule a timeout to show banner at T-15.
     * - Clears and resets when schedule changes.
     */
    async function setupDepartureNotifierForSelectedSchedule() {
        clearDepartureTimers();
        clearDepartureWarningBanner();

        const select = elements.scheduleSelect;
        if (!select || !select.value) return;

        // Make sure we have the schedule data
        let s = appState.activeSchedulesMap[String(select.value)];
        if (!s) {
            await refreshActiveSchedulesIfNeeded();
            s = appState.activeSchedulesMap[String(select.value)];
            if (!s) return; // nothing to do
        }

        appState.departureWarn.currentScheduleId = String(select.value);

        const now = Date.now();
        const depMs = new Date(s.departure_time).getTime();
        if (isNaN(depMs)) return;

        const delta = depMs - now;

        // If already past, trigger expired handling
        if (delta <= 0) {
            showExpiredScheduleNotice('This departure has already left. Please choose another schedule.');
            return;
        }

        // If within threshold, start countdown immediately
        if (delta <= appState.departureWarn.thresholdMs) {
            showDepartureWarningBanner(delta);
            appState.departureWarn.countdownIntervalId = setInterval(() => {
                const remaining = depMs - Date.now();
                if (remaining <= 0) {
                    clearDepartureTimers();
                    showExpiredScheduleNotice('This departure has already left. Please choose another schedule.');
                    clearDepartureWarningBanner();
                } else {
                    showDepartureWarningBanner(remaining);
                }
            }, 1000);
            return;
        }

        // If more than threshold away, schedule a pre-warn timeout
        const wait = delta - appState.departureWarn.thresholdMs;
        appState.departureWarn.preWarnTimeoutId = setTimeout(() => {
            // Only warn if user still has the same schedule selected
            if (elements.scheduleSelect?.value === appState.departureWarn.currentScheduleId) {
                setupDepartureNotifierForSelectedSchedule();
            }
        }, wait);
    }

    /* ====================== END SCHEDULE FRESHNESS & WARNINGS ================== */

    function restoreFormData() {
        Object.entries(appState.formData).forEach(([key, value]) => {
            const field = elements.form.querySelector(`[name="${key}"]`);
            if (field) {
                if (field.type === 'checkbox') {
                    field.checked = value === 'on' || value === true;
                    if (key === 'add_vehicle' && field.checked) {
                        elements.vehicleFields?.classList.remove('hidden');
                    }
                    if (key === 'add_cargo' && field.checked) {
                        elements.cargoFields?.classList.remove('hidden');
                    }
                } else if (field.type !== 'file') {
                    field.value = value;
                }
            }
        });

        // ensure add-ons in form are captured right after restoration
        utils.saveAddOnsToState();
    }

    function showStep(stepNumber) {
        appState.currentStep = Math.max(1, Math.min(4, stepNumber));

        document.querySelectorAll('.form-step').forEach((stepEl, index) => {
            const stepIndex = index + 1;
            stepEl.classList.toggle('active', stepIndex === appState.currentStep);
            stepEl.style.display = stepIndex === appState.currentStep ? 'block' : 'none';
        });

        utils.updateProgress(appState.currentStep);
        elements.currentStepInput.value = appState.currentStep;

        setTimeout(() => {
            const activeStep = document.querySelector('.form-step.active');
            const firstInput = activeStep?.querySelector('input, select, textarea');
            firstInput?.focus();
        }, 100);

        utils.saveToSession();

        if (appState.currentStep === 4) {
            loadSummary();
        }
        if (appState.currentStep === 2) {
            updatePassengerFields();
        }

        console.log(`Step ${appState.currentStep} shown`);
    }

    function updatePassengerFields() {
        console.log('Updating passenger fields...');

        appState.totalPassengers = {
            adults: Math.max(1, parseInt(elements.adultsInput?.value) || 1),
            children: parseInt(elements.childrenInput?.value) || 0,
            infants: parseInt(elements.infantsInput?.value) || 0
        };
        console.log('Passenger counts:', appState.totalPassengers);

        const passengerTypes = ['adult', 'child', 'infant'];
        const containers = {
            adult: document.getElementById('adult-fields'),
            child: document.getElementById('child-fields'),
            infant: document.getElementById('infant-fields')
        };

        const countMap = { adult: 'adults', child: 'children', infant: 'infants' };

        if (!elements.passengerTemplate) {
            console.error('Passenger template not found');
            return;
        }

        passengerTypes.forEach(type => {
            const countKey = countMap[type];
            const count = appState.totalPassengers[countKey];
            const container = containers[type];

            if (!container) return;

            const currentValues = {};
            container.querySelectorAll('input, select, textarea').forEach(field => {
                currentValues[field.name] = field.value;
            });

            container.innerHTML = '';

            for (let i = 0; i < count; i++) {
                const clone = elements.passengerTemplate.content.cloneNode(true);

                clone.querySelectorAll('[id], [name], [for]').forEach(el => {
                    ['id', 'name', 'for'].forEach(attr => {
                        const val = el.getAttribute(attr);
                        if (val) {
                            el.setAttribute(attr, val.replace('{type}', type).replace('{index}', i));
                        }
                    });
                });

                const title = clone.querySelector('.passenger-title');
                if (title) title.textContent = `${type.charAt(0).toUpperCase() + type.slice(1)} ${i + 1}`;

                const ageSection = clone.querySelector('[data-for="non-infant"]');
                const dobSection = clone.querySelector('[data-for="infant"]');
                const linkedSection = clone.querySelector('[data-for="child-infant"]');

                if (ageSection) ageSection.style.display = type !== 'infant' ? 'block' : 'none';
                if (dobSection) dobSection.style.display = type === 'infant' ? 'block' : 'none';
                if (linkedSection) linkedSection.style.display = type !== 'adult' ? 'block' : 'none';

                const content = clone.querySelector('.passenger-content');
                if (content) content.style.display = 'block';

                const header = clone.querySelector('.passenger-header, .passenger-card-header');
                if (header) {
                    header.setAttribute('aria-expanded', 'true');
                    if (!header.querySelector('.toggle-icon')) {
                        const icon = document.createElement('span');
                        icon.className = 'toggle-icon';
                        icon.textContent = 'Down Arrow';
                        header.appendChild(icon);
                    }
                    header.classList.add('passenger-card-header');
                }

                const passengerCard = clone.querySelector('.passenger-card') || clone;
                passengerCard.classList.add('passenger-card');

                container.appendChild(clone);

                const newFields = container.querySelectorAll(`input[name*="${type}_${i}"], select[name*="${type}_${i}"]`);
                newFields.forEach(field => {
                    const fieldName = field.getAttribute('name');
                    if (appState.formData[fieldName] !== undefined) {
                        if (field.type === 'checkbox') {
                            field.checked = appState.formData[fieldName] === 'on' || appState.formData[fieldName] === true;
                        } else {
                            field.value = appState.formData[fieldName];
                        }
                    } else if (currentValues[fieldName] !== undefined) {
                        field.value = currentValues[fieldName];
                    }
                });
            }

            console.log(`${type} fields generated and restored: ${container.children.length}`);
        });

        setTimeout(() => {
            const adults = [];
            document.querySelectorAll('#adult-fields .passenger-card').forEach((card, index) => {
                const firstNameInput = card.querySelector(`input[name="adult_first_name_${index}"]`);
                const lastNameInput = card.querySelector(`input[name="adult_last_name_${index}"]`);
                const firstName = firstNameInput?.value || '';
                const lastName = lastNameInput?.value || '';
                adults.push({
                    index,
                    name: `${firstName} ${lastName}`.trim() || `Adult ${index + 1}`
                });
            });

            ['child', 'infant'].forEach(type => {
                const count = appState.totalPassengers[countMap[type]];
                for (let i = 0; i < count; i++) {
                    const select = document.querySelector(`select[name="${type}_linked_adult_${i}"]`);
                    if (!select) continue;

                    select.innerHTML = '<option value="">Select adult passenger</option>';

                    adults.forEach(adult => {
                        const option = document.createElement('option');
                        option.value = adult.index;
                        option.textContent = adult.name;
                        select.appendChild(option);
                    });

                    const savedKey = `${type}_linked_adult_${i}`;
                    if (appState.formData[savedKey] !== undefined) {
                        select.value = appState.formData[savedKey];
                    }
                }
            });

            console.log('Linked adults populated');
        }, 100);

        document.querySelectorAll('input[type="file"]').forEach(input => {
            input.removeEventListener('change', handleFileChange);
            input.addEventListener('change', (e) => handleFileChange(e.target));
        });

        utils.saveToSession();
        // keep add-ons state in sync after any passenger UI rebuild
        utils.saveAddOnsToState();
    }

    async function validateCurrentStep() {
        const activeStep = document.querySelector('.form-step.active');
        if (activeStep) activeStep.setAttribute('aria-busy', 'true');

        const formData = new FormData(elements.form);
        try {
            const response = await fetch('/bookings/api/validate_step/', {
                method: 'POST',
                body: formData,
                headers: { 'X-CSRFToken': utils.getCsrfToken() }
            });
            const result = await response.json();

            // --- Normalize server error shapes to [{ field, message }] ---
            if (!result.valid && result.errors && !Array.isArray(result.errors)) {
                const normalized = [];
                for (const [field, val] of Object.entries(result.errors)) {
                    if (Array.isArray(val)) {
                        val.forEach(msg => normalized.push({ field, message: String(msg) }));
                    } else if (val && typeof val === 'object') {
                        Object.values(val).forEach(msg => normalized.push({ field, message: String(msg) }));
                    } else {
                        normalized.push({ field, message: String(val || 'Invalid') });
                    }
                }
                result.errors = normalized;
            }
            // ----------------------------------------------------------------

            if (!result.valid) {
                validation.displayBackendErrors(result.errors);
                return false;
            }
        } catch (error) {
            console.warn('Validation failed:', error);
        } finally {
            if (activeStep) activeStep.setAttribute('aria-busy', 'false');
        }
        return true;
    }

    function setupEventListeners() {
        document.querySelectorAll('.next-step').forEach(btn => {
            btn.classList.add('cta-button', 'cta-button-primary');
            btn.addEventListener('click', async (e) => {
                e.preventDefault();
                validation.toggleButtonLoading(btn, true);

                if (await validateCurrentStep()) {
                    const nextStep = parseInt(btn.dataset.next);
                    showStep(nextStep);
                }

                validation.toggleButtonLoading(btn, false);
            });
        });

        document.querySelectorAll('.prev-step').forEach(btn => {
            btn.classList.add('cta-button', 'cta-button-secondary');
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                const prevStep = parseInt(btn.dataset.prev) || appState.currentStep - 1;
                showStep(prevStep);
            });
        });

        [elements.adultsInput, elements.childrenInput, elements.infantsInput].forEach(input => {
            if (input) {
                input.classList.add('form-input');
                input.addEventListener('change', utils.debounce(updatePassengerFields, 300));
            }
        });

        if (elements.vehicleCheckbox) {
            const wrapper = elements.vehicleCheckbox.closest('.form-group') || elements.vehicleCheckbox.parentElement;
            wrapper?.classList.add('form-checkbox');
            elements.vehicleCheckbox.addEventListener('change', () => {
                elements.vehicleFields?.classList.toggle('hidden', !elements.vehicleCheckbox.checked);
                utils.saveToSession();
            });
        }

        if (elements.cargoCheckbox) {
            const wrapper = elements.cargoCheckbox.closest('.form-group') || elements.cargoCheckbox.parentElement;
            wrapper?.classList.add('form-checkbox');
            elements.cargoCheckbox.addEventListener('change', () => {
                elements.cargoFields?.classList.toggle('hidden', !elements.cargoCheckbox.checked);
                utils.saveToSession();
            });
        }

        if (elements.submitBtn) {
            elements.submitBtn.classList.add('cta-button', 'cta-button-primary');
            elements.submitBtn.addEventListener('click', async (e) => {
                e.preventDefault();
                console.log('Payment initiated');

                if (!(await validateCurrentStep())) {
                    console.warn('Validation failed');
                    return;
                }

                // NEW: Guard — ensure schedule still fresh before creating checkout session
                const stillFresh = await ensureSelectedScheduleIsFresh();
                if (!stillFresh) {
                    validation.toggleButtonLoading(elements.submitBtn, false);
                    return; // stop checkout flow
                }

                if (!window.stripe) {
                    validation.displayBackendErrors([{ field: 'general', message: 'Payment system not available' }]);
                    return;
                }

                validation.toggleButtonLoading(elements.submitBtn, true);

                try {
                    const formData = new FormData(elements.form);
                    const checkoutUrl = window.urls.createCheckoutSession || '/bookings/api/create_checkout_session/';
                    console.log('Creating checkout session at:', checkoutUrl);

                    const response = await fetch(checkoutUrl, {
                        method: 'POST',
                        body: formData,
                        headers: {
                            'X-CSRFToken': utils.getCsrfToken(),
                            'X-Requested-With': 'XMLHttpRequest'
                        }
                    });

                    if (!response.ok) {
                        const errorData = await response.json().catch(() => ({}));
                        const errorMsg = errorData.errors?.[0]?.message || `Server error: ${response.status}`;
                        throw new Error(errorMsg);
                    }

                    const result = await response.json();
                    console.log('Checkout session created:', result);

                    if (result.sessionId) {
                        const { error } = await stripe.redirectToCheckout({
                            sessionId: result.sessionId
                        });

                        if (error) {
                            console.error('Stripe checkout error:', error);
                            validation.displayBackendErrors([{ field: 'general', message: error.message }]);
                        }
                    } else {
                        const errorMsg = result.error || 'Failed to create payment session';
                        validation.displayBackendErrors([{ field: 'general', message: errorMsg }]);
                    }
                } catch (error) {
                    console.error('Payment error:', error);
                    validation.displayBackendErrors([{
                        field: 'general',
                        message: `Payment failed: ${error.message}`
                    }]);
                } finally {
                    validation.toggleButtonLoading(elements.submitBtn, false);
                }
            });
        }

        // Existing file change handler
        elements.form.addEventListener('change', async (e) => {
            if (e.target.type === 'file') {
                await handleFileChange(e.target);
            }
        });

        // NEW: capture any addon quantity changes and persist
        elements.form.addEventListener('change', (e) => {
            const t = e.target;
            if (!t) return;
            const isAddon = t.matches('input[name$="_quantity"], select[name$="_quantity"], [data-addon]');
            if (isAddon) {
                utils.saveAddOnsToState();
                utils.saveToSession();
            }
        });

        // NEW: when schedule changes, clear banners, re-check, and set up notifier
        elements.scheduleSelect?.addEventListener('change', async () => {
            clearExpiredScheduleNotice();
            clearDepartureWarningBanner();
            clearDepartureTimers();
            await ensureSelectedScheduleIsFresh();
            await setupDepartureNotifierForSelectedSchedule();
        });

        elements.form.addEventListener('input', utils.debounce(utils.saveToSession, 1000));
        elements.form.addEventListener('change', utils.saveToSession);

        elements.form.addEventListener('click', (e) => {
            const header = e.target.closest('.passenger-header, .passenger-card-header');
            if (header) {
                const content = header.nextElementSibling;
                const icon = header.querySelector('.toggle-icon');
                const isExpanded = content.style.display !== 'none';

                content.style.display = isExpanded ? 'none' : 'block';
                if (icon) {
                    icon.textContent = isExpanded ? 'Right Arrow' : 'Down Arrow';
                }
                header.setAttribute('aria-expanded', !isExpanded);
            }
        });

        // Proactive re-checks while the user is on the page
        setInterval(ensureSelectedScheduleIsFresh, 30_000);
        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'visible') ensureSelectedScheduleIsFresh();
        });
        window.addEventListener('focus', ensureSelectedScheduleIsFresh);
    }

    async function handleFileChange(input) {
        const file = input.files[0];
        if (!file) return;

        const result = await validation.validateFile(file, input);
        if (!result.valid) {
            input.value = '';
            validation.displayBackendErrors([{ field: input.name, message: result.error }]);
            return;
        }

        const preview = input.parentElement.querySelector('.file-preview');
        if (preview) {
            preview.innerHTML = '';
            preview.className = 'file-preview';
            if (file.type.startsWith('image/')) {
                const img = document.createElement('img');
                img.src = URL.createObjectURL(file);
                img.alt = `Preview of ${file.name}`;
                img.style.maxWidth = '100px';
                img.style.maxHeight = '100px';
                preview.appendChild(img);
            } else {
                const fileInfo = document.createElement('div');
                fileInfo.className = 'pdf-icon';
                fileInfo.innerHTML = `PDF ${file.name} (${(file.size / 1024).toFixed(1)}KB)`;
                preview.appendChild(fileInfo);
            }
        }
    }

    async function loadSummary() {
        if (!elements.bookingSummary || !elements.scheduleSelect?.value) {
            console.warn('Cannot load summary: missing elements or schedule');
            return;
        }

        // ensure we have most recent add-on selections before rendering
        utils.saveAddOnsToState();

        // NEW: guard against stale/just-departed schedules BEFORE pricing call
        const freshOk = await ensureSelectedScheduleIsFresh();
        if (!freshOk) {
            elements.bookingSummary.innerHTML = `
                <div class="p-6 rounded-lg border border-red-200 bg-red-50 text-red-700">
                  <div class="font-semibold mb-1">Your selected departure is no longer available.</div>
                  <p class="text-sm mb-4">It likely departed moments ago. Please select another schedule to continue.</p>
                  <button class="px-4 py-2 rounded bg-blue-600 text-white" id="btn-reload-schedules">Refresh schedules</button>
                </div>
            `;
            document.getElementById('btn-reload-schedules')?.addEventListener('click', () => {
                populateSchedules();
                document.getElementById('schedule_id')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
            });
            return;
        }

        try {
            elements.bookingSummary.innerHTML = `
                <div class="summary-card p-6 text-center">
                    <div class="loading-spinner mx-auto mb-4" aria-hidden="true"></div>
                    <p class="text-gray-600">Calculating your booking total...</p>
                </div>
            `;

            const pricingUrl = window.urls.getPricing || '/bookings/api/pricing/';
            const formData = new FormData(elements.form);
            const response = await utils.apiRequest(pricingUrl, { body: formData });

            const total = parseFloat(response.total_price || 0).toFixed(2);
            const breakdown = response.breakdown || {};
            const scheduleInfo = response.schedule_info || {};

            let summaryHTML = `
                <div class="summary-card" data-aos="fade-up">
                    <!-- Schedule Information -->
                    ${scheduleInfo.departure_time || scheduleInfo.route ? `
                        <div class="summary-section mb-6 p-4 bg-gray-50 rounded-lg border border-gray-200" data-aos="fade-up" data-aos-delay="100">
                            <h4 class="font-semibold text-gray-800 mb-2">Trip Details</h4>
                            ${scheduleInfo.route ? `<div class="text-sm text-gray-600 mb-1">${scheduleInfo.route}</div>` : ''}
                            ${scheduleInfo.departure_time ? `<div class="text-lg font-medium">${scheduleInfo.departure_time}</div>` : ''}
                            ${scheduleInfo.return_time ? `<div class="text-sm text-gray-500">Return: ${scheduleInfo.return_time}</div>` : ''}
                        </div>
                    ` : ''}

                    <!-- Total Price Header -->
                    <div class="flex justify-between items-start mb-6" data-aos="fade-up" data-aos-delay="200">
                        <div>
                            <h3 class="text-2xl font-bold text-gray-800 mb-1">Booking Summary</h3>
                            <p class="text-gray-600">Review your selection before payment</p>
                        </div>
                        <div class="text-right">
                            <div class="text-3xl font-bold text-primary">FJD ${total}</div>
                            <div class="text-sm text-green-600 font-medium">Secure payment required</div>
                        </div>
                    </div>

                    <div class="space-y-6 mb-6">
                        <!-- Passengers -->
                        <div class="summary-section" data-aos="fade-up" data-aos-delay="300">
                            <h4 class="font-semibold text-gray-800 mb-2">Passengers</h4>
                            <div class="space-y-3">
            `;

            ['adults', 'children', 'infants'].forEach(type => {
                const count = parseInt(elements.form.querySelector(`[name="${type}"]`)?.value || 0);
                if (count > 0) {
                    const amount = parseFloat(breakdown[type] || 0);
                    const unitPrice = count > 0 ? (amount / count).toFixed(2) : '0.00';
                    const typeLabel = type.charAt(0).toUpperCase() + type.slice(1) + (count > 1 ? 's' : '');
                    summaryHTML += `
                        <div class="summary-row">
                            <span class="summary-label">${typeLabel} × ${count}</span>
                            <span class="summary-value">${count} × FJD ${unitPrice} = FJD ${amount.toFixed(2)}</span>
                        </div>
                    `;
                }
            });

            summaryHTML += `
                            </div>
                        </div>
            `;

            if (breakdown.vehicle && parseFloat(breakdown.vehicle) > 0) {
                const vehicleType = elements.form.querySelector('select[name="vehicle_type"]')?.value || 'Vehicle';
                summaryHTML += `
                    <div class="summary-section" data-aos="fade-up" data-aos-delay="400">
                        <h4 class="font-semibold text-gray-800 mb-2">Vehicle</h4>
                        <div class="summary-row">
                            <span class="summary-label">${vehicleType}</span>
                            <span class="summary-value">+ FJD ${parseFloat(breakdown.vehicle).toFixed(2)}</span>
                        </div>
                    </div>
                `;
            }

            if (breakdown.cargo && parseFloat(breakdown.cargo) > 0) {
                const cargoWeight = elements.form.querySelector('input[name="cargo_weight_kg"]')?.value || '';
                const cargoLabel = cargoWeight ? `Cargo (${cargoWeight}kg)` : 'Cargo';
                summaryHTML += `
                    <div class="summary-section" data-aos="fade-up" data-aos-delay="500">
                        <h4 class="font-semibold text-gray-800 mb-2">Cargo</h4>
                        <div class="summary-row">
                            <span class="summary-label">${cargoLabel}</span>
                            <span class="summary-value">+ FJD ${parseFloat(breakdown.cargo).toFixed(2)}</span>
                        </div>
                    </div>
                `;
            }

            // --- Add-ons (use state if present; fallback to bookingConfig) ---
            let addOns = [];
            const stateAddOns = (appState.formData && appState.formData.addOnsSelected) || [];

            if (stateAddOns.length > 0) {
                addOns = stateAddOns.map(a => ({
                    ...a,
                    unitPrice: Number.parseFloat(a.unitPrice || 0),
                    amount: Number.parseFloat(a.amount || (a.quantity * (a.unitPrice || 0))).toFixed(2)
                }));
            } else {
                (window.bookingConfig.addOns || []).forEach(addon => {
                    const quantity = parseInt(elements.form.querySelector(`[name="${addon.id}_quantity"]`)?.value || 0);
                    if (quantity > 0) {
                        const amount = (quantity * Number.parseFloat(addon.price || 0)).toFixed(2);
                        addOns.push({
                            id: addon.id,
                            label: addon.label,
                            quantity,
                            amount,
                            unitPrice: Number.parseFloat(addon.price || 0).toFixed(2)
                        });
                    }
                });
            }

            if (addOns.length > 0) {
                const addOnsTotal = addOns.reduce((sum, addon) => sum + Number.parseFloat(addon.amount), 0).toFixed(2);
                const backendAddOnsTotal = Number.parseFloat(breakdown.addons || 0).toFixed(2);
                if (backendAddOnsTotal !== '0.00' && addOnsTotal !== backendAddOnsTotal) {
                    console.warn(`Add-ons total mismatch: Frontend=${addOnsTotal}, Backend=${backendAddOnsTotal}`);
                }

                summaryHTML += `
                    <div class="summary-section addon-group" data-aos="fade-up" data-aos-delay="600">
                        <h4 class="font-semibold text-gray-800 mb-2">Add-ons</h4>
                        <div class="space-y-3">
                            ${addOns.map(a => `
                                <div class="summary-row">
                                    <span class="summary-label">${a.label} × ${a.quantity}</span>
                                    <span class="summary-value">${a.quantity} × FJD ${(Number(a.unitPrice)).toFixed(2)} = FJD ${Number(a.amount).toFixed(2)}</span>
                                </div>
                            `).join('')}
                            <div class="summary-row font-semibold">
                                <span class="summary-label">Add-ons Total</span>
                                <span class="summary-value">FJD ${addOnsTotal}</span>
                            </div>
                        </div>
                    </div>
                `;
            }
            // -----------------------------------------------------------------

            const subtotal = parseFloat(breakdown.subtotal || total).toFixed(2);
            if (breakdown.taxes || breakdown.fees) {
                summaryHTML += `
                    <div class="summary-section" data-aos="fade-up" data-aos-delay="700">
                        <div class="summary-row font-semibold">
                            <span class="summary-label">Subtotal</span>
                            <span class="summary-value">FJD ${subtotal}</span>
                        </div>
                    </div>
                `;
            }

            if (breakdown.taxes && parseFloat(breakdown.taxes) > 0) {
                summaryHTML += `
                    <div class="summary-section" data-aos="fade-up" data-aos-delay="800">
                        <div class="summary-row">
                            <span class="summary-label">Taxes</span>
                            <span class="summary-value">+ FJD ${parseFloat(breakdown.taxes).toFixed(2)}</span>
                        </div>
                    </div>
                `;
            }

            if (breakdown.fees && parseFloat(breakdown.fees) > 0) {
                summaryHTML += `
                    <div class="summary-section" data-aos="fade-up" data-aos-delay="900">
                        <div class="summary-row">
                            <span class="summary-label">Processing Fees</span>
                            <span class="summary-value">+ FJD ${parseFloat(breakdown.fees).toFixed(2)}</span>
                        </div>
                    </div>
                `;
            }

            summaryHTML += `
                    </div>

                    <!-- Total Section -->
                    <div class="border-t pt-4 bg-gray-50 rounded-lg p-4" data-aos="fade-up" data-aos-delay="1000">
                        <div class="flex justify-between items-center text-lg font-semibold mb-2">
                            <span class="text-gray-800">Total Amount Due</span>
                            <span class="text-2xl font-bold text-primary">FJD ${total}</span>
                        </div>
                        <div class="text-center">
                            <p class="text-xs text-gray-500 mb-3">
                                Secure payment via Stripe. Your information is encrypted and safe.
                            </p>
                            ${response.payment_methods ? `
                                <p class="text-xs text-gray-500">
                                    Accepts Visa, Mastercard, American Express
                                </p>
                            ` : ''}
                        </div>
                    </div>
                </div>
            `;

            elements.bookingSummary.innerHTML = summaryHTML;

            const summaryCard = elements.bookingSummary.querySelector('.summary-card');
            if (appState.currentStep === 4 && summaryCard) {
                summaryCard.classList.add('step-4-active');
            }

        } catch (error) {
            console.error('Error loading summary:', error);
            elements.bookingSummary.innerHTML = `
                <div class="p-6 rounded-lg border border-red-200 bg-red-50 text-red-700">
                    <div class="font-semibold mb-1">Unable to calculate pricing.</div>
                    <p class="text-sm mb-4">Please ensure you've selected a valid schedule and passenger details, then try again.</p>
                    <button class="px-4 py-2 rounded bg-blue-600 text-white" id="btn-reload-schedules">Refresh schedules</button>
                </div>
            `;
            document.getElementById('btn-reload-schedules')?.addEventListener('click', () => {
                populateSchedules();
                document.getElementById('schedule_id')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
            });
        }
    }

    async function populateSchedules() {
        try {
           // Build URL with current route/date from form or URL params
            const scheduleUrl = new URL(window.urls.getActiveSchedules || '/bookings/api/bookings/', window.location.origin);
            const currentRoute = elements.form.querySelector('[name="route"]')?.value?.trim();
            const currentDate = elements.form.querySelector('[name="date"]')?.value;

            if (currentRoute) {
                scheduleUrl.searchParams.set('route', encodeURIComponent(currentRoute));
            }
            if (currentDate) {
                scheduleUrl.searchParams.set('date', currentDate);
            }

            const schedulesResponse = await utils.apiRequest(scheduleUrl.toString(), { method: 'GET' });
            const schedules = schedulesResponse.schedules || [];
            if (!elements.scheduleSelect) {
                console.error('Schedule select element not found');
                return;
            }

            // Update map for freshness & notifier
            appState.activeSchedulesMap = {};
            schedules.forEach(s => { appState.activeSchedulesMap[String(s.id)] = s; });

            // Sort schedules by departure time ascending
            schedules.sort((a, b) => new Date(a.departure_time) - new Date(b.departure_time));

            // Group schedules by departure date (YYYY-MM-DD)
            const groupedSchedules = schedules.reduce((groups, schedule) => {
                const departureDate = new Date(schedule.departure_time).toISOString().split('T')[0];
                if (!groups[departureDate]) {
                    groups[departureDate] = [];
                }
                groups[departureDate].push(schedule);
                return groups;
            }, {});

            // Clear select and add default option
            elements.scheduleSelect.innerHTML = '<option value="">Select a schedule</option>';

            // Create optgroups for each date
            Object.keys(groupedSchedules).sort().forEach(dateKey => {
                const group = document.createElement('optgroup');
                const dateObj = new Date(dateKey);
                group.label = dateObj.toLocaleDateString('en-GB', {
                    weekday: 'long',
                    year: 'numeric',
                    month: 'long',
                    day: 'numeric'
                });

                groupedSchedules[dateKey].forEach(schedule => {
                    const option = document.createElement('option');
                    option.value = schedule.id;

                    // Improved display: Ferry - Route - Time (and return if available) - Seats
                    let displayText = `Ferry ${schedule.ferry_name} - ${schedule.route} - Dep: ${new Date(schedule.departure_time).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}`;
                    if (schedule.return_time) {
                        displayText += ` | Ret: ${new Date(schedule.return_time).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}`;
                    }
                    displayText += ` (Seats: ${schedule.available_seats})`;

                    option.textContent = displayText;
                    group.appendChild(option);
                });

                elements.scheduleSelect.appendChild(group);
            });

            // Restore saved selection if available
            if (appState.formData.schedule_id) {
                elements.scheduleSelect.value = appState.formData.schedule_id;
            }

            // Set up notifier for restored selection
            await setupDepartureNotifierForSelectedSchedule();

            console.log('Active schedules populated and grouped:', schedules.length);
        } catch (error) {
            console.error('Error fetching active schedules:', error);
            if (elements.scheduleSelect) {
                elements.scheduleSelect.innerHTML = '<option value="">No active schedules available</option>';
            }
            showToast('error', 'Failed to load active schedules. Please try refreshing the page.');
        }
    }

    // ---------------------------------------------------------------
    // Helper: wait for an <option> to appear
    // ---------------------------------------------------------------
    function waitForOption(select, value, timeout = 3000) {
        return new Promise((resolve, reject) => {
            if (select.querySelector(`option[value="${value}"]`)) return resolve();
            const start = Date.now();
            const iv = setInterval(() => {
                const opt = select.querySelector(`option[value="${value}"]`);
                if (opt) { clearInterval(iv); resolve(); }
                else if (Date.now() - start > timeout) { clearInterval(iv); reject(new Error(`Option ${value} not found`)); }
            }, 50);
        });
    }

    // ---------------------------------------------------------------
    // Helper: safely select schedule + fire change
    // ---------------------------------------------------------------
    async function selectScheduleIfNeeded(select, scheduleId) {
        if (!scheduleId || !select) return;
        try { await waitForOption(select, scheduleId); }
        catch (e) { console.warn(e.message); return; }
        select.value = scheduleId;
        select.dispatchEvent(new Event('change', { bubbles: true }));
    }

    // ---------------------------------------------------------------
    // init() – now async‑aware
    // ---------------------------------------------------------------
    function init() {
        console.log('Initializing booking system...');

        elements.form?.classList.add('booking-form-container');
        elements.form?.querySelectorAll('input:not([type="file"]), select, textarea').forEach(el => {
            el.classList.add('form-input', 'form-select');
        });

        utils.loadFromSession();

        // === READ URL PARAMS ===
        const urlParams = new URLSearchParams(window.location.search);
        const urlRoute      = urlParams.get('route');
        const urlDate       = urlParams.get('date');
        const urlPassengers = urlParams.get('passengers');
        const urlScheduleId = urlParams.get('schedule_id');

        if (urlRoute)      appState.formData.route = urlRoute;
        if (urlDate)       appState.formData.date  = urlDate;
        if (urlPassengers) appState.formData.passengers = urlPassengers;
        if (urlScheduleId) appState.formData.schedule_id = urlScheduleId;

        // -----------------------------------------------------------------
        // 1. Load schedules → 2. restore → 3. select → 4. scroll
        // -----------------------------------------------------------------
        (async () => {
            try {
                await populateSchedules();               // <-- fills <select>
                restoreFormData();                       // <-- restores schedule_id
                updatePassengerFields();

                await selectScheduleIfNeeded(elements.scheduleSelect, urlScheduleId);

                if (urlRoute || urlDate || urlScheduleId) {
                    setTimeout(() => elements.scheduleSelect?.scrollIntoView({ behavior: 'smooth', block: 'center' }), 500);
                }
            } catch (e) { console.error('Schedule init error:', e); }
        })();

        setupEventListeners();
        showStep(appState.currentStep);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    return true;
};

console.log('Book.js loaded successfully');
console.log('initializeBookingSystem available:', typeof window.initializeBookingSystem);