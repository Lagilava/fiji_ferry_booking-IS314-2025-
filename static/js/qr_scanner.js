document.addEventListener('DOMContentLoaded', function() {
    // Reuse theme colors from admin_custom.css
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

    // Load jsQR with fallbacks
    function loadJsQR() {
        return new Promise((resolve, reject) => {
            if (typeof jsQR !== 'undefined') {
                console.log('jsQR already loaded.');
                resolve();
                return;
            }
            const cdnScript = document.createElement('script');
            cdnScript.src = 'https://cdn.jsdelivr.net/npm/jsqr@1.4.0/dist/jsQR.min.js';
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

    // Check camera permission
    async function checkCameraPermission() {
        if (!navigator.permissions || !navigator.permissions.query) {
            console.warn('Permissions API not supported. Assuming permission prompt.');
            return true;
        }
        try {
            const permissionStatus = await navigator.permissions.query({ name: 'camera' });
            if (permissionStatus.state === 'granted') {
                console.log('Camera permission already granted.');
                return true;
            } else if (permissionStatus.state === 'prompt') {
                console.log('Camera permission prompt required.');
                return confirm('This feature requires camera access to scan QR codes. Allow camera access?');
            } else {
                console.error('Camera permission denied.');
                alert('Camera access is required to scan QR codes. Please enable camera permissions in your browser settings.');
                return false;
            }
        } catch (error) {
            console.error('Error checking camera permission:', error);
            return true; // Fallback to prompt
        }
    }

    // QR Code Scanner Logic
    let videoStream = null;
    let isScanning = false;
    let scanHistory = [];
    let currentQrToken = null;

    function startQRScanner() {
        const video = document.getElementById('qr-video');
        const qrResult = document.getElementById('qr-result');
        const qrError = document.getElementById('qr-error');
        const qrSection = document.getElementById('qrScannerSection');
        const scanOverlay = document.getElementById('qr-scan-overlay');
        const scanProgress = document.getElementById('qr-scan-progress');
        const scanFeedback = document.getElementById('qr-scan-feedback');
        const scanHistoryList = document.querySelector('#qr-scan-history .list-group');
        const closeButton = document.getElementById('qr-close');

        if (!video || !qrResult || !qrError || !qrSection || !scanOverlay || !scanProgress || !scanFeedback || !scanHistoryList || !closeButton) {
            console.error('QR scanner elements not found:', {
                video, qrResult, qrError, qrSection, scanOverlay, scanProgress, scanFeedback, scanHistoryList, closeButton
            });
            alert('QR scanner initialization failed. Required elements are missing. Please refresh the page.');
            return;
        }

        // Check camera permission
        checkCameraPermission().then(hasPermission => {
            if (!hasPermission) {
                qrError.style.display = 'block';
                qrError.textContent = 'Camera access denied. Please enable camera permissions and try again.';
                return;
            }

            // Show QR scanner section with smooth transition
            qrSection.style.display = 'block';
            qrSection.style.opacity = '0';
            qrSection.style.transition = 'opacity 0.5s ease-out';
            setTimeout(() => { qrSection.style.opacity = '1'; }, 10);

            // Reset UI
            qrResult.style.display = 'none';
            qrError.style.display = 'none';
            video.style.display = 'block';
            scanOverlay.style.display = 'block';
            scanProgress.style.display = 'block';
            scanFeedback.style.display = 'block';
            scanFeedback.textContent = 'Scanning...';
            const infoColor = theme.info || '#007bff';  // fallback to a default blue
            scanFeedback.style.background = `rgba(${infoColor.replace('#', '')}, 0.1)`;
            scanFeedback.style.color = infoColor;
            scanFeedback.style.color = theme.info;
            isScanning = true;
            scanHistory = [];
            scanHistoryList.innerHTML = '';
            currentQrToken = null;
            const hiddenTokenField = document.getElementById('qr-actual-token');
            if (hiddenTokenField) hiddenTokenField.value = '';

            // Stop any existing stream
            if (videoStream) {
                videoStream.getTracks().forEach(track => track.stop());
                videoStream = null;
                video.srcObject = null;
                console.log('Previous camera stream stopped.');
            }

            // Request camera access
            navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment', width: { ideal: 1280 }, height: { ideal: 720 } } })
                .then(stream => {
                    videoStream = stream;
                    video.srcObject = stream;

                    // Wait for video metadata to load
                    video.onloadedmetadata = () => {
                        video.play().catch(err => {
                            console.error('Error playing video:', err);
                            qrError.style.display = 'block';
                            qrError.textContent = `Unable to start video stream: ${err.message}. Please check permissions and try again.`;
                            video.style.display = 'none';
                            scanOverlay.style.display = 'none';
                            scanProgress.style.display = 'none';
                            scanFeedback.style.display = 'none';
                            isScanning = false;
                        });
                    };

                    console.log('QR scanner camera started');

                    // Scan QR code with optimized performance
                    const canvas = document.createElement('canvas');
                    const context = canvas.getContext('2d', { willReadFrequently: true });
                    let lastScannedCode = null;
                    let scanAttempts = 0;
                    const maxAttempts = 300; // Prevent infinite loops
                    let progress = 0;

                    function scan() {
                        if (!isScanning || scanAttempts >= maxAttempts) {
                            if (scanAttempts >= maxAttempts) {
                                console.warn('Max scan attempts reached. Stopping scan.');
                                qrError.style.display = 'block';
                                qrError.textContent = 'Unable to detect QR code after multiple attempts. Please try again.';
                                stopScanner();
                            }
                            return;
                        }

                        if (typeof jsQR === 'undefined') {
                            console.error('jsQR is not defined. Cannot scan QR code.');
                            qrError.style.display = 'block';
                            qrError.textContent = 'QR scanner library not loaded. Please refresh the page.';
                            stopScanner();
                            return;
                        }

                        if (video.readyState === video.HAVE_ENOUGH_DATA) {
                            // Dynamic resolution adjustment
                            const targetWidth = Math.min(video.videoWidth, 640); // Optimize for performance
                            const targetHeight = Math.min(video.videoHeight, 480);
                            canvas.width = targetWidth;
                            canvas.height = targetHeight;
                            context.drawImage(video, 0, 0, targetWidth, targetHeight);

                            const imageData = context.getImageData(0, 0, targetWidth, targetHeight);
                            try {
                                const code = jsQR(imageData.data, targetWidth, targetHeight, {
                                    inversionAttempts: 'attemptBoth' // Improve detection
                                });
                                scanAttempts++;

                                // Update progress bar
                                progress = Math.min(progress + 2, 100);
                                scanProgress.querySelector('.progress-bar').style.width = `${progress}%`;
                                scanFeedback.textContent = `Scanning... (${Math.round(progress)}%)`;

                                if (code && code.data && code.data !== lastScannedCode) {
                                    lastScannedCode = code.data;
                                    console.log('QR code scanned:', code.data);
                                    currentQrToken = code.data;
                                    validateQRCode(code.data, scanHistoryList);
                                    stopScanner();
                                } else {
                                    requestAnimationFrame(scan);
                                }
                            } catch (err) {
                                console.error('Error processing QR code:', err);
                                scanAttempts++;
                                requestAnimationFrame(scan);
                            }
                        } else {
                            requestAnimationFrame(scan);
                        }
                    }

                    function stopScanner() {
                        isScanning = false;
                        scanOverlay.style.display = 'none';
                        scanProgress.style.display = 'none';
                        scanFeedback.style.display = 'none';
                        if (videoStream) {
                            videoStream.getTracks().forEach(track => track.stop());
                            videoStream = null;
                            video.srcObject = null;
                        }
                    }

                    scan();
                })
                .catch(error => {
                    console.error('Error accessing camera:', error);
                    qrError.style.display = 'block';
                    qrError.textContent = `Unable to access camera: ${error.message}. Please check permissions or try another device.`;
                    video.style.display = 'none';
                    scanOverlay.style.display = 'none';
                    scanProgress.style.display = 'none';
                    scanFeedback.style.display = 'none';
                    isScanning = false;
                });

            // Handle section close
            const closeHandler = () => {
                stopScanner();
                qrResult.style.display = 'none';
                qrError.style.display = 'none';
                qrSection.style.opacity = '0';
                setTimeout(() => {
                    qrSection.style.display = 'none';
                    const scanQrButton = document.getElementById('scan-qr-code');
                    if (scanQrButton) scanQrButton.focus();
                }, 500);
            };

            closeButton.replaceWith(closeButton.cloneNode(true));
            const newCloseButton = document.getElementById('qr-close');
            newCloseButton.addEventListener('click', closeHandler);
        });
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
            showToast('error', 'QR scanner result elements missing. Please refresh the page.');
            return;
        }

        if (hiddenTokenField) {
            hiddenTokenField.value = qrToken;
        }
        currentQrToken = qrToken;
        console.log('Stored QR token:', qrToken);

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
                if (hiddenTokenField) hiddenTokenField.value = '';
                currentQrToken = null;
                showToast('error', data.error);
            } else {
                qrResult.style.display = 'block';
                qrError.style.display = 'none';
                qrTicketId.textContent = data.ticket_id || 'N/A';
                qrBookingId.textContent = data.booking_id || 'N/A';
                qrPassenger.textContent = data.passenger || 'N/A';
                qrRoute.textContent = data.route || 'N/A';
                qrBookingDate.textContent = data.booking_date ? new Date(data.booking_date).toLocaleString() : 'N/A';
                qrTicketStatus.textContent = data.status || 'N/A';

                // Visual feedback
                qrResult.style.border = `2px solid ${theme.success}`;
                qrResult.style.borderRadius = '8px';
                qrResult.style.padding = '10px';
                qrResult.style.background = `rgba(${theme.success.replace('#', '')}, 0.1)`;
                qrResult.style.transition = 'all 0.3s ease';
                setTimeout(() => {
                    qrResult.style.border = '';
                    qrResult.style.borderRadius = '';
                    qrResult.style.padding = '';
                    qrResult.style.background = '';
                }, 2000);

                console.log('QR code validated successfully:', data);
                showToast('success', 'QR code scanned successfully!');

                // Update button states
                const markUsedBtn = document.getElementById('qr-mark-used');
                const markUnusedBtn = document.getElementById('qr-mark-unused');
                const viewBookingBtn = document.getElementById('qr-view-booking');

                if (markUsedBtn) {
                    markUsedBtn.disabled = data.status === 'used';
                    markUsedBtn.style.opacity = data.status === 'used' ? '0.6' : '1';
                    markUsedBtn.title = data.status === 'used' ? 'Ticket already marked as used' : 'Mark this ticket as used';
                }

                if (markUnusedBtn) {
                    markUnusedBtn.disabled = data.status === 'active';
                    markUnusedBtn.style.opacity = data.status === 'active' ? '0.6' : '1';
                    markUnusedBtn.title = data.status === 'active' ? 'Ticket is already active' : 'Mark this ticket as active/unused';
                }

                if (viewBookingBtn) {
                    viewBookingBtn.disabled = !data.booking_id;
                    viewBookingBtn.style.opacity = data.booking_id ? '1' : '0.6';
                }

                // Add to scan history
                const scanTime = new Date().toLocaleString();
                scanHistory.push({ ticket_id: data.ticket_id, status: data.status, time: scanTime, qr_token: qrToken });
                const historyItem = document.createElement('li');
                historyItem.className = 'list-group-item';
                historyItem.style.cssText = `color: ${theme.text}; font-size: 0.9rem; border-left: 4px solid ${theme.success}; padding-left: 10px; background: ${theme.background};`;
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
            if (hiddenTokenField) hiddenTokenField.value = '';
            currentQrToken = null;
            showToast('error', 'Error validating QR code. Please try again.');
        });
    }

    // Toast notification for better UX
    function showToast(type, message) {
        const toast = document.createElement('div');
        const bgColor = type === 'success' ? theme.success : theme.warning;
        toast.style.cssText = `
            position: fixed; top: 20px; right: 20px; background: ${bgColor};
            color: white; padding: 15px 20px; border-radius: 5px; z-index: 9999;
            box-shadow: 0 4px 12px rgba(0,0,0,0.15); transform: translateX(400px);
            transition: transform 0.3s ease; font-size: 0.9rem; max-width: 300px;
        `;
        toast.textContent = message;
        document.body.appendChild(toast);
        setTimeout(() => { toast.style.transform = 'translateX(0)'; }, 100);
        setTimeout(() => {
            toast.style.transform = 'translateX(400px)';
            setTimeout(() => document.body.removeChild(toast), 300);
        }, 3000);
    }

    function updateTicketStatus(newStatus) {
        const qrResult = document.getElementById('qr-result');
        const qrError = document.getElementById('qr-error');
        const qrTicketStatus = document.getElementById('qr-ticket-status');
        const scanHistoryList = document.querySelector('#qr-scan-history .list-group');
        const hiddenTokenField = document.getElementById('qr-actual-token');

        if (!qrResult || !qrError || !qrTicketStatus || !scanHistoryList || !hiddenTokenField) {
            console.error('QR update elements not found:', {
                qrResult, qrError, qrTicketStatus, scanHistoryList, hiddenTokenField
            });
            showToast('error', 'QR scanner update elements missing. Please refresh the page.');
            return;
        }

        const qrToken = hiddenTokenField.value;
        if (!qrToken) {
            console.error('No QR token available for status update');
            qrError.style.display = 'block';
            qrError.textContent = 'No QR token available. Please scan a ticket first.';
            showToast('error', 'No QR token available. Please scan a ticket first.');
            return;
        }

        console.log(`Updating ticket status for QR token: ${qrToken} to ${newStatus}`);

        // Show loading state
        qrError.style.display = 'none';
        const originalStatusText = qrTicketStatus.textContent;
        qrTicketStatus.textContent = `Updating to ${newStatus}...`;
        qrTicketStatus.style.color = theme.info;
        qrTicketStatus.style.fontWeight = 'bold';

        // Mimic change_list.js fetchJsonAndUpdate
        fetch('/admin/scan-qr-code/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken'),
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify({ qr_token: qrToken, ticket_status: newStatus })
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
            if (data.exists !== undefined && !data.exists) {
                qrError.style.display = 'block';
                qrError.textContent = `Ticket ${qrToken} no longer exists.`;
                qrTicketStatus.textContent = originalStatusText;
                qrTicketStatus.style.color = '';
                qrTicketStatus.style.fontWeight = '';
                console.warn(`Ticket ${qrToken} no longer exists`);
                showToast('error', `Ticket ${qrToken} no longer exists.`);
                return;
            }

            qrError.style.display = 'none';
            qrTicketStatus.textContent = data.status || 'N/A';
            qrTicketStatus.style.color = theme.success;
            qrTicketStatus.style.fontWeight = 'bold';
            setTimeout(() => {
                qrTicketStatus.style.color = '';
                qrTicketStatus.style.fontWeight = '';
            }, 2000);

            console.log(`Ticket status updated to ${newStatus}:`, data);
            showToast('success', `Ticket status updated to ${data.status} ✓`);

            // Update button states
            const markUsedBtn = document.getElementById('qr-mark-used');
            const markUnusedBtn = document.getElementById('qr-mark-unused');
            if (markUsedBtn) {
                markUsedBtn.disabled = data.status === 'used';
                markUsedBtn.style.opacity = data.status === 'used' ? '0.6' : '1';
                markUsedBtn.title = data.status === 'used' ? 'Ticket already marked as used' : 'Mark this ticket as used';
            }
            if (markUnusedBtn) {
                markUnusedBtn.disabled = data.status === 'active';
                markUnusedBtn.style.opacity = data.status === 'active' ? '0.6' : '1';
                markUnusedBtn.title = data.status === 'active' ? 'Ticket is already active' : 'Mark this ticket as active/unused';
            }

            // Update scan history
            const scanTime = new Date().toLocaleString();
            scanHistory.push({ ticket_id: qrToken, status: data.status, time: scanTime });
            const historyItem = document.createElement('li');
            historyItem.className = 'list-group-item';
            historyItem.style.cssText = `color: ${theme.text}; font-size: 0.9rem; border-left: 4px solid ${theme.success}; padding-left: 10px; background: ${theme.background};`;
            historyItem.innerHTML = `
                <strong>Updated:</strong> Ticket status changed to
                <span class="badge bg-${data.status === 'used' ? 'success' : 'primary'}">${data.status}</span>
                <small class="text-muted float-end">${scanTime}</small>
            `;
            scanHistoryList.prepend(historyItem);

            // Update recent bookings table
            updateRecentBookingsTable();
        })
        .catch(error => {
            qrError.style.display = 'block';
            qrError.textContent = error.message || 'Error updating ticket status. Please try again.';
            qrTicketStatus.textContent = originalStatusText;
            qrTicketStatus.style.color = '';
            qrTicketStatus.style.fontWeight = '';
            console.error('Error updating ticket status:', error);
            showToast('error', error.message || 'Error updating ticket status.');
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
            showToast('error', 'Error updating recent bookings table.');
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
                    showToast('error', 'Failed to load QR scanner library.');
                });
        });
    }

    // Mark as Used button
    const markUsedBtn = document.getElementById('qr-mark-used');
    if (markUsedBtn) {
        markUsedBtn.addEventListener('click', () => {
            if (!markUsedBtn.disabled) {
                updateTicketStatus('used');
            }
        });
    }

    // Mark as Active button
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
                showToast('error', 'No valid booking ID available.');
            }
        });
    }

    // Scan Again button
    const scanAgainBtn = document.getElementById('qr-scan-again');
    if (scanAgainBtn) {
        scanAgainBtn.addEventListener('click', () => {
            const qrResult = document.getElementById('qr-result');
            const qrError = document.getElementById('qr-error');
            const video = document.getElementById('qr-video');
            const scanOverlay = document.getElementById('qr-scan-overlay');
            const scanProgress = document.getElementById('qr-scan-progress');
            const scanFeedback = document.getElementById('qr-scan-feedback');
            const hiddenTokenField = document.getElementById('qr-actual-token');
            const scanHistoryList = document.querySelector('#qr-scan-history .list-group');

            if (!qrResult || !qrError || !video || !scanOverlay || !scanProgress || !scanFeedback || !scanHistoryList) {
                console.error('QR scan again elements not found');
                showToast('error', 'QR scanner elements missing for scan again.');
                return;
            }

            qrResult.style.display = 'none';
            qrError.style.display = 'none';
            video.style.display = 'block';
            scanOverlay.style.display = 'block';
            scanProgress.style.display = 'block';
            scanProgress.querySelector('.progress-bar').style.width = '0%';
            scanFeedback.style.display = 'block';
            scanFeedback.textContent = 'Scanning...';
            isScanning = true;
            currentQrToken = null;
            if (hiddenTokenField) hiddenTokenField.value = '';
            scanHistoryList.innerHTML = '';
            console.log('Resumed QR scanning - cleared previous data');
        });
    }

    // Initialize Tooltips with Tippy.js
    if (typeof tippy !== 'undefined') {
        tippy('#qr-mark-used, #qr-mark-unused, #qr-view-booking, #qr-scan-again, #qr-close, #scan-qr-code', {
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