document.addEventListener('DOMContentLoaded', function () {
    const bookingForm = document.getElementById('booking-form');
    const isDebug = true; // Enable for debugging

    // Exit if no booking form
    if (!bookingForm) {
        if (isDebug) console.log('Booking form not found, skipping initialization');
        return;
    }

    // Disable browser native validation
    bookingForm.setAttribute('novalidate', '');

    const submitButton = document.getElementById('submit-button');
    const steps = document.querySelectorAll('.form-step');
    const stepIndicators = document.querySelectorAll('.step');
    const adultsInput = document.getElementById('adults');
    const childrenInput = document.getElementById('children');
    const infantsInput = document.getElementById('infants');
    const scheduleSelect = document.getElementById('schedule_id');
    const cargoCheckbox = document.getElementById('add_cargo_checkbox');
    const cargoTypeSelect = document.getElementById('cargo_type');
    const weightInput = document.getElementById('weight_kg');
    const dimensionsInput = document.getElementById('dimensions_cm');
    const emergencyCheckbox = document.getElementById('is_emergency');
    const unaccompaniedMinorCheckbox = document.getElementById('is_unaccompanied_minor');
    const unaccompaniedMinorFields = document.getElementById('unaccompanied-minor-fields');
    const cargoFields = document.getElementById('cargo-fields');
    const groupBookingCheckbox = document.getElementById('is_group_booking');
    const summarySchedule = document.getElementById('summary-schedule');
    const summaryPassengers = document.getElementById('summary-passengers');
    const summaryCargo = document.getElementById('summary-cargo');
    const summaryExtras = document.getElementById('summary-extras');
    const summaryTotal = document.getElementById('summary-total');
    const passengerDetails = document.getElementById('passenger-details');
    const adultFields = document.getElementById('adult-fields');
    const childFields = document.getElementById('child-fields');
    const infantFields = document.getElementById('infant-fields');
    const validationErrors = document.getElementById('validation-errors');
    const validationErrorList = document.getElementById('validation-error-list');
    const responsibilityDeclarationInput = document.getElementById('responsibility_declaration');
    const responsibilityDeclarationFields = document.getElementById('responsibility-declaration-fields');

    // Check for required elements
    if (!adultsInput || !childrenInput || !infantsInput || !passengerDetails) {
        console.error('Required form elements are missing:', {
            adultsInput: !!adultsInput,
            childrenInput: !!childrenInput,
            infantsInput: !!infantsInput,
            passengerDetails: !!passengerDetails
        });
        return;
    }

    let currentStep = 1;
    let passengerData = { adult: [], child: [], infant: [] };

    // Safely parse form_data with fallback
    let formDataElement = document.getElementById('form_data');
    window.form_data = { step: 1, hasParent: false };
    if (formDataElement && formDataElement.textContent) {
        try {
            window.form_data = JSON.parse(formDataElement.textContent);
            if (isDebug) console.log('Parsed form_data:', window.form_data);
        } catch (error) {
            if (isDebug) console.error('Error parsing form_data:', error);
            window.form_data = { step: 1, hasParent: false };
        }
    } else {
        if (isDebug) console.warn('form_data element not found or empty');
    }
    currentStep = parseInt(window.form_data.step || 1);

    function showError(field, message) {
        if (!field) return;
        const errorElement = field.parentElement.querySelector('.error-message');
        if (errorElement) {
            errorElement.textContent = message;
            errorElement.classList.remove('hidden');
            const fieldset = field.closest('.passenger-fieldset');
            if (fieldset) {
                fieldset.style.border = '2px solid #ef4444';
                fieldset.scrollIntoView({ behavior: 'smooth', block: 'center' });
                setTimeout(() => {
                    fieldset.style.border = '';
                }, 2000);
            }
        }
    }

    function clearErrors() {
        document.querySelectorAll('.error-message').forEach(el => {
            el.textContent = '';
            el.classList.add('hidden');
        });
        document.querySelectorAll('.passenger-fieldset').forEach(fieldset => {
            fieldset.style.border = '';
        });
        validationErrors.classList.add('hidden');
        validationErrorList.innerHTML = '';
    }

    function showValidationErrors(errors) {
        validationErrorList.innerHTML = errors.map(err => `<li>${err}</li>`).join('');
        validationErrors.classList.remove('hidden');
    }

    function updateStep(step) {
        steps.forEach(s => s.classList.add('hidden'));
        steps[step - 1].classList.remove('hidden');
        stepIndicators.forEach(ind => ind.classList.remove('active', 'completed'));
        stepIndicators[step - 1].classList.add('active');
        for (let i = 0; i < step - 1; i++) {
            stepIndicators[i].classList.add('completed');
        }
        currentStep = step;
        clearErrors();
        generatePassengerFields();
    }

    function savePassengerData() {
        const newPassengerData = { adult: [], child: [], infant: [] };
        ['adult', 'child', 'infant'].forEach(type => {
            const fields = document.getElementById(`${type}-fields`).querySelectorAll('.passenger-fieldset');
            newPassengerData[type] = Array.from(fields).map((fieldset, index) => {
                const firstNameInput = fieldset.querySelector(`#passenger_${type}_${index}_first_name`);
                const lastNameInput = fieldset.querySelector(`#passenger_${type}_${index}_last_name`);
                const ageInput = fieldset.querySelector(`#passenger_${type}_${index}_age`);
                const isGroupLeaderInput = type === 'adult' ? fieldset.querySelector(`#passenger_${type}_${index}_is_group_leader`) : null;
                const documentInput = fieldset.querySelector(`#passenger_${type}_${index}_document`);
                const existingDocument = passengerData[type][index]?.document || null;
                const currentDocument = documentInput?.files[0] || existingDocument;

                if (isDebug && documentInput && !currentDocument) {
                    console.warn(`No document uploaded for ${type} passenger ${index + 1}`);
                } else if (currentDocument) {
                    console.log(`Document retained for ${type} passenger ${index + 1}: ${currentDocument.name}`);
                }

                return {
                    firstName: firstNameInput?.value.trim() || '',
                    lastName: lastNameInput?.value.trim() || '',
                    age: ageInput?.value || '',
                    isGroupLeader: isGroupLeaderInput?.checked || false,
                    document: currentDocument
                };
            });
        });
        passengerData = newPassengerData;
        if (isDebug) console.log('Saved passenger data:', passengerData);
    }

    function validateStep(step) {
        if (typeof document === 'undefined') {
            console.error('Document is not available');
            return false;
        }
        if (!adultsInput || !childrenInput || !infantsInput || !passengerDetails) {
            console.error('Required form elements are missing:', {
                adultsInput: !!adultsInput,
                childrenInput: !!childrenInput,
                infantsInput: !!infantsInput,
                passengerDetails: !!passengerDetails
            });
            return false;
        }
        clearErrors();
        const errors = [];

        if (step === 1) {
            const email = document.getElementById('guest_email');
            if (isDebug) {
                console.log('Validating Step 1', { schedule: scheduleSelect.value, email: email?.value });
            }
            if (!scheduleSelect.value) {
                showError(scheduleSelect, 'Please select a schedule.');
                errors.push('Please select a schedule.');
            }
            if (email && !email.value.trim()) {
                showError(email, 'Please provide a guest email.');
                errors.push('Please provide a guest email.');
            } else if (email && !email.value.match(/^[^@]+@[^@]+\.[^@]+$/)) {
                showError(email, 'Please provide a valid guest email.');
                errors.push('Please provide a valid guest email.');
            }
        } else if (step === 2) {
            const adults = parseInt(adultsInput.value) || 0;
            const children = parseInt(childrenInput.value) || 0;
            const infants = parseInt(infantsInput.value) || 0;
            const totalPassengers = adults + children + infants;
            const hasMinors = children > 0 || infants > 0;
            const hasParent = passengerData.adult.some(p => parseInt(p.age) >= 18);

            if (isDebug) console.log(`Validating Step 2: adults=${adults}, children=${children}, infants=${infants}`);

            if (totalPassengers === 0) {
                showError(adultsInput, 'Please select at least one passenger.');
                errors.push('Please select at least one passenger.');
                if (isDebug) console.log('Error: No passengers selected');
            }

            ['adult', 'child', 'infant'].forEach(type => {
                const count = type === 'adult' ? adults : type === 'child' ? children : infants;
                for (let i = 0; i < count; i++) {
                    const fieldset = document.getElementById(`${type}-fields`).querySelectorAll('.passenger-fieldset')[i];
                    const content = fieldset?.querySelector('.passenger-fieldset-content');
                    const firstName = document.getElementById(`passenger_${type}_${i}_first_name`);
                    const lastName = document.getElementById(`passenger_${type}_${i}_last_name`);
                    const age = document.getElementById(`passenger_${type}_${i}_age`);
                    const documentInput = document.getElementById(`passenger_${type}_${i}_document`);

                    if (content && !content.classList.contains('open')) {
                        content.classList.add('open');
                        fieldset.querySelector('.toggle-icon').textContent = '−';
                        const inputs = content.querySelectorAll('input');
                        inputs.forEach(input => {
                            if (input.name.includes('first_name') || input.name.includes('last_name') || input.name.includes('age')) {
                                input.required = true;
                            }
                        });
                        if (isDebug) console.log(`Auto-expanded fieldset for ${type} ${i + 1}`);
                    }

                    if (!firstName || !lastName || !age) {
                        errors.push(`${type.charAt(0).toUpperCase() + type.slice(1)} ${i + 1}: Required fields are missing.`);
                        if (isDebug) console.error(`Missing elements for ${type} ${i + 1}`);
                        continue;
                    }

                    if (!firstName.value.trim()) {
                        showError(firstName, 'First name is required.');
                        errors.push(`${type.charAt(0).toUpperCase() + type.slice(1)} ${i + 1}: First name is required.`);
                    }
                    if (!lastName.value.trim()) {
                        showError(lastName, 'Last name is required.');
                        errors.push(`${type.charAt(0).toUpperCase() + type.slice(1)} ${i + 1}: Last name is required.`);
                    }
                    if (!age.value || isNaN(age.value) || parseInt(age.value) < (type === 'adult' ? 12 : type === 'child' ? 2 : 0) || parseInt(age.value) > (type === 'adult' ? 150 : type === 'child' ? 11 : 1)) {
                        showError(age, `Age must be ${type === 'adult' ? '12 or older' : type === 'child' ? '2-11' : '0-1'}.`);
                        errors.push(`${type.charAt(0).toUpperCase() + type.slice(1)} ${i + 1}: Age must be ${type === 'adult' ? '12 or older' : type === 'child' ? '2-11' : '0-1'}.`);
                    }
                    if (type !== 'adult' && documentInput && !documentInput.files.length && !emergencyCheckbox.checked) {
                        showError(documentInput, 'Document is required.');
                        errors.push(`${type.charAt(0).toUpperCase() + type.slice(1)} ${i + 1}: Document is required.`);
                    }
                }
            });

            if (hasMinors && !hasParent && !responsibilityDeclarationInput.files.length) {
                showError(responsibilityDeclarationInput, 'Responsibility declaration is required for non-parent adults traveling with minors.');
                errors.push('Responsibility declaration is required for non-parent adults traveling with minors.');
            }
        } else if (step === 3) {
            if (cargoCheckbox.checked) {
                if (!cargoTypeSelect.value) {
                    showError(cargoTypeSelect, 'Cargo type is required.');
                    errors.push('Cargo type is required.');
                }
                if (!weightInput.value || weightInput.value <= 0) {
                    showError(weightInput, 'Weight must be greater than 0.');
                    errors.push('Cargo weight must be greater than 0.');
                }
                if (dimensionsInput.value && !/^\d+\s*x\s*\d+\s*x\s*\d+$/.test(dimensionsInput.value)) {
                    showError(dimensionsInput, 'Dimensions must be in the format "length x width x height".');
                    errors.push('Cargo dimensions must be in the format "length x width x height".');
                }
            }
            if (unaccompaniedMinorCheckbox.checked) {
                const guardianContact = document.getElementById('guardian_contact');
                const consentForm = document.getElementById('consent_form');
                if (!guardianContact.value.trim()) {
                    showError(guardianContact, 'Guardian contact is required.');
                    errors.push('Guardian contact is required for unaccompanied minors.');
                }
                if (!consentForm.files.length) {
                    showError(consentForm, 'Consent form is required.');
                    errors.push('Consent form is required for unaccompanied minors.');
                }
            }
        } else if (step === 4) {
            const privacyConsent = document.getElementById('privacy-consent');
            if (!privacyConsent.checked) {
                showError(privacyConsent, 'You must agree to the privacy policy.');
                errors.push('You must agree to the privacy policy.');
            }
        }

        if (errors.length > 0) {
            showValidationErrors(errors);
            if (isDebug) console.log('Validation errors:', errors);
            return false;
        }
        return true;
    }

    function validatePassengers() {
        const adults = parseInt(adultsInput.value) || 0;
        const children = parseInt(childrenInput.value) || 0;
        const infants = parseInt(infantsInput.value) || 0;
        const totalPassengers = adults + children + infants;
        submitButton.disabled = totalPassengers === 0;
        return totalPassengers > 0;
    }

    function setupFilePreview(input) {
        input.addEventListener('change', () => {
            const preview = input.parentElement.querySelector('.file-preview');
            preview.innerHTML = '';
            preview.classList.add('hidden');
            if (input.files.length > 0) {
                const file = input.files[0];
                if (isDebug) console.log(`File selected for ${input.id}: ${file.name}`);
                if (file.type.startsWith('image/')) {
                    const img = document.createElement('img');
                    img.src = URL.createObjectURL(file);
                    preview.appendChild(img);
                    preview.classList.remove('hidden');
                } else if (file.type === 'application/pdf') {
                    const pdfIcon = document.createElement('div');
                    pdfIcon.className = 'pdf-icon';
                    preview.appendChild(pdfIcon);
                    preview.classList.remove('hidden');
                }
                savePassengerData();
            }
        });
    }

    function generatePassengerFields() {
        if (typeof document === 'undefined') {
            console.error('Document is not available, skipping passenger field generation');
            return;
        }

        const adults = parseInt(adultsInput.value) || 0;
        const children = parseInt(childrenInput.value) || 0;
        const infants = parseInt(infantsInput.value) || 0;
        const totalPassengers = adults + children + infants;
        const hasMinors = children > 0 || infants > 0;

        if (isDebug) console.log(`Generating passenger fields: adults=${adults}, children=${children}, infants=${infants}`);

        const preservedDocuments = {};
        ['adult', 'child', 'infant'].forEach(type => {
            preservedDocuments[type] = passengerData[type].map(p => p.document).filter(Boolean);
        });

        adultFields.innerHTML = '';
        childFields.innerHTML = '';
        infantFields.innerHTML = '';

        if (totalPassengers > 0) {
            passengerDetails.classList.remove('hidden');
        } else {
            passengerDetails.classList.add('hidden');
        }

        if (hasMinors && !passengerData.adult.some(p => parseInt(p.age) >= 18)) {
            responsibilityDeclarationFields.classList.remove('hidden');
            responsibilityDeclarationInput.required = true;
        } else {
            responsibilityDeclarationFields.classList.add('hidden');
            responsibilityDeclarationInput.required = false;
        }

        function createFieldset(type, count, startIndex) {
            if (typeof document === 'undefined') {
                console.error(`Cannot create fieldset for ${type}: document is not available`);
                return;
            }

            const container = document.getElementById(`${type}-fields`);
            if (!container) {
                console.error(`Container for ${type}-fields not found`);
                return;
            }

            for (let i = 0; i < count; i++) {
                const index = startIndex + i;
                const isRequired = type !== 'adult';
                const existingData = passengerData[type]?.[i] || {};
                const preservedFile = preservedDocuments[type]?.[i] || null;
                const fieldset = document.createElement('div');
                fieldset.className = 'passenger-fieldset';
                fieldset.innerHTML = `
                    <div class="passenger-fieldset-header">
                        <h4 class="text-lg font-semibold text-gray-900 dark:text-blue-200 font-playfair" id="${type}-${i}-legend">${type.charAt(0).toUpperCase() + type.slice(1)} ${i + 1}</h4>
                        <span class="toggle-icon text-gray-900 dark:text-gray-300">${existingData.firstName ? '−' : '+'}</span>
                    </div>
                    <div class="passenger-fieldset-content ${existingData.firstName ? 'open' : ''}">
                        <div class="mb-4">
                            <label for="passenger_${type}_${i}_first_name" class="block text-sm font-medium text-gray-900 dark:text-gray-300 font-roboto">First Name:</label>
                            <input type="text" name="passenger_${type}_${i}_first_name" id="passenger_${type}_${i}_first_name" value="${existingData.firstName || ''}" class="mt-1 w-full p-3 border rounded-lg bg-input-bg dark:bg-gray-700 text-gray-900 dark:text-gray-200 border-border-color dark:border-gray-600 focus:outline-none focus:ring-2 focus:ring-button-bg dark:focus:ring-blue-400">
                            <p class="error-message text-red-600 dark:text-red-400 text-sm hidden mt-1"></p>
                        </div>
                        <div class="mb-4">
                            <label for="passenger_${type}_${i}_last_name" class="block text-sm font-medium text-gray-900 dark:text-gray-300 font-roboto">Last Name:</label>
                            <input type="text" name="passenger_${type}_${i}_last_name" id="passenger_${type}_${i}_last_name" value="${existingData.lastName || ''}" class="mt-1 w-full p-3 border rounded-lg bg-input-bg dark:bg-gray-700 text-gray-900 dark:text-gray-200 border-border-color dark:border-gray-600 focus:outline-none focus:ring-2 focus:ring-button-bg dark:focus:ring-blue-400">
                            <p class="error-message text-red-600 dark:text-red-400 text-sm hidden mt-1"></p>
                        </div>
                        <div class="mb-4">
                            <label for="passenger_${type}_${i}_age" class="block text-sm font-medium text-gray-900 dark:text-gray-300 font-roboto">Age:</label>
                            <input type="number" name="passenger_${type}_${i}_age" id="passenger_${type}_${i}_age" min="${type === 'adult' ? 12 : type === 'child' ? 2 : 0}" max="${type === 'adult' ? 150 : type === 'child' ? 11 : 1}" value="${existingData.age || (type === 'adult' ? 30 : type === 'child' ? 10 : 1)}" class="mt-1 w-full p-3 border rounded-lg bg-input-bg dark:bg-gray-700 text-gray-900 dark:text-gray-200 border-border-color dark:border-gray-600 focus:outline-none focus:ring-2 focus:ring-button-bg dark:focus:ring-blue-400" required>
                            <p class="error-message text-red-600 dark:text-red-400 text-sm hidden mt-1"></p>
                        </div>
                        ${type === 'adult' ? `
                        <div class="mb-4">
                            <label class="flex items-center text-sm font-medium text-gray-900 dark:text-gray-300 font-roboto">
                                <input type="checkbox" name="passenger_${type}_${i}_is_group_leader" id="passenger_${type}_${i}_is_group_leader" class="mr-2 h-5 w-5 text-blue-600 dark:text-blue-400 focus:ring-button-bg dark:focus:ring-blue-400 border-border-color dark:border-gray-600" ${existingData.isGroupLeader ? 'checked' : ''}>
                                Group Leader
                            </label>
                        </div>` : ''}
                        <div class="mb-4">
                            <label for="passenger_${type}_${i}_document" class="block text-sm font-medium text-gray-900 dark:text-gray-300 font-roboto">Document (${type === 'adult' ? 'ID/Passport (optional)' : 'Birth Certificate/ID'}):</label>
                            <input type="file" name="passenger_${type}_${i}_document" id="passenger_${type}_${i}_document" accept=".pdf,.jpg,.jpeg,.png" class="mt-1 w-full p-3 border rounded-lg bg-input-bg dark:bg-gray-700 text-gray-900 dark:text-gray-200 border-border-color dark:border-gray-600 focus:outline-none focus:ring-2 focus:ring-button-bg dark:focus:ring-blue-400" ${isRequired && !emergencyCheckbox.checked ? 'required' : ''}>
                            <div class="file-preview mt-2 hidden"></div>
                            <p class="error-message text-red-600 dark:text-red-400 text-sm hidden mt-1"></p>
                        </div>
                    </div>
                `;
                container.appendChild(fieldset);

                if (isDebug) console.log(`Created fieldset for ${type} ${i + 1}`);

                const header = fieldset.querySelector('.passenger-fieldset-header');
                const content = fieldset.querySelector('.passenger-fieldset-content');
                const toggleIcon = header.querySelector('.toggle-icon');
                header.addEventListener('click', () => {
                    content.classList.toggle('open');
                    toggleIcon.textContent = content.classList.contains('open') ? '−' : '+';
                    const inputs = content.querySelectorAll('input');
                    inputs.forEach(input => {
                        if (input.name.includes('first_name') || input.name.includes('last_name')) {
                            input.required = content.classList.contains('open');
                        }
                    });
                    if (isDebug) console.log(`Toggled fieldset for ${type} ${i + 1}: ${content.classList.contains('open') ? 'open' : 'closed'}`);
                    savePassengerData();
                });

                const fileInput = fieldset.querySelector(`#passenger_${type}_${i}_document`);
                setupFilePreview(fileInput);

                if (preservedFile) {
                    const preview = fileInput.parentElement.querySelector('.file-preview');
                    if (preservedFile.type.startsWith('image/')) {
                        const img = document.createElement('img');
                        img.src = URL.createObjectURL(preservedFile);
                        preview.appendChild(img);
                        preview.classList.remove('hidden');
                    } else if (preservedFile.type === 'application/pdf') {
                        const pdfIcon = document.createElement('div');
                        pdfIcon.className = 'pdf-icon';
                        preview.appendChild(pdfIcon);
                        preview.classList.remove('hidden');
                    }
                    if (isDebug) console.log(`Restored file preview for ${type} ${i + 1}: ${preservedFile.name}`);
                }

                ['first_name', 'last_name', 'age', 'is_group_leader'].forEach(field => {
                    const input = fieldset.querySelector(`#passenger_${type}_${i}_${field}`);
                    if (input) {
                        input.addEventListener('input', () => {
                            savePassengerData();
                            if (isDebug) console.log(`Input updated for ${type} ${i + 1} ${field}: ${input.value}`);
                        });
                        if (field === 'is_group_leader') {
                            input.addEventListener('change', savePassengerData);
                        }
                    }
                });
            }
        }

        createFieldset('adult', adults, 0);
        createFieldset('child', children, adults);
        createFieldset('infant', infants, adults + children);

        if (isDebug) console.log('Passenger fields generated:', document.querySelectorAll('.passenger-fieldset').length);
    }

    async function updateSummary() {
        const adults = parseInt(adultsInput.value) || 0;
        const children = parseInt(childrenInput.value) || 0;
        const infants = parseInt(infantsInput.value) || 0;
        const selectedSchedule = scheduleSelect.options[scheduleSelect.selectedIndex];
        const cargoType = cargoTypeSelect.value;
        const weight = parseFloat(weightInput.value) || 0;
        const isEmergency = emergencyCheckbox.checked;
        const hasMinors = children > 0 || infants > 0;

        let total = 0;
        let breakdown = {};

        if (!scheduleSelect.value) {
            if (isDebug) console.warn('No schedule selected, skipping pricing fetch');
            summarySchedule.textContent = 'Not selected';
            summaryPassengers.textContent = `${adults} Adult${adults !== 1 ? 's' : ''}, ${children} Child${children !== 1 ? 'ren' : ''}, ${infants} Infant${infants !== 1 ? 's' : ''}`;
            summaryCargo.textContent = cargoCheckbox.checked && cargoType && weight ? `${cargoType.charAt(0).toUpperCase() + cargoType.slice(1)} (${weight} kg${dimensionsInput.value ? ', ' + dimensionsInput.value : ''})` : 'None';
            summaryExtras.textContent = [
                isEmergency ? 'Emergency Travel (FJD 50)' : null,
                unaccompaniedMinorCheckbox.checked ? 'Unaccompanied Minor' : null,
                groupBookingCheckbox.checked ? 'Group Booking' : null,
                hasMinors && !passengerData.adult.some(p => parseInt(p.age) >= 18) && responsibilityDeclarationInput.files.length ? 'Responsibility Declaration' : null
            ].filter(Boolean).join(', ') || 'None';
            summaryTotal.textContent = '0.00';
            return;
        }

        try {
            const response = await fetch(`/bookings/get_pricing/?schedule_id=${scheduleSelect.value}&adults=${adults}&children=${children}&infants=${infants}&add_cargo=${cargoCheckbox.checked}&cargo_type=${cargoType}&weight_kg=${weight}&is_emergency=${isEmergency}`);
            const data = await response.json();
            if (data.error) {
                console.error('Pricing error:', data.error);
                if (isDebug) console.log('Pricing fetch failed:', data.error);
                return;
            }
            total = parseFloat(data.total_price);
            breakdown = data.breakdown;
        } catch (error) {
            console.error('Pricing fetch error:', error);
            if (isDebug) console.log('Pricing fetch exception:', error);
        }

        summarySchedule.textContent = selectedSchedule && scheduleSelect.value ? selectedSchedule.text : 'Not selected';
        summaryPassengers.textContent = `${adults} Adult${adults !== 1 ? 's' : ''}, ${children} Child${children !== 1 ? 'ren' : ''}, ${infants} Infant${infants !== 1 ? 's' : ''}`;
        summaryCargo.textContent = cargoCheckbox.checked && cargoType && weight ? `${cargoType.charAt(0).toUpperCase() + cargoType.slice(1)} (${weight} kg${dimensionsInput.value ? ', ' + dimensionsInput.value : ''})` : 'None';
        summaryExtras.textContent = [
            isEmergency ? 'Emergency Travel (FJD 50)' : null,
            unaccompaniedMinorCheckbox.checked ? 'Unaccompanied Minor' : null,
            groupBookingCheckbox.checked ? 'Group Booking' : null,
            hasMinors && !passengerData.adult.some(p => parseInt(p.age) >= 18) && responsibilityDeclarationInput.files.length ? 'Responsibility Declaration' : null
        ].filter(Boolean).join(', ') || 'None';
        summaryTotal.textContent = total.toFixed(2);
    }

    // Initialize passengerData from form_data
    ['adult', 'child', 'infant'].forEach(type => {
        passengerData[type] = [];
        const count = parseInt(window.form_data[`${type}s`] || 0);
        for (let i = 0; i < count; i++) {
            passengerData[type][i] = {
                firstName: window.form_data[`passenger_${type}_${i}_first_name`] || '',
                lastName: window.form_data[`passenger_${type}_${i}_last_name`] || '',
                age: window.form_data[`passenger_${type}_${i}_age`] || (type === 'adult' ? 30 : type === 'child' ? 10 : 1),
                isGroupLeader: window.form_data[`passenger_${type}_${i}_is_group_leader`] || false,
                document: null
            };
        }
    });

    // Handle server-side errors
    if (window.form_data.error) {
        updateStep(window.form_data.step || 1);
        const errorDiv = document.createElement('div');
        errorDiv.className = 'alert error bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200 p-4 rounded-lg shadow-md animate__animated animate__fadeIn';
        errorDiv.textContent = window.form_data.error;
        document.querySelector('.messages').appendChild(errorDiv);
    }

    cargoCheckbox.addEventListener('change', () => {
        cargoFields.classList.toggle('hidden', !cargoCheckbox.checked);
        const cargoInputs = cargoFields.querySelectorAll('input, select');
        cargoInputs.forEach(input => input.required = cargoCheckbox.checked);
        updateSummary();
    });

    unaccompaniedMinorCheckbox.addEventListener('change', () => {
        unaccompaniedMinorFields.classList.toggle('hidden', !unaccompaniedMinorCheckbox.checked);
        const minorInputs = unaccompaniedMinorFields.querySelectorAll('input');
        minorInputs.forEach(input => input.required = unaccompaniedMinorCheckbox.checked);
        setupFilePreview(document.getElementById('consent_form'));
        updateSummary();
    });

    responsibilityDeclarationInput.addEventListener('change', () => {
        setupFilePreview(responsibilityDeclarationInput);
        updateSummary();
    });

    [adultsInput, childrenInput, infantsInput].forEach(input => {
        input.addEventListener('input', () => {
            if (input.value === '' || parseInt(input.value) < 0) {
                input.value = '0';
            }
            savePassengerData();
            validatePassengers();
            generatePassengerFields();
            updateSummary();
        });
    });

    [scheduleSelect, cargoTypeSelect, weightInput, dimensionsInput, emergencyCheckbox, groupBookingCheckbox, unaccompaniedMinorCheckbox].forEach(input => {
        input.addEventListener('change', updateSummary);
    });

    function debounce(func, wait) {
        let timeout;
        return function (...args) {
            clearTimeout(timeout);
            timeout = setTimeout(() => func.apply(this, args), wait);
        };
    }

    document.querySelectorAll('.next-step').forEach(btn => {
        btn.addEventListener('click', debounce(() => {
            if (currentStep === 1) {
                if (!scheduleSelect.value) {
                    showError(scheduleSelect, 'Please select a schedule before proceeding.');
                    let errors = ['Please select a schedule.'];
                    showValidationErrors(errors);
                    return;
                }
                if (!validateStep(1)) {
                    return;
                }
            }
            savePassengerData();
            if (currentStep === 1 || currentStep === 2) {
                generatePassengerFields();
            }
            if (validateStep(currentStep)) {
                updateStep(parseInt(btn.dataset.next));
                updateSummary();
            }
        }, 300));
    });

    document.querySelectorAll('.prev-step').forEach(btn => {
        btn.addEventListener('click', debounce(() => {
            savePassengerData();
            updateStep(parseInt(btn.dataset.prev));
            updateSummary();
        }, 300));
    });

    bookingForm.addEventListener('submit', (e) => {
        e.preventDefault();
        savePassengerData();
        if (!validatePassengers()) {
            showValidationErrors(['Please select at least one passenger.']);
            updateStep(2);
            return;
        }
        for (let step = 1; step <= 4; step++) {
            if (!validateStep(step)) {
                updateStep(step);
                return;
            }
        }
        const formData = new FormData(bookingForm);
        ['adult', 'child', 'infant'].forEach(type => {
            passengerData[type].forEach((passenger, index) => {
                if (passenger.document) {
                    formData.append(`passenger_${type}_${index}_document`, passenger.document);
                    if (isDebug) console.log(`Appended document for ${type} ${index + 1}:`, passenger.document.name);
                }
            });
        });
        if (unaccompaniedMinorCheckbox.checked && document.getElementById('consent_form').files[0]) {
            formData.append('consent_form', document.getElementById('consent_form').files[0]);
            if (isDebug) console.log('Appended consent form:', document.getElementById('consent_form').files[0].name);
        }
        if (responsibilityDeclarationInput.files[0]) {
            formData.append('responsibility_declaration', responsibilityDeclarationInput.files[0]);
            if (isDebug) console.log('Appended responsibility declaration:', responsibilityDeclarationInput.files[0].name);
        }
        if (isDebug) {
            const formDataObj = {};
            formData.forEach((value, key) => {
                if (!(value instanceof File)) {
                    formDataObj[key] = value;
                } else {
                    formDataObj[key] = value.name;
                }
            });
            console.log('Form data submitted:', formDataObj);
        }
        submitButton.disabled = true;
        fetch(bookingForm.action, {
            method: 'POST',
            body: formData,
            headers: {
                'X-CSRFToken': bookingForm.querySelector('[name=csrfmiddlewaretoken]').value
            }
        })
        .then(response => {
            if (!response.ok) {
                return response.text().then(text => {
                    console.error('Submission error:', text);
                    throw new Error('Network response was not ok');
                });
            }
            return response.json();
        })
        .then(data => {
            if (data.success) {
                window.location.href = data.redirect_url;
            } else {
                showValidationErrors([data.error || 'Submission failed. Please try again.']);
                submitButton.disabled = false;
            }
        })
        .catch(error => {
            console.error('Submission error:', error);
            showValidationErrors(['An error occurred during submission. Please try again.']);
            submitButton.disabled = false;
        });
    });

    validatePassengers();
    generatePassengerFields();
    updateSummary();
    updateStep(currentStep);
});