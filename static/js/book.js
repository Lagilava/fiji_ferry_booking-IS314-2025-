(function () {
    const bookingForm = document.getElementById('booking-form');
    const adultsInput = document.getElementById('adults');
    const youthsInput = document.getElementById('youths');
    const childrenInput = document.getElementById('children');
    const infantsInput = document.getElementById('infants');
    const scheduleInput = document.getElementById('schedule_id');
    const passengerDetails = document.getElementById('passenger-details');
    const adultFields = document.getElementById('adult-fields');
    const youthFields = document.getElementById('youth-fields');
    const childFields = document.getElementById('child-fields');
    const infantFields = document.getElementById('infant-fields');
    const cargoCheckbox = document.getElementById('add_cargo_checkbox');
    const cargoFields = document.getElementById('cargo-fields');
    const unaccompaniedMinorCheckbox = document.getElementById('is_unaccompanied_minor');
    const unaccompaniedMinorFields = document.getElementById('unaccompanied-minor-fields');
    const groupBookingCheckbox = document.getElementById('is_group_booking');
    const emergencyCheckbox = document.getElementById('is_emergency');
    const responsibilityDeclarationFields = document.getElementById('responsibility-declaration-fields');
    const nextButtons = document.querySelectorAll('.next-step');
    const prevButtons = document.querySelectorAll('.prev-step');

    let currentStep = parseInt(bookingForm.querySelector('input[name="step"]').value) || 1;
    let passengerData = { adult: [{ open: true }], youth: [], child: [], infant: [] };
    let latestTotalPrice = '0.00'; // Store total_price from get_pricing

    const isDev = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";

    const logger = {
        log: (...args) => isDev && console.log(...args),
        warn: (...args) => isDev && console.warn(...args),
        error: console.error.bind(console)
    };

    const getCsrfToken = () => {
        const name = 'csrftoken';
        const decodedCookie = decodeURIComponent(document.cookie);
        const cookieArray = decodedCookie.split(';');
        for (let cookie of cookieArray) {
            cookie = cookie.trim();
            if (cookie.indexOf(name + '=') === 0) {
                return cookie.substring(name.length + 1);
            }
        }
        return '';
    };

    const updateStep = (step) => {
        currentStep = step;
        document.querySelectorAll('.form-step').forEach(s => {
            s.classList.remove('active');
            s.style.display = 'none';
        });
        const targetStep = document.querySelector(`.form-step.step-${step}`);
        if (targetStep) {
            targetStep.classList.add('active');
            targetStep.style.display = 'block';
            logger.log(`Added active class to Step ${step}`, targetStep);
        }
        document.querySelector('input[name="step"]').value = step;

        document.querySelectorAll('.step').forEach(s => {
            s.classList.remove('active', 'completed');
            const stepNum = parseInt(s.dataset.step);
            if (stepNum < step) s.classList.add('completed');
            if (stepNum === step) s.classList.add('active');
        });

        const progressPercent = ((step - 1) / 3) * 100;
        document.querySelector('.progress-bar-fill').style.width = `${progressPercent}%`;
        document.querySelector('.progress-bar-fill').style.background = `var(--step-${step}-accent)`;
    };

    const debounce = (func, wait) => {
        let timeout;
        return (...args) => {
            clearTimeout(timeout);
            timeout = setTimeout(() => func(...args), wait);
        };
    };

    const saveFormData = debounce(() => {
        const formData = {
            step: currentStep,
            schedule_id: scheduleInput?.value || '',
            adults: adultsInput?.value || 1,
            youths: youthsInput?.value || 0,
            children: childrenInput?.value || 0,
            infants: infantsInput?.value || 0,
            passengerData,
            guest_email: document.getElementById('guest_email')?.value || '',
            add_cargo: cargoCheckbox?.checked || false,
            cargo_type: document.getElementById('cargo_type')?.value || '',
            weight_kg: document.getElementById('weight_kg')?.value || '',
            dimensions_cm: document.getElementById('dimensions_cm')?.value || '',
            is_unaccompanied_minor: unaccompaniedMinorCheckbox?.checked || false,
            guardian_contact: document.getElementById('guardian_contact')?.value || '',
            is_group_booking: groupBookingCheckbox?.checked || false,
            is_emergency: emergencyCheckbox?.checked || false,
            privacy_consent: document.getElementById('privacy-consent')?.checked || false
        };
        try {
            localStorage.setItem('bookingFormData', JSON.stringify(formData));
            logger.log('Saving formData:', formData);
        } catch (e) {
            logger.warn('localStorage unavailable:', e);
        }
    }, 500);

    const loadFormData = () => {
        try {
            const savedData = JSON.parse(localStorage.getItem('bookingFormData')) || {};
            if (savedData.step) currentStep = parseInt(savedData.step);
            if (!window.isAuthenticated && savedData.guest_email) {
                const guestEmailInput = document.getElementById('guest_email');
                if (guestEmailInput) guestEmailInput.value = savedData.guest_email;
            }
            if (savedData.schedule_id && scheduleInput) {
                scheduleInput.value = savedData.schedule_id;
                const option = scheduleInput.querySelector(`option[value="${savedData.schedule_id}"]`);
                if (option) option.selected = true;
            }
            if (savedData.adults && adultsInput) adultsInput.value = savedData.adults;
            if (savedData.youths && youthsInput) youthsInput.value = savedData.youths;
            if (savedData.children && childrenInput) childrenInput.value = savedData.children;
            if (savedData.infants && infantsInput) infantsInput.value = savedData.infants;
            passengerData = savedData.passengerData || { adult: [{ open: true }], youth: [], child: [], infant: [] };
            if (savedData.add_cargo && cargoCheckbox) {
                cargoCheckbox.checked = savedData.add_cargo;
                cargoFields.classList.toggle('hidden', !savedData.add_cargo);
            }
            if (savedData.cargo_type) document.getElementById('cargo_type').value = savedData.cargo_type;
            if (savedData.weight_kg) document.getElementById('weight_kg').value = savedData.weight_kg;
            if (savedData.dimensions_cm) document.getElementById('dimensions_cm').value = savedData.dimensions_cm;
            if (savedData.is_unaccompanied_minor && unaccompaniedMinorCheckbox) {
                unaccompaniedMinorCheckbox.checked = savedData.is_unaccompanied_minor;
                unaccompaniedMinorFields.classList.toggle('hidden', !savedData.is_unaccompanied_minor);
            }
            if (savedData.guardian_contact) document.getElementById('guardian_contact').value = savedData.guardian_contact;
            if (savedData.is_group_booking && groupBookingCheckbox) groupBookingCheckbox.checked = savedData.is_group_booking;
            if (savedData.is_emergency && emergencyCheckbox) emergencyCheckbox.checked = savedData.is_emergency;
            if (savedData.privacy_consent) document.getElementById('privacy-consent').checked = savedData.privacy_consent;

            logger.log('Loaded passengerData:', passengerData);
            updateStep(currentStep);
            updatePassengerFields();
            toggleRequiredFields();
            updateSummary();
        } catch (e) {
            logger.warn('localStorage unavailable or corrupted:', e);
        }
    };

    const clearFormData = () => {
        try {
            localStorage.removeItem('bookingFormData');
            localStorage.removeItem('file-responsibility_declaration');
            localStorage.removeItem('file-consent_form');
            passengerData = { adult: [{ open: true }], youth: [], child: [], infant: [] };
            bookingForm.reset();
            updateStep(1);
            updatePassengerFields();
        } catch (e) {
            logger.warn('localStorage unavailable:', e);
        }
    };

    const updatePassengerFields = () => {
        if (!passengerDetails || !adultFields || !youthFields || !childFields || !infantFields) {
            logger.error('Required passenger containers missing');
            return;
        }

        const counts = {
            adult: parseInt(adultsInput?.value) || 1,
            youth: parseInt(youthsInput?.value) || 0,
            child: parseInt(childrenInput?.value) || 0,
            infant: parseInt(infantsInput?.value) || 0
        };

        const containers = { adult: adultFields, youth: youthFields, child: childFields, infant: infantFields };

        for (const [type, container] of Object.entries(containers)) {
            passengerData[type] = passengerData[type] || [];

            // Ensure we have the right number of passenger slots
            for (let i = 0; i < counts[type]; i++) {
                const existing = document.getElementById(`${type}_fieldset_${i}`);

                // Reuse existing fieldset if it already exists
                if (existing) {
                    continue;
                }

                const data = passengerData[type][i] || { first_name: '', last_name: '', age: '', open: true };
                passengerData[type][i] = data;

                const fieldset = document.createElement('fieldset');
                fieldset.className = 'passenger-fieldset';
                fieldset.id = `${type}_fieldset_${i}`;

                fieldset.innerHTML = `
                    <button type="button" class="passenger-fieldset-header">
                        <h4>${type.charAt(0).toUpperCase() + type.slice(1)} ${i + 1}</h4>
                        <span class="toggle-icon">${data.open ? '−' : '+'}</span>
                    </button>
                    <div class="passenger-fieldset-content ${data.open ? 'open' : ''}">
                        <div class="form-group">
                            <label for="${type}_first_name_${i}" class="block text-sm font-semibold text-var-text-color font-poppins">First Name</label>
                            <input type="text" id="${type}_first_name_${i}" name="${type}_first_name_${i}" value="${data.first_name || ''}" required
                                class="w-full p-2 border rounded bg-var-input-bg text-var-text-color focus:outline-none focus:ring-2 focus:ring-var-step-2-accent"
                                aria-required="true">
                            <p id="error-${type}_first_name_${i}" class="error-message hidden mt-1 text-sm text-var-alert-error-text font-poppins"></p>
                        </div>
                        <div class="form-group mt-2">
                            <label for="${type}_last_name_${i}" class="block text-sm font-semibold text-var-text-color font-poppins">Last Name</label>
                            <input type="text" id="${type}_last_name_${i}" name="${type}_last_name_${i}" value="${data.last_name || ''}" required
                                class="w-full p-2 border rounded bg-var-input-bg text-var-text-color focus:outline-none focus:ring-2 focus:ring-var-step-2-accent"
                                aria-required="true">
                            <p id="error-${type}_last_name_${i}" class="error-message hidden mt-1 text-sm text-var-alert-error-text font-poppins"></p>
                        </div>
                        <div class="form-group mt-2">
                            <label for="${type}_age_${i}" class="block text-sm font-semibold text-var-text-color font-poppins">Age</label>
                            <input type="number" id="${type}_age_${i}" name="${type}_age_${i}" value="${data.age || ''}" required
                                class="w-full p-2 border rounded bg-var-input-bg text-var-text-color focus:outline-none focus:ring-2 focus:ring-var-step-2-accent"
                                min="0" aria-required="true">
                            <p id="error-${type}_age_${i}" class="error-message hidden mt-1 text-sm text-var-alert-error-text font-poppins"></p>
                        </div>
                        ${type === 'adult' ? `
                        <div class="form-group mt-2">
                            <label class="flex items-center">
                                <input type="checkbox" id="${type}_is_parent_guardian_${i}" name="${type}_is_parent_guardian_${i}" ${data.is_parent_guardian ? 'checked' : ''}
                                    class="mr-2 h-5 w-5 text-var-step-2-accent focus:ring-var-step-2-accent border-var-border-color">
                                <span class="text-sm font-semibold text-var-text-color font-poppins">Parent/Guardian</span>
                            </label>
                        </div>
                        <div class="form-group mt-2">
                            <label class="flex items-center">
                                <input type="checkbox" id="${type}_is_group_leader_${i}" name="${type}_is_group_leader_${i}" ${data.is_group_leader ? 'checked' : ''}
                                    class="mr-2 h-5 w-5 text-var-step-2-accent focus:ring-var-step-2-accent border-var-border-color">
                                <span class="text-sm font-semibold text-var-text-color font-poppins">Group Leader</span>
                            </label>
                        </div>` : ''}
                    </div>`;

                container.appendChild(fieldset);
            }

            // If user reduced count (e.g. from 2 adults → 1), remove extra fieldsets
            const existingFieldsets = container.querySelectorAll('.passenger-fieldset');
            existingFieldsets.forEach((fs, idx) => {
                if (idx >= counts[type]) {
                    fs.remove();
                    passengerData[type].splice(idx, 1);
                }
            });
        }

        toggleRequiredFields();
        savePassengerData();
    };

    const savePassengerData = () => {
        for (const type of ['adult', 'youth', 'child', 'infant']) {
            const count = parseInt(document.getElementById(`${type}s`)?.value) || 0;
            passengerData[type] = passengerData[type].slice(0, count);
            for (let i = 0; i < count; i++) {
                passengerData[type][i] = {
                    first_name: document.getElementById(`${type}_first_name_${i}`)?.value || '',
                    last_name: document.getElementById(`${type}_last_name_${i}`)?.value || '',
                    age: document.getElementById(`${type}_age_${i}`)?.value || '',
                    open: passengerData[type][i]?.open ?? true,
                    is_parent_guardian: document.getElementById(`${type}_is_parent_guardian_${i}`)?.checked || false,
                    is_group_leader: document.getElementById(`${type}_is_group_leader_${i}`)?.checked || false
                };
            }
        }
        saveFormData();
    };

    const toggleRequiredFields = () => {
        const hasMinors = (parseInt(childrenInput?.value) || 0) + (parseInt(infantsInput?.value) || 0) + (parseInt(youthsInput?.value) || 0) > 0;
        const hasParentGuardian = passengerData.adult.some(p => p.is_parent_guardian);
        const isUnaccompaniedMinor = unaccompaniedMinorCheckbox?.checked || false;

        responsibilityDeclarationFields.classList.toggle('hidden', !hasMinors || hasParentGuardian);
        unaccompaniedMinorFields.classList.toggle('hidden', !isUnaccompaniedMinor);

        const responsibilityInput = document.getElementById('responsibility_declaration');
        if (responsibilityInput) {
            responsibilityInput.required = hasMinors && !hasParentGuardian;
        }
        const consentInput = document.getElementById('consent_form');
        if (consentInput) {
            consentInput.required = isUnaccompaniedMinor;
        }
        const guardianContactInput = document.getElementById('guardian_contact');
        if (guardianContactInput) {
            guardianContactInput.required = isUnaccompaniedMinor;
        }
    };

    const calculateTotalPrice = () => {
        return 0; // Rely on backend /bookings/get_pricing/
    };

    const updateSummary = async () => {
        // --- Gather input values ---
        const scheduleId = scheduleInput?.value?.trim() || '';
        const adults = Math.max(parseInt(adultsInput?.value) || 0, 0);
        const youths = Math.max(parseInt(youthsInput?.value) || 0, 0);
        const children = Math.max(parseInt(childrenInput?.value) || 0, 0);
        const infants = Math.max(parseInt(infantsInput?.value) || 0, 0);

        const addCargo = cargoCheckbox?.checked || false;
        const cargoType = addCargo ? document.getElementById('cargo_type')?.value?.trim() || '' : '';
        const weightKg = addCargo ? Math.max(parseFloat(document.getElementById('weight_kg')?.value) || 0, 0) : 0;
        const dimensions = addCargo ? document.getElementById('dimensions_cm')?.value?.trim() || 'None' : 'None';

        const isEmergency = emergencyCheckbox?.checked || false;
        const unaccompaniedMinor = unaccompaniedMinorCheckbox?.checked || false;
        const isGroupBooking = groupBookingCheckbox?.checked || false;

        const extras = [];
        if (unaccompaniedMinor) extras.push('Unaccompanied Minor');
        if (isGroupBooking) extras.push('Group Booking');
        if (isEmergency) extras.push('Emergency Travel');

        // --- Log emergency status for debugging ---
        logger.log(`Emergency checkbox status: is_emergency=${isEmergency}`);

        // --- Validate required fields before sending ---
        if (!scheduleId) {
            console.warn("No schedule selected. Cannot fetch pricing.");
            document.getElementById('summary-schedule').textContent = 'Not selected';
            document.getElementById('summary-cost').textContent = '0.00';
            latestTotalPrice = '0.00';
            return;
        }

        if (addCargo && !cargoType) {
            console.warn("Cargo type is required when adding cargo.");
            document.getElementById('summary-cargo').textContent = 'Missing cargo type';
            document.getElementById('summary-cost').textContent = '0.00';
            latestTotalPrice = '0.00';
            return;
        }

        // --- Update summary UI ---
        document.getElementById('summary-schedule').textContent =
            document.querySelector(`#schedule_id option[value="${scheduleId}"]`)?.textContent || 'Not selected';

        document.getElementById('summary-passengers').textContent =
            `${adults} Adults, ${youths} Youths, ${children} Children, ${infants} Infants`;

        document.getElementById('summary-cargo').textContent = addCargo
            ? `${cargoType} (${weightKg}kg, ${dimensions}cm)`
            : 'None';

        document.getElementById('summary-extras').textContent = extras.length
            ? extras.join(', ')
            : 'None';

        // --- Prepare FormData for backend ---
        const formData = new FormData(bookingForm);
        formData.set('schedule_id', scheduleId);
        formData.set('adults', adults.toString());
        formData.set('youths', youths.toString());
        formData.set('children', children.toString());
        formData.set('infants', infants.toString());
        formData.set('add_cargo', addCargo ? 'true' : 'false');
        formData.set('cargo_type', cargoType);
        formData.set('weight_kg', weightKg.toString());
        formData.set('is_emergency', isEmergency ? 'true' : 'false');

        console.log("Sending get_pricing data:", Object.fromEntries(formData.entries()));

        // --- Send AJAX request ---
        try {
            const response = await fetch(window.urls.getPricing, {
                method: 'POST',
                body: formData,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                    'X-CSRFToken': getCsrfToken()
                }
            });
            if (!response.ok) {
                const text = await response.text();
                console.error(`Server returned ${response.status}:`, text);
                throw new Error(`Server returned ${response.status}`);
            }

            const data = await response.json();

            // --- Update pricing in summary and store total_price ---
            document.getElementById('summary-cost').textContent =
                data.total_price ? parseFloat(data.total_price).toFixed(2) : '0.00';
            latestTotalPrice = data.total_price || '0.00'; // Store total_price

        } catch (e) {
            console.error('Error fetching price:', e);
            document.getElementById('summary-cost').textContent = '0.00';
            latestTotalPrice = '0.00'; // Fallback
        }
    };

    const displayBackendErrors = (errors, button) => {
        const existingErrors = button.parentNode.querySelector('#validation-errors-next') || button.parentNode.querySelector('#validation-errors-payment');
        if (existingErrors) existingErrors.remove();

        if (!Array.isArray(errors)) {
            errors = [{ field: 'general', message: 'An unexpected error occurred. Please try again.' }];
        }
        const validationErrorsNext = document.createElement('div');
        validationErrorsNext.id = 'validation-errors-next';
        validationErrorsNext.className = 'alert error bg-red-50 p-4 rounded-lg shadow-sm animate__animated animate__fadeIn mt-4';
        validationErrorsNext.innerHTML = '<p class="font-semibold text-var-text-color font-poppins">Please fix the following errors:</p><ul id="validation-error-list-next" class="list-disc pl-5"></ul>';
        button.parentNode.appendChild(validationErrorsNext);

        errors.forEach(error => {
            const li = document.createElement('li');
            li.textContent = error.message;
            li.style.color = 'var(--alert-error-text)';
            document.getElementById('validation-error-list-next').appendChild(li);
            const errorElement = document.getElementById(`error-${error.field}`);
            if (errorElement) {
                errorElement.textContent = error.message;
                errorElement.classList.remove('hidden');
                const field = document.getElementById(error.field);
                if (field) {
                    field.classList.add('border', 'border-red-500');
                    setTimeout(() => field.classList.remove('border', 'border-red-500'), 3000);
                }
            }
        });
    };

    const validateStep = async (step, button) => {
        document.querySelectorAll('.error-message').forEach(e => {
            e.classList.add('hidden');
            e.textContent = '';
        });
        document.querySelectorAll('#validation-errors-next').forEach(e => e.remove());
        document.querySelectorAll('#validation-errors-payment').forEach(e => e.remove());

        const formData = new FormData(bookingForm);
        formData.append('step', step);
        formData.append('user_authenticated', window.isAuthenticated ? 'true' : 'false');

        if (step === 1) {
            const scheduleId = scheduleInput?.value || '';
            if (!scheduleId || isNaN(parseInt(scheduleId))) {
                const errorElement = document.getElementById('error-schedule_id');
                if (errorElement) {
                    errorElement.textContent = 'Please select a valid schedule.';
                    errorElement.classList.remove('hidden');
                }
                const validationErrorsNext = document.createElement('div');
                validationErrorsNext.id = 'validation-errors-next';
                validationErrorsNext.className = 'alert error bg-red-50 p-4 rounded-lg shadow-sm animate__animated animate__fadeIn mt-4';
                validationErrorsNext.innerHTML = '<p class="font-semibold text-var-text-color font-poppins">Please fix the following errors:</p><ul id="validation-error-list-next" class="list-disc pl-5"><li style="color: var(--alert-error-text);">Please select a valid schedule.</li></ul>';
                button.parentNode.appendChild(validationErrorsNext);
                return false;
            }
            formData.append('schedule_id', scheduleId);
            if (!window.isAuthenticated) {
                const guestEmail = document.getElementById('guest_email')?.value || '';
                if (!guestEmail) {
                    const errorElement = document.getElementById('error-guest_email');
                    if (errorElement) {
                        errorElement.textContent = 'Email is required for guest users.';
                        errorElement.classList.remove('hidden');
                    }
                    const validationErrorsNext = document.createElement('div');
                    validationErrorsNext.id = 'validation-errors-next';
                    validationErrorsNext.className = 'alert error bg-red-50 p-4 rounded-lg shadow-sm animate__animated animate__fadeIn mt-4';
                    validationErrorsNext.innerHTML = '<p class="font-semibold text-var-text-color font-poppins">Please fix the following errors:</p><ul id="validation-error-list-next" class="list-disc pl-5"><li style="color: var(--alert-error-text);">Email is required for guest users.</li></ul>';
                    button.parentNode.appendChild(validationErrorsNext);
                    return false;
                }
                formData.append('guest_email', guestEmail);
            }
        } else if (step === 2) {
            const counts = {
                adult: parseInt(adultsInput?.value) || 0,
                youth: parseInt(youthsInput?.value) || 0,
                child: parseInt(childrenInput?.value) || 0,
                infant: parseInt(infantsInput?.value) || 0
            };
            if (counts.adult + counts.youth + counts.child + counts.infant === 0) {
                const errorElement = document.getElementById('passenger-details-error');
                errorElement.textContent = 'At least one passenger is required.';
                errorElement.classList.remove('hidden');
                return false;
            }
            for (const type of ['adult', 'youth', 'child', 'infant']) {
                for (let i = 0; i < counts[type]; i++) {
                    formData.append(`${type}_first_name_${i}`, document.getElementById(`${type}_first_name_${i}`)?.value || '');
                    formData.append(`${type}_last_name_${i}`, document.getElementById(`${type}_last_name_${i}`)?.value || '');
                    formData.append(`${type}_age_${i}`, document.getElementById(`${type}_age_${i}`)?.value || '');
                    if (type === 'adult') {
                        formData.append(`${type}_is_parent_guardian_${i}`, document.getElementById(`${type}_is_parent_guardian_${i}`)?.checked ? 'on' : '');
                        formData.append(`${type}_is_group_leader_${i}`, document.getElementById(`${type}_is_group_leader_${i}`)?.checked ? 'on' : '');
                    }
                }
            }
            if ((counts.child + counts.infant + counts.youth > 0) && !passengerData.adult.some(p => p.is_parent_guardian)) {
                const savedFileId = localStorage.getItem('file-responsibility_declaration');
                if (savedFileId) {
                    formData.append('responsibility_declaration', savedFileId);
                }
            }
        } else if (step === 3) {
            if (cargoCheckbox?.checked) {
                formData.append('add_cargo', 'on');
                formData.append('cargo_type', document.getElementById('cargo_type')?.value || '');
                formData.append('weight_kg', document.getElementById('weight_kg')?.value || '');
                formData.append('dimensions_cm', document.getElementById('dimensions_cm')?.value || '');
            }
            if (unaccompaniedMinorCheckbox?.checked) {
                formData.append('is_unaccompanied_minor', 'on');
                formData.append('guardian_contact', document.getElementById('guardian_contact')?.value || '');
                const savedFileId = localStorage.getItem('file-consent_form');
                if (savedFileId) {
                    formData.append('consent_form', savedFileId);
                }
            }
            if (groupBookingCheckbox?.checked) formData.append('is_group_booking', 'on');
            if (emergencyCheckbox?.checked) formData.append('is_emergency', 'on');
        } else if (step === 4) {
            const privacyConsent = document.getElementById('privacy-consent');
            const errorElement = document.getElementById('error-privacy-consent');

            if (!privacyConsent) {
                console.error('Privacy consent checkbox not found in DOM');
                return false;
            }

            // Hide previous error if any
            if (errorElement) {
                errorElement.classList.add('hidden');
                errorElement.textContent = '';
            }

            // Validate
            if (!privacyConsent.checked) {
                if (errorElement) {
                    errorElement.textContent = 'You must agree to the Privacy Policy and Terms of Service.';
                    errorElement.classList.remove('hidden');
                }
                console.log('Privacy consent not checked');
                return false;
            }

            formData.append('privacy_consent', 'true');
            console.log('Privacy consent checked ✅');
        }

        logger.log('FormData for validation:', Object.fromEntries(formData.entries()));

        const fetchWithRetry = async (url, options, retries = 3) => {
            for (let i = 1; i <= retries; i++) {
                try {
                    const response = await fetch(url, options);
                    if (!response.ok) throw new Error(`HTTP error! Status: ${response.status}`);
                    return response;
                } catch (error) {
                    logger.error(`Fetch attempt ${i} failed:`, error);
                    if (i === retries) throw new Error('Network error: Unable to connect to the server. Please check your connection or try again later.');
                }
            }
        };

        try {
            const response = await fetchWithRetry('/bookings/validate-step/', {
                method: 'POST',
                body: formData,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                    'X-CSRFToken': getCsrfToken()
                }
            });
            const data = await response.json();
            if (data.success) {
                logger.log(`Backend validation passed for step: ${step}`);
                return true;
            } else {
                logger.log('Backend validation failed:', JSON.stringify(data.errors, null, 2));
                displayBackendErrors(data.errors, button);
                return false;
            }
        } catch (error) {
            logger.error('Validation error:', error);
            const validationErrorsNext = document.createElement('div');
            validationErrorsNext.id = 'validation-errors-next';
            validationErrorsNext.className = 'alert error bg-red-50 p-4 rounded-lg shadow-sm animate__animated animate__fadeIn mt-4';
            validationErrorsNext.innerHTML = `<p class="font-semibold text-var-text-color font-poppins">Please fix the following errors:</p><ul id="validation-error-list-next" class="list-disc pl-5"><li style="color: var(--alert-error-text);">${error.message}</li></ul>`;
            button.parentNode.appendChild(validationErrorsNext);
            return false;
        }
    };

    const handleFileUpload = async (input, previewContainer) => {
        const file = input.files[0];
        if (!file) return;
        if (!['application/pdf', 'image/jpeg', 'image/png'].includes(file.type)) {
            const errorElement = document.getElementById(`error-${input.id}`);
            errorElement.textContent = 'Only PDF, JPG, or PNG files are allowed.';
            errorElement.classList.remove('hidden');
            return;
        }
        if (file.size > 5 * 1024 * 1024) {
            const errorElement = document.getElementById(`error-${input.id}`);
            errorElement.textContent = 'File size must be less than 5MB.';
            errorElement.classList.remove('hidden');
            return;
        }
        const formData = new FormData();
        formData.append('file', file);
        try {
            const response = await fetch('/bookings/validate_file/', {
                method: 'POST',
                body: formData,
                headers: { 'X-CSRFToken': getCsrfToken() }
            });
            const data = await response.json();
            if (data.success && data.file_id) {
                localStorage.setItem(`file-${input.id}`, data.file_id);
                previewContainer.classList.remove('hidden');
                previewContainer.innerHTML = file.type === 'application/pdf'
                    ? `<span class="pdf-icon">PDF: ${file.name}</span>`
                    : `<img src="${URL.createObjectURL(file)}" alt="File preview" class="max-w-full max-h-24 object-contain rounded">`;
            } else {
                const errorElement = document.getElementById(`error-${input.id}`);
                errorElement.textContent = data.error || 'File upload failed.';
                errorElement.classList.remove('hidden');
            }
        } catch (e) {
            logger.error('File upload error:', e);
            const errorElement = document.getElementById(`error-${input.id}`);
            errorElement.textContent = 'File upload failed. Please try again.';
            errorElement.classList.remove('hidden');
        }
    };

    async function proceedToPayment() {
        if (typeof window.stripe === 'undefined') {
            logger.error('Stripe is not defined');
            displayBackendErrors([{ field: 'general', message: 'Payment processing is unavailable. Please try again later.' }], document.getElementById('proceed-to-payment'));
            return;
        }

        const button = document.getElementById('proceed-to-payment');
        button.querySelector('.spinner').classList.remove('hidden');
        button.disabled = true;

        // Prevent multiple submissions
        if (button.dataset.isSubmitting === 'true') {
            logger.warn('Submission already in progress, ignoring.');
            button.querySelector('.spinner').classList.add('hidden');
            button.disabled = false;
            return;
        }
        button.dataset.isSubmitting = 'true';

        // Prepare FormData
        const formData = new FormData(bookingForm);
        formData.append('privacy_consent', 'true');
        formData.append('total_price', latestTotalPrice);
        formData.append('is_emergency', emergencyCheckbox?.checked ? 'true' : 'false'); // Ensure is_emergency is included

        // Validate total_price
        if (!latestTotalPrice || parseFloat(latestTotalPrice) <= 0) {
            logger.error('Invalid or missing total_price');
            displayBackendErrors([{ field: 'general', 'message': 'Invalid total price. Please try again.' }], button);
            button.querySelector('.spinner').classList.add('hidden');
            button.disabled = false;
            button.dataset.isSubmitting = 'false';
            return;
        }

        // Add passenger details
        for (const type of ['adult', 'youth', 'child', 'infant']) {
            const count = parseInt(document.getElementById(`${type}s`)?.value || 0);
            for (let i = 0; i < count; i++) {
                formData.append(`${type}_first_name_${i}`, document.getElementById(`${type}_first_name_${i}`)?.value || '');
                formData.append(`${type}_last_name_${i}`, document.getElementById(`${type}_last_name_${i}`)?.value || '');
                formData.append(`${type}_age_${i}`, document.getElementById(`${type}_age_${i}`)?.value || '');
                if (type === 'adult' || type === 'youth') {
                    formData.append(`${type}_is_parent_guardian_${i}`, document.getElementById(`${type}_is_parent_guardian_${i}`)?.checked ? 'true' : 'false');
                    formData.append(`${type}_is_group_leader_${i}`, document.getElementById(`${type}_is_group_leader_${i}`)?.checked ? 'true' : 'false');
                }
                const documentInput = document.getElementById(`${type}_document_${i}`);
                if (documentInput?.files[0]) {
                    formData.append(`${type}_document_${i}`, documentInput.files[0]);
                }
            }
        }

        // Add guest_email for unauthenticated users
        if (!window.isAuthenticated) {
            const guestEmail = document.getElementById('guest_email')?.value || '';
            if (!guestEmail) {
                displayBackendErrors([{ field: 'guest_email', 'message': 'Email is required for guest users.' }], button);
                button.querySelector('.spinner').classList.add('hidden');
                button.disabled = false;
                button.dataset.isSubmitting = 'false';
                return;
            }
            formData.append('guest_email', guestEmail);
        }

        // Add cargo details if applicable
        if (formData.get('add_cargo') === 'true') {
            formData.append('cargo_type', document.getElementById('cargo_type')?.value || '');
            formData.append('weight_kg', document.getElementById('weight_kg')?.value || '0');
            formData.append('dimensions_cm', document.getElementById('dimensions_cm')?.value || '');
        }

        // Add file IDs for responsibility_declaration and consent_form
        ['responsibility_declaration', 'consent_form'].forEach(id => {
            const savedFileId = localStorage.getItem(`file-${id}`);
            if (savedFileId) {
                formData.append(id, savedFileId);
            }
        });

        // Log formData for debugging
        console.log('FormData for booking:', Object.fromEntries(formData.entries()));

        try {
            // Step 1: Create booking
            const bookingResponse = await fetch('/bookings/', {
                method: 'POST',
                body: formData,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                    'X-CSRFToken': getCsrfToken()
                }
            });

            const bookingData = await bookingResponse.json();
            if (!bookingResponse.ok || !bookingData.success) {
                logger.error('Booking creation failed:', bookingData.errors);
                displayBackendErrors(bookingData.errors || [{ field: 'general', 'message': 'Failed to create booking.' }], button);
                button.querySelector('.spinner').classList.add('hidden');
                button.disabled = false;
                button.dataset.isSubmitting = 'false';
                return;
            }

            console.log('Booking created:', bookingData.booking_id);

            // Step 2: Create checkout session
            console.log('FormData for checkout:', Object.fromEntries(formData.entries()));
            const checkoutResponse = await fetch('/bookings/create-checkout-session/', {
                method: 'POST',
                body: formData,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                    'X-CSRFToken': getCsrfToken()
                }
            });

            const checkoutData = await checkoutResponse.json();
            if (checkoutData.sessionId) {
                // Store sessionId in localStorage for debugging
                localStorage.setItem('last_stripe_session_id', checkoutData.sessionId);
                logger.log('Redirecting to Stripe with sessionId:', checkoutData.sessionId);
                await window.stripe.redirectToCheckout({ sessionId: checkoutData.sessionId });
            } else {
                logger.error('Checkout session creation failed:', checkoutData.errors);
                displayBackendErrors(checkoutData.errors || [{ field: 'general', 'message': 'Failed to create payment session.' }], button);
            }
        } catch (e) {
            logger.error('Payment error:', e);
            displayBackendErrors([{ field: 'general', 'message': 'Payment initiation failed. Please try again.' }], button);
        } finally {
            button.querySelector('.spinner').classList.add('hidden');
            button.disabled = false;
            button.dataset.isSubmitting = 'false';
        }
    }

    document.addEventListener('DOMContentLoaded', () => {
        loadFormData();
        updatePassengerFields();
        toggleRequiredFields();
        updateSummary();

        bookingForm.addEventListener('input', saveFormData);
        [adultsInput, youthsInput, childrenInput, infantsInput].forEach(input => {
            if (input) {
                input.addEventListener('change', () => {
                    updatePassengerFields();
                    toggleRequiredFields();
                    saveFormData();
                    updateSummary();
                });
            }
        });

        nextButtons.forEach(button => {
            button.addEventListener('click', async () => {
                button.querySelector('.spinner').classList.remove('hidden');
                button.disabled = true;
                const nextStep = parseInt(button.dataset.next);
                const valid = await validateStep(nextStep - 1, button);
                if (valid) {
                    updateStep(nextStep);
                    saveFormData();
                    updateSummary();
                }
                button.querySelector('.spinner').classList.add('hidden');
                button.disabled = false;
            });
        });

        prevButtons.forEach(button => {
            button.addEventListener('click', () => {
                const prevStep = parseInt(button.dataset.prev);
                updateStep(prevStep);
                saveFormData();
            });
        });

        cargoCheckbox?.addEventListener('change', () => {
            cargoFields.classList.toggle('hidden', !cargoCheckbox.checked);
            saveFormData();
            updateSummary();
        });

        unaccompaniedMinorCheckbox?.addEventListener('change', () => {
            unaccompaniedMinorFields.classList.toggle('hidden', !unaccompaniedMinorCheckbox.checked);
            toggleRequiredFields();
            saveFormData();
            updateSummary();
        });

        [groupBookingCheckbox, emergencyCheckbox].forEach(checkbox => {
            checkbox?.addEventListener('change', () => {
                saveFormData();
                updateSummary();
            });
        });

        passengerDetails?.addEventListener('click', (e) => {
            if (e.target.classList.contains('passenger-fieldset-header')) {
                const index = Array.from(e.target.parentNode.parentNode.children).indexOf(e.target.parentNode);
                const type = e.target.closest('.passenger-fieldset').parentNode.id.replace('-fields', '');
                const content = e.target.nextElementSibling;
                const isOpen = content.classList.toggle('open');
                e.target.querySelector('.toggle-icon').textContent = isOpen ? '−' : '+';
                passengerData[type][index].open = isOpen;
                savePassengerData();
            }
        });

        document.getElementById('proceed-to-payment')?.addEventListener('click', async () => {
            const valid = await validateStep(4, document.getElementById('proceed-to-payment'));
            if (valid) {
                await proceedToPayment();
            }
        });

        [document.getElementById('responsibility_declaration'), document.getElementById('consent_form')].forEach(input => {
            if (input) {
                input.addEventListener('change', () => handleFileUpload(input, input.nextElementSibling));
            }
        });

        AOS.init();
    });
})();