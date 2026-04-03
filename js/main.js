// Caduceus public site — main.js

// Copy install command to clipboard
function copyInstall() {
    const btns = document.querySelectorAll('.copy-btn');
    const cmd = document.getElementById('install-command') ||
                 document.getElementById('install-command-2');
    if (!cmd) return;

    const text = cmd.textContent.trim();

    navigator.clipboard.writeText(text).then(() => {
        btns.forEach(btn => {
            btn.classList.add('copied');
            // Swap icon to check
            btn.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"></polyline></svg>`;
        });
        setTimeout(() => {
            btns.forEach(btn => {
                btn.classList.remove('copied');
                btn.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>
                    <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>
                </svg>`;
            });
        }, 2000);
    });
}

// Simulate install count (in production this would fetch from an API)
function setInstallCount() {
    const el = document.getElementById('install-count');
    if (!el) return;
    // Placeholder — would fetch from a real API in production
    el.textContent = 'open source';
}

// Smooth scroll for anchor links
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
        e.preventDefault();
        const target = document.querySelector(this.getAttribute('href'));
        if (target) {
            target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }
    });
});

// Init
document.addEventListener('DOMContentLoaded', () => {
    setInstallCount();
});
