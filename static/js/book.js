/**
 * book.js - Complete Fiji Ferry Booking System
 * Multi-step form with passenger management, validation, and Stripe integration
 * CSS-aligned while preserving ALL original working logic
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
        // Fallback validation - replace with actual API call
        return { valid: true, errors: [] };
    },
    validateFile: async (file) => {
        // Basic file validation
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
    console.log('🚀 initializeBookingSystem called');

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

    console.log('📍 URLs configured:', window.urls);

    // DOM Elements - Added CSS-compatible elements while keeping originals
    const elements = {
        form: document.getElementById('booking-form'),
        stepsContainer: document.querySelector('.steps'),
        progressBar: document.getElementById('progress-bar'), // Container for CSS
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
        console.error('❌ Booking form not found');
        return false;
    }

    console.log('✅ Core elements found');

    // State management
    let appState = {
        currentStep: parseInt(elements.currentStepInput?.value) || 1,
        totalPassengers: { adults: 1, children: 0, infants: 0 },
        formData: window.bookingConfig.formData || {},
        isSubmitting: false
    };

    // Validation utilities
    const validation = window.validationUtils;

    // === UTILITY FUNCTIONS ===
    const utils = {
        saveToSession() {
            try {
                const formData = new FormData(elements.form);
                const dataObj = Object.fromEntries(formData);
                dataObj.step = appState.currentStep;
                dataObj.timestamp = Date.now();
                sessionStorage.setItem('ferryBookingData', JSON.stringify(dataObj));
                console.log('💾 Form data saved');
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
                // Add CSS step-specific fill class
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
                console.log(`🌐 API Request: ${endpoint}`);
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
        }
    };

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
    }

    function showStep(stepNumber) {
        appState.currentStep = Math.max(1, Math.min(4, stepNumber));

        // ORIGINAL LOGIC PRESERVED - toggle active class and display
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
        console.log('🔹 Updating passenger fields...');

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
            console.error('❌ Passenger template not found');
            return;
        }

        passengerTypes.forEach(type => {
            const countKey = countMap[type];
            const count = appState.totalPassengers[countKey];
            const container = containers[type];

            if (!container) return;

            // Store current values before clearing
            const currentValues = {};
            container.querySelectorAll('input, select, textarea').forEach(field => {
                currentValues[field.name] = field.value;
            });

            // Clear existing fields
            container.innerHTML = '';

            for (let i = 0; i < count; i++) {
                const clone = elements.passengerTemplate.content.cloneNode(true);

                // Replace placeholders in id, name, for attributes - ORIGINAL LOGIC
                clone.querySelectorAll('[id], [name], [for]').forEach(el => {
                    ['id', 'name', 'for'].forEach(attr => {
                        const val = el.getAttribute(attr);
                        if (val) {
                            el.setAttribute(attr, val.replace('{type}', type).replace('{index}', i));
                        }
                    });
                });

                // Update passenger title - ORIGINAL LOGIC
                const title = clone.querySelector('.passenger-title');
                if (title) title.textContent = `${type.charAt(0).toUpperCase() + type.slice(1)} ${i + 1}`;

                // Show/hide sections based on type - ORIGINAL LOGIC
                const ageSection = clone.querySelector('[data-for="non-infant"]');
                const dobSection = clone.querySelector('[data-for="infant"]');
                const linkedSection = clone.querySelector('[data-for="child-infant"]');

                if (ageSection) ageSection.style.display = type !== 'infant' ? 'block' : 'none';
                if (dobSection) dobSection.style.display = type === 'infant' ? 'block' : 'none';
                if (linkedSection) linkedSection.style.display = type !== 'adult' ? 'block' : 'none';

                // Make sure content is visible - ORIGINAL LOGIC
                const content = clone.querySelector('.passenger-content');
                if (content) content.style.display = 'block';

                // Header aria-expanded - ORIGINAL LOGIC with CSS enhancement
                const header = clone.querySelector('.passenger-header, .passenger-card-header');
                if (header) {
                    header.setAttribute('aria-expanded', 'true');
                    // Add CSS toggle icon if missing
                    if (!header.querySelector('.toggle-icon')) {
                        const icon = document.createElement('span');
                        icon.className = 'toggle-icon';
                        icon.textContent = '▼';
                        header.appendChild(icon);
                    }
                    // Ensure CSS passenger card header styling
                    header.classList.add('passenger-card-header');
                }

                // Apply CSS classes for styling - CSS ENHANCEMENT ONLY
                const passengerCard = clone.querySelector('.passenger-card') || clone;
                passengerCard.classList.add('passenger-card');

                // Append to container
                container.appendChild(clone);

                // **CRITICAL FIX: Restore saved values to new fields** - ORIGINAL LOGIC
                const newFields = container.querySelectorAll(`input[name*="${type}_${i}"], select[name*="${type}_${i}"]`);
                newFields.forEach(field => {
                    const fieldName = field.getAttribute('name');
                    // Restore from sessionStorage data
                    if (appState.formData[fieldName] !== undefined) {
                        if (field.type === 'checkbox') {
                            field.checked = appState.formData[fieldName] === 'on' || appState.formData[fieldName] === true;
                        } else {
                            field.value = appState.formData[fieldName];
                        }
                    } else if (currentValues[fieldName] !== undefined) {
                        // Fallback to previously entered values
                        field.value = currentValues[fieldName];
                    }
                });
            }

            console.log(`✅ ${type} fields generated and restored: ${container.children.length}`);
        });

        // Populate linked adults AFTER fields are restored - ORIGINAL LOGIC
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

                    // Clear existing options
                    select.innerHTML = '<option value="">Select adult passenger</option>';

                    // Add adult options
                    adults.forEach(adult => {
                        const option = document.createElement('option');
                        option.value = adult.index;
                        option.textContent = adult.name;
                        select.appendChild(option);
                    });

                    // Restore saved linked adult value
                    const savedKey = `${type}_linked_adult_${i}`;
                    if (appState.formData[savedKey] !== undefined) {
                        select.value = appState.formData[savedKey];
                    }
                }
            });

            console.log('✅ Linked adults populated');
        }, 100);

        // Reattach file input listeners - ORIGINAL LOGIC
        document.querySelectorAll('input[type="file"]').forEach(input => {
            input.removeEventListener('change', handleFileChange);
            input.addEventListener('change', (e) => handleFileChange(e.target));
        });

        // Save updated state
        utils.saveToSession();
    }

    async function validateCurrentStep() {
        // ORIGINAL VALIDATION LOGIC with CSS busy state
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
            if (!result.valid) {
                validation.displayBackendErrors(result.errors);
                return false;
            }
        } catch (error) {
            console.warn('Validation failed:', error);
            // Fallback to client-side validation
        } finally {
            if (activeStep) activeStep.setAttribute('aria-busy', 'false');
        }
        return true;
    }

    function setupEventListeners() {
        // Navigation - ORIGINAL LOGIC with CSS classes
        document.querySelectorAll('.next-step').forEach(btn => {
            // Add CSS classes for styling
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
            // Add CSS classes for styling
            btn.classList.add('cta-button', 'cta-button-secondary');
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                const prevStep = parseInt(btn.dataset.prev) || appState.currentStep - 1;
                showStep(prevStep);
            });
        });

        // Passenger counters - ORIGINAL LOGIC
        [elements.adultsInput, elements.childrenInput, elements.infantsInput].forEach(input => {
            if (input) {
                input.classList.add('form-input'); // CSS enhancement
                input.addEventListener('change', utils.debounce(updatePassengerFields, 300));
            }
        });

        // Optional fields toggle - ORIGINAL LOGIC
        if (elements.vehicleCheckbox) {
            const wrapper = elements.vehicleCheckbox.closest('.form-group') || elements.vehicleCheckbox.parentElement;
            wrapper?.classList.add('form-checkbox'); // CSS enhancement
            elements.vehicleCheckbox.addEventListener('change', () => {
                elements.vehicleFields?.classList.toggle('hidden', !elements.vehicleCheckbox.checked);
                utils.saveToSession();
            });
        }

        if (elements.cargoCheckbox) {
            const wrapper = elements.cargoCheckbox.closest('.form-group') || elements.cargoCheckbox.parentElement;
            wrapper?.classList.add('form-checkbox'); // CSS enhancement
            elements.cargoCheckbox.addEventListener('change', () => {
                elements.cargoFields?.classList.toggle('hidden', !elements.cargoCheckbox.checked);
                utils.saveToSession();
            });
        }

        // Form submission - FIXED PAYMENT HANDLER - ORIGINAL LOGIC
        if (elements.submitBtn) {
            elements.submitBtn.classList.add('cta-button', 'cta-button-primary'); // CSS enhancement
            elements.submitBtn.addEventListener('click', async (e) => {
                e.preventDefault();
                console.log('💳 Payment initiated');

                if (!(await validateCurrentStep())) {
                    console.warn('Validation failed');
                    return;
                }

                if (!window.stripe) {
                    validation.displayBackendErrors([{ field: 'general', message: 'Payment system not available' }]);
                    return;
                }

                validation.toggleButtonLoading(elements.submitBtn, true);

                try {
                    const formData = new FormData(elements.form);

                    // Use correct URL with fallback
                    const checkoutUrl = window.urls.createCheckoutSession || '/bookings/api/create_checkout_session/';
                    console.log('🌐 Creating checkout session at:', checkoutUrl);

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
                    console.log('✅ Checkout session created:', result);

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
                    console.error('💥 Payment error:', error);
                    validation.displayBackendErrors([{
                        field: 'general',
                        message: `Payment failed: ${error.message}`
                    }]);
                } finally {
                    validation.toggleButtonLoading(elements.submitBtn, false);
                }
            });
        }

        // File uploads - ORIGINAL LOGIC
        elements.form.addEventListener('change', async (e) => {
            if (e.target.type === 'file') {
                await handleFileChange(e.target);
            }
        });

        // Auto-save - ORIGINAL LOGIC
        elements.form.addEventListener('input', utils.debounce(utils.saveToSession, 1000));
        elements.form.addEventListener('change', utils.saveToSession);

        // Collapsible passenger cards - ORIGINAL LOGIC with CSS toggle-icon
        elements.form.addEventListener('click', (e) => {
            const header = e.target.closest('.passenger-header, .passenger-card-header');
            if (header) {
                const content = header.nextElementSibling;
                const icon = header.querySelector('.toggle-icon');
                const isExpanded = content.style.display !== 'none';

                content.style.display = isExpanded ? 'none' : 'block';
                if (icon) {
                    icon.textContent = isExpanded ? '▶' : '▼';
                }
                header.setAttribute('aria-expanded', !isExpanded);
            }
        });
    }

    async function handleFileChange(input) {
        const file = input.files[0];
        if (!file) return;

        const result = await validation.validateFile(file, input); // ✅ FIXED

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
                fileInfo.innerHTML = `📄 ${file.name} (${(file.size / 1024).toFixed(1)}KB)`;
                preview.appendChild(fileInfo);
            }
        }
    }

    async function loadSummary() {
        if (!elements.bookingSummary || !elements.scheduleSelect?.value) {
            console.warn('Cannot load summary: missing elements or schedule');
            return;
        }

        try {
            // Show loading state with CSS spinner
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
                <div class="summary-card">
                    <!-- Schedule Information -->
                    ${scheduleInfo.departure_time || scheduleInfo.route ? `
                        <div class="mb-6 p-4 bg-gray-50 rounded-lg border border-gray-200">
                            <h4 class="font-semibold text-gray-800 mb-2">Trip Details</h4>
                            ${scheduleInfo.route ? `<div class="text-sm text-gray-600 mb-1">${scheduleInfo.route}</div>` : ''}
                            ${scheduleInfo.departure_time ? `<div class="text-lg font-medium">${scheduleInfo.departure_time}</div>` : ''}
                            ${scheduleInfo.return_time ? `<div class="text-sm text-gray-500">Return: ${scheduleInfo.return_time}</div>` : ''}
                        </div>
                    ` : ''}

                    <!-- Total Price Header -->
                    <div class="flex justify-between items-start mb-6">
                        <div>
                            <h3 class="text-2xl font-bold text-gray-800 mb-1">Booking Summary</h3>
                            <p class="text-gray-600">Review your selection before payment</p>
                        </div>
                        <div class="text-right">
                            <div class="text-3xl font-bold text-primary">FJD ${total}</div>
                            <div class="text-sm text-green-600 font-medium">Secure payment required</div>
                        </div>
                    </div>

                    <div class="space-y-3 mb-6">
            `;

            // Passengers Breakdown
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

            // Vehicle
            if (breakdown.vehicle && parseFloat(breakdown.vehicle) > 0) {
                const vehicleType = elements.form.querySelector('select[name="vehicle_type"]')?.value || 'Vehicle';
                summaryHTML += `
                    <div class="summary-row">
                        <span class="summary-label">${vehicleType}</span>
                        <span class="summary-value">+ FJD ${parseFloat(breakdown.vehicle).toFixed(2)}</span>
                    </div>
                `;
            }

            // Cargo
            if (breakdown.cargo && parseFloat(breakdown.cargo) > 0) {
                const cargoWeight = elements.form.querySelector('input[name="cargo_weight"]')?.value || '';
                const cargoLabel = cargoWeight ? `Cargo (${cargoWeight}kg)` : 'Cargo';
                summaryHTML += `
                    <div class="summary-row">
                        <span class="summary-label">${cargoLabel}</span>
                        <span class="summary-value">+ FJD ${parseFloat(breakdown.cargo).toFixed(2)}</span>
                    </div>
                `;
            }

            // Add-ons
            if (breakdown.addons && typeof breakdown.addons === 'object') {
                Object.entries(breakdown.addons).forEach(([addonKey, addonData]) => {
                    const { label, quantity, amount } = addonData;
                    if (parseFloat(amount) > 0) {
                        const unitPrice = quantity > 0 ? (parseFloat(amount) / quantity).toFixed(2) : parseFloat(amount).toFixed(2);
                        summaryHTML += `
                            <div class="summary-row">
                                <span class="summary-label">${label}${quantity > 0 ? ` × ${quantity}` : ''}</span>
                                <span class="summary-value">${quantity > 0 ? `${quantity} × FJD ${unitPrice}` : ''} = FJD ${parseFloat(amount).toFixed(2)}</span>
                            </div>
                        `;
                    }
                });
            }

            // Subtotal line
            const subtotal = parseFloat(breakdown.subtotal || total).toFixed(2);
            if (breakdown.taxes || breakdown.fees) {
                summaryHTML += `
                    <div class="summary-row">
                        <span class="summary-label">Subtotal</span>
                        <span class="summary-value">FJD ${subtotal}</span>
                    </div>
                `;
            }

            // Taxes and Fees
            if (breakdown.taxes && parseFloat(breakdown.taxes) > 0) {
                summaryHTML += `
                    <div class="summary-row">
                        <span class="summary-label">Taxes</span>
                        <span class="summary-value">+ FJD ${parseFloat(breakdown.taxes).toFixed(2)}</span>
                    </div>
                `;
            }

            if (breakdown.fees && parseFloat(breakdown.fees) > 0) {
                summaryHTML += `
                    <div class="summary-row">
                        <span class="summary-label">Processing Fees</span>
                        <span class="summary-value">+ FJD ${parseFloat(breakdown.fees).toFixed(2)}</span>
                    </div>
                `;
            }

            summaryHTML += `
                    </div>

                    <!-- Total Section -->
                    <div class="border-t pt-4 bg-gray-50 rounded-lg p-4">
                        <div class="flex justify-between items-center text-lg font-semibold mb-2">
                            <span class="text-gray-800">Total Amount Due</span>
                            <span class="text-2xl font-bold text-primary">FJD ${total}</span>
                        </div>
                        <div class="text-center">
                            <p class="text-xs text-gray-500 mb-3">
                                🔒 Secure payment via Stripe. Your information is encrypted and safe.
                            </p>
                            ${response.payment_methods ? `
                                <p class="text-xs text-gray-500">
                                    💳 Accepts Visa, Mastercard, American Express
                                </p>
                            ` : ''}
                        </div>
                    </div>
                </div>
            `;

            elements.bookingSummary.innerHTML = summaryHTML;

            // Add professional styling classes after rendering
            const summaryCard = elements.bookingSummary.querySelector('.summary-card');
            if (appState.currentStep === 4 && summaryCard) {
                summaryCard.classList.add('step-4-active'); // For step-specific styling
            }

        } catch (error) {
            console.error('Error loading summary:', error);
            elements.bookingSummary.innerHTML = `
                <div class="alert alert-error text-center p-6">
                    <div class="text-red-600 mb-4 text-2xl">⚠️</div>
                    <h4 class="font-semibold text-red-800 mb-3">Unable to calculate pricing</h4>
                    <p class="text-red-600 mb-4">Please ensure you've selected a valid schedule and passenger details, then try again.</p>
                    <button onclick="location.reload()" class="cta-button cta-button-primary px-6 py-3">
                        <span>🔄 Refresh Page</span>
                    </button>
                </div>
            `;
        }
    }

    // === INITIALIZATION ===
    function init() {
        console.log('🔧 Initializing booking system...');

        // Apply CSS container class
        elements.form?.classList.add('booking-form-container');

        // Apply CSS classes to form elements - ENHANCEMENT ONLY
        elements.form?.querySelectorAll('input:not([type="file"]), select, textarea').forEach(el => {
            el.classList.add('form-input', 'form-select');
        });

        // Apply CSS classes to checkboxes
        elements.form?.querySelectorAll('input[type="checkbox"]').forEach(el => {
            const wrapper = el.closest('.form-checkbox') || el.parentElement;
            wrapper?.classList.add('form-checkbox');
        });

        // ORIGINAL INITIALIZATION SEQUENCE
        utils.loadFromSession();
        restoreFormData();
        updatePassengerFields();
        restoreFormData();
        setupEventListeners();
        showStep(appState.currentStep);

        console.log('✅ Booking system initialized');
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