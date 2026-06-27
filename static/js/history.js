// history.js
document.addEventListener('DOMContentLoaded', function() {
    'use strict';

    computeStats();
    initCountdowns();

    // ----------------------------------------------------------------
    // 1. COMPUTE STATS FROM LIVE DOM
    //    "Upcoming" = scheduled/pending with future departure
    //    "Past"     = scheduled/pending with past departure
    // ----------------------------------------------------------------
    function computeStats() {
        var cards = document.querySelectorAll('.booking-card');
        var elTotal    = document.getElementById('stat-total');
        var elUpcoming = document.getElementById('stat-upcoming');
        var elPast     = document.getElementById('stat-past');
        var elSpent    = document.getElementById('stat-spent');

        if (!elTotal) return;

        var upcoming = 0;
        var past     = 0;
        var spent    = 0;
        var now      = Date.now();

        for (var i = 0; i < cards.length; i++) {
            var card   = cards[i];
            var status = card.getAttribute('data-status');
            var isCancelled = (status === 'cancelled');

            // Price — count all non-cancelled bookings
            if (!isCancelled) {
                var priceEl = card.querySelector('.meta-value.price');
                if (priceEl) {
                    var raw = priceEl.textContent.replace(/[^0-9.]/g, '').trim();
                    var val = parseFloat(raw);
                    if (!isNaN(val)) spent += val;
                }
            }

            // Timing — only for active bookings
            if (!isCancelled) {
                var timeEl = card.querySelector('.countdown-text');
                if (timeEl) {
                    var departure = new Date(timeEl.getAttribute('data-departure-time')).getTime();
                    if (departure > now) {
                        upcoming++;
                    } else {
                        past++;
                    }
                }
            }
        }

        elTotal.textContent    = cards.length;
        elUpcoming.textContent = upcoming;
        elPast.textContent     = past;
        elSpent.textContent    = 'FJD ' + spent.toFixed(2);
    }

    // ----------------------------------------------------------------
    // 2. COUNTDOWN TIMERS
    // ----------------------------------------------------------------
    function initCountdowns() {
        var countdownEls = document.querySelectorAll('.countdown-text');

        for (var i = 0; i < countdownEls.length; i++) {
            (function(el) {
                var departureTime = new Date(el.getAttribute('data-departure-time')).getTime();
                var strip = el.closest('.countdown-strip');

                function tick() {
                    var now  = Date.now();
                    var diff = departureTime - now;

                    if (diff <= 0) {
                        el.textContent = 'Departed';
                        if (strip) strip.classList.remove('urgent');
                        return;
                    }

                    var d = Math.floor(diff / 86400000);
                    var h = Math.floor((diff % 86400000) / 3600000);
                    var m = Math.floor((diff % 3600000) / 60000);
                    var s = Math.floor((diff % 60000) / 1000);

                    if (d > 0) {
                        el.textContent = d + 'd ' + h + 'h ' + m + 'm';
                    } else if (h > 0) {
                        el.textContent = h + 'h ' + m + 'm ' + s + 's';
                    } else {
                        el.textContent = m + 'm ' + s + 's';
                    }

                    if (diff < 3600000) {
                        if (strip) strip.classList.add('urgent');
                    } else {
                        if (strip) strip.classList.remove('urgent');
                    }
                }

                tick();
                setInterval(tick, 1000);
            })(countdownEls[i]);
        }
    }

    // ----------------------------------------------------------------
    // 3. MODAL & CANCELLATION
    // ----------------------------------------------------------------
    var cancelModal     = document.getElementById('cancelModal');
    var confirmCancelBtn = document.getElementById('confirmCancel');
    var closeModalBtn   = document.getElementById('closeModal');
    var currentBookingId = null;

    var cancelButtons = document.querySelectorAll('.cancel-booking');
    for (var c = 0; c < cancelButtons.length; c++) {
        (function(btn) {
            btn.addEventListener('click', function(e) {
                e.preventDefault();
                currentBookingId = btn.getAttribute('data-booking-id');
                cancelModal.classList.add('show');
                closeModalBtn.focus();
            });
        })(cancelButtons[c]);
    }

    closeModalBtn.addEventListener('click', closeModal);

    cancelModal.addEventListener('click', function(e) {
        if (e.target === cancelModal) closeModal();
    });

    confirmCancelBtn.addEventListener('click', function() {
        if (!currentBookingId) return;

        var spinner = confirmCancelBtn.querySelector('.spinner');
        spinner.classList.add('active');
        confirmCancelBtn.disabled = true;

        var csrfInput = document.querySelector('[name="csrfmiddlewaretoken"]');
        var csrfToken = csrfInput ? csrfInput.value : getCookie('csrftoken');

        fetch('/bookings/cancel/' + currentBookingId + '/', {
            method: 'POST',
            headers: {
                'X-CSRFToken': csrfToken,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({})
        })
        .then(function(response) {
            return response.json().then(function(data) {
                return { ok: response.ok, data: data };
            });
        })
        .then(function(result) {
            if (result.ok) {
                var card = document.querySelector('.booking-card[data-booking-id="' + currentBookingId + '"]');
                if (card) {
                    card.style.transition = 'opacity 0.35s ease, transform 0.35s ease';
                    card.style.opacity = '0';
                    card.style.transform = 'scale(0.96) translateY(-6px)';
                    setTimeout(function() {
                        card.remove();
                        computeStats();
                    }, 360);
                }
                showNotification('Booking has been cancelled successfully.', 'success');
                closeModal();
            } else {
                var msg = (result.data && (result.data.error || result.data.message)) || 'Unable to cancel this booking.';
                showNotification(msg, 'error');
            }
        })
        .catch(function(err) {
            console.error('Cancellation error:', err);
            showNotification('A network error occurred. Please try again.', 'error');
        })
        .finally(function() {
            spinner.classList.remove('active');
            confirmCancelBtn.disabled = false;
        });
    });

    cancelModal.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') { closeModal(); return; }
        if (e.key === 'Tab') {
            var btns  = cancelModal.querySelectorAll('button');
            var first = btns[0];
            var last  = btns[btns.length - 1];
            if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
            else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
        }
    });

    function closeModal() {
        cancelModal.classList.remove('show');
        currentBookingId = null;
    }

    // ----------------------------------------------------------------
    // 4. TOAST NOTIFICATIONS
    // ----------------------------------------------------------------
    function showNotification(message, type) {
        type = type || 'success';

        var container = document.getElementById('toast-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'toast-container';
            container.style.position = 'fixed';
            container.style.bottom = '24px';
            container.style.right = '24px';
            container.style.zIndex = '9999';
            container.style.display = 'flex';
            container.style.flexDirection = 'column';
            container.style.gap = '10px';
            container.style.pointerEvents = 'none';
            document.body.appendChild(container);
        }

        var colors = {
            success: { bg: '#065f46', border: '#10b981' },
            error:   { bg: '#7f1d1d', border: '#ef4444' }
        };
        var clr = colors[type] || colors.success;

        var toast = document.createElement('div');
        toast.setAttribute('role', 'alert');
        toast.style.background = clr.bg;
        toast.style.borderLeft = '3px solid ' + clr.border;
        toast.style.color = '#fff';
        toast.style.padding = '14px 18px';
        toast.style.borderRadius = '10px';
        toast.style.boxShadow = '0 8px 24px rgba(0,0,0,0.18)';
        toast.style.minWidth = '280px';
        toast.style.maxWidth = '380px';
        toast.style.display = 'flex';
        toast.style.alignItems = 'center';
        toast.style.gap = '10px';
        toast.style.transform = 'translateX(120%)';
        toast.style.opacity = '0';
        toast.style.transition = 'all 0.4s cubic-bezier(0.22, 1, 0.36, 1)';
        toast.style.pointerEvents = 'auto';
        toast.style.fontSize = '14px';
        toast.style.fontWeight = '500';
        toast.style.lineHeight = '1.4';

        var icon = document.createElement('div');
        icon.style.flexShrink = '0';
        if (type === 'success') {
            icon.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>';
        } else {
            icon.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>';
        }
        toast.appendChild(icon);

        var msg = document.createElement('span');
        msg.style.flex = '1';
        msg.textContent = message;
        toast.appendChild(msg);

        var closeBtn = document.createElement('button');
        closeBtn.innerHTML = '&times;';
        closeBtn.style.cssText = 'background:none;border:none;color:rgba(255,255,255,0.6);font-size:18px;cursor:pointer;padding:0;width:24px;height:24px;display:flex;align-items:center;justify-content:center;border-radius:50%;transition:background 0.2s,color 0.2s;margin-left:auto;flex-shrink:0;';
        closeBtn.addEventListener('click', function(e) {
            e.stopPropagation();
            removeToast(toast);
        });
        toast.appendChild(closeBtn);

        container.appendChild(toast);
        requestAnimationFrame(function() {
            toast.style.transform = 'translateX(0)';
            toast.style.opacity = '1';
        });

        var timer = setTimeout(function() { removeToast(toast); }, 4500);
        toast.addEventListener('click', function() {
            clearTimeout(timer);
            removeToast(toast);
        });
    }

    function removeToast(toast) {
        toast.style.transform = 'translateX(120%)';
        toast.style.opacity = '0';
        var handler = function() {
            if (toast.parentNode) toast.parentNode.removeChild(toast);
        };
        toast.addEventListener('transitionend', handler, { once: true });
        setTimeout(handler, 500);
    }

    // ----------------------------------------------------------------
    // 5. HELPERS
    // ----------------------------------------------------------------
    function getCookie(name) {
        if (document.cookie && document.cookie !== '') {
            var parts = document.cookie.split(';');
            for (var i = 0; i < parts.length; i++) {
                var c = parts[i].trim();
                if (c.substring(0, name.length + 1) === (name + '=')) {
                    return decodeURIComponent(c.substring(name.length + 1));
                }
            }
        }
        return '';
    }
});