// Dashboard Page Specific JS
document.addEventListener('DOMContentLoaded', () => {
    const menuButton = document.querySelector('[data-dashboard-menu]');
    const sidebarOverlay = document.querySelector('[data-sidebar-overlay]');
    const profileToggle = document.querySelector('[data-profile-menu-toggle]');
    const profileMenu = document.querySelector('[data-profile-menu]');

    const closeSidebar = () => document.body.classList.remove('dashboard-sidebar-open');
    const closeProfileMenu = () => profileMenu?.classList.remove('is-open');

    menuButton?.addEventListener('click', () => {
        document.body.classList.toggle('dashboard-sidebar-open');
        closeProfileMenu();
    });

    sidebarOverlay?.addEventListener('click', closeSidebar);

    profileToggle?.addEventListener('click', (event) => {
        event.stopPropagation();
        profileMenu?.classList.toggle('is-open');
        closeSidebar();
    });

    document.addEventListener('click', (event) => {
        if (!event.target.closest('.profile-menu-wrap')) closeProfileMenu();
    });

    document.addEventListener('click', (event) => {
        const requestButton = event.target.closest('.btn-send-request');
        if (!requestButton || requestButton.disabled) return;

        sendRequestDashboard(
            requestButton.dataset.receiverId,
            requestButton.dataset.skillRequested,
            requestButton.dataset.skillOffered
        );
    });

    window.addEventListener('resize', () => {
        if (window.innerWidth > 900) closeSidebar();
    });

    document.querySelectorAll('[data-load-recommendations]').forEach((button) => {
        button.addEventListener('click', (event) => {
            event.preventDefault();
            loadMoreRecommendations(button);
        });
    });

    // Intercept Dashboard Skills Form
    const dashboardSkillsForm = document.getElementById('dashboardSkillsForm');
    
    if (dashboardSkillsForm) {
        dashboardSkillsForm.addEventListener('submit', (e) => {
            e.preventDefault();
            
            const skillsOffered = document.getElementById('dbSkillsOffered').value;
            const skillsWanted = document.getElementById('dbSkillsWanted').value;
            
            fetch('/update_skills', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    skills_offered: skillsOffered,
                    skills_wanted: skillsWanted
                })
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    // Update the tags in the DOM
                    updateTags('tagsOffered', data.skills_offered, 'badge-purple');
                    updateTags('tagsWanted', data.skills_wanted, 'badge-secondary');
                    
                    SkillFlowUI.success('Skills updated successfully!');
                } else {
                    SkillFlowUI.error(data.error || 'Unable to update skills.');
                }
            })
            .catch(err => {
                console.error('Fetch error:', err);
                SkillFlowUI.error('Failed to save skills.');
            });
        });
    }
    
    function updateTags(containerId, skillsString, badgeClass) {
        const container = document.getElementById(containerId);
        container.innerHTML = '';
        
        if (!skillsString) return;
        
        const skills = skillsString.split(',').map(s => s.trim()).filter(s => s);
        skills.forEach(skill => {
            const span = document.createElement('span');
            span.className = `badge ${badgeClass}`;
            span.textContent = skill;
            container.appendChild(span);
        });
    }
});

function escapeHTML(value) {
    const div = document.createElement('div');
    div.textContent = value || '';
    return div.innerHTML;
}

function firstSkill(value) {
    return String(value || 'Skill').split(',')[0].trim() || 'Skill';
}

function matchBadgeVariant(percentage) {
    if (percentage >= 100) return 'full';
    if (percentage > 0) return 'partial';
    return 'none';
}

function buildDashboardRequestAction(user) {
    const relationship = user.relationship || { can_request: true };
    if (relationship.can_request === false) {
        const status = relationship.status || 'pending';
        return `
            <span class="request-state-badge request-state-${escapeHTML(status)}">
                <i class="${requestStateIcon(status)}"></i>
                ${escapeHTML(relationship.label || 'Request Sent')}
            </span>
        `;
    }

    return `
        <button class="btn-send-request"
            data-receiver-id="${escapeHTML(String(user.id))}"
            data-skill-requested="${escapeHTML(firstSkill(user.skills_offered))}"
            data-skill-offered="${escapeHTML(firstSkill(window.currentUserOfferedSkill || 'Skill'))}">
            <i class="fa-solid fa-paper-plane"></i>
            Send Request
        </button>
    `;
}

