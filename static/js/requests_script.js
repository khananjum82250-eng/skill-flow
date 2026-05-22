(function () {
// SkillFlow Requests Page JavaScript

const requestsApi = {
  incoming: '/api/request/incoming',
  sent: '/api/request/sent',
  accept: '/api/request/accept',
  reject: '/api/request/reject',
  cancel: '/api/request/cancel',
  matches: '/api/matches',
  saved: '/api/favorites/list',
  removeSaved: '/api/favorites/remove'
};

function createBadge(text, variant = 'primary') {
  return `<span class="badge badge-${variant}">${text}</span>`;
}

function formatRelativeTime(value) {
  if (!value) return 'Just now';
  const date = new Date(value);
  const diff = Date.now() - date.getTime();
  const minutes = Math.floor(diff / 60000);
  if (minutes < 1) return 'Just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function showToast(message) {
  SkillFlowUI.info(message);
}

function buildSkillMatchHtml(item) {
  const percent = Number(item.match_percentage || 0);
  const pairs = Array.isArray(item.match_pairs) ? item.match_pairs : [];
  const learning = pairs.find((pair) => pair.direction === 'they_teach_you')?.your_skill;
  const teaching = pairs.find((pair) => pair.direction === 'you_teach_them')?.your_skill;
  const learningHtml = learning ? `<span class="req-tag learn">Learning: ${learning}</span>` : '';
  const teachingHtml = teaching ? `<span class="req-tag teach">Teaching: ${teaching}</span>` : '';

  return `
    <div class="req-skill-col req-match-compact">
      <span class="req-label">SKILL MATCH</span>
      <div class="req-tags">
        <span class="req-tag match-percent">Skill Match: ${percent}%</span>
        ${learningHtml}
        ${teachingHtml}
      </div>
    </div>
  `;
}

function switchTab(tabKey) {
  document.querySelectorAll('.tab-link').forEach((button) => {
    button.classList.toggle('active', button.dataset.tab === tabKey);
  });
  document.querySelectorAll('.tab-pane').forEach((panel) => {
    if (panel.id === tabKey) {
      panel.classList.add('active');
    } else {
      panel.classList.remove('active');
    }
  });
}

function buildRequestCard(request, type = 'incoming') {
  const avatar = request.avatar_url || '';
  const timeLabel = formatRelativeTime(request.created_at);
  const locationHtml = request.location && request.location !== 'Remote' ? `<span class="req-loc"><i class="fa-solid fa-location-dot"></i> ${request.location}</span>` : '<span class="req-loc"><i class="fa-solid fa-globe"></i> Remote</span>';
  const profileUserId = request.sender_id || request.receiver_id;
  const viewProfileHtml = profileUserId
    ? `<button class="btn-view-profile" data-action="view-profile" data-user-id="${profileUserId}"><i class="fa-regular fa-user"></i> View Profile</button>`
    : '';

  let actionHtml = '';
  if (request.status === 'pending') {
    if (type === 'incoming') {
      actionHtml = `
        <button class="btn-outline-accept" data-action="accept" data-request-id="${request.id}"><i class="fa-solid fa-check"></i> Accept</button>
        <button class="btn-outline-reject" data-action="reject" data-request-id="${request.id}"><i class="fa-solid fa-xmark"></i> Decline</button>
      `;
    } else {
      actionHtml = `
        <span class="badge-pending"><i class="fa-regular fa-hourglass-half"></i> Pending</span>
        <button class="btn-outline-reject" data-action="cancel" data-request-id="${request.id}"><i class="fa-solid fa-ban"></i> Unsend Request</button>
      `;
    }
  } else if (request.status === 'accepted') {
    actionHtml = `<span class="badge-accepted"><i class="fa-solid fa-check"></i> Accepted</span>`;
  } else if (request.status === 'rejected') {
    actionHtml = `<span class="badge-rejected"><i class="fa-solid fa-xmark"></i> Declined</span>`;
  }

  let wantsToLearn = request.learns ? request.learns.split(',').map(s => `<span class="req-tag learn">${s.trim()}</span>`).join('') : '<span class="req-tag learn">None</span>';
  let offersToTeach = request.teaches ? request.teaches.split(',').map(s => `<span class="req-tag teach">${s.trim()}</span>`).join('') : '<span class="req-tag teach">None</span>';

  return `
    <div class="req-card req-card-request">
      <div class="req-main">
        <div class="req-user">
            <img src="${avatar}" alt="${request.name}" class="req-avatar">
            <div class="req-user-info">
                <h4>${request.name}</h4>
                <span class="req-role">${request.role}</span>
                ${locationHtml}
                <span class="req-time">${timeLabel}</span>
            </div>
        </div>
        <div class="req-skills">
            <div class="req-skill-col">
                <span class="req-label">WANTS TO LEARN</span>
                <div class="req-tags">${wantsToLearn}</div>
            </div>
            <div class="req-skill-col">
                <span class="req-label">OFFERS TO TEACH</span>
                <div class="req-tags">${offersToTeach}</div>
            </div>
            ${buildSkillMatchHtml(request)}
        </div>
      </div>
      <div class="req-actions">
        <div class="req-left-actions">
          ${actionHtml}
        </div>
        <div class="req-right-actions">
          ${viewProfileHtml}
        </div>
      </div>
    </div>
  `;
}

function buildMatchCard(match) {
  const avatar = match.avatar_url || '';
  const timeDate = new Date(match.matched_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
  const locationHtml = match.location && match.location !== 'Remote' ? `<span class="req-loc"><i class="fa-solid fa-location-dot"></i> ${match.location}</span>` : '<span class="req-loc"><i class="fa-solid fa-globe"></i> Remote</span>';
  const profileButton = `<button class="btn-view-profile" data-action="view-profile" data-user-id="${match.other_id}"><i class="fa-regular fa-user"></i> View Profile</button>`;
  const chatButton = match.can_chat && match.request_id
    ? `<button class="btn-outline-primary" data-action="message" data-user-id="${match.other_id}" data-request-id="${match.request_id}"><i class="fa-regular fa-message"></i> Message</button>`
    : `<span class="badge-pending"><i class="fa-solid fa-wand-magic-sparkles"></i> Skill Match</span>`;

  const pairs = Array.isArray(match.match_pairs) ? match.match_pairs : [];
  const theyTeachYou = pairs.find((pair) => pair.direction === 'they_teach_you');
  const youTeachThem = pairs.find((pair) => pair.direction === 'you_teach_them');
  const yourTeach = youTeachThem?.your_skill || 'Not matched';
  const yourLearn = theyTeachYou?.your_skill || 'Not matched';
  const theirTeach = theyTeachYou?.their_skill || theyTeachYou?.your_skill || 'Not matched';
  const theirLearn = youTeachThem?.their_skill || youTeachThem?.your_skill || 'Not matched';
  const yourStatus = youTeachThem || theyTeachYou ? 'Match found' : 'No matching skill yet';
  const theirStatus = theyTeachYou || youTeachThem ? 'Match found' : 'No matching skill yet';
  const percent = Number(match.match_percentage || 0);

  const skillPill = (label, value, type, matched) => `
    <span class="match-skill-pill ${type} ${matched ? 'is-matched' : 'is-unmatched'}">
      <strong>${label}:</strong> ${value}
    </span>
  `;

  return `
    <div class="req-card req-card-match match-card-modern">
      <div class="match-user-panel">
        <img src="${avatar}" alt="${match.name}" class="req-avatar match-avatar">
        <div class="req-user-info match-user-info">
          <h4>${match.name}</h4>
          <span class="req-role">@${match.username || 'skillflow'}</span>
          <span class="match-percent-badge"><i class="fa-solid fa-star"></i> ${percent}% Match</span>
          ${locationHtml}
        </div>
      </div>

      <div class="match-compare-panel">
        <div class="match-skill-box">
          <span class="match-box-label"><i class="fa-solid fa-user-check"></i> Your Skills</span>
          <div class="match-skill-list">
            ${skillPill('Teach', yourTeach, 'teach', !!youTeachThem)}
            ${skillPill('Learn', yourLearn, 'learn', !!theyTeachYou)}
          </div>
          <span class="match-status ${yourStatus === 'Match found' ? 'matched' : 'unmatched'}">${yourStatus}</span>
        </div>

        <div class="match-swap-icon"><i class="fa-solid fa-right-left"></i></div>

        <div class="match-skill-box">
          <span class="match-box-label"><i class="fa-solid fa-graduation-cap"></i> Their Skills</span>
          <div class="match-skill-list">
            ${skillPill('Teach', theirTeach, 'teach', !!theyTeachYou)}
            ${skillPill('Learn', theirLearn, 'learn', !!youTeachThem)}
          </div>
          <span class="match-status ${theirStatus === 'Match found' ? 'matched' : 'unmatched'}">${theirStatus}</span>
        </div>
      </div>

      <div class="match-actions-panel">
        <div class="match-meta">
          <span>Matched on</span>
          <span class="match-date">${timeDate}</span>
        </div>
        <div class="match-card-actions">
          ${chatButton}
          ${profileButton}
        </div>
      </div>
    </div>
  `;
}

function buildSkillTags(value, variant) {
  const skills = String(value || '')
    .split(',')
    .map((skill) => skill.trim())
    .filter(Boolean);
  if (!skills.length) return `<span class="req-tag ${variant}">None</span>`;
  return skills.map((skill) => `<span class="req-tag ${variant}">${skill}</span>`).join('');
}

function buildSavedProfileCard(profile) {
  const avatar = profile.avatar_url || '';
  const locationHtml = profile.location && profile.location !== 'Remote'
    ? `<span class="req-loc"><i class="fa-solid fa-location-dot"></i> ${profile.location}</span>`
    : '<span class="req-loc"><i class="fa-solid fa-globe"></i> Remote</span>';

  return `
    <div class="req-card saved-profile-card">
      <div class="saved-profile-main">
        <img src="${avatar}" alt="${profile.name}" class="req-avatar saved-profile-avatar">
        <div class="req-user-info saved-profile-info">
          <h4>${profile.name}</h4>
          <span class="req-role">@${profile.username || 'skillflow'}</span>
          ${locationHtml}
          <span class="match-percent-badge"><i class="fa-solid fa-star"></i> ${Number(profile.match_percentage || 0)}% Match</span>
        </div>
      </div>
      <div class="saved-profile-skills">
        <div class="req-skill-col">
          <span class="req-label">TEACHES</span>
          <div class="req-tags">${buildSkillTags(profile.teaches, 'teach')}</div>
        </div>
        <div class="req-skill-col">
          <span class="req-label">WANTS TO LEARN</span>
          <div class="req-tags">${buildSkillTags(profile.learns, 'learn')}</div>
        </div>
      </div>
      <div class="saved-profile-actions">
        <button class="btn-view-profile" data-action="view-profile" data-user-id="${profile.id}"><i class="fa-regular fa-user"></i> View Profile</button>
        <button class="btn-outline-reject" data-action="remove-saved" data-user-id="${profile.id}"><i class="fa-solid fa-bookmark-slash"></i> Remove Saved</button>
      </div>
    </div>
  `;
}

function handleMessage(userId, requestId) {
  if (!userId || !requestId) {
    showToast('Invalid chat session.');
    return;
  }
  window.location.href = `/chat?user_id=${userId}&request_id=${requestId}`;
}

function viewProfile(userId) {
  if (!userId) {
    showToast('Profile unavailable.');
    return;
  }
  window.location.href = `/profile/${userId}`;
}

function payToUnlock(requestId) {
  function paymentErrorMessage(data) {
    if (!data) return 'Payment failed. Please try again';
    if (data.details && data.details.phonepe_response) return data.details.phonepe_response;
    if (data.details && data.details.exception) return data.details.exception;
    return data.error || 'Payment failed. Please try again';
  }

  fetch('/api/payment/create', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ request_id: requestId })
  })
  .then(resp => resp.json())
  .then(data => {
    if (data.error) {
      SkillFlowUI.error(paymentErrorMessage(data));
      return;
    }

    if (data.payment_url) {
      window.location.href = data.payment_url;
      return;
    }

    if (data.redirect_url) {
      window.location.href = data.redirect_url;
      return;
    }

    SkillFlowUI.error('Payment failed. Please try again');
  })
  .catch(() => SkillFlowUI.error('Payment failed. Please try again'));
}

