/**
 * book.js - Handles the multi-step booking form for Fiji Ferry Booking
 * Dependencies: Stripe.js, AOS.js
 * Uses window.urls for API endpoints and window.isAuthenticated for user status
 */
let currentStep = 1;
let eventListenersAdded = false;
let scheduleCache = null;
let pricingCache = null;
let latestTotalPrice = '0.00';
// DOM elements
const bookingForm = document.getElementById('booking-form');
const scheduleInput = document.getElementById('schedule_id');
const guestEmailInput = document.getElementById('guest_email');
const adultsInput = document.getElementById('adults');
const childrenInput = document.getElementById('children');
const infantsInput = document.getElementById('infants');
const summarySection = document.getElementById('summary-section');
const summarySchedule = document.getElementById('summary-schedule');
const summaryDuration = document.getElementById('summary-duration');
const summaryPassengers = document.getElementById('summary-passengers');
const summaryPassengerBreakdown = document.getElementById('summary-passenger-breakdown');
const summaryAddOns = document.getElementById('summary-add-ons');
const summaryVehicle = document.getElementById('summary-vehicle');
const summaryCargo = document.getElementById('summary-cargo');
const summaryCost = document.getElementById('summary-cost');
const weatherWarning = document.getElementById('weather-warning');
const addVehicleCheckbox = document.getElementById('add_vehicle');
const vehicleFields = document.getElementById('vehicle-fields');
const addCargoCheckbox = document.getElementById('add_cargo');
const cargoFields = document.getElementById('cargo-fields');
const privacyConsent = document.getElementById('privacy-consent');
const proceedToPayment = document.getElementById('proceed-to-payment');
const nextButtons = document.querySelectorAll('.next-step');
const prevButtons = document.querySelectorAll('.prev-step');
const steps = document.querySelectorAll('.step');
const progressBarFill = document.querySelector('.progress-bar-fill');
const resetScheduleButton = document.getElementById('reset-schedule');
const scheduleErrorReset = document.getElementById('schedule-error-reset');
// Logger for debugging
const logger = {
    log: (...args) => console.log('[Booking]', ...args),
    warn: (...args) => console.warn('[Booking]', ...args),
    error: (...args) => console.error('[Booking]', ...args)
};
// Debounce utility
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}
// Get CSRF token
function getCsrfToken() {
    const tokenElement = document.querySelector('input[name=csrfmiddlewaretoken]');
    const token = tokenElement ? tokenElement.value : '';
    if (!token) logger.warn('CSRF token not found');
    return token;
}
// Toggle button loading state
function toggleButtonLoading(button, isLoading) {
    if (!button) return;
    const spinner = button.querySelector('.spinner');
    if (spinner) {
        spinner.classList.toggle('hidden', !isLoading);
    }
    button.setAttribute('aria-busy', isLoading);
}
// Update progress bar
function updateProgressBar(step) {
    if (!progressBarFill || !steps.length) {
        logger.warn('Progress bar or steps not found');
        return;
    }
    const percentage = ((step - 1) / 3) * 100;
    progressBarFill.style.width = `${percentage}%`;
    steps.forEach(s => {
        const stepNum = parseInt(s.dataset.step);
        const stepNumber = s.querySelector('.step-number');
        if (!stepNumber) return;
        s.classList.remove('active', 'completed');
        stepNumber.classList.remove('bg-var-step-1-accent', 'text-white', 'bg-gray-300', 'text-gray-600');
        if (stepNum < step) {
            s.classList.add('completed');
            stepNumber.classList.add('bg-var-step-1-accent', 'text-white');
        } else if (stepNum === step) {
            s.classList.add('active');
            stepNumber.classList.add('bg-var-step-1-accent', 'text-white');
        } else {
            stepNumber.classList.add('bg-gray-300', 'text-gray-600');
        }
    });
}
// Update form steps
function updateStep(step) {
    currentStep = step;
    const formSteps = document.querySelectorAll('.form-step');
    formSteps.forEach(s => {
        const isActive = parseInt(s.dataset.step) === step;
        s.classList.toggle('active', isActive);
        s.style.opacity = isActive ? '1' : '0';
        s.style.transform = isActive ? 'translateY(0)' : 'translateY(20px)';
        if (!isActive) {
            setTimeout(() => {
                s.classList.remove('active');
            }, 300);
        }
    });
    updateProgressBar(step);
    saveFormData();
    if (step === 4) {
        debouncedUpdateSummary();
    }
}
// Save form data
function saveFormData() {
    if (!bookingForm) return;
    const data = {
        step: currentStep,
        schedule_id: scheduleInput?.value?.trim() || '',
        guest_email: window.isAuthenticated ? '' : (guestEmailInput?.value?.trim() || ''),
        adults: adultsInput?.value || '0',
        children: childrenInput?.value || '0',
        infants: infantsInput?.value || '0',
        add_vehicle: addVehicleCheckbox?.checked || false,
        add_cargo: addCargoCheckbox?.checked || false,
        add_ons: [
            { add_on_type: 'premium_seating', quantity: document.getElementById('premium_seating_quantity')?.value || '0' },
            { add_on_type: 'priority_boarding', quantity: document.getElementById('priority_boarding_quantity')?.value || '0' },
            { add_on_type: 'cabin', quantity: document.getElementById('cabin_quantity')?.value || '0' },
            { add_on_type: 'meal_breakfast', quantity: document.getElementById('meal_breakfast_quantity')?.value || '0' },
            { add_on_type: 'meal_lunch', quantity: document.getElementById('meal_lunch_quantity')?.value || '0' },
            { add_on_type: 'meal_dinner', quantity: document.getElementById('meal_dinner_quantity')?.value || '0' },
            { add_on_type: 'meal_snack', quantity: document.getElementById('meal_snack_quantity')?.value || '0' }
        ],
        passengers: []
    };
    ['adult', 'child', 'infant'].forEach(type => {
        const count = parseInt(document.getElementById(`${type}s`)?.value || 0);
        for (let i = 0; i < count; i++) {
            const passenger = {
                type,
                first_name: document.querySelector(`[name="${type}_first_name_${i}"]`)?.value || '',
                last_name: document.querySelector(`[name="${type}_last_name_${i}"]`)?.value || '',
                age: type !== 'infant' ? (document.querySelector(`[name="${type}_age_${i}"]`)?.value || '') : '',
                dob: type === 'infant' ? (document.querySelector(`[name="${type}_dob_${i}"]`)?.value || '') : '',
                phone: type === 'adult' ? (document.querySelector(`[name="${type}_phone_${i}"]`)?.value || '') : '',
                linked_adult_index: type !== 'adult' ? (document.querySelector(`[name="${type}_linked_adult_${i}"]`)?.value || '') : ''
            };
            data.passengers.push(passenger);
        }
    });
    if (data.add_vehicle) {
        data.vehicle = {
            vehicle_type: document.getElementById('vehicle_type')?.value || '',
            dimensions: document.getElementById('vehicle_dimensions')?.value || '',
            license_plate: document.getElementById('vehicle_license_plate')?.value || ''
        };
    }
    if (data.add_cargo) {
        data.cargo = {
            cargo_type: document.getElementById('cargo_type')?.value || '',
            weight_kg: document.getElementById('cargo_weight_kg')?.value || '',
            dimensions_cm: document.getElementById('cargo_dimensions_cm')?.value || '',
            license_plate: document.getElementById('cargo_license_plate')?.value || ''
        };
    }
    try {
        sessionStorage.setItem('bookingFormData', JSON.stringify(data));
        logger.log('Form data saved to sessionStorage:', data);
    } catch (e) {
        logger.warn('sessionStorage unavailable:', e);
    }
}
// Clear form data
function clearFormData() {
    try {
        sessionStorage.removeItem('bookingFormData');
        logger.log('Form data cleared from sessionStorage');
    } catch (e) {
        logger.warn('sessionStorage unavailable:', e);
    }
    if (bookingForm) {
        bookingForm.reset();
        document.querySelectorAll('.error-message').forEach(el => {
            el.textContent = '';
            el.classList.add('hidden');
        });
        document.querySelectorAll('.file-preview').forEach(el => el.innerHTML = '');
        if (vehicleFields) vehicleFields.classList.add('hidden');
        if (cargoFields) cargoFields.classList.add('hidden');
        if (scheduleErrorReset) scheduleErrorReset.style.display = 'none';
        document.getElementById('adult-fields').innerHTML = '';
        document.getElementById('child-fields').innerHTML = '';
        document.getElementById('infant-fields').innerHTML = '';
        if (adultsInput) adultsInput.value = '1';
        if (childrenInput) childrenInput.value = '0';
        if (infantsInput) infantsInput.value = '0';
        updatePassengerFields();
        toggleVehicleFields();
        toggleCargoFields();
    }
}
// Load form data
async function loadFormData() {
    try {
        const savedData = JSON.parse(sessionStorage.getItem('bookingFormData')) || {};
        if (savedData.step) {
            currentStep = parseInt(savedData.step);
        }
        if (savedData.schedule_id && scheduleInput) {
            scheduleInput.value = savedData.schedule_id;
            const option = scheduleInput.querySelector(`option[value="${savedData.schedule_id}"]`);
            if (option) {
                option.selected = true;
                try {
                    const response = await fetch(window.urls.getScheduleUpdates, {
                        headers: { 'X-Requested-With': 'XMLHttpRequest' }
                    });
                    if (!response.ok) throw new Error('Schedule fetch failed');
                    scheduleCache = await response.json();
                    const schedule = scheduleCache.schedules.find(s => String(s.id) === String(savedData.schedule_id));
                    if (!schedule || schedule.status !== 'scheduled' || new Date(schedule.departure_time) <= new Date()) {
                        logger.warn(`Schedule ID ${savedData.schedule_id} not available`);
                        savedData.schedule_id = '';
                        scheduleInput.value = '';
                        currentStep = 1;
                        displayBackendErrors(
                            [{ field: 'schedule_id', message: 'Selected schedule is no longer available. Please choose a new schedule.' }],
                            document.querySelector('.next-step[data-next="2"]')
                        );
                    }
                } catch (e) {
                    logger.error('Error verifying schedule_id:', e);
                    savedData.schedule_id = '';
                    scheduleInput.value = '';
                    currentStep = 1;
                    displayBackendErrors(
                        [{ field: 'schedule_id', message: 'Unable to verify schedule availability. Please choose a new schedule.' }],
                        document.querySelector('.next-step[data-next="2"]')
                    );
                }
            } else {
                logger.warn(`Schedule ID ${savedData.schedule_id} not found in options`);
                savedData.schedule_id = '';
                scheduleInput.value = '';
                currentStep = 1;
                displayBackendErrors(
                    [{ field: 'schedule_id', message: 'Selected schedule is no longer available. Please choose a new schedule.' }],
                    document.querySelector('.next-step[data-next="2"]')
                );
            }
        }
        if (currentStep > 1 && (!savedData.schedule_id || isNaN(parseInt(savedData.schedule_id)))) {
            currentStep = 1;
            displayBackendErrors(
                [{ field: 'schedule_id', message: 'Please select a valid schedule to continue.' }],
                document.querySelector('.next-step[data-next="2"]')
            );
        }
        if (guestEmailInput && savedData.guest_email) guestEmailInput.value = savedData.guest_email;
        if (adultsInput) adultsInput.value = savedData.adults || '1';
        if (childrenInput) childrenInput.value = savedData.children || '0';
        if (infantsInput) infantsInput.value = savedData.infants || '0';
        if (addVehicleCheckbox) addVehicleCheckbox.checked = savedData.add_vehicle || false;
        if (addCargoCheckbox) addCargoCheckbox.checked = savedData.add_cargo || false;
        savedData.add_ons?.forEach(addOn => {
            const input = document.getElementById(`${addOn.add_on_type}_quantity`);
            if (input && addOn.quantity) input.value = addOn.quantity;
        });
        if (savedData.passengers) {
            savedData.passengers.forEach((passenger, index) => {
                const count = parseInt(document.getElementById(`${passenger.type}s`)?.value || 0);
                if (passenger.type === 'adult' && index < count) {
                    const firstName = document.querySelector(`[name="adult_first_name_${index}"]`);
                    const lastName = document.querySelector(`[name="adult_last_name_${index}"]`);
                    const age = document.querySelector(`[name="adult_age_${index}"]`);
                    const phone = document.querySelector(`[name="adult_phone_${index}"]`);
                    if (firstName) firstName.value = passenger.first_name;
                    if (lastName) lastName.value = passenger.last_name;
                    if (age) age.value = passenger.age;
                    if (phone) phone.value = passenger.phone;
                } else if (passenger.type === 'child' && index < count) {
                    const firstName = document.querySelector(`[name="child_first_name_${index}"]`);
                    const lastName = document.querySelector(`[name="child_last_name_${index}"]`);
                    const age = document.querySelector(`[name="child_age_${index}"]`);
                    const linkedAdult = document.querySelector(`[name="child_linked_adult_${index}"]`);
                    if (firstName) firstName.value = passenger.first_name;
                    if (lastName) lastName.value = passenger.last_name;
                    if (age) age.value = passenger.age;
                    if (linkedAdult) linkedAdult.value = passenger.linked_adult_index;
                } else if (passenger.type === 'infant' && index < count) {
                    const firstName = document.querySelector(`[name="infant_first_name_${index}"]`);
                    const lastName = document.querySelector(`[name="infant_last_name_${index}"]`);
                    const dob = document.querySelector(`[name="infant_dob_${index}"]`);
                    const linkedAdult = document.querySelector(`[name="infant_linked_adult_${index}"]`);
                    if (firstName) firstName.value = passenger.first_name;
                    if (lastName) lastName.value = passenger.last_name;
                    if (dob) dob.value = passenger.dob;
                    if (linkedAdult) linkedAdult.value = passenger.linked_adult_index;
                }
            });
        }
        if (savedData.vehicle && addVehicleCheckbox?.checked) {
            const vehicleType = document.getElementById('vehicle_type');
            const vehicleDimensions = document.getElementById('vehicle_dimensions');
            const vehicleLicensePlate = document.getElementById('vehicle_license_plate');
            if (vehicleType) vehicleType.value = savedData.vehicle.vehicle_type;
            if (vehicleDimensions) vehicleDimensions.value = savedData.vehicle.dimensions;
            if (vehicleLicensePlate) vehicleLicensePlate.value = savedData.vehicle.license_plate;
        }
        if (savedData.cargo && addCargoCheckbox?.checked) {
            const cargoType = document.getElementById('cargo_type');
            const cargoWeightKg = document.getElementById('cargo_weight_kg');
            const cargoDimensionsCm = document.getElementById('cargo_dimensions_cm');
            const cargoLicensePlate = document.getElementById('cargo_license_plate');
            if (cargoType) cargoType.value = savedData.cargo.cargo_type;
            if (cargoWeightKg) cargoWeightKg.value = savedData.cargo.weight_kg;
            if (cargoDimensionsCm) cargoDimensionsCm.value = savedData.cargo.dimensions_cm;
            if (cargoLicensePlate) cargoLicensePlate.value = savedData.cargo.license_plate;
        }
        updateStep(currentStep);
        updatePassengerFields();
        toggleVehicleFields();
        toggleCargoFields();
        debouncedUpdateSummary();
    } catch (e) {
        logger.warn('sessionStorage unavailable or corrupted:', e);
        updateStep(1);
    }
}
// Display backend errors
function displayBackendErrors(errors, button) {
    if (!button) return;
    logger.log('Displaying backend errors:', errors);
    const errorContainerId = button.id === 'proceed-to-payment' ? 'validation-errors-payment' : 'validation-errors-next';
    document.querySelectorAll(`#${errorContainerId}`).forEach(e => e.remove());
    const errorContainer = document.createElement('div');
    errorContainer.id = errorContainerId;
    errorContainer.className = 'alert error bg-var-alert-error-bg p-4 rounded-lg shadow-sm mt-4';
    const ul = document.createElement('ul');
    ul.className = 'list-disc pl-5 text-xs md:text-sm text-var-alert-error-text font-poppins';
    let generalErrorElement = document.getElementById('error-general');
    if (!generalErrorElement) {
        generalErrorElement = document.createElement('p');
        generalErrorElement.id = 'error-general';
        generalErrorElement.className = 'error-message hidden mt-1 text-xs md:text-sm text-var-alert-error-text font-poppins';
        generalErrorElement.setAttribute('aria-live', 'polite');
        button.parentElement.appendChild(generalErrorElement);
    }
    errors.forEach(error => {
        const li = document.createElement('li');
        li.textContent = error.message;
        ul.appendChild(li);
        if (error.field === 'general') {
            generalErrorElement.textContent = error.message;
            generalErrorElement.classList.remove('hidden');
        } else {
            const errorElement = document.getElementById(`error-${error.field}`);
            if (errorElement) {
                errorElement.textContent = error.message;
                errorElement.classList.remove('hidden');
            } else {
                logger.warn(`Error element not found for field: ${error.field}`);
                const passengerError = document.getElementById('passenger-details-error');
                if (passengerError && (error.field.includes('id_document') || error.field.includes('first_name') || error.field.includes('last_name') || error.field.includes('age') || error.field.includes('linked_adult') || error.field.includes('dob'))) {
                    passengerError.textContent = error.message;
                    passengerError.classList.remove('hidden');
                } else {
                    generalErrorElement.textContent = error.message;
                    generalErrorElement.classList.remove('hidden');
                }
            }
        }
        if (error.field === 'schedule_id' && error.message.includes('no longer available')) {
            if (scheduleErrorReset) scheduleErrorReset.style.display = 'block';
        }
    });
    errorContainer.appendChild(ul);
    button.insertAdjacentElement('afterend', errorContainer);
}
// Update passenger fields
function updatePassengerFields() {
    const adults = parseInt(adultsInput?.value || 0);
    const children = parseInt(childrenInput?.value || 0);
    const infants = parseInt(infantsInput?.value || 0);
    const adultFields = document.getElementById('adult-fields');
    const childFields = document.getElementById('child-fields');
    const infantFields = document.getElementById('infant-fields');
    if (!adultFields || !childFields || !infantFields) {
        logger.warn('Passenger fields containers not found');
        return;
    }
    function createPassengerField(type, index) {
        const isPassengerForm = true; // All forms (adult, child, infant) are open by default
        const isAdultOrChild = type === 'adult' || type === 'child';
        const isInfant = type === 'infant';
        const div = document.createElement('div');
        div.className = 'passenger-card';
        div.setAttribute('role', 'group');
        div.setAttribute('aria-labelledby', `${type}-header-${index}`);
        const adultsCount = parseInt(adultsInput?.value || 0);
        let linkedAdultOptions = '';
        if (type !== 'adult' && adultsCount > 0) {
            linkedAdultOptions = `
                <div class="form-group mt-2">
                    <label class="block text-sm font-semibold text-var-text-color font-poppins" for="${type}_linked_adult_${index}">Linked Adult *</label>
                    <select id="${type}_linked_adult_${index}" name="${type}_linked_adult_${index}" class="w-full p-2 border rounded bg-var-input-bg text-var-text-color focus:outline-none focus:ring-2 focus:ring-var-step-2-accent transition-all duration-300" required aria-required="true" aria-describedby="error-${type}_linked_adult_${index}">
                        <option value="" disabled selected>Select an adult</option>`;
            for (let i = 0; i < adultsCount; i++) {
                const adultName = document.querySelector(`[name="adult_first_name_${i}"]`)?.value || `Adult ${i + 1}`;
                linkedAdultOptions += `<option value="${i}">${adultName}</option>`;
            }
            linkedAdultOptions += `
                    </select>
                    <p id="error-${type}_linked_adult_${index}" class="error-message hidden mt-1 text-xs md:text-sm text-var-alert-error-text font-poppins" aria-live="polite"></p>
                </div>`;
        }
        div.innerHTML = `
            <button type="button" id="${type}-header-${index}" class="passenger-card-header font-semibold text-var-text-color font-poppins" aria-expanded="${isPassengerForm}" aria-controls="${type}-details-${index}">
                ${type.charAt(0).toUpperCase() + type.slice(1)} ${index + 1}
                <span class="toggle-icon">${isPassengerForm ? '−' : '+'}</span>
            </button>
            <div id="${type}-details-${index}" class="passenger-details mt-2" style="display: ${isPassengerForm ? 'block' : 'none'};">
                <div class="form-group">
                    <label class="block text-sm font-semibold text-var-text-color font-poppins" for="${type}_first_name_${index}">First Name *</label>
                    <input type="text" id="${type}_first_name_${index}" name="${type}_first_name_${index}" class="w-full p-2 border rounded bg-var-input-bg text-var-text-color focus:outline-none focus:ring-2 focus:ring-var-step-2-accent transition-all duration-300" required aria-required="true" aria-describedby="error-${type}_first_name_${index}">
                    <p id="error-${type}_first_name_${index}" class="error-message hidden mt-1 text-xs md:text-sm text-var-alert-error-text font-poppins" aria-live="polite"></p>
                </div>
                <div class="form-group mt-2">
                    <label class="block text-sm font-semibold text-var-text-color font-poppins" for="${type}_last_name_${index}">Last Name *</label>
                    <input type="text" id="${type}_last_name_${index}" name="${type}_last_name_${index}" class="w-full p-2 border rounded bg-var-input-bg text-var-text-color focus:outline-none focus:ring-2 focus:ring-var-step-2-accent transition-all duration-300" required aria-required="true" aria-describedby="error-${type}_last_name_${index}">
                    <p id="error-${type}_last_name_${index}" class="error-message hidden mt-1 text-xs md:text-sm text-var-alert-error-text font-poppins" aria-live="polite"></p>
                </div>
                ${isAdultOrChild ? `
                <div class="form-group mt-2">
                    <label class="block text-sm font-semibold text-var-text-color font-poppins" for="${type}_age_${index}">Age *</label>
                    <input type="number" id="${type}_age_${index}" name="${type}_age_${index}" min="${type === 'adult' ? '18' : '2'}" max="${type === 'adult' ? '120' : '17'}" class="w-full p-2 border rounded bg-var-input-bg text-var-text-color focus:outline-none focus:ring-2 focus:ring-var-step-2-accent transition-all duration-300" required aria-required="true" aria-describedby="error-${type}_age_${index}">
                    <p id="error-${type}_age_${index}" class="error-message hidden mt-1 text-xs md:text-sm text-var-alert-error-text font-poppins" aria-live="polite"></p>
                </div>
                <div class="form-group mt-2">
                    <label class="block text-sm font-semibold text-var-text-color font-poppins" for="${type}_id_document_${index}">ID Document (PDF, JPG, JPEG, PNG; max 2.5MB) *</label>
                    <input type="file" id="${type}_id_document_${index}" name="${type}_id_document_${index}" accept="image/jpeg,image/png,application/pdf" class="w-full p-2 border rounded bg-var-input-bg text-var-text-color focus:outline-none focus:ring-2 focus:ring-var-step-2-accent transition-all duration-300" required aria-required="true" aria-describedby="error-${type}_id_document_${index}">
                    <p id="error-${type}_id_document_${index}" class="error-message hidden mt-1 text-xs md:text-sm text-var-alert-error-text font-poppins" aria-live="polite"></p>
                    <div class="file-preview mt-2"></div>
                </div>
                ${type === 'child' ? linkedAdultOptions : ''}` : `
                <div class="form-group mt-2">
                    <label class="block text-sm font-semibold text-var-text-color font-poppins" for="${type}_dob_${index}">Date of Birth *</label>
                    <input type="date" id="${type}_dob_${index}" name="${type}_dob_${index}" class="w-full p-2 border rounded bg-var-input-bg text-var-text-color focus:outline-none focus:ring-2 focus:ring-var-step-2-accent transition-all duration-300" required aria-required="true" aria-describedby="error-${type}_dob_${index}">
                    <p id="error-${type}_dob_${index}" class="error-message hidden mt-1 text-xs md:text-sm text-var-alert-error-text font-poppins" aria-live="polite"></p>
                </div>
                ${linkedAdultOptions}`}
                ${type === 'adult' ? `
                <div class="form-group mt-2">
                    <label class="block text-sm font-semibold text-var-text-color font-poppins" for="${type}_phone_${index}">Phone Number *</label>
                    <input type="tel" id="${type}_phone_${index}" name="${type}_phone_${index}" class="w-full p-2 border rounded bg-var-input-bg text-var-text-color focus:outline-none focus:ring-2 focus:ring-var-step-2-accent transition-all duration-300" required aria-required="true" aria-describedby="error-${type}_phone_${index}">
                    <p id="error-${type}_phone_${index}" class="error-message hidden mt-1 text-xs md:text-sm text-var-alert-error-text font-poppins" aria-live="polite"></p>
                </div>` : ''}
            </div>
        `;
        return div;
    }
    function updateFields(container, type, count) {
        const existing = container.querySelectorAll('.passenger-card').length;
        if (existing > count) {
            container.querySelectorAll(`.passenger-card:nth-child(n+${count + 1})`).forEach(el => el.remove());
        } else if (existing < count) {
            for (let i = existing; i < count; i++) {
                container.appendChild(createPassengerField(type, i));
            }
        }
    }
    updateFields(adultFields, 'adult', adults);
    updateFields(childFields, 'child', children);
    updateFields(infantFields, 'infant', infants);
    updateChildLinkedAdultOptions();
    // Event delegation for passenger card headers
    document.querySelectorAll('input[type="file"]').forEach(fileInput => {
        fileInput.removeEventListener('change', handleFileChange);
        fileInput.addEventListener('change', handleFileChange);
        fileInput.required = true;
        fileInput.setAttribute('aria-required', 'true');
    });
    setTimeout(() => {
        document.querySelectorAll('input[type="file"]').forEach(fileInput => {
            if (!fileInput.files || fileInput.files.length === 0) {
                const index = fileInput.name.match(/\d+/)[0];
                const type = fileInput.name.includes('adult') ? 'Adult' : 'Child';
                const errorElement = document.getElementById(`error-${fileInput.name}`);
                if (errorElement) {
                    errorElement.textContent = `${type} ${parseInt(index) + 1}: ID document is required.`;
                    errorElement.classList.remove('hidden');
                }
            }
        });
    }, 0);
    async function handleFileChange(e) {
        const fileInput = e.target;
        const file = fileInput.files[0];
        const preview = fileInput.nextElementSibling.nextElementSibling;
        const errorElement = fileInput.nextElementSibling;
        preview.innerHTML = '';
        if (!file) {
            errorElement.textContent = 'Please upload an ID document.';
            errorElement.classList.remove('hidden');
            fileInput.setCustomValidity('Please upload an ID document.');
            return;
        }
        fileInput.setCustomValidity('');
        if (file.size > 2621440) {
            errorElement.textContent = 'File size exceeds 2.5MB limit. Please upload a smaller file.';
            errorElement.classList.remove('hidden');
            fileInput.value = '';
            fileInput.setCustomValidity('File size exceeds 2.5MB limit.');
            return;
        }
        const validTypes = ['image/jpeg', 'image/png', 'application/pdf'];
        if (!validTypes.includes(file.type)) {
            errorElement.textContent = 'Invalid file type. Please upload a PDF, JPG, or PNG file.';
            errorElement.classList.remove('hidden');
            fileInput.value = '';
            fileInput.setCustomValidity('Invalid file type.');
            return;
        }
        const clearButton = document.createElement('button');
        clearButton.type = 'button';
        clearButton.className = 'text-xs text-var-alert-error-text mt-1';
        clearButton.textContent = 'Clear File';
        clearButton.addEventListener('click', () => {
            fileInput.value = '';
            preview.innerHTML = '';
            clearButton.remove();
            errorElement.textContent = '';
            errorElement.classList.add('hidden');
            fileInput.setCustomValidity('');
            fileInput.dataset.verificationStatus = '';
        });
        if (file.type.startsWith('image/')) {
            const img = document.createElement('img');
            img.src = URL.createObjectURL(file);
            img.alt = 'File preview';
            img.className = 'max-w-full h-auto';
            preview.appendChild(img);
        } else if (file.type === 'application/pdf') {
            const span = document.createElement('span');
            span.className = 'pdf-icon';
            span.textContent = '📄 PDF';
            preview.appendChild(span);
        }
        preview.appendChild(clearButton);
        const formData = new FormData();
        formData.append('file', file);
        try {
            const response = await fetch(window.urls.validateFile, {
                method: 'POST',
                body: formData,
                headers: { 'X-CSRFToken': getCsrfToken() }
            });
            const contentType = response.headers.get('content-type');
            if (!contentType || !contentType.includes('application/json')) {
                logger.error('Non-JSON response received from validate_file');
                errorElement.textContent = 'Server error: Unable to validate file. Please try a smaller file or contact support.';
                errorElement.classList.remove('hidden');
                fileInput.value = '';
                preview.innerHTML = '';
                clearButton.remove();
                fileInput.setCustomValidity('Server error.');
                return;
            }
            const data = await response.json();
            if (!data.valid) {
                errorElement.textContent = data.error || 'Invalid file. Please upload a valid PDF, JPG, or PNG file.';
                errorElement.classList.remove('hidden');
                fileInput.value = '';
                preview.innerHTML = '';
                clearButton.remove();
                fileInput.setCustomValidity('Invalid file.');
                fileInput.dataset.verificationStatus = '';
            } else {
                fileInput.dataset.verificationStatus = data.verification_status || 'pending';
                errorElement.textContent = data.verification_status === 'verified' ? '' : 'Document verification pending. Please wait for confirmation.';
                errorElement.classList.toggle('hidden', data.verification_status === 'verified');
                fileInput.setCustomValidity('');
            }
        } catch (err) {
            logger.error('File validation failed:', err);
            errorElement.textContent = 'Error validating file. Please try a smaller file or contact support.';
            errorElement.classList.remove('hidden');
            fileInput.value = '';
            preview.innerHTML = '';
            clearButton.remove();
            fileInput.setCustomValidity('Error validating file.');
            fileInput.dataset.verificationStatus = '';
        }
    }
}
// Update child and infant linked adult dropdowns
function updateChildLinkedAdultOptions() {
    const adultsCount = parseInt(adultsInput?.value || 0);
    const childFields = document.getElementById('child-fields');
    const infantFields = document.getElementById('infant-fields');
    [childFields, infantFields].forEach(container => {
        if (!container) return;
        container.querySelectorAll('select[name*="_linked_adult_"]').forEach(select => {
            const index = parseInt(select.name.match(/child_linked_adult_(\d+)/)?.[1] || select.name.match(/infant_linked_adult_(\d+)/)?.[1] || 0);
            const currentValue = select.value;
            select.innerHTML = '<option value="" disabled>Select an adult</option>';
            for (let i = 0; i < adultsCount; i++) {
                const adultName = document.querySelector(`[name="adult_first_name_${i}"]`)?.value || `Adult ${i + 1}`;
                const option = document.createElement('option');
                option.value = i;
                option.textContent = adultName;
                if (String(i) === currentValue) option.selected = true;
                select.appendChild(option);
            }
            if (currentValue && !select.querySelector(`option[value="${currentValue}"]`)) {
                select.value = '';
            }
        });
    });
}
// Toggle vehicle fields
function toggleVehicleFields() {
    if (addVehicleCheckbox && vehicleFields) {
        vehicleFields.classList.toggle('hidden', !addVehicleCheckbox.checked);
        vehicleFields.querySelectorAll('input:not([name="vehicle_license_plate"]), select').forEach(input => {
            input.required = addVehicleCheckbox.checked;
        });
    }
}
// Toggle cargo fields
function toggleCargoFields() {
    if (addCargoCheckbox && cargoFields) {
        cargoFields.classList.toggle('hidden', !addCargoCheckbox.checked);
        cargoFields.querySelectorAll('input:not([name="cargo_license_plate"]):not([name="cargo_dimensions_cm"]), select').forEach(input => {
            input.required = addCargoCheckbox.checked;
        });
    }
}
// Update booking summary
const debouncedUpdateSummary = debounce(async function updateSummary() {
    if (currentStep !== 4) {
        logger.log('Not on Step 4, skipping summary update');
        return;
    }
    if (!summarySection || !summarySchedule || !summaryDuration || !summaryPassengers || !summaryPassengerBreakdown || !summaryAddOns || !summaryVehicle || !summaryCargo || !summaryCost || !weatherWarning) {
        logger.warn('Summary elements missing');
        if (summarySection) {
            summarySection.innerHTML = '<div class="alert error bg-var-alert-error-bg p-4 rounded-lg shadow-sm"><p class="font-semibold text-var-alert-error-text font-poppins">Error: Unable to load summary due to missing elements.</p></div>';
        }
        if (summaryCost) summaryCost.textContent = '0.00';
        latestTotalPrice = '0.00';
        if (weatherWarning) weatherWarning.innerHTML = '';
        return;
    }
    const step4 = document.querySelector('.form-step[data-step="4"]');
    if (step4) step4.setAttribute('aria-busy', 'true');
    if (summarySection) {
        summarySection.innerHTML = '<div class="spinner w-8 h-8 border-2 border-var-text-color border-t-transparent rounded-full animate-spin mx-auto" aria-live="polite"></div>';
    }
    const scheduleId = scheduleInput?.value?.trim() || '';
    if (!scheduleId || isNaN(parseInt(scheduleId))) {
        if (summarySection) {
            summarySection.innerHTML = `
                <div class="alert error bg-var-alert-error-bg p-4 rounded-lg shadow-sm">
                    <p class="font-semibold text-var-alert-error-text font-poppins">Error: Please select a valid schedule in Step 1 to view the booking summary.</p>
                </div>`;
        }
        if (summaryCost) summaryCost.textContent = '0.00';
        latestTotalPrice = '0.00';
        if (weatherWarning) weatherWarning.innerHTML = '';
        if (step4) step4.setAttribute('aria-busy', 'false');
        return;
    }
    try {
        if (!scheduleCache) {
            const response = await fetch(window.urls.getScheduleUpdates, {
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            });
            if (!response.ok) throw new Error('Schedule fetch failed');
            scheduleCache = await response.json();
        }
        const schedule = scheduleCache.schedules.find(s => String(s.id) === String(scheduleId));
        if (!schedule || schedule.status !== 'scheduled' || new Date(schedule.departure_time) <= new Date()) {
            if (summarySection) {
                summarySection.innerHTML = `
                    <div class="alert error bg-var-alert-error-bg p-4 rounded-lg shadow-sm">
                        <p class="font-semibold text-var-alert-error-text font-poppins">Error: Selected schedule is no longer available. Please choose a new schedule in Step 1.</p>
                    </div>`;
            }
            if (summaryCost) summaryCost.textContent = '0.00';
            latestTotalPrice = '0.00';
            if (weatherWarning) weatherWarning.innerHTML = '';
            if (scheduleErrorReset) scheduleErrorReset.style.display = 'block';
            if (step4) step4.setAttribute('aria-busy', 'false');
            return;
        }
        const formData = new FormData(bookingForm);
        formData.append('step', currentStep);
        ['premium_seating', 'priority_boarding', 'cabin', 'meal_breakfast', 'meal_lunch', 'meal_dinner', 'meal_snack'].forEach((type, index) => {
            const quantity = document.getElementById(`${type}_quantity`)?.value || '0';
            if (parseInt(quantity) > 0) {
                formData.append(`add_ons[${index}][add_on_type]`, type);
                formData.append(`add_ons[${index}][quantity]`, quantity);
            }
        });
        const pricingResponse = await fetch(window.urls.getPricing, {
            method: 'POST',
            body: formData,
            headers: { 'X-CSRFToken': getCsrfToken() }
        });
        if (!pricingResponse.ok) throw new Error('Pricing fetch failed');
        pricingCache = await pricingResponse.json();
        latestTotalPrice = pricingCache.total_price || '0.00';
        let backendSummary = window.backendSummary || null;
        if (!backendSummary) {
            const summaryResponse = await fetch(window.urls.bookings, {
                method: 'POST',
                body: formData,
                headers: { 'X-CSRFToken': getCsrfToken() }
            });
            if (summaryResponse.ok) {
                const data = await summaryResponse.json();
                if (data.success && data.summary) {
                    backendSummary = data.summary;
                    logger.log('Backend summary loaded:', backendSummary);
                }
            }
        }
        let weatherHtml = '';
        try {
            const weatherResponse = await fetch(`${window.urls.getWeatherConditions}?schedule_id=${scheduleId}`, {
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            });
            if (weatherResponse.ok) {
                const weatherData = await weatherResponse.json();
                if (weatherData.warning) {
                    weatherHtml = `
                        <div class="alert warning bg-yellow-100 p-4 rounded-lg shadow-sm">
                            <p class="font-semibold text-yellow-800 font-poppins">${weatherData.warning}</p>
                        </div>`;
                }
            }
        } catch (e) {
            logger.warn('Weather fetch failed:', e);
        }
        if (summarySchedule) {
            summarySchedule.textContent = backendSummary?.schedule?.route || `${schedule.route.departure_port} to ${schedule.route.destination_port} - ${new Date(schedule.departure_time).toLocaleString('en-US', {
                weekday: 'short',
                month: 'short',
                day: 'numeric',
                hour: 'numeric',
                minute: '2-digit',
                hour12: true
            })}`;
        }
        if (summaryDuration) {
            summaryDuration.textContent = backendSummary?.schedule?.estimated_duration || schedule.estimated_duration;
        }
        const adults = parseInt(adultsInput?.value || 0);
        const children = parseInt(childrenInput?.value || 0);
        const infants = parseInt(infantsInput?.value || 0);
        if (summaryPassengers) {
            summaryPassengers.textContent = `${adults} Adult${adults !== 1 ? 's' : ''}, ${children} Child${children !== 1 ? 'ren' : ''}, ${infants} Infant${infants !== 1 ? 's' : ''}`;
        }
        let passengerBreakdown = '';
        document.querySelectorAll('#adult-fields .passenger-card').forEach((card, i) => {
            const firstName = card.querySelector('[name^="adult_first_name"]')?.value || 'Unknown';
            const lastName = card.querySelector('[name^="adult_last_name"]')?.value || '';
            const age = card.querySelector('[name^="adult_age"]')?.value || '';
            passengerBreakdown += `<p class="text-xs md:text-sm text-var-text-color font-poppins">Adult ${i + 1}: ${firstName} ${lastName}${age ? ` (Age: ${age})` : ''}</p>`;
        });
        document.querySelectorAll('#child-fields .passenger-card').forEach((card, i) => {
            const firstName = card.querySelector('[name^="child_first_name"]')?.value || 'Unknown';
            const lastName = card.querySelector('[name^="child_last_name"]')?.value || '';
            const age = card.querySelector('[name^="child_age"]')?.value || '';
            const linkedAdultIndex = card.querySelector('[name^="child_linked_adult"]')?.value || '';
            const linkedAdultName = linkedAdultIndex !== ''
                ? document.querySelector(`[name="adult_first_name_${linkedAdultIndex}"]`)?.value || `Adult ${parseInt(linkedAdultIndex)+1}`
                : '';
            passengerBreakdown += `<p class="text-xs md:text-sm text-var-text-color font-poppins">Child ${i + 1}: ${firstName} ${lastName}${age ? ` (Age: ${age})` : ''}${linkedAdultName ? `, Linked Adult: ${linkedAdultName}` : ''}</p>`;
        });
        document.querySelectorAll('#infant-fields .passenger-card').forEach((card, i) => {
            const firstName = card.querySelector('[name^="infant_first_name"]')?.value || 'Unknown';
            const lastName = card.querySelector('[name^="infant_last_name"]')?.value || '';
            const dob = card.querySelector('[name^="infant_dob"]')?.value || '';
            const linkedAdultIndex = card.querySelector('[name^="infant_linked_adult"]')?.value || '';
            const linkedAdultName = linkedAdultIndex !== ''
                ? document.querySelector(`[name="adult_first_name_${linkedAdultIndex}"]`)?.value || `Adult ${parseInt(linkedAdultIndex)+1}`
                : '';
            passengerBreakdown += `<p class="text-xs md:text-sm text-var-text-color font-poppins">Infant ${i + 1}: ${firstName} ${lastName}${dob ? ` (DOB: ${new Date(dob).toLocaleDateString('en-US')})` : ''}${linkedAdultName ? `, Linked Adult: ${linkedAdultName}` : ''}</p>`;
        });
        if (summaryPassengerBreakdown) {
            summaryPassengerBreakdown.innerHTML = passengerBreakdown;
        }
        const addOns = [];
        ['premium_seating', 'priority_boarding', 'cabin', 'meal_breakfast', 'meal_lunch', 'meal_dinner', 'meal_snack'].forEach(type => {
            const quantity = document.getElementById(`${type}_quantity`)?.value || '0';
            if (parseInt(quantity) > 0) {
                addOns.push(`${quantity} ${type.replace('meal_', '').replace('_', ' ').replace(/\b\w/g, c => c.toUpperCase())}`);
            }
        });
        if (summaryAddOns) {
            summaryAddOns.innerHTML = addOns.length > 0 ? addOns.map(item => `<p class="text-xs md:text-sm text-var-text-color font-poppins">${item}</p>`).join('') : '<p class="text-xs md:text-sm text-var-text-color font-poppins">None</p>';
        }
        if (summaryVehicle) {
            summaryVehicle.innerHTML = addVehicleCheckbox?.checked ? `
                <p class="text-xs md:text-sm text-var-text-color font-poppins">Type: ${document.getElementById('vehicle_type')?.value || 'N/A'}</p>
                <p class="text-xs md:text-sm text-var-text-color font-poppins">Dimensions: ${document.getElementById('vehicle_dimensions')?.value || 'N/A'}</p>
                <p class="text-xs md:text-sm text-var-text-color font-poppins">License Plate: ${document.getElementById('vehicle_license_plate')?.value || 'N/A'}</p>
            ` : '<p class="text-xs md:text-sm text-var-text-color font-poppins">None</p>';
        }
        if (summaryCargo) {
            summaryCargo.innerHTML = addCargoCheckbox?.checked ? `
                <p class="text-xs md:text-sm text-var-text-color font-poppins">Type: ${document.getElementById('cargo_type')?.value || 'N/A'}</p>
                <p class="text-xs md:text-sm text-var-text-color font-poppins">Weight: ${document.getElementById('cargo_weight_kg')?.value || '0'} kg</p>
                <p class="text-xs md:text-sm text-var-text-color font-poppins">Dimensions: ${document.getElementById('cargo_dimensions_cm')?.value || 'N/A'}</p>
                <p class="text-xs md:text-sm text-var-text-color font-poppins">License Plate: ${document.getElementById('cargo_license_plate')?.value || 'N/A'}</p>
            ` : '<p class="text-xs md:text-sm text-var-text-color font-poppins">None</p>';
        }
        if (summaryCost) {
            summaryCost.textContent = parseFloat(latestTotalPrice).toFixed(2);
        }
        if (weatherWarning) {
            weatherWarning.innerHTML = weatherHtml;
        }
        if (summarySection) {
            summarySection.innerHTML = `
                <div class="bg-var-card-bg p-4 rounded-lg shadow-sm">
                    <h3 class="text-lg font-semibold text-var-text-color font-poppins">Schedule</h3>
                    <p class="text-xs md:text-sm text-var-text-color font-poppins"><strong>Route:</strong> <span id="summary-schedule">${summarySchedule?.textContent || 'N/A'}</span></p>
                    <p class="text-xs md:text-sm text-var-text-color font-poppins"><strong>Duration:</strong> <span id="summary-duration">${summaryDuration?.textContent || 'N/A'}</span></p>
                </div>
                <div class="bg-var-card-bg p-4 rounded-lg shadow-sm">
                    <h3 class="text-lg font-semibold text-var-text-color font-poppins">Passengers</h3>
                    <p class="text-xs md:text-sm text-var-text-color font-poppins"><span id="summary-passengers">${summaryPassengers?.textContent || 'None'}</span></p>
                    <div id="summary-passenger-breakdown">${summaryPassengerBreakdown?.innerHTML || ''}</div>
                </div>
                <div id="summary-add-ons" class="bg-var-card-bg p-4 rounded-lg shadow-sm">
                    <h3 class="text-lg font-semibold text-var-text-color font-poppins">Add-Ons</h3>
                    ${summaryAddOns?.innerHTML || '<p class="text-xs md:text-sm text-var-text-color font-poppins">None</p>'}
                </div>
                <div id="summary-vehicle" class="bg-var-card-bg p-4 rounded-lg shadow-sm">
                    <h3 class="text-lg font-semibold text-var-text-color font-poppins">Vehicle</h3>
                    ${summaryVehicle?.innerHTML || '<p class="text-xs md:text-sm text-var-text-color font-poppins">None</p>'}
                </div>
                <div id="summary-cargo" class="bg-var-card-bg p-4 rounded-lg shadow-sm">
                    <h3 class="text-lg font-semibold text-var-text-color font-poppins">Cargo</h3>
                    ${summaryCargo?.innerHTML || '<p class="text-xs md:text-sm text-var-text-color font-poppins">None</p>'}
                </div>
                <div class="bg-var-card-bg p-4 rounded-lg shadow-sm">
                    <h3 class="text-lg font-semibold text-var-text-color font-poppins">Total Cost</h3>
                    <p class="text-base md:text-lg font-bold text-var-step-4-accent font-poppins">FJD <span id="summary-cost">${summaryCost?.textContent || '0.00'}</span></p>
                </div>
            `;
        }
    } catch (e) {
        logger.error('Summary update failed:', e);
        if (summarySection) {
            summarySection.innerHTML = `
                <div class="alert error bg-var-alert-error-bg p-4 rounded-lg shadow-sm">
                    <p class="font-semibold text-var-alert-error-text font-poppins">Error: Unable to load booking summary. Please try again.</p>
                </div>`;
        }
        if (summaryCost) summaryCost.textContent = '0.00';
        latestTotalPrice = '0.00';
        if (weatherWarning) weatherWarning.innerHTML = '';
    } finally {
        if (step4) step4.setAttribute('aria-busy', 'false');
    }
}, 300);
// Validate email format
function isValidEmail(email) {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return emailRegex.test(email);
}
// Validate step and proceed
async function validateStep(step, button) {
    if (!bookingForm || !button) {
        logger.warn('Booking form or button not found');
        return;
    }
    toggleButtonLoading(button, true);
    document.querySelectorAll('.error-message').forEach(el => {
        el.textContent = '';
        el.classList.add('hidden');
    });
    document.querySelectorAll('.alert.error').forEach(el => el.remove());
    if (step === 1) {
        const scheduleId = scheduleInput?.value?.trim() || '';
        if (!scheduleId || isNaN(parseInt(scheduleId))) {
            displayBackendErrors(
                [{ field: 'schedule_id', message: 'Please select a valid schedule.' }],
                button
            );
            toggleButtonLoading(button, false);
            return;
        }
        if (!window.isAuthenticated && guestEmailInput) {
            const guestEmail = guestEmailInput.value?.trim() || '';
            if (!guestEmail || !isValidEmail(guestEmail)) {
                displayBackendErrors(
                    [{ field: 'guest_email', message: 'Please enter a valid email address.' }],
                    button
                );
                toggleButtonLoading(button, false);
                return;
            }
        }
        try {
            const response = await fetch(window.urls.getScheduleUpdates, {
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            });
            if (!response.ok) throw new Error('Schedule fetch failed');
            scheduleCache = await response.json();
            const schedule = scheduleCache.schedules.find(s => String(s.id) === String(scheduleId));
            if (!schedule || schedule.status !== 'scheduled' || new Date(schedule.departure_time) <= new Date()) {
                displayBackendErrors(
                    [{ field: 'schedule_id', message: 'Selected schedule is no longer available. Please choose a new schedule.' }],
                    button
                );
                if (scheduleErrorReset) scheduleErrorReset.style.display = 'block';
                toggleButtonLoading(button, false);
                return;
            }
        } catch (e) {
            logger.error('Error verifying schedule_id:', e);
            displayBackendErrors(
                [{ field: 'schedule_id', message: 'Unable to verify schedule availability. Please try again.' }],
                button
            );
            toggleButtonLoading(button, false);
            return;
        }
    }
    if (step === 2) {
        const adults = parseInt(adultsInput?.value || 0);
        const children = parseInt(childrenInput?.value || 0);
        const infants = parseInt(infantsInput?.value || 0);
        if (adults === 0) {
            displayBackendErrors(
                [{ field: 'passenger-details', message: 'At least one adult is required.' }],
                button
            );
            toggleButtonLoading(button, false);
            return;
        }
        const errors = [];
        ['adult', 'child', 'infant'].forEach(type => {
            const count = parseInt(document.getElementById(`${type}s`)?.value || 0);
            for (let i = 0; i < count; i++) {
                const firstName = document.querySelector(`[name="${type}_first_name_${i}"]`)?.value?.trim();
                if (!firstName) {
                    errors.push({ field: `${type}_first_name_${i}`, message: `${type.charAt(0).toUpperCase() + type.slice(1)} ${i + 1}: First name is required.` });
                }
                const lastName = document.querySelector(`[name="${type}_last_name_${i}"]`)?.value?.trim();
                if (!lastName) {
                    errors.push({ field: `${type}_last_name_${i}`, message: `${type.charAt(0).toUpperCase() + type.slice(1)} ${i + 1}: Last name is required.` });
                }
                if (type !== 'infant') {
                    const age = document.querySelector(`[name="${type}_age_${i}"]`)?.value;
                    if (!age || isNaN(parseInt(age)) || (type === 'adult' && parseInt(age) < 18) || (type === 'child' && (parseInt(age) < 2 || parseInt(age) > 17))) {
                        errors.push({ field: `${type}_age_${i}`, message: `${type.charAt(0).toUpperCase() + type.slice(1)} ${i + 1}: Valid age is required (Adult: 18+, Child: 2-17).` });
                    }
                    const fileInput = document.querySelector(`[name="${type}_id_document_${i}"]`);
                    const errorElement = document.getElementById(`error-${type}_id_document_${i}`);
                    if (!fileInput || !fileInput.files || fileInput.files.length === 0) {
                        errors.push({ field: `${type}_id_document_${i}`, message: `${type.charAt(0).toUpperCase() + type.slice(1)} ${i + 1}: ID document is required.` });
                        if (errorElement) {
                            errorElement.textContent = `${type.charAt(0).toUpperCase() + type.slice(1)} ${i + 1}: ID document is required.`;
                            errorElement.classList.remove('hidden');
                        }
                    } else {
                        const status = fileInput.dataset.verificationStatus || 'pending';
                        if (status !== 'verified') {
                            errors.push({ field: `${type}_id_document_${i}`, message: `${type.charAt(0).toUpperCase() + type.slice(1)} ${i + 1}: ID document is ${status}. Please upload a verified document.` });
                            if (errorElement) {
                                errorElement.textContent = `${type.charAt(0).toUpperCase() + type.slice(1)} ${i + 1}: ID document is ${status}. Please upload a verified document.`;
                                errorElement.classList.remove('hidden');
                            }
                        }
                    }
                }
                if (type === 'infant') {
                    const dobInput = document.querySelector(`[name="${type}_dob_${i}"]`);
                    if (!dobInput || !dobInput.value) {
                        errors.push({ field: `${type}_dob_${i}`, message: `Infant ${i + 1}: Date of birth is required.` });
                    } else {
                        const dob = new Date(dobInput.value);
                        const now = new Date();
                        const ageInMonths = (now - dob) / (1000 * 60 * 60 * 24 * 30);
                        if (ageInMonths > 24) {
                            errors.push({ field: `${type}_dob_${i}`, message: `Infant ${i + 1}: Must be under 2 years old.` });
                        }
                    }
                }
                if (type !== 'adult') {
                    const linkedAdult = document.querySelector(`[name="${type}_linked_adult_${i}"]`);
                    if (!linkedAdult || !linkedAdult.value) {
                        errors.push({ field: `${type}_linked_adult_${i}`, message: `${type.charAt(0).toUpperCase() + type.slice(1)} ${i + 1}: Must be linked to an adult.` });
                    } else if (isNaN(parseInt(linkedAdult.value)) || parseInt(linkedAdult.value) >= adults) {
                        errors.push({ field: `${type}_linked_adult_${i}`, message: `${type.charAt(0).toUpperCase() + type.slice(1)} ${i + 1}: Invalid linked adult.` });
                    }
                }
                if (type === 'adult') {
                    const phone = document.querySelector(`[name="${type}_phone_${i}"]`)?.value?.trim();
                    if (!phone || !/^\+?[\d\s-]{7,15}$/.test(phone)) {
                        errors.push({ field: `${type}_phone_${i}`, message: `${type.charAt(0).toUpperCase() + type.slice(1)} ${i + 1}: Valid phone number is required.` });
                    }
                }
            }
        });
        if (errors.length > 0) {
            displayBackendErrors(errors, button);
            toggleButtonLoading(button, false);
            return;
        }
    }
    if (step === 3) {
        const errors = [];
        if (addCargoCheckbox?.checked) {
            const cargoType = document.getElementById('cargo_type')?.value?.trim();
            const weightKg = document.getElementById('cargo_weight_kg')?.value?.trim();
            if (!cargoType) {
                errors.push({ field: 'cargo_type', message: 'Cargo type is required when adding cargo.' });
            }
            if (!weightKg || isNaN(parseFloat(weightKg)) || parseFloat(weightKg) <= 0) {
                errors.push({ field: 'cargo_weight_kg', message: 'Cargo weight must be a positive number.' });
            }
        }
        if (errors.length > 0) {
            displayBackendErrors(errors, button);
            toggleButtonLoading(button, false);
            return;
        }
    }
    if (step === 4 && !privacyConsent?.checked) {
        displayBackendErrors(
            [{ field: 'privacy-consent', message: 'You must agree to the Privacy Policy and Terms of Service.' }],
            button
        );
        toggleButtonLoading(button, false);
        return;
    }
    const formData = new FormData(bookingForm);
    formData.append('step', step);
    ['premium_seating', 'priority_boarding', 'cabin', 'meal_breakfast', 'meal_lunch', 'meal_dinner', 'meal_snack'].forEach((type, index) => {
        const quantity = document.getElementById(`${type}_quantity`)?.value || '0';
        if (parseInt(quantity) > 0) {
            formData.append(`add_ons[${index}][add_on_type]`, type);
            formData.append(`add_ons[${index}][quantity]`, quantity);
        }
    });
    try {
        const csrfToken = getCsrfToken();
        if (!csrfToken) {
            displayBackendErrors(
                [{ field: 'general', message: 'CSRF token missing. Please refresh the page and try again.' }],
                button
            );
            toggleButtonLoading(button, false);
            return;
        }
        logger.log('Form data sent to validate_step:', [...formData.entries()]);
        const response = await fetch(window.urls.validateStep, {
            method: 'POST',
            body: formData,
            headers: { 'X-CSRFToken': csrfToken }
        });
        if (!response.ok) {
            let errorMessage = `HTTP error! Status: ${response.status}`;
            try {
                const contentType = response.headers.get('content-type');
                if (contentType && contentType.includes('application/json')) {
                    const errorData = await response.json();
                    errorMessage = errorData.message || errorMessage;
                    if (errorData.errors) {
                        displayBackendErrors(errorData.errors, button);
                        toggleButtonLoading(button, false);
                        return;
                    }
                }
            } catch (e) {
                logger.error('Error parsing error response:', e);
            }
            if (response.status === 413) {
                displayBackendErrors(
                    [{ field: 'general', message: 'Uploaded files are too large. Please ensure all files are under 2.5MB and try again.' }],
                    button
                );
            } else {
                displayBackendErrors(
                    [{ field: 'general', message: `${errorMessage}. Please try again or contact support.` }],
                    button
                );
            }
            toggleButtonLoading(button, false);
            return;
        }
        const contentType = response.headers.get('content-type');
        if (!contentType || !contentType.includes('application/json')) {
            logger.error('Non-JSON response received from validate_step');
            displayBackendErrors(
                [{ field: 'general', message: 'Server error: Unable to process request. Please try smaller files or contact support.' }],
                button
            );
            toggleButtonLoading(button, false);
            return;
        }
        const data = await response.json();
        logger.log('validate_step response:', data);
        if (data.valid) {
            if (step === 4) {
                const paymentResponse = await fetch(window.urls.createCheckoutSession, {
                    method: 'POST',
                    body: formData,
                    headers: { 'X-CSRFToken': csrfToken }
                });
                const paymentContentType = paymentResponse.headers.get('content-type');
                if (!paymentContentType || !paymentContentType.includes('application/json')) {
                    logger.error('Non-JSON response received from createCheckoutSession');
                    displayBackendErrors(
                        [{ field: 'payment', message: 'Server error: Unable to initiate payment. Please try again or contact support.' }],
                        button
                    );
                    toggleButtonLoading(button, false);
                    return;
                }
                const paymentData = await paymentResponse.json();
                if (paymentData.sessionId) {
                    window.stripe.redirectToCheckout({ sessionId: paymentData.sessionId });
                } else {
                    const errors = paymentData.errors || [{ field: 'payment', message: 'Failed to initiate payment. Please check your input and try again.' }];
                    displayBackendErrors(errors, button);
                }
            } else {
                updateStep(step + 1);
            }
        } else {
            logger.error('Server validation errors:', data.errors);
            displayBackendErrors(
                data.errors && data.errors.length > 0
                    ? data.errors
                    : [{ field: 'general', message: 'An error occurred. Please check your input and try again.' }],
                button
            );
        }
    } catch (e) {
        logger.error('Step validation failed:', e);
        displayBackendErrors(
            [{ field: 'general', message: `Validation failed: ${e.message}. Please try again or contact support.` }],
            button
        );
    } finally {
        toggleButtonLoading(button, false);
    }
}
// Initialize event listeners
function initializeEventListeners() {
    if (eventListenersAdded) return;
    eventListenersAdded = true;
    nextButtons.forEach(button => {
        button.addEventListener('click', () => {
            const nextStep = parseInt(button.dataset.next);
            if (!isNaN(nextStep)) {
                validateStep(nextStep - 1, button);
            }
        });
    });
    prevButtons.forEach(button => {
        button.addEventListener('click', () => {
            const prevStep = parseInt(button.dataset.prev);
            if (!isNaN(prevStep)) {
                updateStep(prevStep);
            }
        });
    });
    if (adultsInput) {
        adultsInput.addEventListener('input', () => {
            updatePassengerFields();
            debouncedUpdateSummary();
            updateChildLinkedAdultOptions();
        });
    }
    if (childrenInput) {
        childrenInput.addEventListener('input', () => {
            updatePassengerFields();
            debouncedUpdateSummary();
        });
    }
    if (infantsInput) {
        infantsInput.addEventListener('input', () => {
            updatePassengerFields();
            debouncedUpdateSummary();
        });
    }
    if (addVehicleCheckbox) {
        addVehicleCheckbox.addEventListener('change', () => {
            toggleVehicleFields();
            debouncedUpdateSummary();
        });
    }
    if (addCargoCheckbox) {
        addCargoCheckbox.addEventListener('change', () => {
            toggleCargoFields();
            debouncedUpdateSummary();
        });
    }
    if (proceedToPayment) {
        proceedToPayment.addEventListener('click', () => {
            if (!privacyConsent?.checked) {
                displayBackendErrors([{ field: 'privacy-consent', message: 'You must agree to the Privacy Policy and Terms of Service.' }], proceedToPayment);
                return;
            }
            validateStep(4, proceedToPayment);
        });
    }
    if (resetScheduleButton) {
        resetScheduleButton.addEventListener('click', () => {
            clearFormData();
            updateStep(1);
        });
    }
    ['premium_seating', 'priority_boarding', 'cabin', 'meal_breakfast', 'meal_lunch', 'meal_dinner', 'meal_snack'].forEach(type => {
        const input = document.getElementById(`${type}_quantity`);
        if (input) {
            input.addEventListener('input', debouncedUpdateSummary);
        }
    });
    if (scheduleInput) {
        scheduleInput.addEventListener('change', () => {
            scheduleCache = null;
            debouncedUpdateSummary();
            saveFormData();
        });
    }
    if (guestEmailInput) {
        guestEmailInput.addEventListener('input', saveFormData);
    }
    document.querySelectorAll('#vehicle-fields input, #vehicle-fields select, #cargo-fields input, #cargo-fields select').forEach(input => {
        input.addEventListener('input', debouncedUpdateSummary);
    });
    document.querySelectorAll('input[name*="adult_first_name_"], input[name*="adult_last_name_"]').forEach(input => {
        input.addEventListener('input', updateChildLinkedAdultOptions);
    });
    // Event delegation for passenger card headers
    document.addEventListener('click', (e) => {
        const header = e.target.closest('.passenger-card-header');
        if (header) {
            const details = header.nextElementSibling;
            const icon = header.querySelector('.toggle-icon');
            const isExpanded = header.getAttribute('aria-expanded') === 'true';
            header.setAttribute('aria-expanded', !isExpanded);
            details.style.display = isExpanded ? 'none' : 'block';
            icon.textContent = isExpanded ? '+' : '−';
        }
    });
}
// Initialize AOS and load form data
document.addEventListener('DOMContentLoaded', () => {
    AOS.init({ duration: 600, once: true });
    loadFormData();
    initializeEventListeners();
});