function buildRecommendationItem(user) {
    const name = user.full_name || user.name || user.username || 'SkillFlow User';
    const matchPercent = Number(user.match_percentage || 0);
    const matchVariant = user.match_badge_variant || matchBadgeVariant(matchPercent);
    const matchLabel = user.match_badge_label || `${matchPercent}% Match`;
    return `
        <article class="recommended-user-item recommended-user-card is-new-recommendation">
            <div class="recommended-card-top">
                <div class="r-user-info">
                    <img src="${escapeHTML(user.avatar_url || '')}" class="r-user-avatar" alt="${escapeHTML(name)} avatar">
                    <div>
                        <span class="r-user-name">${escapeHTML(name)}</span>
                        <span class="r-user-subtitle">Skill partner</span>
                    </div>
                </div>
                <span class="match-pill match-pill-${escapeHTML(matchVariant)}">${escapeHTML(matchLabel)}</span>
            </div>
            <div class="r-user-skills">
                <div class="r-skill">
                    <span class="r-skill-label teach">Teaches:</span>
                    <span class="r-skill-val">${escapeHTML(user.skills_offered || 'None')}</span>
                </div>
                <div class="r-skill">
                    <span class="r-skill-label learn">Wants to Learn:</span>
                    <span class="r-skill-val">${escapeHTML(user.skills_wanted || 'None')}</span>
                </div>
            </div>
            <div class="r-user-actions">
                <a class="btn-view-profile-dashboard" href="/profile/${encodeURIComponent(user.id)}">
                    <i class="fa-regular fa-user"></i>
                    View Profile
                </a>
                ${buildDashboardRequestAction(user)}
            </div>
        </article>
    `;
}

function loadMoreRecommendations(button) {
    const list = document.querySelector('.recommended-users-list');
    if (!list || button.disabled) return;

    window.currentUserOfferedSkill = button.dataset.skillOffered || 'Skill';
    const offset = Number(button.dataset.offset || 0);
    const limit = Number(button.dataset.limit || 4);
    button.disabled = true;
    const originalHTML = button.innerHTML;
    button.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Loading...';

    fetch(`/recommendations?offset=${encodeURIComponent(offset)}&limit=${encodeURIComponent(limit)}`)
        .then((response) => response.json())
        .then((data) => {
            if (data.error) {
                SkillFlowUI.error(data.error);
                return;
            }

            if (!data.users || data.users.length === 0) {
                SkillFlowUI.info('No more recommendations available.');
                button.hidden = true;
                return;
            }

            list.insertAdjacentHTML('beforeend', data.users.map(buildRecommendationItem).join(''));
            const panelCount = document.querySelector('.recommendations-panel .panel-count');
            button.dataset.offset = String(data.next_offset || (offset + data.users.length));
            if (panelCount) panelCount.textContent = `${button.dataset.offset} shown`;
            if (!data.has_more) {
                button.hidden = true;
            }
        })
        .catch(() => SkillFlowUI.error('Unable to load more recommendations.'))
        .finally(() => {
            button.disabled = false;
            button.innerHTML = originalHTML;
        });
}

// Function to send request from dashboard
window.sendRequestDashboard = function(receiverId, skillRequested, skillOffered) {
    if (!receiverId) return;
    const button = document.querySelector(`.btn-send-request[data-receiver-id="${receiverId}"]`);
    if (button) {
        button.disabled = true;
        button.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Sending...';
    }
    
    fetch('/api/request/send', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            receiver_id: receiverId,
            skill_requested: skillRequested.trim() || 'Skill',
            skill_offered: skillOffered.trim() || 'Skill'
        })
    })
    .then(res => res.json())
    .then(data => {
        if (data.success) {
            if (button) replaceDashboardRequestButton(button, data.relationship || { status: 'pending', label: 'Request Sent' });
            SkillFlowUI.success('Request sent successfully!');
        } else {
            SkillFlowUI.error(data.error || 'Failed to send request.');
            if (data.relationship && button) replaceDashboardRequestButton(button, data.relationship);
            else if (button) {
                button.disabled = false;
                button.innerHTML = 'Send Request';
            }
        }
    })
    .catch(err => {
        console.error('Fetch error:', err);
        SkillFlowUI.error('Failed to send request.');
        if (button) {
            button.disabled = false;
            button.innerHTML = 'Send Request';
        }
    });
};

function requestStateIcon(status) {
    if (status === 'matched' || status === 'accepted') return 'fa-solid fa-check';
    if (status === 'rejected') return 'fa-solid fa-xmark';
    return 'fa-regular fa-hourglass-half';
}

function replaceDashboardRequestButton(button, relationship) {
    const status = relationship.status || 'pending';
    const label = relationship.label || 'Request Sent';
    const badge = document.createElement('span');
    badge.className = `request-state-badge request-state-${status}`;
    badge.innerHTML = `<i class="${requestStateIcon(status)}"></i> ${label}`;
    button.replaceWith(badge);
}
