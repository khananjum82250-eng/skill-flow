
(function () {
    const container = document.getElementById('container');
    const registerBtn = document.getElementById('register');
    const loginBtn = document.getElementById('login');

    if (registerBtn && container) {
        registerBtn.addEventListener('click', () => {
            container.classList.add('active');
        });
    }

    if (loginBtn && container) {
        loginBtn.addEventListener('click', () => {
            container.classList.remove('active');
        });
    }

    document.querySelectorAll('.password-toggle').forEach((button) => {
        button.addEventListener('click', () => {
            const input = button.closest('.password-field')?.querySelector('input');
            const icon = button.querySelector('i');
            if (!input) return;

            const shouldShow = input.type === 'password';
            input.type = shouldShow ? 'text' : 'password';
            button.setAttribute('aria-label', shouldShow ? 'Hide password' : 'Show password');
            if (icon) {
                icon.classList.toggle('fa-eye', !shouldShow);
                icon.classList.toggle('fa-eye-slash', shouldShow);
            }
        });
    });
})();