function acceptRequest(requestId) {
  fetch(requestsApi.accept, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ request_id: requestId })
  })
    .then((resp) => resp.json())
    .then((data) => {
      if (data.success) {
        SkillFlowUI.success('Request accepted successfully.');
        fetchAllTabs();
      } else {
        SkillFlowUI.error(data.error || 'Unable to accept this request.');
      }
    })
    .catch(() => SkillFlowUI.error('Unable to accept request.'));
}

function rejectRequest(requestId) {
  fetch(requestsApi.reject, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ request_id: requestId })
  })
    .then((resp) => resp.json())
    .then((data) => {
      if (data.success) {
        SkillFlowUI.success('Request declined.');
        fetchAllTabs();
      } else {
        SkillFlowUI.error(data.error || 'Unable to reject this request.');
      }
    })
    .catch(() => SkillFlowUI.error('Unable to reject request.'));
}

function cancelRequest(requestId) {
  fetch(requestsApi.cancel, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ request_id: requestId, reason: 'Wrong request sent' })
  })
    .then((resp) => resp.json())
    .then((data) => {
      if (data.success) {
        SkillFlowUI.success('Request unsent.');
        fetchAllTabs();
      } else {
        SkillFlowUI.error(data.error || 'Unable to unsend this request.');
      }
    })
    .catch(() => SkillFlowUI.error('Unable to unsend request.'));
}

