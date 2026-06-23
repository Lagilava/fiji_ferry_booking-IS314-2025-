document.addEventListener('DOMContentLoaded', () => {
    // Apply glow and vibrant animations based on status
    document.querySelectorAll('.booking-card').forEach(card => {
        const status = card.dataset.status;
        if (status) {
            card.classList.add(`glow-${status}`);
            card.classList.add('vibrant');
        }
    });

    // Initialize countdown timers
    initCountdowns();

    const cancelModal = document.getElementById('cancelModal');
    const confirmCancelBtn = document.getElementById('confirmCancel');
    const closeModalBtn = document.getElementById('closeModal');
    let currentBookingId = null;

    // Handle cancel button clicks
    document.querySelectorAll('.cancel-booking').forEach(button => {
        button.addEventListener('click', (e) => {
            e.preventDefault();
            currentBookingId = button.dataset.bookingId;
            cancelModal.classList.remove('hidden');
            cancelModal.classList.add('show');
            cancelModal.focus();
        });
    });

    // Close modal
    closeModalBtn.addEventListener('click', () => {
        closeModal();
    });

    // Handle confirm cancellation
    confirmCancelBtn.addEventListener('click', async () => {
        if (!currentBookingId) return;

        const confirmBtn = confirmCancelBtn;
        const spinner = confirmBtn.querySelector('.loading-spinner');
        spinner.style.display = 'inline-block';
        confirmBtn.disabled = true;

        try {
            const response = await fetch(`/bookings/cancel/${currentBookingId}/`, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({})
            });

            if (response.ok) {
                // Remove booking card from DOM
                const bookingCard = document.querySelector(`.booking-card[data-booking-id="${currentBookingId}"]`);
                if (bookingCard) {
                    bookingCard.style.transition = 'all 0.4s ease';
                    bookingCard.style.opacity = '0';
                    bookingCard.style.transform = 'translateY(-10px)';
                    setTimeout(() => bookingCard.remove(), 400);
                }

                // Show success toast
                showNotification('Booking successfully cancelled', 'success');

                // Close modal
                closeModal();
            } else {
                const error = await response.json().catch(() => ({}));
                showNotification(error.error || error.message || 'Failed to cancel booking', 'error');
            }
        } catch (error) {
            console.error('Cancellation error:', error);
            alert('An error occurred. Please try again.');
        } finally {
            spinner.style.display = 'none';
            confirmBtn.disabled = false;
        }
    });

    // Keyboard navigation for accessibility
    cancelModal.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeModal();
        } else if (e.key === 'Tab') {
            const focusable = cancelModal.querySelectorAll('button');
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            if (e.shiftKey && document.activeElement === first) {
                e.preventDefault();
                last.focus();
            } else if (!e.shiftKey && document.activeElement === last) {
                e.preventDefault();
                first.focus();
            }
        }
    });

    // Close modal helper
    function closeModal() {
        cancelModal.classList.add('hidden');
        cancelModal.classList.remove('show');
        currentBookingId = null;
    }

    // Toast Notification System
    function showNotification(message, type = 'success') {
        // Create toast container if not exists
        let container = document.getElementById('toast-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'toast-container';
            container.style.cssText = `
                position: fixed;
                bottom: 24px;
                right: 24px;
                z-index: 9999;
                display: flex;
                flex-direction: column;
                gap: 12px;
                pointer-events: none;
            `;
            document.body.appendChild(container);
        }

        // Create toast
        const toast = document.createElement('div');
        toast.setAttribute('role', 'alert');
        toast.setAttribute('aria-live', 'polite');
        toast.style.cssText = `
            background: ${type === 'success' ? '#10B981' : '#EF4444'};
            color: white;
            padding: 16px 20px;
            border-radius: 12px;
            box-shadow: 0 10px 25px rgba(0,0,0,0.15);
            min-width: 300px;
            max-width: 400px;
            display: flex;
            align-items: center;
            gap: 12px;
            transform: translateX(120%);
            opacity: 0;
            transition: all 0.4s cubic-bezier(0.25, 0.8, 0.25, 1);
            pointer-events: auto;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            font-size: 15px;
            font-weight: 500;
        `;

        // Icon
        const icon = document.createElement('div');
        icon.innerHTML = type === 'success'
            ? `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M20 6L9 17l-5-5"/></svg>`
            : `<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M18 6L6 18M6 6l12 12"/></svg>`;
        toast.appendChild(icon);

        // Message
        const msg = document.createElement('span');
        msg.textContent = message;
        toast.appendChild(msg);

        // Close button
        const closeBtn = document.createElement('button');
        closeBtn.innerHTML = '&times;';
        closeBtn.style.cssText = `
            margin-left: auto;
            background: none;
            border: none;
            color: white;
            font-size: 20px;
            cursor: pointer;
            padding: 0;
            width: 24px;
            height: 24px;
            display: flex;
            align-items: center;
            justify-content: center;
            border-radius: 50%;
            transition: background 0.2s;
        `;
        closeBtn.onclick = () => removeToast(toast);
        closeBtn.onmouseover = () => closeBtn.style.background = 'rgba(255,255,255,0.2)';
        closeBtn.onmouseout = () => closeBtn.style.background = 'none';
        toast.appendChild(closeBtn);

        // Add to container
        container.appendChild(toast);

        // Trigger animation
        requestAnimationFrame(() => {
            toast.style.transform = 'translateX(0)';
            toast.style.opacity = '1';
        });

        // Auto-dismiss after 4 seconds
        const autoDismiss = setTimeout(() => removeToast(toast), 4000);

        // Manual dismiss
        toast.addEventListener('click', (e) => {
            if (e.target !== closeBtn) {
                clearTimeout(autoDismiss);
                removeToast(toast);
            }
        });
    }

    function removeToast(toast) {
        toast.style.transform = 'translateX(120%)';
        toast.style.opacity = '0';
        toast.addEventListener('transitionend', () => {
            if (toast.parentNode) toast.parentNode.removeChild(toast);
        });
    }

    // Countdown timers
    function initCountdowns() {
        document.querySelectorAll('.countdown').forEach(element => {
            const departureTime = new Date(element.dataset.departureTime).getTime();
            const updateCountdown = () => {
                const now = new Date().getTime();
                const distance = departureTime - now;

                if (distance < 0) {
                    element.textContent = 'Departure Time Passed';
                    element.classList.remove('urgent');
                    return;
                }

                const days = Math.floor(distance / (1000 * 60 * 60 * 24));
                const hours = Math.floor((distance % (1000 * 60 * 60 * 24)) / (1000 * 60 * 60));
                const minutes = Math.floor((distance % (1000 * 60 * 60)) / (1000 * 60));
                const seconds = Math.floor((distance % (1000 * 60)) / 1000);

                element.textContent = `Countdown: ${days}d ${hours}h ${minutes}m ${seconds}s`;

                if (distance < 3600000) {
                    element.classList.add('urgent');
                } else {
                    element.classList.remove('urgent');
                }
            };

            updateCountdown();
            setInterval(updateCountdown, 1000);
        });
    }
});