// Profile Page Specific JS
document.addEventListener('DOMContentLoaded', () => {
    const avatarOptions = document.querySelectorAll('.profile-avatar-option');
    const selectedAvatarInput = document.getElementById('selectedAvatarUrl');
    let currentAvatarDisplay = document.getElementById('currentAvatarDisplay');
    const avatarModal = document.getElementById('avatarModal');
    const btnOpenAvatarModal = document.getElementById('btnOpenAvatarModal');
    const btnCloseAvatarModal = document.getElementById('btnCloseAvatarModal');
    const btnConfirmAvatar = document.getElementById('btnConfirmAvatar');
    const avatarSaveStatus = document.getElementById('avatarSaveStatus');
    const editableSections = document.querySelectorAll('.profile-editable-section');
    const defaultAvatarUrl = avatarOptions[0]?.dataset.url || '';
    let savedAvatarUrl = selectedAvatarInput?.value || defaultAvatarUrl;

    function setSelectedAvatar(url) {
        const nextUrl = url || defaultAvatarUrl;
        if (!nextUrl) return;

        if (selectedAvatarInput) selectedAvatarInput.value = nextUrl;
        if (currentAvatarDisplay && currentAvatarDisplay.tagName !== 'IMG') {
            const img = document.createElement('img');
            img.id = 'currentAvatarDisplay';
            img.alt = 'Profile Avatar';
            img.className = 'profile-avatar-img';
            currentAvatarDisplay.replaceWith(img);
            currentAvatarDisplay = img;
        }
        if (currentAvatarDisplay) currentAvatarDisplay.src = nextUrl;

        avatarOptions.forEach((option) => {
            option.classList.toggle('selected', option.dataset.url === nextUrl);
        });

        document.querySelectorAll('.header-avatar, .chat-topbar-avatar').forEach((img) => {
            img.src = nextUrl;
        });
    }

    function showSaved(statusEl) {
        if (!statusEl) return;
        statusEl.hidden = false;
        window.clearTimeout(statusEl._hideTimer);
        statusEl._hideTimer = window.setTimeout(() => {
            statusEl.hidden = true;
        }, 2200);
    }

    function getControls(section) {
        return section.querySelectorAll('input, textarea, select');
    }

    function setSectionMode(section, isEditing) {
        section.classList.toggle('is-editing', isEditing);
        const editButton = section.querySelector('.profile-edit-btn');
        const saveButton = section.querySelector('.profile-save-btn');
        const status = section.querySelector('[data-save-status]');

        if (editButton) editButton.hidden = isEditing;
        if (saveButton) saveButton.hidden = !isEditing;
        if (isEditing && status) status.hidden = true;

        getControls(section).forEach((control) => {
            if (control.dataset.alwaysDisabled === 'true') {
                control.disabled = true;
                return;
            }

            if (control.type === 'checkbox' || control.tagName === 'SELECT') {
                control.disabled = !isEditing;
            } else {
                control.readOnly = !isEditing;
            }
        });

        if (isEditing) {
            const firstEditable = Array.from(getControls(section)).find((control) => {
                return control.dataset.alwaysDisabled !== 'true' && !control.disabled && control.type !== 'hidden';
            });
            firstEditable?.focus();
        }
    }

    function readPayload() {
        return {
            full_name: document.getElementById('fullName')?.value || '',
            location: document.getElementById('location')?.value || '',
            skills_offered: document.getElementById('skillsOffered')?.value || '',
            skills_wanted: document.getElementById('skillsWanted')?.value || '',
            bio: document.getElementById('bio')?.value || '',
            video_url: document.getElementById('video_url')?.value || '',
            video_description: document.getElementById('video_description')?.value || '',
            phone: document.getElementById('phone')?.value || '',
            contact_number: document.getElementById('contact_number')?.value || '',
            instagram_id: document.getElementById('instagram_id')?.value || '',
            contact_sharing: document.getElementById('contact_sharing')?.checked || false,
            allow_contact_after_payment: document.getElementById('contact_sharing')?.checked || false,
            email_notifications: document.getElementById('emailNotifications')?.checked || false,
            profile_visibility: document.getElementById('profileVisibility')?.checked || false,
            match_notifications: document.getElementById('matchNotifications')?.checked || false,
            avatar_url: selectedAvatarInput?.value || defaultAvatarUrl
        };
    }

    function submitProfileData() {
        const payload = readPayload();

        if (payload.video_url) {
            const ytRegex = /^(https?:\/\/)?(www\.youtube\.com|youtu\.be)\/.+$/;
            const driveRegex = /^(https?:\/\/)?(drive\.google\.com)\/.+$/;
            if (!ytRegex.test(payload.video_url) && !driveRegex.test(payload.video_url)) {
                SkillFlowUI.error('Please provide a valid YouTube or Google Drive link for the Demo Video.');
                return Promise.resolve(false);
            }
        }

        return fetch('/api/profile/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        .then((res) => res.json())
        .then((data) => {
            if (data.success) {
                setSelectedAvatar(data.avatar_url || payload.avatar_url);
                return true;
            }
            SkillFlowUI.error(data.error || 'Unable to update profile');
            return false;
        })
        .catch((err) => {
            console.error(err);
            SkillFlowUI.error('Unable to save profile changes.');
            return false;
        });
    }

    btnOpenAvatarModal?.addEventListener('click', () => {
        if (avatarSaveStatus) avatarSaveStatus.hidden = true;
        avatarModal?.classList.add('active');
    });

    function closeAvatarModal({ keepPreview = false } = {}) {
        if (!keepPreview) setSelectedAvatar(savedAvatarUrl);
        avatarModal?.classList.remove('active');
    }

    btnCloseAvatarModal?.addEventListener('click', () => closeAvatarModal());

    avatarModal?.addEventListener('click', (event) => {
        if (event.target === avatarModal) closeAvatarModal();
    });

    btnConfirmAvatar?.addEventListener('click', () => {
        submitProfileData().then((success) => {
            if (!success) return;
            savedAvatarUrl = selectedAvatarInput?.value || savedAvatarUrl;
            closeAvatarModal({ keepPreview: true });
            showSaved(avatarSaveStatus);
        });
    });

    avatarOptions.forEach((option) => {
        const image = option.querySelector('img');
        image?.addEventListener('error', () => {
            option.classList.add('image-unavailable');
        });

        option.addEventListener('click', () => {
            setSelectedAvatar(option.dataset.url);
        });
    });

    editableSections.forEach((section) => {
        const editButton = section.querySelector('.profile-edit-btn');
        const form = section.querySelector('form');

        setSectionMode(section, false);

        editButton?.addEventListener('click', () => {
            setSectionMode(section, true);
        });

        form?.addEventListener('submit', (event) => {
            event.preventDefault();
            submitProfileData().then((success) => {
                if (!success) return;
                setSectionMode(section, false);
                showSaved(section.querySelector('[data-save-status]'));
            });
        });
    });

    const btnChangePassword = document.getElementById('btnChangePassword');
    if (btnChangePassword) {
        btnChangePassword.addEventListener('click', async () => {
            const values = await SkillFlowUI.input({
                title: 'Change Password',
                message: 'Enter your current password and choose a new one.',
                confirmText: 'Update Password',
                fields: [
                    { name: 'current_password', label: 'Current Password', type: 'password', required: true },
                    { name: 'new_password', label: 'New Password', type: 'password', required: true }
                ]
            });
            if (!values) return;

            fetch('/api/account/change-password', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    current_password: values.current_password,
                    new_password: values.new_password
                })
            })
            .then((res) => res.json())
            .then((data) => {
                if (data.success) SkillFlowUI.success('Password changed successfully!');
                else SkillFlowUI.error(data.error || 'Unable to change password.');
            })
            .catch(() => SkillFlowUI.error('Failed to change password.'));
        });
    }

    const btnDeleteAccount = document.getElementById('btnDeleteAccount');
    if (btnDeleteAccount) {
        btnDeleteAccount.addEventListener('click', async () => {
            const confirmed = await SkillFlowUI.confirmDialog('Are you sure? This cannot be undone.', {
                title: 'Delete Account',
                confirmText: 'Delete Account',
                cancelText: 'Cancel',
                danger: true
            });
            if (!confirmed) return;

            fetch('/api/account/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
            })
            .then((res) => res.json())
            .then((data) => {
                if (data.success) {
                    SkillFlowUI.success('Account deleted. Redirecting...');
                    window.location.href = '/';
                } else {
                    SkillFlowUI.error(data.error || 'Unable to delete account.');
                }
            })
            .catch(() => SkillFlowUI.error('Failed to delete account.'));
        });
    }

    setSelectedAvatar(savedAvatarUrl);
});
