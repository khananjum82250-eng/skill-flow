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
    const settingsModal = document.getElementById('profileSettingsModal');
    const btnOpenSettingsModal = document.getElementById('btnOpenSettingsModal');
    const btnCloseSettingsModal = document.getElementById('btnCloseSettingsModal');
    const profileSettingsForm = document.getElementById('profileSettingsForm');
    const btnDeactivateAccount = document.getElementById('btnDeactivateAccount');
    const btnSettingsDeleteAccount = document.getElementById('btnSettingsDeleteAccount');
    const defaultAvatarUrl = avatarOptions[0]?.dataset.url || '';
    let savedAvatarUrl = selectedAvatarInput?.value || defaultAvatarUrl;
    let settingsLoaded = false;

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
        const payload = {
            username: document.getElementById('usernameInput')?.value || '',
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
            avatar_url: selectedAvatarInput?.value || defaultAvatarUrl
        };

        const skillCategoryInputs = Array.from(document.querySelectorAll('input[name="skillCategories"]'));
        if (skillCategoryInputs.length) {
            payload.skill_category_ids = skillCategoryInputs.filter((item) => item.checked).map((item) => item.value);
        }

        const emailNotifications = document.getElementById('emailNotifications');
        const profileVisibility = document.getElementById('profileVisibility');
        const matchNotifications = document.getElementById('matchNotifications');
        if (emailNotifications) payload.email_notifications = emailNotifications.checked;
        if (profileVisibility) payload.profile_visibility = profileVisibility.checked;
        if (matchNotifications) payload.match_notifications = matchNotifications.checked;

        return payload;
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
                document.querySelectorAll('.profile-username-display').forEach((item) => {
                    item.textContent = `@${data.username || payload.username}`;
                });
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

    function setCheckbox(id, value) {
        const checkbox = document.getElementById(id);
        if (checkbox) checkbox.checked = Boolean(value);
    }

    function populateSettings(settings = {}) {
        const contactInfoVisibility = document.getElementById('contactInfoVisibility');
        if (contactInfoVisibility) contactInfoVisibility.value = settings.contact_info_visibility || 'matched';
        setCheckbox('showDemoVideoPublicly', settings.show_demo_video_publicly);
        setCheckbox('showLocationPublicly', settings.show_location_publicly);
        setCheckbox('requestNotifications', settings.request_notifications);
        setCheckbox('chatNotifications', settings.chat_notifications);
        setCheckbox('reviewNotifications', settings.review_notifications);
        setCheckbox('paymentNotifications', settings.payment_notifications);
        setCheckbox('allowMatchedMessages', settings.allow_matched_messages);
        setCheckbox('autoScrollMessages', settings.auto_scroll_messages);
    }

    function collectSettingsPayload() {
        return {
            contact_info_visibility: document.getElementById('contactInfoVisibility')?.value || 'matched',
            show_demo_video_publicly: document.getElementById('showDemoVideoPublicly')?.checked || false,
            show_location_publicly: document.getElementById('showLocationPublicly')?.checked || false,
            request_notifications: document.getElementById('requestNotifications')?.checked || false,
            chat_notifications: document.getElementById('chatNotifications')?.checked || false,
            review_notifications: document.getElementById('reviewNotifications')?.checked || false,
            payment_notifications: document.getElementById('paymentNotifications')?.checked || false,
            allow_matched_messages: document.getElementById('allowMatchedMessages')?.checked || false,
            auto_scroll_messages: document.getElementById('autoScrollMessages')?.checked || false
        };
    }

    function loadProfileSettings() {
        return fetch('/api/user/settings')
            .then((res) => res.json())
            .then((data) => {
                if (!data.success) throw new Error(data.error || 'Unable to load settings');
                populateSettings(data.settings || {});
                settingsLoaded = true;
            })
            .catch((err) => {
                console.error(err);
                SkillFlowUI.error('Unable to load profile settings.');
            });
    }

    function closeSettingsModal() {
        settingsModal?.classList.remove('active');
    }

    btnOpenSettingsModal?.addEventListener('click', () => {
        settingsModal?.classList.add('active');
        if (!settingsLoaded) loadProfileSettings();
    });

    btnCloseSettingsModal?.addEventListener('click', closeSettingsModal);

    settingsModal?.addEventListener('click', (event) => {
        if (event.target === settingsModal) closeSettingsModal();
    });

    profileSettingsForm?.addEventListener('submit', (event) => {
        event.preventDefault();
        const saveButton = document.getElementById('btnSaveProfileSettings');
        if (saveButton) {
            saveButton.disabled = true;
            saveButton.classList.add('is-loading');
        }
        fetch('/api/user/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(collectSettingsPayload())
        })
        .then((res) => res.json())
        .then((data) => {
            if (!data.success) throw new Error(data.error || 'Unable to save settings');
            populateSettings(data.settings || collectSettingsPayload());
            settingsLoaded = true;
            SkillFlowUI.success('Settings saved successfully.');
            closeSettingsModal();
        })
        .catch((err) => {
            console.error(err);
            SkillFlowUI.error('Unable to save profile settings.');
        })
        .finally(() => {
            if (saveButton) {
                saveButton.disabled = false;
                saveButton.classList.remove('is-loading');
            }
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

    btnDeactivateAccount?.addEventListener('click', async () => {
        const confirmed = await SkillFlowUI.confirmDialog('Deactivate your account? You will be logged out and your profile will be hidden.', {
            title: 'Deactivate Account',
            confirmText: 'Deactivate',
            cancelText: 'Cancel',
            danger: true
        });
        if (!confirmed) return;

        fetch('/api/account/deactivate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        })
        .then((res) => res.json())
        .then((data) => {
            if (data.success) {
                SkillFlowUI.success('Account deactivated. Redirecting...');
                window.location.href = '/';
            } else {
                SkillFlowUI.error(data.error || 'Unable to deactivate account.');
            }
        })
        .catch(() => SkillFlowUI.error('Failed to deactivate account.'));
    });

    btnSettingsDeleteAccount?.addEventListener('click', async () => {
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

    setSelectedAvatar(savedAvatarUrl);
});
