/**
 * validation.js - Comprehensive validation utilities for Fiji Ferry Booking
 * Provides global validation functions and error handling
 */

(function() {
    'use strict';

    // Comprehensive error messages
    const ERROR_MESSAGES = {
        // Step 1
        scheduleRequired: 'Please select a valid ferry schedule',
        scheduleUnavailable: 'Selected schedule is no longer available',
        emailRequired: 'Email address is required for guest bookings',
        emailInvalid: 'Please enter a valid email address',

        // Step 2
        noPassengers: 'At least one passenger is required',
        noAdults: 'At least one adult passenger is required',
        firstNameRequired: 'First name is required',
        lastNameRequired: 'Last name is required',
        ageRequired: 'Age is required',
        ageInvalid: 'Age must be between 2-120 years',
        dobRequired: 'Date of birth is required for infants',
        dobInvalid: 'Infant must be under 2 years old',
        idDocumentRequired: 'Valid ID document is required',
        linkedAdultRequired: 'Child/infant must be linked to an adult',

        // Step 3
        vehicleTypeRequired: 'Vehicle type is required',
        vehicleDimensionsInvalid: 'Dimensions must be in format LxWxH (e.g., 480x180x150)',
        cargoTypeRequired: 'Cargo type is required',
        cargoWeightInvalid: 'Cargo weight must be greater than 0kg',

        // Step 4
        privacyConsentRequired: 'You must agree to the Privacy Policy and Terms of Service',

        // File uploads
        fileMissing: 'Please select a file',
        fileTooLarge: 'File size exceeds 2.5MB limit',
        fileTypeInvalid: 'Only PDF, JPG, and PNG files are accepted',
        fileValidationFailed: 'File validation failed',

        // General
        serverError: 'Server error occurred',
        networkError: 'Network connection failed',
        validationFailed: 'Form validation failed'
    };

    // === VALIDATION FUNCTIONS ===
    function isValidEmail(email) {
        if (!email) return false;
        const trimmed = email.trim();
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        return emailRegex.test(trimmed);
    }

    function validateDimensions(dimensions) {
        if (!dimensions) return false;
        const trimmed = dimensions.trim();
        const dimensionRegex = /^\d+x\d+x\d+$/;
        if (!dimensionRegex.test(trimmed)) return false;

        const [length, width, height] = trimmed.split('x').map(Number);
        return length > 0 && width > 0 && height > 0;
    }

    function validateAge(type, age) {
        const ageNum = parseInt(age);
        if (isNaN(ageNum) || ageNum < 0) return false;

        switch (type) {
            case 'adult': return ageNum >= 18;
            case 'child': return ageNum >= 2 && ageNum <= 17;
            case 'infant': return true; // Validated via DOB
            default: return ageNum >= 0;
        }
    }

    function validateInfantDob(dobString) {
        if (!dobString) return false;
        const dob = new Date(dobString);
        if (isNaN(dob.getTime())) return false;

        const today = new Date();
        const ageInMonths = (today - dob) / (1000 * 60 * 60 * 24 * 30.44);
        return ageInMonths <= 24; // Under 2 years
    }

    async function validateFile(file, inputElement) {
        // Client-side validation
        if (!file) {
            showFieldError(inputElement, ERROR_MESSAGES.fileMissing);
            return { valid: false };
        }

        if (file.size > 2621440) { // 2.5MB
            showFieldError(inputElement, ERROR_MESSAGES.fileTooLarge);
            return { valid: false };
        }

        const validTypes = ['image/jpeg', 'image/jpg', 'image/png', 'application/pdf'];
        if (!validTypes.includes(file.type)) {
            showFieldError(inputElement, ERROR_MESSAGES.fileTypeInvalid);
            return { valid: false };
        }

        // Server-side validation (if endpoint exists)
        try {
            if (window.urls?.validateFile) {
                const formData = new FormData();
                formData.append('file', file);

                const response = await fetch(window.urls.validateFile, {
                    method: 'POST',
                    body: formData,
                    headers: {
                        'X-CSRFToken': getCsrfToken(),
                        'X-Requested-With': 'XMLHttpRequest'
                    }
                });

                const result = await response.json();
                if (!result.valid) {
                    showFieldError(inputElement, result.error || ERROR_MESSAGES.fileValidationFailed);
                    return { valid: false };
                }
            }
        } catch (error) {
            console.warn('File server validation failed:', error);
            // Continue with client validation on network error
        }

        // Success - show preview
        showFilePreview(file, inputElement);
        clearFieldError(inputElement);
        return { valid: true, file };
    }

    // === ERROR HANDLING ===
    function displayBackendErrors(errors, targetElement) {
        // Clear all existing errors
        document.querySelectorAll('.error-message.show, .alert-error').forEach(el => {
            el.classList.remove('show');
            el.textContent = '';
        });

        errors.forEach(error => {
            let errorContainer;

            // Field-specific error
            if (error.field && error.field !== 'general') {
                const fieldSelector = `[name="${error.field}"], #${error.field}`;
                const field = document.querySelector(fieldSelector);

                if (field) {
                    errorContainer = document.getElementById(`error-${error.field}`);
                    if (!errorContainer) {
                        errorContainer = document.createElement('p');
                        errorContainer.id = `error-${error.field}`;
                        errorContainer.className = 'error-message text-red-500 text-sm mt-1';
                        field.parentNode.insertBefore(errorContainer, field.nextSibling);
                    }

                    // Highlight field
                    field.classList.add('border-red-500', 'ring-1', 'ring-red-200');
                    setTimeout(() => field.classList.remove('border-red-500', 'ring-1', 'ring-red-200'), 5000);
                }
            }

            // Fallback general error
            if (!errorContainer) {
                errorContainer = document.createElement('div');
                errorContainer.className = 'alert alert-error p-4 mt-4 rounded bg-red-50 border border-red-200';
                if (targetElement) {
                    targetElement.parentNode.insertBefore(errorContainer, targetElement.nextSibling);
                } else {
                    const form = document.getElementById('booking-form');
                    if (form) {
                        form.appendChild(errorContainer);
                    } else {
                        console.error('Form not found for error display');
                    }
                }
            }

            errorContainer.textContent = error.message || 'An error occurred';
            errorContainer.classList.add('show');
            errorContainer.setAttribute('role', 'alert');
            errorContainer.setAttribute('aria-live', 'assertive');

            // Scroll to error
            errorContainer.scrollIntoView({
                behavior: 'smooth',
                block: 'center'
            });
        });

        // Screen reader announcement
        const announcement = document.createElement('div');
        announcement.setAttribute('aria-live', 'polite');
        announcement.style.position = 'fixed';
        announcement.style.left = '-9999px';
        announcement.textContent = `${errors.length} validation error${errors.length !== 1 ? 's' : ''}`;
        document.body.appendChild(announcement);
        setTimeout(() => announcement.remove(), 2000);
    }

    function showFieldError(field, message) {
        let errorEl = document.getElementById(`error-${field.id || field.name}`);

        if (!errorEl) {
            errorEl = document.createElement('p');
            errorEl.id = `error-${field.id || field.name}`;
            errorEl.className = 'error-message text-red-500 text-sm mt-1';
            field.parentNode.insertBefore(errorEl, field.nextSibling);
        }

        errorEl.textContent = message;
        errorEl.classList.add('show');

        // Highlight field
        field.classList.add('border-red-500', 'ring-1', 'ring-red-200');
        field.focus();

        setTimeout(() => {
            field.classList.remove('border-red-500', 'ring-1', 'ring-red-200');
            errorEl.classList.remove('show');
        }, 5000);
    }

    function clearFieldError(field) {
        const errorId = `error-${field.id || field.name}`;
        const errorEl = document.getElementById(errorId);
        if (errorEl) {
            errorEl.classList.remove('show');
            errorEl.textContent = '';
        }
        field.classList.remove('border-red-500', 'ring-1', 'ring-red-200');
    }

    function toggleButtonLoading(button, isLoading) {
        if (!button) return;

        const originalContent = button.dataset.originalContent || button.innerHTML;
        button.dataset.originalContent = originalContent;

        if (isLoading) {
            button.disabled = true;
            button.setAttribute('aria-busy', 'true');

            const spinnerHTML = `
                <svg class="animate-spin -ml-1 mr-2 h-4 w-4 inline" fill="none" viewBox="0 0 24 24">
                    <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                    <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
            `;

            button.innerHTML = spinnerHTML + (button.dataset.originalText || 'Processing...');
        } else {
            button.disabled = false;
            button.setAttribute('aria-busy', 'false');
            button.innerHTML = originalContent;
        }
    }

    function showFilePreview(file, input) {
        const previewId = `preview-${input.name}`;
        const preview = document.getElementById(previewId);

        if (!preview) return;

        preview.innerHTML = '';

        if (file.type.startsWith('image/')) {
            const img = document.createElement('img');
            img.src = URL.createObjectURL(file);
            img.className = 'max-w-48 h-32 object-cover rounded border mt-2';
            img.alt = 'File preview';
            preview.appendChild(img);

            // Cleanup memory
            img.onload = () => URL.revokeObjectURL(img.src);
        } else {
            const icon = document.createElement('div');
            icon.className = 'w-48 h-32 border-2 border-dashed border-gray-300 rounded flex items-center justify-center';
            icon.innerHTML = file.type === 'application/pdf' ?
                '📄 PDF' : '📎 Document';
            preview.appendChild(icon);
        }
    }

    // === CSRF HELPER ===
    function getCsrfToken() {
        return window.csrfToken ||
               document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
               '';
    }

    // === STEP VALIDATION ===
    function validateStep(currentStep, formData) {
        const errors = [];
        const passengerTypes = ['adult', 'child', 'infant'];
        const isAuthenticated = window.isAuthenticated === true || window.isAuthenticated === "true";

        switch (currentStep) {
            case 1:
                // Schedule check
                if (!formData.get('schedule_id')) {
                    errors.push({ field: 'schedule_id', message: ERROR_MESSAGES.scheduleRequired });
                }

                // Guest email validation only
                if (!isAuthenticated) {
                    const email = formData.get('guest_email')?.trim();

                    if (!email) {
                        errors.push({ field: 'guest_email', message: ERROR_MESSAGES.emailRequired });
                    } else if (!isValidEmail(email)) {
                        errors.push({ field: 'guest_email', message: ERROR_MESSAGES.emailInvalid });
                    }
                }
                break;

            case 2:
                const adults = parseInt(formData.get('adults') || 0);
                if (adults === 0) {
                    errors.push({ field: 'adults', message: ERROR_MESSAGES.noAdults });
                }

                // Validate each passenger
                passengerTypes.forEach(type => {
                    const count = parseInt(formData.get(`${type}s`) || 0);
                    for (let i = 0; i < count; i++) {
                        // First & last names
                        if (!formData.get(`${type}_first_name_${i}`)?.trim()) {
                            errors.push({ field: `${type}_first_name_${i}`, message: ERROR_MESSAGES.firstNameRequired });
                        }
                        if (!formData.get(`${type}_last_name_${i}`)?.trim()) {
                            errors.push({ field: `${type}_last_name_${i}`, message: ERROR_MESSAGES.lastNameRequired });
                        }

                        // Age check
                        if (type !== 'infant') {
                            const age = formData.get(`${type}_age_${i}`);
                            if (!age || !validateAge(type, age)) {
                                errors.push({ field: `${type}_age_${i}`, message: ERROR_MESSAGES.ageInvalid });
                            }
                        } else {
                            const dob = formData.get(`infant_dob_${i}`);
                            if (!dob || !validateInfantDob(dob)) {
                                errors.push({ field: `infant_dob_${i}`, message: ERROR_MESSAGES.dobInvalid });
                            }
                        }

                        // ID documents for non-infants
                        if (type !== 'infant' && !formData.get(`${type}_id_document_${i}`)) {
                            errors.push({ field: `${type}_id_document_${i}`, message: ERROR_MESSAGES.idDocumentRequired });
                        }

                        // Linked adult for child/infant
                        if (type !== 'adult' && !formData.get(`${type}_linked_adult_${i}`)) {
                            errors.push({ field: `${type}_linked_adult_${i}`, message: ERROR_MESSAGES.linkedAdultRequired });
                        }
                    }
                });
                break;

            case 3:
                // Vehicle
                if (formData.get('add_vehicle') === 'on') {
                    if (!formData.get('vehicle_type')) {
                        errors.push({ field: 'vehicle_type', message: ERROR_MESSAGES.vehicleTypeRequired });
                    }
                    const dims = formData.get('vehicle_dimensions');
                    if (dims && !validateDimensions(dims)) {
                        errors.push({ field: 'vehicle_dimensions', message: ERROR_MESSAGES.vehicleDimensionsInvalid });
                    }
                }

                // Cargo
                if (formData.get('add_cargo') === 'on') {
                    if (!formData.get('cargo_type')) {
                        errors.push({ field: 'cargo_type', message: ERROR_MESSAGES.cargoTypeRequired });
                    }
                    const weight = parseFloat(formData.get('cargo_weight_kg'));
                    if (isNaN(weight) || weight <= 0) {
                        errors.push({ field: 'cargo_weight_kg', message: ERROR_MESSAGES.cargoWeightInvalid });
                    }
                }

                // Add-ons
                if (window.bookingConfig?.addOns) {
                    window.bookingConfig.addOns.forEach(addon => {
                        const qty = parseInt(formData.get(`${addon.id}_quantity`) || 0);
                        if (qty < 0 || qty > (addon.max_quantity || 10)) {
                            errors.push({ field: `${addon.id}_quantity`, message: `Invalid quantity for ${addon.label}` });
                        }
                    });
                }
                break;

            case 4:
                if (!formData.get('privacy_consent')) {
                    errors.push({ field: 'privacy_consent', message: ERROR_MESSAGES.privacyConsentRequired });
                }
                break;
        }

        return {
            valid: errors.length === 0,
            errors
        };
    }

    // === PUBLIC API ===
    window.validationUtils = {
        ERROR_MESSAGES,
        isValidEmail,
        validateFile,
        validateStep,
        validateDimensions,
        validateAge,
        validateInfantDob,
        displayBackendErrors,
        showFieldError,
        clearFieldError,
        toggleButtonLoading,
        showFilePreview,
        getCsrfToken
    };

    window.ERROR_MESSAGES = ERROR_MESSAGES;

    console.log('✅ Validation utilities loaded successfully');
    console.log('Available validators:', Object.keys(window.validationUtils));
})();