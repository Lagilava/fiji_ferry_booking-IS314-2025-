document.addEventListener('DOMContentLoaded', function() {
    // Reuse theme colors from admin_custom.js
    const theme = window.colors ? window.colors[window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'] : {
        text: '#1f2937',
        warning: '#b91c1c',
        success: '#047857',
        secondaryHover: '#d1d5db',
        background: '#f8fafc',
        primary: '#1e40af',
        primaryHover: '#2563eb',
        info: '#0288d1'
    };

    // Get CSRF token
    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        console.log(`CSRF token retrieved: ${cookieValue ? 'Present' : 'Missing'}`);
        return cookieValue;
    }

    // QR Code Scanner Logic
    let videoStream = null;
    let isScanning = false;
    let scanHistory = [];
    let currentQrToken = null; // Global storage for current QR token

    // Load jsQR with fallbacks
    function loadJsQR() {
        return new Promise((resolve, reject) => {
            if (typeof jsQR !== 'undefined') {
                console.log('jsQR already loaded.');
                resolve();
                return;
            }
            const cdnScript = document.createElement('script');
            cdnScript.src = 'https://unpkg.com/jsqr@1.4.0/dist/jsQR.min.js';
            cdnScript.onload = () => {
                console.log('jsQR loaded from CDN.');
                resolve();
            };
            cdnScript.onerror = () => {
                console.warn('jsQR CDN failed. Attempting local fallback.');
                const localScript = document.createElement('script');
                localScript.src = '/static/js/jsQR.min.js';
                localScript.onload = () => {
                    console.log('jsQR loaded from local.');
                    resolve();
                };
                localScript.onerror = () => {
                    console.error('Failed to load jsQR from local fallback.');
                    reject(new Error('Failed to load jsQR library.'));
                };
                document.head.appendChild(localScript);
            };
            document.head.appendChild(cdnScript);
        });
    }

    function startQRScanner() {
        const video = document.getElementById('qr-video');
        const qrResult = document.getElementById('qr-result');
        const qrError = document.getElementById('qr-error');
        const qrSection = document.getElementById('qrScannerSection');
        const scanOverlay = document.getElementById('qr-scan-overlay');
        const scanHistoryList = document.getElementById('qr-scan-history');
        const closeButton = document.getElementById('qr-close');

        if (!video || !qrResult || !qrError || !qrSection || !scanOverlay || !scanHistoryList || !closeButton) {
            console.error('QR scanner elements not found:', {
                video, qrResult, qrError, qrSection, scanOverlay, scanHistoryList, closeButton
            });
            alert('QR scanner initialization failed. One or more interface elements are missing. Please refresh the page.');
            return;
        }

        // Show the QR scanner section
        qrSection.style.display = 'block';
        qrSection.style.opacity = '0';
        qrSection.style.transition = 'opacity 0.5s ease-out';
        setTimeout(() => { qrSection.style.opacity = '1'; }, 10);

        // Reset UI and clear stored token
        qrResult.style.display = 'none';
        qrError.style.display = 'none';
        video.style.display = 'block';
        scanOverlay.style.display = 'block';
        isScanning = true;
        scanHistory = [];
        scanHistoryList.innerHTML = '';
        currentQrToken = null; // Clear previous token
        const hiddenTokenField = document.getElementById('qr-actual-token');
        if (hiddenTokenField) hiddenTokenField.value = ''; // Clear hidden field

        // Stop any existing stream
        if (videoStream) {
            videoStream.getTracks().forEach(track => track.stop());
            videoStream = null;
            video.srcObject = null;
            console.log('Previous camera stream stopped.');
        }

        // Request camera access
        navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' } })
            .then(stream => {
                videoStream = stream;
                video.srcObject = stream;
                video.play().catch(err => {
                    console.error('Error playing video:', err);
                    qrError.style.display = 'block';
                    qrError.textContent = 'Unable to start video stream. Please check permissions and try again.';
                    video.style.display = 'none';
                    scanOverlay.style.display = 'none';
                    isScanning = false;
                });
                console.log('QR scanner camera started');

                // Scan QR code with optimized canvas
                const canvas = document.createElement('canvas');
                const context = canvas.getContext('2d', { willReadFrequently: true });
                let lastScannedCode = null;

                function scan() {
                    if (!isScanning) return;
                    if (video.readyState === video.HAVE_ENOUGH_DATA) {
                        canvas.width = video.videoWidth;
                        canvas.height = video.videoHeight;
                        context.drawImage(video, 0, 0, canvas.width, canvas.height);
                        const imageData = context.getImageData(0, 0, canvas.width, canvas.height);
                        try {
                            const code = jsQR(imageData.data, imageData.width, imageData.height);
                            if (code && code.data && code.data !== lastScannedCode) {
                                lastScannedCode = code.data;
                                console.log('QR code scanned:', code.data);
                                currentQrToken = code.data; // Store globally
                                validateQRCode(code.data, scanHistoryList);
                                isScanning = false;
                                scanOverlay.style.display = 'none';
                            }
                            requestAnimationFrame(scan);
                        } catch (err) {
                            console.error('Error processing QR code:', err);
                            qrError.style.display = 'block';
                            qrError.textContent = 'Error processing QR code. Please try again.';
                            isScanning = false;
                            scanOverlay.style.display = 'none';
                        }
                    } else {
                        requestAnimationFrame(scan);
                    }
                }
                scan();
            })
            .catch(error => {
                console.error('Error accessing camera:', error);
                qrError.style.display = 'block';
                qrError.textContent = 'Unable to access camera. Please check permissions or try another device.';
                video.style.display = 'none';
                scanOverlay.style.display = 'none';
                isScanning = false;
            });

        // Handle section close - clears stored data
        const closeHandler = () => {
            if (videoStream) {
                videoStream.getTracks().forEach(track => track.stop());
                videoStream = null;
                console.log('QR scanner camera stopped');
            }
            video.srcObject = null;
            qrResult.style.display = 'none';
            qrError.style.display = 'none';
            scanOverlay.style.display = 'none';
            isScanning = false;
            scanHistory = [];
            scanHistoryList.innerHTML = '';
            currentQrToken = null; // Clear stored token
            if (hiddenTokenField) hiddenTokenField.value = ''; // Clear hidden field
            // Hide the section with fade-out
            qrSection.style.opacity = '0';
            setTimeout(() => {
                qrSection.style.display = 'none';
                // Restore focus
                const scanQrButton = document.getElementById('scan-qr-code');
                if (scanQrButton) scanQrButton.focus();
            }, 500);
        };

        // Remove existing listeners to prevent duplicates
        closeButton.replaceWith(closeButton.cloneNode(true));
        const newCloseButton = document.getElementById('qr-close');
        newCloseButton.addEventListener('click', closeHandler);
    }

    function validateQRCode(qrToken, scanHistoryList) {
        const qrResult = document.getElementById('qr-result');
        const qrError = document.getElementById('qr-error');
        const qrTicketId = document.getElementById('qr-ticket-id');
        const qrBookingId = document.getElementById('qr-booking-id');
        const qrPassenger = document.getElementById('qr-passenger');
        const qrRoute = document.getElementById('qr-route');
        const qrBookingDate = document.getElementById('qr-booking-date');
        const qrTicketStatus = document.getElementById('qr-ticket-status');
        const hiddenTokenField = document.getElementById('qr-actual-token');

        if (!qrResult || !qrError || !qrTicketId || !qrBookingId || !qrPassenger || !qrRoute || !qrBookingDate || !qrTicketStatus) {
            console.error('QR result elements not found:', {
                qrResult, qrError, qrTicketId, qrBookingId, qrPassenger, qrRoute, qrBookingDate, qrTicketStatus
            });
            alert('QR scanner result elements missing. Please refresh the page.');
            return;
        }

        // Store the actual QR token in hidden field and global variable
        if (hiddenTokenField) {
            hiddenTokenField.value = qrToken;
        }
        currentQrToken = qrToken;
        console.log('Stored QR token:', qrToken);

        // Show loading state
        qrError.style.display = 'none';
        qrResult.style.display = 'none';

        fetch('/admin/scan-qr-code/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken'),
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify({ qr_token: qrToken })
        })
        .then(response => {
            if (!response.ok) throw new Error(`HTTP error! Status: ${response.status}`);
            return response.json();
        })
        .then(data => {
            if (data.error) {
                qrError.style.display = 'block';
                qrError.textContent = data.error;
                qrResult.style.display = 'none';
                console.error('QR validation error:', data.error);
                // Clear stored token on validation error
                if (hiddenTokenField) hiddenTokenField.value = '';
                currentQrToken = null;
            } else {
                qrResult.style.display = 'block';
                qrError.style.display = 'none';
                qrTicketId.textContent = data.ticket_id || 'N/A';
                qrBookingId.textContent = data.booking_id || 'N/A';
                qrPassenger.textContent = data.passenger || 'N/A';
                qrRoute.textContent = data.route || 'N/A';
                qrBookingDate.textContent = data.booking_date ? new Date(data.booking_date).toLocaleString() : 'N/A';
                qrTicketStatus.textContent = data.status || 'N/A';

                // Visual success feedback
                qrResult.style.border = '2px solid #28a745';
                qrResult.style.borderRadius = '8px';
                qrResult.style.padding = '10px';
                qrResult.style.backgroundColor = '#d4edda';
                qrResult.style.transition = 'all 0.3s ease';

                setTimeout(() => {
                    qrResult.style.border = '';
                    qrResult.style.borderRadius = '';
                    qrResult.style.padding = '';
                    qrResult.style.backgroundColor = '';
                }, 2000);

                console.log('QR code validated successfully:', data);

                // Enable/disable buttons based on current status (using 'active' not 'unused')
                const markUsedBtn = document.getElementById('qr-mark-used');
                const markUnusedBtn = document.getElementById('qr-mark-unused');
                const viewBookingBtn = document.getElementById('qr-view-booking');
                const logActivityBtn = document.getElementById('qr-log-activity');

                if (markUsedBtn) {
                    markUsedBtn.disabled = data.status === 'used';
                    if (data.status === 'used') {
                        markUsedBtn.style.opacity = '0.6';
                        markUsedBtn.title = 'Ticket already marked as used';
                    } else {
                        markUsedBtn.style.opacity = '1';
                        markUsedBtn.title = 'Mark this ticket as used';
                    }
                }

                if (markUnusedBtn) {
                    markUnusedBtn.disabled = data.status === 'active';
                    if (data.status === 'active') {
                        markUnusedBtn.style.opacity = '0.6';
                        markUnusedBtn.title = 'Ticket is already active';
                    } else {
                        markUnusedBtn.style.opacity = '1';
                        markUnusedBtn.title = 'Mark this ticket as active/unused';
                    }
                }

                if (viewBookingBtn) {
                    viewBookingBtn.disabled = !data.booking_id;
                    viewBookingBtn.style.opacity = data.booking_id ? '1' : '0.6';
                }

                if (logActivityBtn) {
                    logActivityBtn.disabled = false;
                    logActivityBtn.style.opacity = '1';
                }

                // Add to scan history
                const scanTime = new Date().toLocaleString();
                scanHistory.push({ ticket_id: data.ticket_id, status: data.status, time: scanTime, qr_token: qrToken });
                const historyItem = document.createElement('li');
                historyItem.className = 'list-group-item';
                historyItem.style.cssText = `color: ${theme.text}; font-size: 0.9rem; border-left: 4px solid ${theme.success}; padding-left: 10px;`;
                historyItem.innerHTML = `
                    <strong>Scanned:</strong> Ticket #${data.ticket_id || 'N/A'}
                    <span class="badge bg-${data.status === 'used' ? 'success' : data.status === 'active' ? 'primary' : 'secondary'}">${data.status || 'N/A'}</span>
                    <small class="text-muted float-end">${scanTime}</small>
                `;
                scanHistoryList.prepend(historyItem);
            }
        })
        .catch(error => {
            qrError.style.display = 'block';
            qrError.textContent = 'Error validating QR code. Please try again.';
            qrResult.style.display = 'none';
            console.error('Error validating QR code:', error);
            // Clear stored token on error
            if (hiddenTokenField) hiddenTokenField.value = '';
            currentQrToken = null;
        });
    }

    function updateTicketStatus(newStatus) {
        const qrResult = document.getElementById('qr-result');
        const qrError = document.getElementById('qr-error');
        const qrTicketStatus = document.getElementById('qr-ticket-status');
        const scanHistoryList = document.getElementById('qr-scan-history');
        const hiddenTokenField = document.getElementById('qr-actual-token');

        if (!qrResult || !qrError || !qrTicketStatus || !scanHistoryList || !hiddenTokenField) {
            console.error('QR update elements not found:', {
                qrResult, qrError, qrTicketStatus, scanHistoryList, hiddenTokenField
            });
            alert('QR scanner update elements missing. Please refresh the page.');
            return;
        }

        const actualQrToken = hiddenTokenField.value;
        if (!actualQrToken) {
            console.error('No QR token available for status update');
            qrError.style.display = 'block';
            qrError.textContent = 'No QR token available. Please scan a ticket first.';
            return;
        }

        console.log(`Updating ticket status for QR token: ${actualQrToken} to ${newStatus}`);

        // Show loading state
        qrError.style.display = 'none';
        const originalStatusText = qrTicketStatus.textContent;
        qrTicketStatus.textContent = `Updating to ${newStatus}...`;

        fetch('/admin/scan-qr-code/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken'),
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify({
                qr_token: actualQrToken,
                ticket_status: newStatus
            })
        })
        .then(response => {
            if (!response.ok) {
                return response.json().then(data => {
                    throw new Error(data.error || `HTTP error! Status: ${response.status}`);
                });
            }
            return response.json();
        })
        .then(data => {
            if (data.error) {
                qrError.style.display = 'block';
                qrError.textContent = data.error;
                qrTicketStatus.textContent = originalStatusText; // Restore original
                console.error('Ticket status update error:', data.error);
            } else {
                qrError.style.display = 'none';
                qrTicketStatus.textContent = data.status || 'N/A';

                // Visual success feedback
                qrTicketStatus.style.color = theme.success;
                qrTicketStatus.style.fontWeight = 'bold';
                setTimeout(() => {
                    qrTicketStatus.style.color = '';
                    qrTicketStatus.style.fontWeight = '';
                }, 2000);

                console.log(`Ticket status updated to ${newStatus}:`, data);

                // Update button states
                const markUsedBtn = document.getElementById('qr-mark-used');
                const markUnusedBtn = document.getElementById('qr-mark-unused');
                if (markUsedBtn) {
                    markUsedBtn.disabled = data.status === 'used';
                    markUsedBtn.style.opacity = data.status === 'used' ? '0.6' : '1';
                }
                if (markUnusedBtn) {
                    markUnusedBtn.disabled = data.status === 'active';
                    markUnusedBtn.style.opacity = data.status === 'active' ? '0.6' : '1';
                }

                // Update scan history
                const scanTime = new Date().toLocaleString();
                scanHistory.push({ ticket_id: actualQrToken, status: data.status, time: scanTime });
                const historyItem = document.createElement('li');
                historyItem.className = 'list-group-item';
                historyItem.style.cssText = `color: ${theme.text}; font-size: 0.9rem; border-left: 4px solid ${theme.success}; padding-left: 10px; background-color: ${theme.background};`;
                historyItem.innerHTML = `
                    <strong>Updated:</strong> Ticket status changed to
                    <span class="badge bg-${data.status === 'used' ? 'success' : 'primary'}">${data.status}</span>
                    <small class="text-muted float-end">${scanTime}</small>
                `;
                scanHistoryList.prepend(historyItem);

                // Notify user with better UX
                const toast = document.createElement('div');
                toast.style.cssText = `
                    position: fixed; top: 20px; right: 20px; background: ${theme.success};
                    color: white; padding: 15px 20px; border-radius: 5px; z-index: 9999;
                    box-shadow: 0 4px 12px rgba(0,0,0,0.15); transform: translateX(400px);
                    transition: transform 0.3s ease;
                `;
                toast.textContent = `Ticket status updated to ${data.status} ✓`;
                document.body.appendChild(toast);

                setTimeout(() => { toast.style.transform = 'translateX(0)'; }, 100);
                setTimeout(() => {
                    toast.style.transform = 'translateX(400px)';
                    setTimeout(() => document.body.removeChild(toast), 300);
                }, 3000);

                // Update recent bookings table
                updateRecentBookingsTable();
            }
        })
        .catch(error => {
            qrError.style.display = 'block';
            qrError.textContent = error.message || 'Error updating ticket status. Please try again.';
            qrTicketStatus.textContent = originalStatusText; // Restore original
            console.error('Error updating ticket status:', error);
        });
    }

    function updateRecentBookingsTable() {
        fetch('/admin/analytics-data/?chart_type=recent_bookings', {
            headers: {
                'X-Requested-With': 'XMLHttpRequest',
                'X-CSRFToken': getCookie('csrftoken')
            }
        })
        .then(response => {
            if (!response.ok) throw new Error(`HTTP error! Status: ${response.status}`);
            return response.json();
        })
        .then(data => {
            const dataElement = document.getElementById('recent-bookings-data');
            if (!dataElement) {
                console.error('Recent bookings data element not found.');
                return;
            }
            dataElement.textContent = JSON.stringify(data.recent_bookings);

            if (typeof window.jQuery !== 'undefined' && window.jQuery.fn.DataTable) {
                const table = window.jQuery('#recent-bookings-table').DataTable();
                if (table) {
                    table.clear();
                    (data.recent_bookings || []).forEach(booking => {
                        table.row.add([
                            booking.id || 'N/A',
                            booking.user_email || 'N/A',
                            `<span title="${booking.route || 'N/A'}">${booking.route || 'N/A'}</span>`,
                            booking.booking_date ? new Date(booking.booking_date).toLocaleString('en-GB', {
                                hour: '2-digit', minute: '2-digit', day: '2-digit', month: 'short', year: 'numeric'
                            }) : 'N/A',
                            `<span data-status="${booking.status || 'N/A'}" class="badge bg-${booking.status === 'confirmed' ? 'success' : booking.status === 'cancelled' ? 'danger' : 'warning'}">${booking.status || 'N/A'}</span>`
                        ]).draw();
                    });
                    console.log('Recent bookings table updated after ticket status change.');
                }
            }
        })
        .catch(error => {
            console.error('Error updating recent bookings:', error);
        });
    }

    function logActivity(qrToken) {
        const qrError = document.getElementById('qr-error');
        const scanHistoryList = document.getElementById('qr-scan-history');

        if (!qrError || !scanHistoryList) {
            console.error('QR log elements not found:', { qrError, scanHistoryList });
            alert('QR scanner log elements missing. Please refresh the page.');
            return;
        }

        fetch('/admin/log-qr-scan/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken'),
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify({ qr_token: qrToken })
        })
        .then(response => {
            if (!response.ok) throw new Error(`HTTP error! Status: ${response.status}`);
            return response.json();
        })
        .then(data => {
            if (data.error) {
                qrError.style.display = 'block';
                qrError.textContent = data.error;
                console.error('Activity log error:', data.error);
            } else {
                qrError.style.display = 'none';
                console.log('Activity logged:', data);

                // Update scan history
                const scanTime = new Date().toLocaleString();
                scanHistory.push({ ticket_id: qrToken, status: 'logged', time: scanTime });
                const historyItem = document.createElement('li');
                historyItem.className = 'list-group-item';
                historyItem.style.cssText = `color: ${theme.info}; font-size: 0.9rem; border-left: 4px solid ${theme.info}; padding-left: 10px;`;
                historyItem.innerHTML = `
                    <strong>Activity Logged:</strong> Scan recorded
                    <small class="text-muted float-end">${scanTime}</small>
                `;
                scanHistoryList.prepend(historyItem);

                // Success notification
                alert('Scan activity logged successfully.');
            }
        })
        .catch(error => {
            qrError.style.display = 'block';
            qrError.textContent = 'Error logging activity. Please try again.';
            console.error('Error logging activity:', error);
        });
    }

    // Initialize QR scanner button
    const scanQrButton = document.getElementById('scan-qr-code');
    if (scanQrButton) {
        scanQrButton.addEventListener('click', () => {
            loadJsQR()
                .then(() => {
                    console.log('Starting QR scanner.');
                    startQRScanner();
                })
                .catch(error => {
                    console.error('Error loading jsQR:', error);
                    const qrError = document.getElementById('qr-error');
                    if (qrError) {
                        qrError.style.display = 'block';
                        qrError.textContent = 'Failed to load QR scanner library. Please check your network and try again.';
                    }
                    alert('Failed to load QR scanner library. Please check your network or ensure the jsQR library is available.');
                });
        });
    }

    // UPDATED: Mark as Used button - only passes status
    const markUsedBtn = document.getElementById('qr-mark-used');
    if (markUsedBtn) {
        markUsedBtn.addEventListener('click', () => {
            if (!markUsedBtn.disabled) {
                updateTicketStatus('used');
            }
        });
    }

    // UPDATED: Mark as Active button - uses 'active' status
    const markUnusedBtn = document.getElementById('qr-mark-unused');
    if (markUnusedBtn) {
        markUnusedBtn.addEventListener('click', () => {
            if (!markUnusedBtn.disabled) {
                updateTicketStatus('active');
            }
        });
    }

    // View Booking button
    const viewBookingBtn = document.getElementById('qr-view-booking');
    if (viewBookingBtn) {
        viewBookingBtn.addEventListener('click', () => {
            const bookingId = document.getElementById('qr-booking-id')?.textContent;
            if (bookingId && bookingId !== 'N/A') {
                window.location.href = `/admin/bookings/booking/${bookingId}/change/`;
            } else {
                alert('No valid booking ID available.');
            }
        });
    }

    // UPDATED: Log Activity button - uses hidden field
    const logActivityBtn = document.getElementById('qr-log-activity');
    if (logActivityBtn) {
        logActivityBtn.addEventListener('click', () => {
            const hiddenTokenField = document.getElementById('qr-actual-token');
            const actualQrToken = hiddenTokenField ? hiddenTokenField.value : null;
            if (actualQrToken) {
                logActivity(actualQrToken);
            } else {
                alert('No valid QR token available. Please scan a ticket first.');
            }
        });
    }

    // Scan Again button - clears previous data
    const scanAgainBtn = document.getElementById('qr-scan-again');
    if (scanAgainBtn) {
        scanAgainBtn.addEventListener('click', () => {
            const qrResult = document.getElementById('qr-result');
            const qrError = document.getElementById('qr-error');
            const video = document.getElementById('qr-video');
            const scanOverlay = document.getElementById('qr-scan-overlay');
            const hiddenTokenField = document.getElementById('qr-actual-token');
            const scanHistoryList = document.getElementById('qr-scan-history');

            if (!qrResult || !qrError || !video || !scanOverlay || !scanHistoryList) {
                console.error('QR scan again elements not found');
                alert('QR scanner elements missing for scan again. Please refresh the page.');
                return;
            }

            // Clear previous data for new scan
            qrResult.style.display = 'none';
            qrError.style.display = 'none';
            video.style.display = 'block';
            scanOverlay.style.display = 'block';
            isScanning = true;
            currentQrToken = null;
            if (hiddenTokenField) hiddenTokenField.value = '';
            scanHistoryList.innerHTML = '';
            console.log('Resumed QR scanning - cleared previous data');
        });
    }

    // Initialize Tooltips with Tippy.js for buttons
    if (typeof tippy !== 'undefined') {
        tippy('#qr-mark-used, #qr-mark-unused, #qr-view-booking, #qr-log-activity, #qr-scan-again, #qr-close, #scan-qr-code', {
            content: element => element?.getAttribute('data-tippy-content') || element?.getAttribute('aria-label') || 'Action',
            theme: window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light',
            placement: 'top',
            animation: 'fade',
            arrow: true,
            role: 'tooltip'
        });
    } else {
        console.warn('Tippy.js not loaded.');
    }

    // Keyboard shortcuts for accessibility
    document.addEventListener('keydown', (e) => {
        if (e.ctrlKey || e.metaKey) {
            switch(e.key) {
                case 'q':
                case 'Q':
                    e.preventDefault();
                    document.getElementById('scan-qr-code')?.click();
                    break;
                case 'u':
                    e.preventDefault();
                    document.getElementById('qr-mark-used')?.click();
                    break;
                case 'a':
                    e.preventDefault();
                    document.getElementById('qr-mark-unused')?.click();
                    break;
            }
        }
        if (e.key === 'Escape' && document.getElementById('qrScannerSection').style.display === 'block') {
            document.getElementById('qr-close')?.click();
        }
    });

    console.log('QR Scanner initialized successfully');
});