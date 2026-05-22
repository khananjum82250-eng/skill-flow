window.showRequestStatusToast = function(status, label) {
    const messages = {
        pending: 'You already sent a request to this user.',
        accepted: 'Chat access is available for this matched user.',
        matched: 'Your request was accepted. You are already matched with this user.',
        unlocked: 'Chat is already unlocked for this matched user.'
    };
    const message = label === 'Request Pending'
        ? 'A request with this user is already pending.'
        : (messages[status] || 'This request status is already updated.');
    if (window.SkillFlowUI && typeof SkillFlowUI.success === 'function') {
        SkillFlowUI.success(message);
    }
};

// Function to send request from dashboard
window.sendRequestDashboard = function(receiverId, skillRequested, skillOffered) {
    if (!receiverId) return;
    const button = document.querySelector(`.btn-send-request[data-receiver-id="${receiverId}"]`);
    if (button) {
        button.disabled = true;
        button.textContent = 'Sending...';
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
            const relationship = data.relationship || {};
            const label = relationship.status === 'matched'
                ? 'Already Matched'
                : relationship.status === 'unlocked'
                    ? 'Unlocked'
                : relationship.status === 'accepted'
                    ? 'Accepted'
                : (relationship.label || data.message || 'Request Sent');
            if (button) {
                button.textContent = label;
                button.disabled = false;
                button.classList.add('request-status-button');
                button.dataset.requestStatus = relationship.status || 'pending';
                button.dataset.requestLabel = label;
                button.removeAttribute('onclick');
                button.addEventListener('click', () => showRequestStatusToast(button.dataset.requestStatus, button.dataset.requestLabel));
            }
            if (!data.already_exists) SkillFlowUI.success('Request sent successfully!');
        } else {
            if (button) {
                button.disabled = false;
                button.textContent = 'Send Request';
            }
            SkillFlowUI.error(data.error || 'Failed to send request.');
        }
    })
    .catch(err => {
        console.error('Fetch error:', err);
        if (button) {
            button.disabled = false;
            button.textContent = 'Send Request';
        }
        SkillFlowUI.error('Failed to send request.');
    });
};
