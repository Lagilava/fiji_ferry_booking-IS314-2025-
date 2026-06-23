/**
 * validation.js - Comprehensive validation utilities for Fiji Ferry Booking
 * Provides global validation functions and error handling for multi-step booking form.
 */
(function() {
    'use strict';

    // =========================
    // Error Messages (original)
    // =========================
    const ERROR_MESSAGES = {
        // Step 1
        scheduleRequired: 'Please select a valid ferry schedule',
        scheduleUnavailable: 'Selected schedule is no longer available',
        emailRequired: 'Email address is required for guest bookings',
        emailInvalid: 'Please enter a valid email address',
        emailNotVerified: 'Please verify your email (click send code to get code for verification).',

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

    // =========================
    // Helpers (added)
    // =========================

    /**
     * Normalize backend error payloads into [{ field, message }, ...]
     */
    function normalizeBackendErrors(raw) {
        if (!raw) return [];
        if (Array.isArray(raw) && raw.every(e => typeof e === 'object' && ('message' in e))) return raw;
        if (Array.isArray(raw) && raw.every(e => typeof e === 'string')) {
            return raw.map(msg => ({ field: 'general', message: msg }));
        }
        if (typeof raw === 'string') return [{ field: 'general', message: raw }];
        if (typeof raw === 'object') {
            const out = [];
            Object.entries(raw).forEach(([field, val]) => {
                if (Array.isArray(val)) {
                    val.forEach(v => out.push({ field, message: String(v) }));
                } else if (typeof val === 'object' && val !== null) {
                    Object.values(val).forEach(v => out.push({ field, message: String(v) }));
                } else {
                    out.push({ field, message: String(val) });
                }
            });
            return out;
        }
        try { return [{ field: 'general', message: JSON.stringify(raw) }]; }
        catch { return [{ field: 'general', message: 'An unknown error occurred' }]; }
    }

    // --- Lightweight script loader (no duplicates) ---
    async function loadScriptOnce(src, { check } = {}) {
        try {
            if (check && check()) return;
        } catch(_) {}
        const existing = Array.from(document.querySelectorAll('script[src]')).some(s => s.src === src || s.getAttribute('src') === src);
        if (existing) {
            // Give time for onload handlers elsewhere
            await new Promise(r => setTimeout(r, 50));
            return;
        }
        await new Promise((resolve, reject) => {
            const s = document.createElement('script');
            s.src = src;
            s.async = true;
            s.crossOrigin = 'anonymous';
            s.onload = resolve;
            s.onerror = () => reject(new Error(`Failed to load ${src}`));
            document.head.appendChild(s);
        });
    }

    // --- Pixel variance helper (detect “nearly blank”) ---
    function pixelStdDev(imageData) {
        const data = imageData.data;
        const len = Math.max(1, data.length / 4);
        let sum = 0, sumSq = 0;
        for (let i = 0; i < data.length; i += 4) {
            const y = 0.2126 * data[i] + 0.7152 * data[i+1] + 0.0722 * data[i+2];
            sum += y;
            sumSq += y * y;
        }
        const mean = sum / len;
        const variance = Math.max(0, (sumSq / len) - (mean * mean));
        return Math.sqrt(variance);
    }

    // --- Canvas factory (uses OffscreenCanvas when available) ---
    function makeCanvas(w, h) {
        const W = Math.max(2, Math.floor(w));
        const H = Math.max(2, Math.floor(h));
        if ('OffscreenCanvas' in window) {
            return new OffscreenCanvas(W, H);
        }
        const c = document.createElement('canvas');
        c.width = W; c.height = H;
        return c;
    }

    // ---------------------------------------------------------------
    // 1. PDF.js Loader – NO manual GlobalWorkerOptions
    // ---------------------------------------------------------------
    let _pdfjsPromise = null;
    async function ensurePdfJs() {
        if (_pdfjsPromise) return _pdfjsPromise;

        _pdfjsPromise = (async () => {
            // Use pre-configured URL with worker + fonts
            const base = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.10.111';
            const pdfSrc = `${base}/pdf.min.js`;
            const workerSrc = `${base}/pdf.worker.min.js`;

            try {
                // Load main script
                await loadScriptOnce(pdfSrc, { check: () => window.pdfjsLib && typeof window.pdfjsLib.getDocument === 'function' });
            } catch (e) {
                console.warn('Failed to load PDF.js main script', e);
                throw e;
            }

            // Set worker via URL param (safe, no getter issues)
            if (window.pdfjsLib && !window.pdfjsLib.GlobalWorkerOptions?.workerSrc) {
                try {
                    // Modern PDF.js allows setting via getDocument params
                    window.pdfjsLib.GlobalWorkerOptions.workerSrc = workerSrc;
                } catch (e) {
                    // Ignore – gives "getter-only" error in newer versions
                    console.debug('PDF.js workerSrc is read-only; will auto-detect', e);
                }
            }

            // Optional: suppress font warnings
            if (window.pdfjsLib) {
                window.pdfjsLib.GlobalWorkerOptions.standardFontDataUrl = `${base}/standard_fonts/`;
            }
        })();

        return _pdfjsPromise;
    }

    // --- Image blank detection ---
    async function analyzeImageFile(file, { blankStdDevThreshold = 3 } = {}) {
        const url = URL.createObjectURL(file);
        try {
            const img = await new Promise((res, rej) => {
                const im = new Image();
                im.crossOrigin = 'anonymous';
                im.onload = () => res(im);
                im.onerror = rej;
                im.src = url;
            });

            const targetW = 640;
            const scale = Math.min(1, targetW / (img.width || targetW));
            const w = Math.max(1, Math.round((img.width || targetW) * scale));
            const h = Math.max(1, Math.round((img.height || targetW) * scale));

            const canvas = makeCanvas(w, h);
            const ctx = canvas.getContext?.('2d', { willReadFrequently: true }) ?? canvas.getContext('2d');
            ctx.drawImage(img, 0, 0, w, h);
            const imgData = ctx.getImageData(0, 0, w, h);
            const std = pixelStdDev(imgData);

            return {
                type: 'image',
                contentPresent: std > blankStdDevThreshold,
                blankPages: std <= blankStdDevThreshold ? [0] : [],
                totalPages: 1,
                metrics: { std }
            };
        } finally {
            URL.revokeObjectURL(url);
        }
    }

    // --- DOCX content scan (Mammoth + optional JSZip for media) ---
    async function analyzeDocxFile(file, { minChars = 16 } = {}) {
        try {
            await loadScriptOnce('https://unpkg.com/mammoth@1.6.0/mammoth.browser.min.js', {
                check: () => window.mammoth
            });
        } catch (e) {
            console.warn('Mammoth load failed, skipping DOCX scan:', e);
            return { type: 'docx', contentPresent: true, blankPages: [], totalPages: 1, metrics: { textLen: 0, hasMedia: false }, warning: 'mammoth-load-failed' };
        }

        let arrayBuffer;
        try {
            arrayBuffer = await file.arrayBuffer();
        } catch (e) {
            console.warn('DOCX arrayBuffer failed:', e);
            return { type: 'docx', contentPresent: true, blankPages: [], totalPages: 1, metrics: { textLen: 0, hasMedia: false } };
        }

        let rawText = '';
        try {
            const result = await window.mammoth.convertToRawText({ arrayBuffer });
            rawText = (result && result.value) ? result.value.trim() : '';
        } catch (e) {
            console.warn('Mammoth convertToRawText failed:', e);
            rawText = '';
        }

        // Optional: detect embedded media to avoid false “blank”
        let hasMedia = false;
        try {
            await loadScriptOnce('https://cdn.jsdelivr.net/npm/jszip@3.10.1/dist/jszip.min.js', {
                check: () => window.JSZip
            });
            const zip = await window.JSZip.loadAsync(arrayBuffer);
            Object.keys(zip.files).some(path => {
                if (path.startsWith('word/media/')) { hasMedia = true; return true; }
                return false;
            });
        } catch (e) {
            // JSZip optional; ignore failures
        }

        const textLen = rawText.length;
        const contentPresent = textLen >= minChars || hasMedia;

        return {
            type: 'docx',
            contentPresent,
            blankPages: contentPresent ? [] : [0],
            totalPages: 1,
            metrics: { textLen, hasMedia }
        };
    }

    // ---------------------------------------------------------------
    // 2. PDF Analysis – Safe, no GlobalWorkerOptions mutation
    // ---------------------------------------------------------------
    async function analyzePdfFile(file, {
        maxPages = 5,
        minCharsTotal = 20,
        renderScale = 0.8,
        blankStdDevThreshold = 2.5,
        pageTimeoutMs = 4000
    } = {}) {
        try {
            await ensurePdfJs();
        } catch (e) {
            console.warn('PDF.js failed to load – skipping PDF scan', e);
            return { type: 'pdf', contentPresent: true, blankPages: [], totalPages: 1, metrics: { totalChars: 0, pagesScanned: 0 }, warning: 'pdfjs-load-failed' };
        }

        if (!window.pdfjsLib || typeof window.pdfjsLib.getDocument !== 'function') {
            console.warn('PDF.js not available after load');
            return { type: 'pdf', contentPresent: true, blankPages: [], totalPages: 1, metrics: { totalChars: 0, pagesScanned: 0 } };
        }

        let arrayBuffer;
        try { arrayBuffer = await file.arrayBuffer(); }
        catch (e) {
            console.warn('PDF arrayBuffer failed:', e);
            return { type: 'pdf', contentPresent: true, blankPages: [], totalPages: 1, metrics: { totalChars: 0, pagesScanned: 0 } };
        }

        let pdf;
        try {
            pdf = await window.pdfjsLib.getDocument({ data: arrayBuffer }).promise;
        } catch (e) {
            console.warn('PDF getDocument failed:', e);
            return { type: 'pdf', contentPresent: true, blankPages: [], totalPages: 1, metrics: { totalChars: 0, pagesScanned: 0 } };
        }

        const totalPages = pdf.numPages || 0;
        let totalChars = 0;
        const blankPages = [];
        const pagesToScan = Math.min(Math.max(1, maxPages), totalPages);

        const withTimeout = (p, ms) => Promise.race([
            p,
            new Promise((_, rej) => setTimeout(() => rej(new Error('timeout')), ms))
        ]);

        for (let i = 1; i <= pagesToScan; i++) {
            let page;
            try { page = await withTimeout(pdf.getPage(i), pageTimeoutMs); }
            catch (e) { console.warn(`PDF getPage(${i}) failed:`, e); continue; }

            try {
                const textContent = await withTimeout(page.getTextContent(), pageTimeoutMs);
                const pageText = (textContent.items || []).map(it => it.str).join(' ');
                totalChars += (pageText || '').trim().length;
            } catch (_) {}

            try {
                const viewport = page.getViewport({ scale: renderScale });
                const w = Math.max(2, Math.round(viewport.width));
                const h = Math.max(2, Math.round(viewport.height));
                const canvas = makeCanvas(w, h);
                const ctx = canvas.getContext?.('2d', { willReadFrequently: true }) ?? canvas.getContext('2d');

                const renderTask = page.render({ canvasContext: ctx, viewport, intent: 'print' });
                await withTimeout(renderTask.promise, pageTimeoutMs);

                const imgData = ctx.getImageData(0, 0, w, h);
                const std = pixelStdDev(imgData);
                if (std <= blankStdDevThreshold) blankPages.push(i - 1);
            } catch (_) {}
        }

        const contentPresent = totalChars >= minCharsTotal || blankPages.length < pagesToScan;

        return {
            type: 'pdf',
            contentPresent,
            blankPages,
            totalPages,
            metrics: { totalChars, pagesScanned: pagesToScan }
        };
    }

    // --- Unified front-end scanner for (PDF, DOCX, Images) ---
    async function frontEndScanDocument(file, options = {}) {
        const mime = (file.type || '').toLowerCase();
        const name = (file.name || '').toLowerCase();

        try {
            if (mime === 'application/pdf' || name.endsWith('.pdf')) {
                return await analyzePdfFile(file, options.pdf || {});
            }
            if (
                mime === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' ||
                name.endsWith('.docx')
            ) {
                return await analyzeDocxFile(file, options.docx || {});
            }
            if (mime.startsWith('image/') || /\.(png|jpg|jpeg)$/i.test(name)) {
                return await analyzeImageFile(file, options.image || {});
            }

            // Legacy .doc not supported client-side
            if (name.endsWith('.doc') && (mime === 'application/msword' || !mime)) {
                return {
                    type: 'doc',
                    contentPresent: false,
                    blankPages: [0],
                    totalPages: 1,
                    warning: '.doc is not supported for client-side scanning; use server-side validation.'
                };
            }
        } catch (e) {
            console.warn('frontEndScanDocument failed (non-blocking):', e);
            // Fall through to permissive default
        }

        return {
            type: 'unknown',
            contentPresent: true, // don’t block unknowns here; server will validate
            blankPages: [],
            totalPages: 1
        };
    }

    // =========================
    // Validation functions (original + minor hardening)
    // =========================

    function isValidEmail(email) {
        if (!email) return false;
        const trimmed = email.trim();
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        return emailRegex.test(trimmed);
    }

    function validateDimensions(dimensions) {
        if (!dimensions) return false;
        const trimmed = dimensions.trim();
        const dimensionRegex = /^\d{1,4}x\d{1,4}x\d{1,4}$/;
        if (!dimensionRegex.test(trimmed)) return false;

        const [length, width, height] = trimmed.split('x').map(Number);
        return length > 0 && width > 0 && height > 0;
    }

    function validateAge(type, age) {
        const ageNum = parseInt(age);
        if (isNaN(ageNum) || ageNum < 0) return false;

        switch (type) {
            case 'adult': return ageNum >= 18 && ageNum <= 120;
            case 'child': return ageNum >= 2 && ageNum <= 17;
            case 'infant': return true; // infants validated via DOB
            default: return ageNum >= 0 && ageNum <= 120;
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

    // ---- NEW: Client-side check for OTP verification flag ----
    // book.js sets sessionStorage.setItem('ffb_guest_verified', '1') on successful OTP verification.
    // Optionally, if you also store 'ffb_guest_verified_email', we’ll ensure it matches the current email.
    function isGuestEmailVerified(email) {
        try {
            const flag = sessionStorage.getItem('ffb_guest_verified');
            if (flag !== '1') return false;
            const storedEmail = (sessionStorage.getItem('ffb_guest_verified_email') || '').trim().toLowerCase();
            if (!storedEmail) return true; // tolerate absence; treat as verified if flag is set
            const current = (email || '').trim().toLowerCase();
            return storedEmail === current;
        } catch (_) {
            return false;
        }
    }

    // =========================
    // File validation (original + client scanning hook)
    // =========================
    async function validateFile(file, inputElement) {
        // Client-side basic checks
        if (!file) {
            showFieldError(inputElement, ERROR_MESSAGES.fileMissing);
            return { valid: false };
        }

        if (file.size > 2621440) { // 2.5MB
            showFieldError(inputElement, ERROR_MESSAGES.fileTooLarge);
            return { valid: false };
        }

        const validTypes = [
            'image/jpeg', 'image/jpg', 'image/png', 'application/pdf',
            // allow docx for front-end content scan (legacy .doc not supported)
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        ];
        if (!validTypes.includes(file.type) &&
            !/\.(pdf|png|jpe?g|docx)$/i.test(file.name || '')) {
            showFieldError(inputElement, ERROR_MESSAGES.fileTypeInvalid);
            return { valid: false };
        }

        // Optional server-side validation
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

                let result = { valid: true };
                try {
                    result = await response.json();
                } catch (e) {
                    if (!response.ok) {
                        showFieldError(inputElement, ERROR_MESSAGES.fileValidationFailed);
                        return { valid: false };
                    }
                }

                if (result && result.valid === false) {
                    showFieldError(inputElement, result.error || ERROR_MESSAGES.fileValidationFailed);
                    return { valid: false };
                }
            }
        } catch (error) {
            console.warn('File server validation failed (continuing with client checks):', error);
        }

        // --- Front-end content presence & blank detection (best-effort) ---
        try {
            const scan = await frontEndScanDocument(file, {
                pdf:  { maxPages: 5, minCharsTotal: 20, renderScale: 0.8, blankStdDevThreshold: 2.3, pageTimeoutMs: 4000 },
                docx: { minChars: 16 },
                image:{ blankStdDevThreshold: 2.5 }
            });

            if (scan && scan.contentPresent === false) {
                showFieldError(inputElement, 'The document appears to be empty or invalid.');
                return { valid: false };
            }

            if (scan && scan.type === 'pdf') {
                const pagesScanned = scan.metrics?.pagesScanned || 1;
                if (pagesScanned > 0 && scan.blankPages && scan.blankPages.length === pagesScanned) {
                    showFieldError(inputElement, 'All scanned PDF pages appear blank.');
                    return { valid: false };
                }
            }
        } catch (e) {
            console.warn('Front-end document scan failed (not blocking):', e);
            // Continue — we already passed basic checks
        }

        // Success – show preview (original behavior, UPDATED to use sibling .file-preview if available)
        showFilePreview(file, inputElement);
        clearFieldError(inputElement);
        return { valid: true, file };
    }

    // =========================
    // Error Handling (UPDATED: Dark-mode safe colors)
    // =========================
    function displayBackendErrors(errors, targetElement) {
        const normalized = normalizeBackendErrors(errors);

        // Clear all existing errors
        document.querySelectorAll('.error-message.show, .alert-error').forEach(el => {
            el.classList.remove('show');
            el.textContent = '';
        });

        normalized.forEach(error => {
            let errorContainer;

            if (error.field && error.field !== 'general') {
                const fieldSelector = `[name="${CSS.escape(error.field)}"], #${CSS.escape(error.field)}`;
                const field = document.querySelector(fieldSelector);

                if (field) {
                    const containerId = `error-${field.id || field.name || error.field}`;
                    errorContainer = document.getElementById(containerId);
                    if (!errorContainer) {
                        errorContainer = document.createElement('p');
                        errorContainer.id = containerId;
                        errorContainer.className = 'error-message text-red-600 dark:text-red-400 text-sm mt-1 font-medium';
                        if (field.parentNode) {
                            field.parentNode.insertBefore(errorContainer, field.nextSibling);
                        } else {
                            document.body.appendChild(errorContainer);
                        }
                    }

                    field.classList.add(
                        'border-red-600', 'dark:border-red-400',
                        'ring-1', 'ring-red-500', 'dark:ring-red-400'
                    );
                    setTimeout(() => {
                        field.classList.remove(
                            'border-red-600', 'dark:border-red-400',
                            'ring-1', 'ring-red-500', 'dark:ring-red-400'
                        );
                    }, 5000);
                }
            }

            if (!errorContainer) {
                const messagesDiv = document.querySelector('.messages');
                if (messagesDiv) {
                    errorContainer = document.createElement('div');
                    errorContainer.className = 'alert alert-error p-4 mt-4 rounded bg-red-50 border border-red-200 dark:bg-red-950 dark:border-red-800';
                    messagesDiv.appendChild(errorContainer);
                } else {
                    errorContainer = document.createElement('div');
                    errorContainer.className = 'alert alert-error p-4 mt-4 rounded bg-red-50 border border-red-200 dark:bg-red-950 dark:border-red-800';
                    if (targetElement && targetElement.parentNode) {
                        targetElement.parentNode.insertBefore(errorContainer, targetElement.nextSibling);
                    } else {
                        const form = document.getElementById('booking-form');
                        if (form) {
                            form.appendChild(errorContainer);
                        } else {
                            document.body.appendChild(errorContainer);
                        }
                    }
                }
            }

            errorContainer.textContent = error.message || 'An error occurred';
            errorContainer.classList.add('show');
            errorContainer.setAttribute('role', 'alert');
            errorContainer.setAttribute('aria-live', 'assertive');

            try {
                errorContainer.scrollIntoView({ behavior: 'smooth', block: 'center' });
            } catch (_) {}
        });

        try {
            const announcement = document.createElement('div');
            announcement.setAttribute('aria-live', 'polite');
            announcement.style.position = 'fixed';
            announcement.style.left = '-9999px';
            announcement.textContent = `${normalized.length} validation error${normalized.length !== 1 ? 's' : ''}`;
            document.body.appendChild(announcement);
            setTimeout(() => announcement.remove(), 2000);
        } catch (_) {}
    }

    function showFieldError(field, message) {
        if (typeof field === 'string') {
            const byId = document.getElementById(field);
            const byName = document.querySelector(`[name="${CSS.escape(field)}"]`);
            field = byId || byName || field;
        }
        if (!(field instanceof HTMLElement)) {
            console.warn('showFieldError: field element not found; falling back to general alert:', message);
            displayBackendErrors([{ field: 'general', message }]);
            return;
        }

        const key = field.id || field.name || 'unknown';
        let errorEl = document.getElementById(`error-${key}`);

        if (!errorEl) {
            errorEl = document.createElement('p');
            errorEl.id = `error-${key}`;
            errorEl.className = 'error-message text-red-600 dark:text-red-400 text-sm mt-1 font-medium';
            if (field.parentNode) {
                field.parentNode.insertBefore(errorEl, field.nextSibling);
            } else {
                document.body.appendChild(errorEl);
            }
        }

        errorEl.textContent = message;
        errorEl.classList.add('show');

        try {
            field.classList.add(
                'border-red-600', 'dark:border-red-400',
                'ring-1', 'ring-red-500', 'dark:ring-red-400'
            );
            field.focus({ preventScroll: true });
        } catch (_) {}

        setTimeout(() => {
            field.classList.remove(
                'border-red-600', 'dark:border-red-400',
                'ring-1', 'ring-red-500', 'dark:ring-red-400'
            );
            errorEl.classList.remove('show');
        }, 5000);
    }

    function clearFieldError(field) {
        if (typeof field === 'string') {
            const byId = document.getElementById(field);
            const byName = document.querySelector(`[name="${CSS.escape(field)}"]`);
            field = byId || byName || field;
        }
        if (!(field instanceof HTMLElement)) return;

        const errorId = `error-${field.id || field.name}`;
        const errorEl = document.getElementById(errorId);
        if (errorEl) {
            errorEl.classList.remove('show');
            errorEl.textContent = '';
        }
        field.classList.remove(
            'border-red-600', 'dark:border-red-400',
            'ring-1', 'ring-red-500', 'dark:ring-red-400'
        );
    }

    function toggleButtonLoading(button, isLoading) {
        if (!button) return;

        const originalContent = button.dataset.originalContent || button.innerHTML;
        button.dataset.originalContent = originalContent;

        if (isLoading) {
            button.disabled = true;
            button.setAttribute('aria-busy', 'true');

            const spinnerHTML = `
                <svg class="animate-spin -ml-1 mr-2 h-4 w-4 inline" fill="none" viewBox="0 0 24 24" aria-hidden="true">
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
        // UPDATED: prefer sibling .file-preview if present; fallback to #preview-${input.name}
        let preview = input?.closest('.form-group')?.querySelector('.file-preview');
        if (!preview) {
            const previewId = `preview-${input.name}`;
            preview = document.getElementById(previewId);
        }

        if (!preview) return;

        preview.innerHTML = '';

        if (file.type.startsWith('image/')) {
            const img = document.createElement('img');
            img.src = URL.createObjectURL(file);
            img.className = 'max-w-48 h-32 object-cover rounded border mt-2';
            img.alt = 'File preview';
            preview.appendChild(img);
            img.onload = () => URL.revokeObjectURL(img.src);
        } else {
            const icon = document.createElement('div');
            icon.className = 'w-48 h-32 border-2 border-dashed border-gray-300 rounded flex items-center justify-center';
            icon.innerHTML = file.type === 'application/pdf' ? 'PDF' : (file.name.endsWith('.docx') ? 'DOCX' : 'Document');
            preview.appendChild(icon);
        }
    }

    function getCsrfToken() {
        return window.csrfToken ||
               document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
               '';
    }

    // =========================
    // Step Validation (UPDATED: Step 1 now checks OTP verification)
    // =========================
    function validateStep(currentStep, formData) {
        const errors = [];
        const passengerTypes = ['adult', 'child', 'infant'];
        const isAuthenticated = window.isAuthenticated === true || window.isAuthenticated === "true";

        switch (currentStep) {
            case 1: {
                if (!formData.get('schedule_id')) {
                    errors.push({ field: 'schedule_id', message: ERROR_MESSAGES.scheduleRequired });
                }
                if (!isAuthenticated) {
                    const email = formData.get('guest_email')?.trim();
                    if (!email) {
                        errors.push({ field: 'guest_email', message: ERROR_MESSAGES.emailRequired });
                    } else if (!isValidEmail(email)) {
                        errors.push({ field: 'guest_email', message: ERROR_MESSAGES.emailInvalid });
                    } else {
                        // NEW: require OTP verification on the client as well
                        if (!isGuestEmailVerified(email)) {
                            errors.push({ field: 'guest_email', message: ERROR_MESSAGES.emailNotVerified });
                        }
                    }
                }
                break;
            }

            case 2: {
                const adults = parseInt(formData.get('adults') || 0);
                if (adults === 0) {
                    errors.push({ field: 'adults', message: ERROR_MESSAGES.noAdults });
                }

                passengerTypes.forEach(type => {
                    const count = parseInt(formData.get(`${type}s`) || 0);
                    for (let i = 0; i < count; i++) {

                        // ---- names -------------------------------------------------
                        if (!formData.get(`${type}_first_name_${i}`)?.trim()) {
                            errors.push({ field: `${type}_first_name_${i}`, message: ERROR_MESSAGES.firstNameRequired });
                        }
                        if (!formData.get(`${type}_last_name_${i}`)?.trim()) {
                            errors.push({ field: `${type}_last_name_${i}`, message: ERROR_MESSAGES.lastNameRequired });
                        }

                        // ---- age / DOB --------------------------------------------
                        if (type !== 'infant') {
                            const age = formData.get(`${type}_age_${i}`);
                            if (!age || !validateAge(type, age)) {
                                errors.push({ field: `${type}_age_${i}`, message: ERROR_MESSAGES.ageInvalid });
                            }
                        } else {
                            const dob = formData.get(`infant_dob_${i}`);
                            if (!dob) {
                                errors.push({ field: `infant_dob_${i}`, message: ERROR_MESSAGES.dobRequired });
                            } else if (!validateInfantDob(dob)) {
                                errors.push({ field: `infant_dob_${i}`, message: ERROR_MESSAGES.dobInvalid });
                            }
                        }

                        // ---- DOCUMENT (CRITICAL CHANGE) ---------------------------
                        const docKey = `${type}_id_document_${i}`;
                        const val = formData.get(docKey);
                        const hasFile = val instanceof File ? (val.size > 0 && !!val.name) : !!val;

                        if (type !== 'infant') {
                            // Adults & Children MUST have a non-empty file
                            if (!hasFile) {
                                errors.push({
                                    field: `${type}_id_document_${i}`,   // UI field name (matches template)
                                    message: ERROR_MESSAGES.idDocumentRequired
                                });
                            }
                        } else {
                            // Infants MUST NOT have a file
                            if (val instanceof File && val.size > 0) {
                                errors.push({
                                    field: `${type}_id_document_${i}`,
                                    message: 'Infants must not upload documents'
                                });
                            }
                        }

                        // ---- linked adult -----------------------------------------
                        if (type !== 'adult' && !formData.get(`${type}_linked_adult_${i}`)) {
                            errors.push({ field: `${type}_linked_adult_${i}`, message: ERROR_MESSAGES.linkedAdultRequired });
                        }
                    }
                });
                break;
            }

            case 3: {
                if (formData.get('add_vehicle') === 'on') {
                    if (!formData.get('vehicle_type')) {
                        errors.push({ field: 'vehicle_type', message: ERROR_MESSAGES.vehicleTypeRequired });
                    }
                    const dims = formData.get('vehicle_dimensions');
                    if (dims && !validateDimensions(dims)) {
                        errors.push({ field: 'vehicle_dimensions', message: ERROR_MESSAGES.vehicleDimensionsInvalid });
                    }
                }
                if (formData.get('add_cargo') === 'on') {
                    if (!formData.get('cargo_type')) {
                        errors.push({ field: 'cargo_type', message: ERROR_MESSAGES.cargoTypeRequired });
                    }
                    const weight = parseFloat(formData.get('cargo_weight_kg'));
                    if (isNaN(weight) || weight <= 0) {
                        errors.push({ field: 'cargo_weight_kg', message: ERROR_MESSAGES.cargoWeightInvalid });
                    }
                }
                if (window.bookingConfig?.addOns) {
                    window.bookingConfig.addOns.forEach(addon => {
                        const qtyRaw = formData.get(`${addon.id}_quantity`);
                        if (qtyRaw !== null && qtyRaw !== undefined && qtyRaw !== '') {
                            const qty = parseInt(qtyRaw, 10);
                            if (!Number.isFinite(qty) || qty < 0 || qty > (addon.max_quantity || 10)) {
                                errors.push({ field: `${addon.id}_quantity`, message: `Invalid quantity for ${addon.label}` });
                            }
                        }
                    });
                }
                break;
            }

            case 4: {
                if (!formData.get('privacy_consent')) {
                    errors.push({ field: 'privacy_consent', message: ERROR_MESSAGES.privacyConsentRequired });
                }
                break;
            }
        }

        return { valid: errors.length === 0, errors };
    }

    // =========================
    // Public API (original)
    // =========================
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
        getCsrfToken,
        // NEW export
        isGuestEmailVerified
    };

    window.ERROR_MESSAGES = ERROR_MESSAGES;

    console.log('Validation utilities loaded successfully');
    console.log('Available validators:', Object.keys(window.validationUtils));
})();
