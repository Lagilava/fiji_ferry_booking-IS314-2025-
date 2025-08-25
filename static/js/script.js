document.addEventListener('DOMContentLoaded', () => {
    // Initialize AOS
    AOS.init({
        duration: 800,
        once: true,
        disable: 'mobile'
    });
    console.log('AOS initialized');

    // Initialize dark mode
    const storedTheme = localStorage.getItem('theme');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const html = document.documentElement;
    const logo = document.getElementById('site-logo');
    const icon = document.querySelector('.dark-mode-icon');
    if (storedTheme === 'dark' || (!storedTheme && prefersDark)) {
        html.classList.add('dark-mode');
        if (logo) logo.src = '/static/logo-dark.png';
        if (icon) icon.textContent = '☀️';
        console.log('Dark mode initialized');
    } else {
        console.log('Light mode initialized');
    }

    // Toggle dark mode
    const themeButton = document.getElementById('theme-icon');
    if (themeButton) {
        themeButton.addEventListener('click', () => {
            html.classList.toggle('dark-mode');
            const theme = html.classList.contains('dark-mode') ? 'dark' : 'light';
            localStorage.setItem('theme', theme);
            if (logo) logo.src = theme === 'dark' ? '/static/logo-dark.png' : '/static/logo-light.png';
            if (icon) icon.textContent = theme === 'dark' ? '☀️' : '🌙';
            console.log('Theme toggled to:', theme);
        });
    } else {
        console.error('Theme button not found');
    }

    // Toggle menu
    const hamburger = document.querySelector('.hamburger');
    const nav = document.getElementById('navMenu');
    if (hamburger && nav) {
        hamburger.addEventListener('click', () => {
            const isExpanded = nav.classList.toggle('show');
            hamburger.setAttribute('aria-expanded', isExpanded);
            console.log('Menu toggled:', isExpanded ? 'open' : 'closed');
        });
    } else {
        console.warn('Hamburger or nav not found');
    }

    // Dropdown keyboard support
    const dropdown = document.querySelector('.dropdown');
    const dropdownContent = document.querySelector('.dropdown-content');
    if (dropdown && dropdownContent) {
        dropdown.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                dropdownContent.style.opacity = '0';
                dropdownContent.style.visibility = 'hidden';
                dropdownContent.style.transform = 'translateY(8px)';
                console.log('Dropdown closed via Escape');
            }
        });
    } else {
        console.warn('Dropdown or dropdown-content not found');
    }

    // Cancellation modal (only for pages with modal, e.g., history.html)
    const modal = document.getElementById('cancelModal');
    const confirmButton = document.getElementById('confirmCancel');
    const closeButton = document.getElementById('closeModal');
    if (modal && confirmButton && closeButton) {
        document.querySelectorAll('.cancel-booking').forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                modal.classList.remove('hidden');
                confirmButton.dataset.href = link.getAttribute('href');
                console.log('Modal opened for booking:', link.dataset.bookingId);
            });
        });

        confirmButton.addEventListener('click', () => {
            window.location.href = confirmButton.dataset.href;
            modal.classList.add('hidden');
            console.log('Modal confirmed, redirecting to:', confirmButton.dataset.href);
        });

        closeButton.addEventListener('click', () => {
            modal.classList.add('hidden');
            console.log('Modal closed');
        });

        modal.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                modal.classList.add('hidden');
                console.log('Modal closed via Escape');
            }
        });
    } else {
        console.log('Cancellation modal not present on this page');
    }
});