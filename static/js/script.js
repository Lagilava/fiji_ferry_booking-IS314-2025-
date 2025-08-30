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
    const themeIcon = document.querySelector('.dark-mode-icon');

    if (logo) logo.src = '/static/logo.png';
    if (storedTheme === 'dark' || (!storedTheme && prefersDark)) {
        html.classList.add('dark-mode');
        if (logo) logo.src = '/static/logo.png';
        if (themeIcon) {
            themeIcon.innerHTML = `
                <svg aria-hidden="true" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--highlight-bg, #F4A261)" stroke-width="2">
                    <path d="M12 3v2m0 14v2m9-9h-2m-14 0H3m16.95-6.95l-1.42 1.42m-12.86 0L4.25 6.55m12.86 12.86l-1.42-1.42m-12.86 0l1.42-1.42M12 17a5 5 0 100-10 5 5 0 000 10z"/>
                </svg>`;
        }
        console.log('Dark mode initialized');
    } else {
        if (logo) logo.src = '/static/logo.png';
        if (themeIcon) {
            themeIcon.innerHTML = `
                <svg aria-hidden="true" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--link-color, #2AB7CA)" stroke-width="2">
                    <path d="M20 15.5A8 8 0 0112 4a8 8 0 100 16 8 8 0 018-4.5 1 1 0 01-.5 1.5z"/>
                    <circle cx="16" cy="8" r="1"/>
                    <circle cx="18" cy="12" r="1"/>
                    <circle cx="16" cy="16" r="1"/>
                </svg>`;
        }
        console.log('Light mode initialized');
    }

    // Toggle dark mode
    const themeButton = document.getElementById('theme-icon');
    if (themeButton) {
        themeButton.addEventListener('click', () => {
            html.classList.toggle('dark-mode');
            const theme = html.classList.contains('dark-mode') ? 'dark' : 'light';
            localStorage.setItem('theme', theme);
            if (logo) logo.src = '/static/logo.png';
            if (themeIcon) {
                themeIcon.innerHTML = theme === 'dark' ? `
                    <svg aria-hidden="true" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--highlight-bg, #F4A261)" stroke-width="2">
                        <path d="M12 3v2m0 14v2m9-9h-2m-14 0H3m16.95-6.95l-1.42 1.42m-12.86 0L4.25 6.55m12.86 12.86l-1.42-1.42m-12.86 0l1.42-1.42M12 17a5 5 0 100-10 5 5 0 000 10z"/>
                    </svg>` : `
                    <svg aria-hidden="true" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="var(--link-color, #2AB7CA)" stroke-width="2">
                        <path d="M20 15.5A8 8 0 0112 4a8 8 0 100 16 8 8 0 018-4.5 1 1 0 01-.5 1.5z"/>
                        <circle cx="16" cy="8" r="1"/>
                        <circle cx="18" cy="12" r="1"/>
                        <circle cx="16" cy="16" r="1"/>
                    </svg>`;
            }
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