function renderIncomingRequests(data) {
  const container = document.getElementById('incoming');
  if (!data || !data.requests || data.requests.length === 0) {
    container.innerHTML = '<p class="text-muted">No incoming requests at the moment.</p>';
    refreshRequestScrollbar(container);
    return;
  }
  container.innerHTML = `<div class="request-list">` + data.requests.map((item) => buildRequestCard(item, 'incoming')).join('') + `</div>`;
  refreshRequestScrollbar(container);
}

function renderSentRequests(data) {
  const container = document.getElementById('sent');
  if (!data || !data.requests || data.requests.length === 0) {
    container.innerHTML = '<p class="text-muted">No sent requests at the moment.</p>';
    refreshRequestScrollbar(container);
    return;
  }
  container.innerHTML = `<div class="request-list">` + data.requests.map((item) => buildRequestCard(item, 'sent')).join('') + `</div>`;
  refreshRequestScrollbar(container);
}

function renderMatches(data) {
  const container = document.getElementById('matches');
  const matches = Array.isArray(data?.matches) ? data.matches : [];
  console.debug('[Matches Debug] response:', data, 'count:', matches.length);
  if (matches.length === 0) {
    container.innerHTML = '<p class="text-muted">No active matches at the moment.</p>';
    refreshRequestScrollbar(container);
    return;
  }
  container.innerHTML = `<div class="request-list">` + matches.map((item) => buildMatchCard(item)).join('') + `</div>`;
  refreshRequestScrollbar(container);
}

