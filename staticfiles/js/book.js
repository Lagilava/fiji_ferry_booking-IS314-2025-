document.addEventListener('DOMContentLoaded', function () {
    const isDebug = true;

    // Cache DOM elements
    const elements = {
        bookingForm: document.getElementById('booking-form'),
        submitButton: document.getElementById('submit-button'),
        steps: Array.from(document.querySelectorAll('.form-step')),
        stepIndicators: Array.from(document.querySelectorAll('.step')),
        adultsInput: document.getElementById('adults'),
        childrenInput: document.getElementById('children'),
        infantsInput: document.getElementById('infants'),
        scheduleSelect: document.getElementById('schedule_id'),
        guestEmail: document.getElementById('guest_email'),
        cargoCheckbox: document.getElementById('add_cargo_checkbox'),
        cargoFields: document.getElementById('cargo-fields'),
        cargoTypeSelect: document.getElementById('cargo_type'),
        weightInput: document.getElementById('weight_kg'),
        dimensionsInput: document.getElementById('dimensions_cm'),
        emergencyCheckbox: document.getElementById('is_emergency'),
        unaccompaniedMinorCheckbox: document.getElementById('is_unaccompanied_minor'),
        unaccompaniedMinorFields: document.getElementById('unaccompanied-minor-fields'),
        groupBookingCheckbox: document.getElementById('is_group_booking'),
        privacyConsent: document.getElementById('privacy-consent'),
        responsibilityDeclarationInput: document.getElementById('responsibility_declaration'),
        responsibilityDeclarationFields: document.getElementById('responsibility-declaration-fields'),
        consentForm: document.getElementById('consent_form'),
        passengerDetails: document.getElementById('passenger-details'),
        adultFields: document.getElementById('adult-fields'),
        childFields: document.getElementById('child-fields'),
        infantFields: document.getElementById('infant-fields'),
        validationErrors: document.getElementById('validation-errors'),
        validationErrorList: document.getElementById('validation-error-list'),
        messages: document.querySelector('.messages'),
        formDataElement: document.getElementById('form_data'),
        csrfToken: document.querySelector('[name=csrfmiddlewaretoken]')
    };

    // Validate required elements
    if (!elements.bookingForm) {
        if (isDebug) console.log('Booking form not found, skipping initialization');
        return;
    }
    elements.bookingForm.setAttribute('novalidate', '');
    for (const [key, el] of Object.entries(elements)) {
        if (!el && ['bookingForm', 'adultsInput', 'childrenInput', 'infantsInput', 'passengerDetails', 'validationErrors', 'validationErrorList'].includes(key)) {
            console.error('Required form element missing:', key);
            return;
        }
    }

    let currentStep = 1;
    let passengerData = { adult: [], child: [], infant: [] };
    window.form_data = { step: 1, hasParent: false };

    // Initialize form data
    if (elements.formDataElement?.textContent) {
        try {
            window.form_data = JSON.parse(elements.formDataElement.textContent);
            if (isDebug) console.log('Parsed form_data:', JSON.stringify(window.form_data, null, 2));
            currentStep = parseInt(window.form_data.step || 1);
        } catch (error) {
            if (isDebug) console.error('Error parsing form_data:', error);
        }
    }

    // Modularized functions
    function createError(field, message) {
        if (!field) return;
        const errorElement = field.parentElement.querySelector('.error-message');
        if (errorElement) {
            errorElement.textContent = message;
            errorElement.classList.remove('hidden');
            errorElement.setAttribute('aria-live', 'assertive');
            field.setAttribute('aria-invalid', 'true');
            field.setAttribute('aria-describedby', errorElement.id || `error-${field.id}`);
            const fieldset = field.closest('.passenger-fieldset');
            if (fieldset && !window.firstInvalidField) {
                window.firstInvalidField = fieldset;
                setTimeout(() => {
                    fieldset.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    setTimeout(() => {
                        fieldset.style.border = '';
                        window.firstInvalidField = null;
                    }, 2000);
                }, 100);
            }
        }
    }

    function clearErrors() {
        document.querySelectorAll('.error-message').forEach(el => {
            el.textContent = '';
            el.classList.add('hidden');
            el.removeAttribute('aria-live');
        });
        document.querySelectorAll('[aria-invalid="true"]').forEach(el => {
            el.removeAttribute('aria-invalid');
            el.removeAttribute('aria-describedby');
        });
        document.querySelectorAll('.passenger-fieldset').forEach(fieldset => {
            fieldset.style.border = '';
        });
        elements.validationErrors.classList.add('hidden');
        elements.validationErrorList.innerHTML = '';
        window.firstInvalidField = null;
    }

    function showValidationErrors(errors) {
        elements.validationErrorList.innerHTML = errors.map(err => `<li>${err}</li>`).join('');
        elements.validationErrors.classList.remove('hidden');
        if (isDebug) console.log('Validation errors:', JSON.stringify(errors, null, 2));
    }

    function updateStep(step) {
        elements.steps.forEach((s, i) => {
            s.classList.toggle('hidden', i !== step - 1);
        });
        elements.stepIndicators.forEach((ind, i) => {
            ind.classList.toggle('active', i === step - 1);
            ind.classList.toggle('completed', i < step - 1);
        });
        currentStep = step;
        clearErrors();
        generatePassengerFields();
    }

    function savePassengerData() {
        const newPassengerData = { adult: [], child: [], infant: [] };
        ['adult', 'child', 'infant'].forEach(type => {
            const count = parseInt(elements[`${type}Input`].value) || 0;
            const fields = elements[`${type}Fields`]?.querySelectorAll('.passenger-fieldset') || [];
            newPassengerData[type] = Array.from({ length: count }, (_, index) => {
                const firstNameInput = document.getElementById(`passenger_${type}_${index}_first_name`);
                const lastNameInput = document.getElementById(`passenger_${type}_${index}_last_name`);
                const ageInput = document.getElementById(`passenger_${type}_${index}_age`);
                const isGroupLeaderInput = type === 'adult' ? document.getElementById(`passenger_${type}_${index}_is_group_leader`) : null;
                const documentInput = document.getElementById(`passenger_${type}_${index}_document`);
                const existingData = passengerData[type][index] || {};
                const currentDocument = documentInput?.files[0] || existingData.document;
                const defaultAge = type === 'adult' ? '30' : type === 'child' ? '10' : '1';
                const ageValue = ageInput?.value && !isNaN(ageInput.value) && ageInput.value !== '' ? ageInput.value : defaultAge;

                if (isDebug) {
                    console.log(`Saving ${type} ${index + 1}: firstName=${firstNameInput?.value || ''}, lastName=${lastNameInput?.value || ''}, age=${ageValue}, document=${currentDocument ? currentDocument.name : 'null'}`);
                    if (!currentDocument && type !== 'adult' && !elements.emergencyCheckbox.checked) {
                        console.warn(`No document uploaded for ${type} passenger ${index + 1}`);
                    } else if (currentDocument) {
                        console.log(`Document retained for ${type} passenger ${index + 1}: ${currentDocument.name}`);
                    }
                }

                return {
                    firstName: firstNameInput?.value.trim() || '',
                    lastName: lastNameInput?.value.trim() || '',
                    age: ageValue,
                    isGroupLeader: isGroupLeaderInput?.checked || false,
                    document: currentDocument
                };
            });
        });
        passengerData = newPassengerData;
        if (isDebug) console.log('Saved passenger data:', JSON.stringify(passengerData, (key, value) => (value instanceof File ? value.name : value), 2));
    }

    async function validateFileAsync(file, input) {
        if (!file) return { valid: true };
        const formData = new FormData();
        formData.append('file', file);
        try {
            const response = await fetch('/bookings/validate_file/', {
                method: 'POST',
                body: formData,
                headers: { 'X-CSRFToken': elements.csrfToken.value }
            });
            const data = await response.json();
            if (!response.ok || data.error) {
                createError(input, data.error || 'Invalid file.');
                return { valid: false, error: data.error || 'Invalid file.' };
            }
            return { valid: true };
        } catch (error) {
            if (isDebug) console.error('File validation error:', error);
            createError(input, 'Failed to validate file.');
            return { valid: false, error: 'Failed to validate file.' };
        }
    }

    function validatePassenger(type, index, data, errors) {
        const fieldset = elements[`${type}Fields`]?.querySelectorAll('.passenger-fieldset')[index];
        const content = fieldset?.querySelector('.passenger-fieldset-content');
        const firstName = document.getElementById(`passenger_${type}_${index}_first_name`);
        const lastName = document.getElementById(`passenger_${type}_${index}_last_name`);
        const age = document.getElementById(`passenger_${type}_${index}_age`);
        const documentInput = document.getElementById(`passenger_${type}_${index}_document`);

        if (content && !content.classList.contains('open')) {
            content.classList.add('open');
            fieldset.querySelector('.toggle-icon').textContent = '−';
            const inputs = content.querySelectorAll('input');
            inputs.forEach(input => {
                if (input.name.includes('first_name') || input.name.includes('last_name') || input.name.includes('age')) {
                    input.required = true;
                }
            });
            if (isDebug) console.log(`Auto-expanded fieldset for ${type} ${index + 1}`);
        }

        if (!firstName || !lastName || !age) {
            errors.push(`${type.charAt(0).toUpperCase() + type.slice(1)} ${index + 1}: Required fields are missing.`);
            if (isDebug) console.error(`Missing elements for ${type} ${index + 1}`);
            return;
        }

        if (isDebug) console.log(`Validating ${type} ${index + 1}: firstName=${data.firstName}, lastName=${data.lastName}, age=${data.age}, document=${data.document ? data.document.name : 'null'}`);

        if (!data.firstName) {
            createError(firstName, 'First name is required.');
            errors.push(`${type.charAt(0).toUpperCase() + type.slice(1)} ${index + 1}: First name is required.`);
        }
        if (!data.lastName) {
            createError(lastName, 'Last name is required.');
            errors.push(`${type.charAt(0).toUpperCase() + type.slice(1)} ${index + 1}: Last name is required.`);
        }
        const minAge = type === 'adult' ? 12 : type === 'child' ? 2 : 0;
        const maxAge = type === 'adult' ? 150 : type === 'child' ? 11 : 1;
        if (!data.age || isNaN(data.age) || parseInt(data.age) < minAge || parseInt(data.age) > maxAge) {
            createError(age, `Age must be ${minAge}-${maxAge}.`);
            errors.push(`${type.charAt(0).toUpperCase() + type.slice(1)} ${index + 1}: Age must be ${minAge}-${maxAge}.`);
        }
        if (type !== 'adult' && !elements.emergencyCheckbox.checked) {
            if (!data.document) {
                createError(documentInput, 'Document is required.');
                errors.push(`${type.charAt(0).toUpperCase() + type.slice(1)} ${index + 1}: Document is required.`);
            } else {
                if (isDebug) console.log(`Child document during validation for ${type} ${index + 1}: ${data.document.name}`);
            }
        }
    }

    function validateStep(step) {
        clearErrors();
        const errors = [];

        if (step === 1) {
            if (isDebug) console.log('Validating Step 1', { schedule: elements.scheduleSelect.value, email: elements.guestEmail?.value });
            if (!elements.scheduleSelect.value) {
                createError(elements.scheduleSelect, 'Please select a schedule.');
                errors.push('Please select a schedule.');
            }
            if (elements.guestEmail && !elements.guestEmail.value.trim()) {
                createError(elements.guestEmail, 'Please provide a guest email.');
                errors.push('Please provide a guest email.');
            } else if (elements.guestEmail && !elements.guestEmail.value.match(/^[^@]+@[^@]+\.[^@]+$/)) {
                createError(elements.guestEmail, 'Please provide a valid guest email.');
                errors.push('Please provide a valid guest email.');
            }
        } else if (step === 2) {
            const adults = parseInt(elements.adultsInput.value) || 0;
            const children = parseInt(elements.childrenInput.value) || 0;
            const infants = parseInt(elements.infantsInput.value) || 0;
            const totalPassengers = adults + children + infants;
            const hasMinors = children > 0 || infants > 0;
            const hasParent = passengerData.adult.some(p => parseInt(p.age) >= 18);

            if (isDebug) console.log(`Validating Step 2: adults=${adults}, children=${children}, infants=${infants}`);

            if (totalPassengers === 0) {
                createError(elements.adultsInput, 'Please select at least one passenger.');
                errors.push('Please select at least one passenger.');
            }
            if (adults < 0 || children < 0 || infants < 0) {
                createError(elements.adultsInput, 'Passenger counts cannot be negative.');
                errors.push('Passenger counts cannot be negative.');
            }

            savePassengerData();
            ['adult', 'child', 'infant'].forEach(type => {
                const count = type === 'adult' ? adults : type === 'child' ? children : infants;
                for (let i = 0; i < count; i++) {
                    if (!passengerData[type][i]) {
                        passengerData[type][i] = {
                            firstName: '',
                            lastName: '',
                            age: type === 'adult' ? '30' : type === 'child' ? '10' : '1',
                            isGroupLeader: false,
                            document: null
                        };
                    }
                    validatePassenger(type, i, passengerData[type][i], errors);
                }
            });

            if (hasMinors && !hasParent && !elements.responsibilityDeclarationInput.files.length) {
                createError(elements.responsibilityDeclarationInput, 'Responsibility declaration is required for non-parent adults traveling with minors.');
                errors.push('Responsibility declaration is required for non-parent adults traveling with minors.');
            }
        } else if (step === 3) {
            if (elements.cargoCheckbox.checked) {
                if (!elements.cargoTypeSelect.value) {
                    createError(elements.cargoTypeSelect, 'Cargo type is required.');
                    errors.push('Cargo type is required.');
                }
                if (!elements.weightInput.value || parseFloat(elements.weightInput.value) <= 0) {
                    createError(elements.weightInput, 'Weight must be greater than 0.');
                    errors.push('Cargo weight must be greater than 0.');
                }
                if (elements.dimensionsInput.value && !/^\d+\s*x\s*\d+\s*x\s*\d+$/.test(elements.dimensionsInput.value)) {
                    createError(elements.dimensionsInput, 'Dimensions must be in the format "length x width x height".');
                    errors.push('Cargo dimensions must be in the format "length x width x height".');
                }
            }
            if (elements.unaccompaniedMinorCheckbox.checked) {
                if (!elements.guardianContact.value.trim()) {
                    createError(elements.guardianContact, 'Guardian contact is required.');
                    errors.push('Guardian contact is required for unaccompanied minors.');
                }
                if (!elements.consentForm.files.length) {
                    createError(elements.consentForm, 'Consent form is required.');
                    errors.push('Consent form is required for unaccompanied minors.');
                }
            }
        } else if (step === 4) {
            if (!elements.privacyConsent.checked) {
                createError(elements.privacyConsent, 'You must agree to the privacy policy.');
                errors.push('You must agree to the privacy policy.');
            }
        }

        if (errors.length > 0) {
            showValidationErrors(errors);
            return false;
        }
        return true;
    }

    async function validateStepAsync(step) {
        const errors = [];
        if (step === 2) {
            const adults = parseInt(elements.adultsInput.value) || 0;
            const children = parseInt(elements.childrenInput.value) || 0;
            const infants = parseInt(elements.infantsInput.value) || 0;
            for (const type of ['adult', 'child', 'infant']) {
                const count = type === 'adult' ? adults : type === 'child' ? children : infants;
                for (let i = 0; i < count; i++) {
                    const data = passengerData[type][i];
                    if (data?.document && type !== 'adult' && !elements.emergencyCheckbox.checked) {
                        const result = await validateFileAsync(data.document, document.getElementById(`passenger_${type}_${i}_document`));
                        if (!result.valid) {
                            errors.push(`${type.charAt(0).toUpperCase() + type.slice(1)} ${i + 1}: ${result.error}`);
                        }
                    }
                }
            }
        }
        if (errors.length > 0) {
            showValidationErrors(errors);
            return false;
        }
        return validateStep(step);
    }

    function validatePassengers() {
        const adults = parseInt(elements.adultsInput.value) || 0;
        const children = parseInt(elements.childrenInput.value) || 0;
        const infants = parseInt(elements.infantsInput.value) || 0;
        const totalPassengers = adults + children + infants;
        elements.submitButton.disabled = totalPassengers === 0;
        return totalPassengers > 0;
    }

    function validateFile(file, field) {
        const allowedTypes = ['application/pdf', 'image/jpeg', 'image/jpg', 'image/png'];
        const maxSize = 5 * 1024 * 1024;
        if (!file) return true;
        if (!allowedTypes.includes(file.type)) {
            createError(field, 'File must be a PDF, JPG, JPEG, or PNG.');
            return false;
        }
        if (file.size > maxSize) {
            createError(field, 'File size must be less than 5MB.');
            return false;
        }
        return true;
    }

    function setupFilePreview(input) {
        input.addEventListener('change', async () => {
            const preview = input.parentElement.querySelector('.file-preview');
            preview.innerHTML = '';
            preview.classList.add('hidden');
            if (input.files.length > 0) {
                const file = input.files[0];
                if (!validateFile(file, input)) return;
                const [_, type, index] = input.id.match(/passenger_(\w+)_(\d+)_document/) || [];
                if (type && index !== undefined) {
                    if (!passengerData[type]) passengerData[type] = [];
                    if (!passengerData[type][index]) {
                        passengerData[type][index] = {
                            firstName: '',
                            lastName: '',
                            age: type === 'adult' ? '30' : type === 'child' ? '10' : '1',
                            isGroupLeader: false,
                            document: null
                        };
                    }
                    if (type !== 'adult' && !elements.emergencyCheckbox.checked) {
                        const result = await validateFileAsync(file, input);
                        if (!result.valid) return;
                    }
                    passengerData[type][index].document = file;
                    if (isDebug) console.log(`File selected for ${input.id}: ${file.name}`);
                    if (isDebug) console.log(`Updated passengerData[${type}][${index}].document: ${file.name}`);
                }
                if (file.type.startsWith('image/')) {
                    const img = document.createElement('img');
                    img.src = URL.createObjectURL(file);
                    img.className = 'w-32 h-32 object-cover rounded';
                    preview.appendChild(img);
                    preview.classList.remove('hidden');
                } else if (file.type === 'application/pdf') {
                    const pdfIcon = document.createElement('div');
                    pdfIcon.className = 'pdf-icon w-32 h-32 flex items-center justify-center rounded';
                    pdfIcon.style.backgroundColor = 'var(--input-bg)';
                    pdfIcon.style.color = 'var(--input-text)';
                    pdfIcon.textContent = 'PDF';
                    preview.appendChild(pdfIcon);
                    preview.classList.remove('hidden');
                }
                savePassengerData();
            }
        });
    }

    function generatePassengerFields() {
        const adults = parseInt(elements.adultsInput.value) || 0;
        const children = parseInt(elements.childrenInput.value) || 0;
        const infants = parseInt(elements.infantsInput.value) || 0;
        const totalPassengers = adults + children + infants;
        const hasMinors = children > 0 || infants > 0;

        if (isDebug) console.log(`Generating passenger fields: adults=${adults}, children=${children}, infants=${infants}`);

        const preservedDocuments = {};
        ['adult', 'child', 'infant'].forEach(type => {
            preservedDocuments[type] = passengerData[type].map(p => p.document).filter(Boolean);
        });

        elements.adultFields.innerHTML = '';
        elements.childFields.innerHTML = '';
        elements.infantFields.innerHTML = '';

        if (totalPassengers > 0) {
            elements.passengerDetails.classList.remove('hidden');
        } else {
            elements.passengerDetails.classList.add('hidden');
        }

        if (hasMinors && !passengerData.adult.some(p => parseInt(p.age) >= 18)) {
            elements.responsibilityDeclarationFields.classList.remove('hidden');
            elements.responsibilityDeclarationInput.required = true;
        } else {
            elements.responsibilityDeclarationFields.classList.add('hidden');
            elements.responsibilityDeclarationInput.required = false;
        }

        function createFieldset(type, count) {
            const container = elements[`${type}Fields`];
            if (!container) {
                console.error(`Container for ${type}-fields not found`);
                return;
            }

            // Optimize for large passenger lists
            const fragment = document.createDocumentFragment();
            for (let i = 0; i < count; i++) {
                const index = i;
                const isRequired = type !== 'adult';
                const existingData = passengerData[type]?.[index] || {};
                const preservedFile = preservedDocuments[type]?.[index] || null;
                const fieldset = document.createElement('div');
                fieldset.className = 'passenger-fieldset mb-4 p-4 rounded-lg';
                fieldset.style.backgroundColor = 'var(--card-bg)';
                fieldset.style.color = 'var(--text-color)';
                fieldset.setAttribute('aria-expanded', !!existingData.firstName);
                fieldset.setAttribute('aria-controls', `passenger_${type}_${index}_content`);
                fieldset.innerHTML = `
                    <div class="passenger-fieldset-header flex justify-between items-center cursor-pointer" role="button" aria-expanded="${!!existingData.firstName}" aria-controls="passenger_${type}_${index}_content">
                        <h4 class="text-lg font-semibold" style="color: var(--text-color);" id="${type}-${index}-legend">${type.charAt(0).toUpperCase() + type.slice(1)} ${index + 1}</h4>
                        <span class="toggle-icon" style="color: var(--text-color);">${existingData.firstName ? '−' : '+'}</span>
                    </div>
                    <div id="passenger_${type}_${index}_content" class="passenger-fieldset-content ${existingData.firstName ? 'open' : ''} mt-2">
                        <div class="mb-4">
                            <label for="passenger_${type}_${index}_first_name" class="block text-sm font-medium" style="color: var(--text-color);">First Name:</label>
                            <input type="text" name="passenger_${type}_${index}_first_name" id="passenger_${type}_${index}_first_name" value="${existingData.firstName || ''}" class="mt-1 w-full p-3 border rounded-lg" style="background-color: var(--input-bg); color: var(--input-text); border-color: var(--border-color);" required aria-describedby="error-passenger_${type}_${index}_first_name">
                            <p id="error-passenger_${type}_${index}_first_name" class="error-message" style="color: var(--alert-error-text); font-size: 0.875rem; display: none; margin-top: 0.25rem;"></p>
                        </div>
                        <div class="mb-4">
                            <label for="passenger_${type}_${index}_last_name" class="block text-sm font-medium" style="color: var(--text-color);">Last Name:</label>
                            <input type="text" name="passenger_${type}_${index}_last_name" id="passenger_${type}_${index}_last_name" value="${existingData.lastName || ''}" class="mt-1 w-full p-3 border rounded-lg" style="background-color: var(--input-bg); color: var(--input-text); border-color: var(--border-color);" required aria-describedby="error-passenger_${type}_${index}_last_name">
                            <p id="error-passenger_${type}_${index}_last_name" class="error-message" style="color: var(--alert-error-text); font-size: 0.875rem; display: none; margin-top: 0.25rem;"></p>
                        </div>
                        <div class="mb-4">
                            <label for="passenger_${type}_${index}_age" class="block text-sm font-medium" style="color: var(--text-color);">Age:</label>
                            <input type="number" name="passenger_${type}_${index}_age" id="passenger_${type}_${index}_age" min="${type === 'adult' ? 12 : type === 'child' ? 2 : 0}" max="${type === 'adult' ? 150 : type === 'child' ? 11 : 1}" value="${existingData.age || (type === 'adult' ? 30 : type === 'child' ? 10 : 1)}" class="mt-1 w-full p-3 border rounded-lg" style="background-color: var(--input-bg); color: var(--input-text); border-color: var(--border-color);" required aria-describedby="error-passenger_${type}_${index}_age">
                            <p id="error-passenger_${type}_${index}_age" class="error-message" style="color: var(--alert-error-text); font-size: 0.875rem; display: none; margin-top: 0.25rem;"></p>
                        </div>
                        ${type === 'adult' ? `
                        <div class="mb-4">
                            <label class="flex items-center text-sm font-medium" style="color: var(--text-color);">
                                <input type="checkbox" name="passenger_${type}_${index}_is_group_leader" id="passenger_${type}_${index}_is_group_leader" class="mr-2 h-5 w-5" style="border-color: var(--border-color); accent-color: var(--button-bg);" ${existingData.isGroupLeader ? 'checked' : ''}>
                                Group Leader
                            </label>
                        </div>` : ''}
                        <div class="mb-4">
                            <label for="passenger_${type}_${index}_document" class="block text-sm font-medium" style="color: var(--text-color);">Document (${type === 'adult' ? 'ID/Passport (optional)' : 'Birth Certificate/ID'}):</label>
                            <input type="file" name="passenger_${type}_${index}_document" id="passenger_${type}_${index}_document" accept=".pdf,.jpg,.jpeg,.png" class="mt-1 w-full p-3 border rounded-lg" style="background-color: var(--input-bg); color: var(--input-text); border-color: var(--border-color);" ${isRequired && !elements.emergencyCheckbox.checked ? 'required' : ''} aria-describedby="error-passenger_${type}_${index}_document">
                            <div class="file-preview mt-2 hidden"></div>
                            <p id="error-passenger_${type}_${index}_document" class="error-message" style="color: var(--alert-error-text); font-size: 0.875rem; display: none; margin-top: 0.25rem;"></p>
                        </div>
                    </div>
                `;
                fragment.appendChild(fieldset);

                const header = fieldset.querySelector('.passenger-fieldset-header');
                const content = fieldset.querySelector('.passenger-fieldset-content');
                const toggleIcon = header.querySelector('.toggle-icon');
                header.addEventListener('click', () => {
                    const isOpen = content.classList.toggle('open');
                    toggleIcon.textContent = isOpen ? '−' : '+';
                    fieldset.setAttribute('aria-expanded', isOpen);
                    const inputs = content.querySelectorAll('input');
                    inputs.forEach(input => {
                        if (input.name.includes('first_name') || input.name.includes('last_name')) {
                            input.required = isOpen;
                        }
                    });
                    if (isDebug) console.log(`Toggled fieldset for ${type} ${index + 1}: ${isOpen ? 'open' : 'closed'}`);
                    savePassengerData();
                });

                const fileInput = fieldset.querySelector(`#passenger_${type}_${index}_document`);
                setupFilePreview(fileInput);

                if (preservedFile) {
                    const preview = fileInput.parentElement.querySelector('.file-preview');
                    if (preservedFile.type.startsWith('image/')) {
                        const img = document.createElement('img');
                        img.src = URL.createObjectURL(preservedFile);
                        img.className = 'w-32 h-32 object-cover rounded';
                        preview.appendChild(img);
                        preview.classList.remove('hidden');
                    } else if (preservedFile.type === 'application/pdf') {
                        const pdfIcon = document.createElement('div');
                        pdfIcon.className = 'pdf-icon w-32 h-32 flex items-center justify-center rounded';
                        pdfIcon.style.backgroundColor = 'var(--input-bg)';
                        pdfIcon.style.color = 'var(--input-text)';
                        pdfIcon.textContent = 'PDF';
                        preview.appendChild(pdfIcon);
                        preview.classList.remove('hidden');
                    }
                    if (isDebug) console.log(`Restored file preview for ${type} ${index + 1}: ${preservedFile.name}`);
                    passengerData[type][index].document = preservedFile;
                }
            }
            container.appendChild(fragment);
            if (isDebug) console.log(`Created ${count} fieldsets for ${type}`);
        }

        createFieldset('adult', adults);
        createFieldset('child', children);
        createFieldset('infant', infants);

        if (isDebug) console.log('Passenger fields generated:', document.querySelectorAll('.passenger-fieldset').length);
        savePassengerData();
    }

    async function updateSummary() {
        const adults = parseInt(elements.adultsInput.value) || 0;
        const children = parseInt(elements.childrenInput.value) || 0;
        const infants = parseInt(elements.infantsInput.value) || 0;
        const selectedSchedule = elements.scheduleSelect.options[elements.scheduleSelect.selectedIndex];
        const cargoType = elements.cargoTypeSelect.value;
        const weight = parseFloat(elements.weightInput.value) || 0;
        const isEmergency = elements.emergencyCheckbox.checked;
        const hasMinors = children > 0 || infants > 0;

        let total = 0;
        let breakdown = {};

        if (!elements.scheduleSelect.value) {
            if (isDebug) console.warn('No schedule selected, skipping pricing fetch');
            elements.summarySchedule.textContent = 'Not selected';
            elements.summaryPassengers.textContent = `${adults} Adult${adults !== 1 ? 's' : ''}, ${children} Child${children !== 1 ? 'ren' : ''}, ${infants} Infant${infants !== 1 ? 's' : ''}`;
            elements.summaryCargo.textContent = elements.cargoCheckbox.checked && cargoType && weight ? `${cargoType.charAt(0).toUpperCase() + cargoType.slice(1)} (${weight} kg${elements.dimensionsInput.value ? ', ' + elements.dimensionsInput.value : ''})` : 'None';
            elements.summaryExtras.textContent = [
                isEmergency ? 'Emergency Travel (FJD 50)' : null,
                elements.unaccompaniedMinorCheckbox.checked ? 'Unaccompanied Minor' : null,
                elements.groupBookingCheckbox.checked ? 'Group Booking' : null,
                hasMinors && !passengerData.adult.some(p => parseInt(p.age) >= 18) && elements.responsibilityDeclarationInput.files.length ? 'Responsibility Declaration' : null
            ].filter(Boolean).join(', ') || 'None';
            elements.summaryTotal.textContent = '0.00';
            return;
        }

        try {
            const response = await fetch(`/bookings/get_pricing/?schedule_id=${elements.scheduleSelect.value}&adults=${adults}&children=${children}&infants=${infants}&add_cargo=${elements.cargoCheckbox.checked}&cargo_type=${cargoType}&weight_kg=${weight}&is_emergency=${isEmergency}`);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            if (data.error) {
                console.error('Pricing error:', data.error);
                showValidationErrors([data.error]);
                return;
            }
            total = parseFloat(data.total_price) || 0;
            breakdown = data.breakdown || {};
        } catch (error) {
            console.error('Pricing fetch error:', error);
            showValidationErrors(['Unable to fetch pricing. Please try again later.']);
            elements.summaryTotal.textContent = '0.00';
            return;
        }

        elements.summarySchedule.textContent = selectedSchedule && elements.scheduleSelect.value ? selectedSchedule.text : 'Not selected';
        elements.summaryPassengers.textContent = `${adults} Adult${adults !== 1 ? 's' : ''}, ${children} Child${children !== 1 ? 'ren' : ''}, ${infants} Infant${infants !== 1 ? 's' : ''}`;
        elements.summaryCargo.textContent = elements.cargoCheckbox.checked && cargoType && weight ? `${cargoType.charAt(0).toUpperCase() + cargoType.slice(1)} (${weight} kg${elements.dimensionsInput.value ? ', ' + elements.dimensionsInput.value : ''})` : 'None';
        elements.summaryExtras.textContent = [
            isEmergency ? 'Emergency Travel (FJD 50)' : null,
            elements.unaccompaniedMinorCheckbox.checked ? 'Unaccompanied Minor' : null,
            elements.groupBookingCheckbox.checked ? 'Group Booking' : null,
            hasMinors && !passengerData.adult.some(p => parseInt(p.age) >= 18) && elements.responsibilityDeclarationInput.files.length ? 'Responsibility Declaration' : null
        ].filter(Boolean).join(', ') || 'None';
        elements.summaryTotal.textContent = total.toFixed(2);
    }

    // Event listeners
    elements.cargoCheckbox.addEventListener('change', () => {
        elements.cargoFields.classList.toggle('hidden', !elements.cargoCheckbox.checked);
        const cargoInputs = elements.cargoFields.querySelectorAll('input, select');
        cargoInputs.forEach(input => input.required = elements.cargoCheckbox.checked);
        updateSummary();
    });

    elements.unaccompaniedMinorCheckbox.addEventListener('change', () => {
        elements.unaccompaniedMinorFields.classList.toggle('hidden', !elements.unaccompaniedMinorCheckbox.checked);
        const minorInputs = elements.unaccompaniedMinorFields.querySelectorAll('input');
        minorInputs.forEach(input => input.required = elements.unaccompaniedMinorCheckbox.checked);
        setupFilePreview(elements.consentForm);
        updateSummary();
    });

    elements.responsibilityDeclarationInput.addEventListener('change', () => {
        setupFilePreview(elements.responsibilityDeclarationInput);
        updateSummary();
    });

    [elements.adultsInput, elements.childrenInput, elements.infantsInput].forEach(input => {
        input.addEventListener('input', () => {
            if (input.value === '' || parseInt(input.value) < 0) {
                input.value = '0';
                createError(input, 'Passenger counts cannot be negative.');
            }
            savePassengerData();
            validatePassengers();
            generatePassengerFields();
            updateSummary();
        });
    });

    [elements.scheduleSelect, elements.cargoTypeSelect, elements.weightInput, elements.dimensionsInput, elements.emergencyCheckbox, elements.groupBookingCheckbox, elements.unaccompaniedMinorCheckbox].forEach(input => {
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
        btn.addEventListener('click', debounce(async () => {
            savePassengerData();
            if (isDebug) console.log('Before validation, passengerData:', JSON.stringify(passengerData, (key, value) => (value instanceof File ? value.name : value), 2));
            if (currentStep === 1 && !elements.scheduleSelect.value) {
                createError(elements.scheduleSelect, 'Please select a schedule before proceeding.');
                showValidationErrors(['Please select a schedule.']);
                return;
            }
            if (await validateStepAsync(currentStep)) {
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

    elements.bookingForm.addEventListener('submit', async e => {
        e.preventDefault();
        savePassengerData();
        if (!validatePassengers()) {
            showValidationErrors(['Please select at least one passenger.']);
            updateStep(2);
            return;
        }
        for (let step = 1; step <= 4; step++) {
            if (!await validateStepAsync(step)) {
                updateStep(step);
                return;
            }
        }
        const formData = new FormData(elements.bookingForm);
        ['adult', 'child', 'infant'].forEach(type => {
            passengerData[type].forEach((passenger, index) => {
                if (passenger.document && validateFile(passenger.document, document.getElementById(`passenger_${type}_${index}_document`))) {
                    formData.append(`passenger_${type}_${index}_document`, passenger.document);
                    if (isDebug) console.log(`Appended document for ${type} ${index + 1}: ${passenger.document.name}`);
                } else if (passenger.document) {
                    showValidationErrors([`Invalid document for ${type.charAt(0).toUpperCase() + type.slice(1)} ${index + 1}.`]);
                    updateStep(2);
                    return;
                }
            });
        });
        if (elements.unaccompaniedMinorCheckbox.checked && elements.consentForm.files[0]) {
            const consentForm = elements.consentForm.files[0];
            if (validateFile(consentForm, elements.consentForm)) {
                formData.append('consent_form', consentForm);
                if (isDebug) console.log('Appended consent form:', consentForm.name);
            } else {
                showValidationErrors(['Invalid consent form file.']);
                updateStep(3);
                return;
            }
        }
        if (elements.responsibilityDeclarationInput.files[0]) {
            const responsibilityForm = elements.responsibilityDeclarationInput.files[0];
            if (validateFile(responsibilityForm, elements.responsibilityDeclarationInput)) {
                formData.append('responsibility_declaration', responsibilityForm);
                if (isDebug) console.log('Appended responsibility declaration:', responsibilityForm.name);
            } else {
                showValidationErrors(['Invalid responsibility declaration file.']);
                updateStep(2);
                return;
            }
        }
        if (isDebug) {
            const formDataObj = {};
            formData.forEach((value, key) => {
                formDataObj[key] = value instanceof File ? value.name : value;
            });
            console.log('Form data submitted:', JSON.stringify(formDataObj, null, 2));
        }
        elements.submitButton.disabled = true;
        try {
            const response = await fetch(elements.bookingForm.action, {
                method: 'POST',
                body: formData,
                headers: { 'X-CSRFToken': elements.csrfToken.value }
            });
            const data = await response.json();
            if (!response.ok) {
                console.error('Submission error:', data.error || 'Unknown error');
                showValidationErrors([data.error || 'Network response was not ok']);
                elements.submitButton.disabled = false;
                return;
            }
            if (data.success) {
                window.location.href = data.redirect_url;
            } else {
                showValidationErrors([data.error || 'Submission failed. Please try again.']);
                updateStep(data.step || 1);
                elements.submitButton.disabled = false;
            }
        } catch (error) {
            console.error('Submission error:', error);
            showValidationErrors(['An error occurred during submission. Please try again.']);
            elements.submitButton.disabled = false;
        }
    });

    // Initialize
    validatePassengers();
    generatePassengerFields();
    updateSummary();
    updateStep(currentStep);

    if (window.form_data.error) {
        const errorDiv = document.createElement('div');
        errorDiv.className = 'alert error p-4 rounded-lg shadow-md animate__animated animate__fadeIn';
        errorDiv.style.backgroundColor = 'var(--alert-error-bg)';
        errorDiv.style.color = 'var(--alert-error-text)';
        errorDiv.textContent = window.form_data.error;
        elements.messages.appendChild(errorDiv);
    }
});