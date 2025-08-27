document.addEventListener('DOMContentLoaded', () => {
    let passengerData = { adult: [], child: [], infant: [] };
    let currentStep = parseInt(JSON.parse(document.getElementById('form-data')?.textContent || '{}').step || 1, 10);
    const form = document.getElementById('booking-form');
    const nextButtons = document.querySelectorAll('.next-step');
    const prevButtons = document.querySelectorAll('.prev-step');

    showStep(currentStep);
    updateProgressBar(currentStep);
    generatePassengerFields();
    setupFilePreview();
    updateSummary();

    // Event listeners for step navigation
    nextButtons.forEach(button => {
        button.addEventListener('click', async () => {
            console.log('Next button clicked for step:', currentStep);
            button.disabled = true;
            button.textContent = 'Validating...';
            await savePassengerData();
            const isValid = await validateStep(currentStep);
            if (isValid) {
                console.log('Proceeding to step:', button.dataset.next);
                currentStep = parseInt(button.dataset.next, 10);
                showStep(currentStep);
                updateProgressBar(currentStep);
                updateSummary();
            } else {
                console.log('Validation failed, staying on step:', currentStep);
            }
            button.disabled = false;
            button.textContent = 'Next';
        });
    });

    prevButtons.forEach(button => {
        button.addEventListener('click', () => {
            currentStep = parseInt(button.dataset.prev, 10);
            showStep(currentStep);
            updateProgressBar(currentStep);
            updateSummary();
        });
    });

    // Form submission
    form.addEventListener('submit', async e => {
        e.preventDefault();
        const submitButton = document.getElementById('submit-button');
        submitButton.disabled = true;
        submitButton.textContent = 'Processing...';
        await savePassengerData();
        const formData = new FormData(form);
        Object.entries(passengerData).forEach(([type, passengers]) => {
            passengers.forEach((p, i) => {
                formData.append(`passenger_${type}_${i}_first_name`, p.firstName || '');
                formData.append(`passenger_${type}_${i}_last_name`, p.lastName || '');
                formData.append(`passenger_${type}_${i}_age`, p.age || '');
                if (p.isGroupLeader) formData.append(`passenger_${type}_${i}_is_group_leader`, 'on');
                if (p.isParent) formData.append(`passenger_${type}_${i}_is_parent`, 'on');
                if (p.document) formData.append(`passenger_${type}_${i}_document`, p.document);
            });
        });
        try {
            const response = await fetch(form.action, {
                method: 'POST',
                body: formData,
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            });
            const data = await response.json();
            if (data.success) {
                window.location.href = data.redirect_url;
            } else {
                showError(data.error || 'An error occurred.', data.step || 1);
                currentStep = data.step || 1;
                showStep(currentStep);
                updateProgressBar(currentStep);
            }
        } catch (error) {
            console.error('Submission error:', error);
            showError('Failed to submit form. Please try again.', currentStep);
        }
        submitButton.disabled = false;
        submitButton.textContent = 'Proceed to Payment';
    });

    // Validate step by sending data to backend
    async function validateStep(step) {
        const formData = new FormData(form);
        formData.append('step', step);
        Object.entries(passengerData).forEach(([type, passengers]) => {
            passengers.forEach((p, i) => {
                formData.append(`passenger_${type}_${i}_first_name`, p.firstName || '');
                formData.append(`passenger_${type}_${i}_last_name`, p.lastName || '');
                formData.append(`passenger_${type}_${i}_age`, p.age || '');
                if (p.isGroupLeader) formData.append(`passenger_${type}_${i}_is_group_leader`, 'on');
                if (p.isParent) formData.append(`passenger_${type}_${i}_is_parent`, 'on');
                if (p.document) formData.append(`passenger_${type}_${i}_document`, p.document);
            });
        });

        try {
            const response = await fetch('/validate-step/', {
                method: 'POST',
                body: formData,
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            });
            const data = await response.json();
            if (data.success) {
                console.log('Backend validation passed for step:', step);
                return true;
            } else {
                console.log('Backend validation failed:', data.errors);
                showValidationErrors(data.errors);
                return false;
            }
        } catch (error) {
            console.error('Validation error:', error);
            showValidationErrors(['Failed to validate. Please try again.']);
            return false;
        }
    }

    // Show validation errors
    function showValidationErrors(errors) {
        const errorContainer = document.getElementById('validation-errors');
        const errorList = document.getElementById('validation-error-list');
        const nextButton = document.querySelector(`.next-step[data-next="${currentStep + 1}"]`) || document.getElementById('submit-button');

        if (!errorContainer || !errorList || !nextButton) {
            console.error('Missing DOM elements:', { errorContainer, errorList, nextButton });
            return false;
        }

        if (errors.length) {
            errorContainer.classList.remove('hidden');
            errorList.innerHTML = errors.map(e => `<li>${e}</li>`).join('');
            nextButton.disabled = true;
            return false;
        }

        errorContainer.classList.add('hidden');
        errorList.innerHTML = '';
        nextButton.disabled = false;
        nextButton.removeAttribute('disabled');
        console.log('Validation passed, enabling Next button');
        return true;
    }

    // Show error message
    function showError(message, step) {
        const errorContainer = document.getElementById('validation-errors');
        const errorList = document.getElementById('validation-error-list');
        errorContainer.classList.remove('hidden');
        errorList.innerHTML = `<li>${message}</li>`;
    }

    // Save passenger data
    async function savePassengerData() {
        passengerData = { adult: [], child: [], infant: [] };
        const adults = parseInt(document.getElementById('adults')?.value || 0, 10);
        const children = parseInt(document.getElementById('children')?.value || 0, 10);
        const infants = parseInt(document.getElementById('infants')?.value || 0, 10);

        ['adult', 'child', 'infant'].forEach(type => {
            const count = type === 'adult' ? adults : type === 'child' ? children : infants;
            for (let i = 0; i < count; i++) {
                const passenger = {};
                const firstName = document.getElementById(`passenger_${type}_${i}_first_name`)?.value;
                const lastName = document.getElementById(`passenger_${type}_${i}_last_name`)?.value;
                const age = document.getElementById(`passenger_${type}_${i}_age`)?.value;
                const isGroupLeader = document.getElementById(`passenger_${type}_${i}_is_group_leader`)?.checked;
                const isParent = document.getElementById(`passenger_${type}_${i}_is_parent`)?.checked;
                const documentInput = document.getElementById(`passenger_${type}_${i}_document`);
                const document = documentInput?.files?.[0];

                if (firstName) passenger.firstName = firstName;
                if (lastName) passenger.lastName = lastName;
                if (age) passenger.age = age;
                if (isGroupLeader) passenger.isGroupLeader = true;
                if (isParent) passenger.isParent = true;
                if (document) passenger.document = document;

                console.log(`Updated ${type} ${i + 1}:`, passenger);
                passengerData[type].push(passenger);
            }
        });

        console.log('Saved passenger data:', passengerData);
    }

    // Generate passenger fields
    function generatePassengerFields() {
        const adults = parseInt(document.getElementById('adults')?.value || 0, 10);
        const children = parseInt(document.getElementById('children')?.value || 0, 10);
        const infants = parseInt(document.getElementById('infants')?.value || 0, 10);

        ['adult', 'child', 'infant'].forEach(type => {
            const container = document.getElementById(`${type}-fields`);
            if (!container) return;
            container.innerHTML = '';
            const count = type === 'adult' ? adults : type === 'child' ? children : infants;
            for (let i = 0; i < count; i++) {
                container.appendChild(createFieldset(type, i));
            }
        });

        document.getElementById('passenger-details').classList.toggle('hidden', !(adults + children + infants));
        toggleResponsibilityDeclaration(adults, children, infants);
        updateEmergencyWarning();
    }

    // Create passenger fieldset
    function createFieldset(type, index) {
        const fieldset = document.createElement('div');
        fieldset.className = 'passenger-fieldset';
        const header = document.createElement('div');
        header.className = 'passenger-fieldset-header';
        header.innerHTML = `
            <h4>${type.charAt(0).toUpperCase() + type.slice(1)} ${index + 1}</h4>
            <span class="toggle-icon">${fieldset.classList.contains('open') ? '−' : '+'}</span>
        `;
        const content = document.createElement('div');
        content.className = `passenger-fieldset-content ${passengerData[type][index]?.open ? 'open' : ''}`;
        content.innerHTML = `
            <div class="relative">
                <label for="passenger_${type}_${index}_first_name" class="block text-sm font-medium text-gray-900 dark:text-gray-300 font-roboto">First Name:</label>
                <input type="text" id="passenger_${type}_${index}_first_name" name="passenger_${type}_${index}_first_name" value="${passengerData[type][index]?.firstName || ''}" class="mt-1 w-full p-3 border rounded-lg bg-input-bg dark:bg-gray-700 text-gray-900 dark:text-gray-200 border-border-color dark:border-gray-600 focus:outline-none focus:ring-2 focus:ring-button-bg dark:focus:ring-blue-400" required aria-describedby="error-passenger_${type}_${index}_first_name">
                <p id="error-passenger_${type}_${index}_first_name" class="error-message text-red-600 dark:text-red-400 text-sm hidden mt-1"></p>
            </div>
            <div class="relative">
                <label for="passenger_${type}_${index}_last_name" class="block text-sm font-medium text-gray-900 dark:text-gray-300 font-roboto">Last Name:</label>
                <input type="text" id="passenger_${type}_${index}_last_name" name="passenger_${type}_${index}_last_name" value="${passengerData[type][index]?.lastName || ''}" class="mt-1 w-full p-3 border rounded-lg bg-input-bg dark:bg-gray-700 text-gray-900 dark:text-gray-200 border-border-color dark:border-gray-600 focus:outline-none focus:ring-2 focus:ring-button-bg dark:focus:ring-blue-400" required aria-describedby="error-passenger_${type}_${index}_last_name">
                <p id="error-passenger_${type}_${index}_last_name" class="error-message text-red-600 dark:text-red-400 text-sm hidden mt-1"></p>
            </div>
            <div class="relative">
                <label for="passenger_${type}_${index}_age" class="block text-sm font-medium text-gray-900 dark:text-gray-300 font-roboto">Age:</label>
                <input type="number" id="passenger_${type}_${index}_age" name="passenger_${type}_${index}_age" min="${type === 'infant' ? 0 : type === 'child' ? 2 : 12}" max="${type === 'infant' ? 1 : type === 'child' ? 11 : 150}" value="${passengerData[type][index]?.age || ''}" class="mt-1 w-full p-3 border rounded-lg bg-input-bg dark:bg-gray-700 text-gray-900 dark:text-gray-200 border-border-color dark:border-gray-600 focus:outline-none focus:ring-2 focus:ring-button-bg dark:focus:ring-blue-400" required aria-describedby="error-passenger_${type}_${index}_age">
                <p id="error-passenger_${type}_${index}_age" class="error-message text-red-600 dark:text-red-400 text-sm hidden mt-1"></p>
            </div>
            ${type === 'adult' ? `
                <div class="relative">
                    <label class="flex items-center">
                        <input type="checkbox" id="passenger_${type}_${index}_is_group_leader" name="passenger_${type}_${index}_is_group_leader" ${passengerData[type][index]?.isGroupLeader ? 'checked' : ''} class="mr-2 h-5 w-5 text-blue-600 dark:text-blue-400 focus:ring-button-bg dark:focus:ring-blue-400 border-border-color dark:border-gray-600">
                        <span class="text-sm font-medium text-gray-900 dark:text-gray-300 font-roboto">Group Leader</span>
                    </label>
                </div>
                <div class="relative">
                    <label class="flex items-center">
                        <input type="checkbox" id="passenger_${type}_${index}_is_parent" name="passenger_${type}_${index}_is_parent" ${passengerData[type][index]?.isParent ? 'checked' : ''} class="mr-2 h-5 w-5 text-blue-600 dark:text-blue-400 focus:ring-button-bg dark:focus:ring-blue-400 border-border-color dark:border-gray-600">
                        <span class="text-sm font-medium text-gray-900 dark:text-gray-300 font-roboto">Parent/Guardian</span>
                    </label>
                </div>
            ` : ''}
            <div class="relative">
                <label for="passenger_${type}_${index}_document" class="block text-sm font-medium text-gray-900 dark:text-gray-300 font-roboto">Document (Optional):</label>
                <input type="file" id="passenger_${type}_${index}_document" name="passenger_${type}_${index}_document" accept=".pdf,.jpg,.jpeg,.png" class="mt-1 w-full p-3 border rounded-lg bg-input-bg dark:bg-gray-700 text-gray-900 dark:text-gray-200 border-border-color dark:border-gray-600 focus:outline-none focus:ring-2 focus:ring-button-bg dark:focus:ring-blue-400">
                <div class="file-preview mt-2 hidden"></div>
                ${type === 'adult' ? `<p class="mt-1 text-sm text-yellow-600 dark:text-yellow-400 font-roboto">No document will mark this as an emergency booking (+FJD 50).</p>` : ''}
                <p id="error-passenger_${type}_${index}_document" class="error-message text-red-600 dark:text-red-400 text-sm hidden mt-1"></p>
            </div>
        `;
        fieldset.appendChild(header);
        fieldset.appendChild(content);
        header.addEventListener('click', () => {
            content.classList.toggle('open');
            header.querySelector('.toggle-icon').textContent = content.classList.contains('open') ? '−' : '+';
        });
        return fieldset;
    }

    // Toggle responsibility declaration
    function toggleResponsibilityDeclaration(adults, children, infants) {
        const hasMinors = children > 0 || infants > 0;
        const declarationFields = document.getElementById('responsibility-declaration-fields');
        if (!declarationFields) return;
        const needsDeclaration = hasMinors && adults > 0 && !passengerData.adult.some(p => p.isParent);
        declarationFields.classList.toggle('hidden', !needsDeclaration);
        updateEmergencyWarning();
    }

    // Update emergency warning
    function updateEmergencyWarning() {
        const adults = parseInt(document.getElementById('adults')?.value || 0, 10);
        const isEmergencyCheckbox = document.getElementById('is_emergency');
        const needsEmergency = passengerData.adult.some(p => !p.document);
        if (needsEmergency && isEmergencyCheckbox) {
            isEmergencyCheckbox.checked = true;
            isEmergencyCheckbox.disabled = true;
            const warning = document.createElement('p');
            warning.className = 'text-yellow-600 dark:text-yellow-400 text-sm mt-2 font-roboto';
            warning.id = 'emergency-warning';
            warning.textContent = 'Emergency booking (+FJD 50) required due to missing adult documents.';
            const existingWarning = document.querySelector('#emergency-warning');
            if (!existingWarning) {
                isEmergencyCheckbox.parentElement.appendChild(warning);
            }
        } else if (isEmergencyCheckbox) {
            isEmergencyCheckbox.disabled = false;
            const existingWarning = document.querySelector('#emergency-warning');
            if (existingWarning) existingWarning.remove();
        }
    }

    // Show form step
    function showStep(step) {
        const steps = document.querySelectorAll('.form-step');
        const indicators = document.querySelectorAll('.step');

        steps.forEach(s => s.classList.add('hidden'));
        indicators.forEach(s => s.classList.remove('active'));

        if (steps[step - 1]) {
            steps[step - 1].classList.remove('hidden');
        }
        if (indicators[step - 1]) {
            indicators[step - 1].classList.add('active');
        }
    }

    // Update progress bar
    function updateProgressBar(step) {
        const progressFill = document.querySelector('.progress-bar-fill');
        if (progressFill) {
            progressFill.style.width = `${step * 25}%`;
        }
    }

    // Clear errors
    function clearErrors() {
        document.querySelectorAll('.error-message').forEach(e => {
            e.textContent = '';
            e.classList.add('hidden');
        });
        document.querySelectorAll('[aria-invalid="true"]').forEach(input => {
            input.removeAttribute('aria-invalid');
        });
    }

    // Setup file preview
    function setupFilePreview() {
        document.querySelectorAll('input[type="file"]').forEach(input => {
            input.addEventListener('change', () => {
                const file = input.files[0];
                if (!file) return;
                console.log(`File selected for ${input.id}: ${file.name}`);
                const preview = input.nextElementSibling;
                if (!preview || !preview.classList.contains('file-preview')) return;
                preview.innerHTML = '';
                preview.classList.remove('hidden');
                if (file.type.startsWith('image/')) {
                    const img = document.createElement('img');
                    img.src = URL.createObjectURL(file);
                    preview.appendChild(img);
                } else if (file.type === 'application/pdf') {
                    const div = document.createElement('div');
                    div.className = 'pdf-icon';
                    div.textContent = 'PDF';
                    preview.appendChild(div);
                }
                updateEmergencyWarning();
            });
        });
    }

    // Update summary
    function updateSummary() {
        const adults = parseInt(document.getElementById('adults')?.value || 0, 10);
        const children = parseInt(document.getElementById('children')?.value || 0, 10);
        const infants = parseInt(document.getElementById('infants')?.value || 0, 10);
        const scheduleId = document.getElementById('schedule_id')?.value;
        const isUnaccompaniedMinor = document.getElementById('is_unaccompanied_minor')?.checked;
        const addCargo = document.getElementById('add_cargo_checkbox')?.checked;
        const isGroupBooking = document.getElementById('is_group_booking')?.checked;
        const isEmergency = document.getElementById('is_emergency')?.checked;

        const scheduleOption = document.querySelector(`#schedule_id option[value="${scheduleId}"]`);
        document.getElementById('summary-schedule').textContent = scheduleOption?.text || 'Not selected';
        document.getElementById('summary-passengers').textContent = `${adults} Adult${adults !== 1 ? 's' : ''}, ${children} Child${children !== 1 ? 'ren' : ''}, ${infants} Infant${infants !== 1 ? 's' : ''}`;
        document.getElementById('summary-cargo').textContent = addCargo ? (document.getElementById('cargo_type')?.value || 'None') : 'None';
        document.getElementById('summary-extras').textContent = [
            isUnaccompaniedMinor ? 'Unaccompanied Minor' : '',
            isGroupBooking ? 'Group Booking' : '',
            isEmergency ? 'Emergency Travel' : ''
        ].filter(Boolean).join(', ') || 'None';

        let total = 0;
        if (scheduleOption) {
            const fareMatch = scheduleOption.text.match(/FJD (\d+\.\d{2})/);
            total += parseFloat(fareMatch ? fareMatch[1] : 0) * (adults + children + infants);
        }
        if (isEmergency) total += 50;
        document.getElementById('summary-total').textContent = total.toFixed(2);
    }

    // Input change listeners
    ['adults', 'children', 'infants', 'schedule_id', 'guest_email', 'is_unaccompanied_minor', 'add_cargo_checkbox', 'is_group_booking', 'is_emergency'].forEach(id => {
        const input = document.getElementById(id);
        if (input) {
            input.addEventListener('change', async () => {
                console.log(`Input ${id} changed to:`, input.value);
                updateSummary();
                await validateStep(currentStep);
            });
        }
    });

    document.getElementById('passenger-details')?.addEventListener('change', async () => {
        await savePassengerData();
        updateEmergencyWarning();
        updateSummary();
        await validateStep(currentStep);
    });
});