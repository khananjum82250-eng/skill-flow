
// ===== SELECT ELEMENTS =====
const container = document.getElementById('container');
const registerBtn = document.getElementById('register');
const loginBtn = document.getElementById('login');

const signUpForm = document.querySelector(".sign-up form");
const signInForm = document.querySelector(".sign-in form");
const signupUsername = document.getElementById('signupUsername');
const signupUsernameStatus = document.getElementById('signupUsernameStatus');
const signupEmail = document.getElementById('signupEmail');
const signupEmailStatus = document.getElementById('signupEmailStatus');
const disposableEmailKeywords = [
    'tempmail',
    'temp-mail',
    '10minutemail',
    'guerrillamail',
    'yopmail',
    'mailinator',
    'fakemail',
    'throwawaymail',
    'trashmail',
    'disposable'
];


// ===============================
// TOGGLE PANELS (UI SWITCH)
// ===============================
if (registerBtn) {
    registerBtn.addEventListener('click', () => {
        container.classList.add("active");
    });
}

if (loginBtn) {
    loginBtn.addEventListener('click', () => {
        container.classList.remove("active");
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

function normalizeUsername(value) {
    return String(value || '').trim().toLowerCase();
}

function validateUsernameFormat(username) {
    if (!username) return '';
    if (username.length < 3 || username.length > 25) return 'Username must be 3 to 25 characters.';
    if (!/^[A-Za-z0-9_.]+$/.test(username)) return 'Only letters, numbers, underscore, and dot are allowed.';
    return '';
}

function setUsernameStatus(message, state = '') {
    if (!signupUsernameStatus) return;
    signupUsernameStatus.textContent = message;
    signupUsernameStatus.classList.toggle('is-valid', state === 'valid');
    signupUsernameStatus.classList.toggle('is-invalid', state === 'invalid');
}

function normalizeEmail(value) {
    return String(value || '').trim().toLowerCase();
}

function validateEmail(value) {
    const email = normalizeEmail(value);
    if (!email) return 'Email is required.';
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(email)) return 'Please enter a valid email address.';
    const domain = email.split('@').pop() || '';
    if (disposableEmailKeywords.some((keyword) => domain.includes(keyword))) {
        return 'Temporary or fake email addresses are not allowed.';
    }
    return '';
}

function setEmailStatus(message, state = '') {
    if (!signupEmailStatus) return;
    signupEmailStatus.textContent = message;
    signupEmailStatus.classList.toggle('is-valid', state === 'valid');
    signupEmailStatus.classList.toggle('is-invalid', state === 'invalid');
}

let usernameTimer;
let latestUsernameCheck = '';

signupUsername?.addEventListener('input', () => {
    const username = normalizeUsername(signupUsername.value);
    signupUsername.value = username;
    window.clearTimeout(usernameTimer);

    const formatError = validateUsernameFormat(username);
    if (!username) {
        setUsernameStatus('Leave blank to auto-generate a unique username.', '');
        return;
    }
    if (formatError) {
        setUsernameStatus(formatError, 'invalid');
        return;
    }

    setUsernameStatus('Checking username...', '');
    usernameTimer = window.setTimeout(() => {
        latestUsernameCheck = username;
        fetch(`/api/username/check?username=${encodeURIComponent(username)}`)
            .then((res) => res.json())
            .then((data) => {
                if (latestUsernameCheck !== username) return;
                if (data.available) setUsernameStatus('Username is available.', 'valid');
                else setUsernameStatus(data.error || 'Username already taken.', 'invalid');
            })
            .catch(() => setUsernameStatus('Unable to check username right now.', 'invalid'));
    }, 300);
});

signupEmail?.addEventListener('input', () => {
    const email = normalizeEmail(signupEmail.value);
    signupEmail.value = email;
    const emailError = validateEmail(email);
    if (emailError) {
        setEmailStatus(emailError, email ? 'invalid' : '');
        return;
    }
    setEmailStatus('Email looks good. We will send a verification OTP.', 'valid');
});

signUpForm?.addEventListener('submit', (event) => {
    const username = normalizeUsername(signupUsername?.value || '');
    const email = normalizeEmail(signupEmail?.value || '');
    const formatError = validateUsernameFormat(username);
    if (formatError) {
        event.preventDefault();
        setUsernameStatus(formatError, 'invalid');
    }
    const emailError = validateEmail(email);
    if (emailError) {
        event.preventDefault();
        setEmailStatus(emailError, 'invalid');
    }
});