function renderSavedProfiles(data) {
  const container = document.getElementById('saved');
  const favorites = Array.isArray(data?.favorites) ? data.favorites : [];
  if (favorites.length === 0) {
    container.innerHTML = '<p class="text-muted">No saved profiles yet.</p>';
    refreshRequestScrollbar(container);
    return;
  }
  container.innerHTML = `<div class="request-list saved-profile-list">` + favorites.map((item) => buildSavedProfileCard(item)).join('') + `</div>`;
  refreshRequestScrollbar(container);
}

function fetchSavedProfiles() {
  return fetch(requestsApi.saved, { headers: { Accept: 'application/json' } })
    .then(async (res) => {
      const text = await res.text();
      let data = {};
      if (text) {
        try {
          data = JSON.parse(text);
        } catch (error) {
          if (res.status === 404) {
            return { favorites: [] };
          }
          throw error;
        }
      }

      if (!res.ok) {
        if (res.status === 404) return { favorites: [] };
        throw new Error(data.error || 'Unable to load saved profiles.');
      }
      return { favorites: Array.isArray(data.favorites) ? data.favorites : [] };
    });
}

function refreshRequestScrollbar(panel) {
  if (!panel) return;
  panel.querySelector('.custom-request-scrollbar')?.remove();
}

function fetchAllTabs() {
  fetch(requestsApi.incoming)
    .then((res) => res.json())
    .then(renderIncomingRequests)
    .catch(() => showToast('Unable to load incoming requests.'));

  fetch(requestsApi.sent)
    .then((res) => res.json())
    .then(renderSentRequests)
    .catch(() => showToast('Unable to load sent requests.'));

  fetch(requestsApi.matches)
    .then((res) => res.json())
    .then(renderMatches)
    .catch(() => showToast('Unable to load matches.'));

  fetchSavedProfiles()
    .then(renderSavedProfiles)
    .catch(() => {
      showToast('Unable to load saved profiles.');
      renderSavedProfiles({ favorites: [] });
    });
}

function initPage() {
  document.querySelectorAll('.tab-link').forEach((button) => {
    button.addEventListener('click', (e) => {
        e.preventDefault();
        switchTab(button.dataset.tab);
    });
  });
  document.querySelector('.requests-content')?.addEventListener('click', (event) => {
    const button = event.target.closest('[data-action]');
    if (!button) return;

    const requestId = button.dataset.requestId;
    if (button.dataset.action === 'accept') {
      acceptRequest(requestId);
    } else if (button.dataset.action === 'reject') {
      rejectRequest(requestId);
    } else if (button.dataset.action === 'cancel') {
      cancelRequest(requestId);
    } else if (button.dataset.action === 'message') {
      handleMessage(button.dataset.userId, requestId);
    } else if (button.dataset.action === 'view-profile') {
      viewProfile(button.dataset.userId);
    } else if (button.dataset.action === 'remove-saved') {
      removeSavedProfile(button.dataset.userId);
    }
  });
  fetchAllTabs();
}

function removeSavedProfile(userId) {
  if (!userId) {
    showToast('Saved profile unavailable.');
    return;
  }
  fetch(requestsApi.removeSaved, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: userId })
  })
    .then((resp) => resp.json())
    .then((data) => {
      if (data.success) {
        SkillFlowUI.success('Profile removed from saved profiles.');
        return fetchSavedProfiles().then(renderSavedProfiles);
      }
      SkillFlowUI.error(data.error || 'Unable to remove saved profile.');
    })
    .catch(() => SkillFlowUI.error('Unable to remove saved profile.'));
}

window.addEventListener('DOMContentLoaded', initPage);
})();
