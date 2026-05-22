// SkillFlow Requests Page JavaScript

const requestsApi = {
  incoming: '/api/request/incoming',
  sent: '/api/request/sent',
  accept: '/api/request/accept',
  reject: '/api/request/reject',
  matches: '/api/matches'
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
      actionHtml = `<span class="badge-pending"><i class="fa-regular fa-hourglass-half"></i> Pending</span>`;
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

  // For matches, 'exchange' string usually comes back from backend like "Their Skill <=> My Skill"
  // But let's build the UI matching the image
  // Let's assume match object has some data, but since api returns 'exchange' as string, we'll parse it simply or fall back
  let parts = match.exchange ? match.exchange.split('<=>') : ['Your Skill', 'Their Skill'];
  let youLearn = parts[1] ? parts[1].trim() : 'Skill';
  let theyLearn = parts[0] ? parts[0].trim() : 'Skill';

  return `
    <div class="req-card">
      <div class="req-user">
          <img src="${avatar}" alt="${match.name}" class="req-avatar">
          <div class="req-user-info">
              <h4>${match.name}</h4>
              <span class="req-role">${match.role || 'Skill Partner'}</span>
              ${locationHtml}
          </div>
      </div>
      <div class="req-skills match-skills">
          <div class="req-skill-col">
              <span class="req-label">YOU ARE LEARNING</span>
              <div class="req-tags"><span class="req-tag learn">${youLearn}</span></div>
          </div>
          <div class="match-arrows"><i class="fa-solid fa-right-left"></i></div>
          <div class="req-skill-col">
              <span class="req-label">THEY ARE LEARNING</span>
              <div class="req-tags"><span class="req-tag teach">${theyLearn}</span></div>
          </div>
      </div>
      <div class="req-actions">
          <div class="match-meta">
              <span>Matched on</span>
              <span class="match-date">${timeDate}</span>
          </div>
          <button class="btn-outline-primary" data-action="message" data-user-id="${match.other_id}" data-request-id="${match.request_id}"><i class="fa-regular fa-message"></i> Message</button>
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
  if (!data || !data.matches || data.matches.length === 0) {
    container.innerHTML = '<p class="text-muted">No active matches at the moment.</p>';
    refreshRequestScrollbar(container);
    return;
  }
  container.innerHTML = `<div class="request-list">` + data.matches.map((item) => buildMatchCard(item)).join('') + `</div>`;
  refreshRequestScrollbar(container);
}

function refreshRequestScrollbar(panel) {
  if (!panel) return;

  panel.querySelector('.custom-request-scrollbar')?.remove();
  const list = panel.querySelector('.request-list');
  if (!list) return;

  const rail = document.createElement('div');
  rail.className = 'custom-request-scrollbar';
  rail.innerHTML = '<div class="custom-scrollbar-thumb"></div>';
  panel.appendChild(rail);

  const thumb = rail.querySelector('.custom-scrollbar-thumb');
  const update = () => {
    const maxScroll = list.scrollHeight - list.clientHeight;
    rail.style.display = maxScroll > 2 ? 'block' : 'none';
    if (maxScroll <= 2) return;

    const trackHeight = rail.clientHeight;
    const thumbHeight = Math.max(54, (list.clientHeight / list.scrollHeight) * trackHeight);
    const maxThumbTop = trackHeight - thumbHeight;
    const thumbTop = (list.scrollTop / maxScroll) * maxThumbTop;

    thumb.style.height = `${thumbHeight}px`;
    thumb.style.transform = `translateY(${thumbTop}px)`;
  };

  list.addEventListener('scroll', update);
  window.addEventListener('resize', update);
  requestAnimationFrame(update);
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
    } else if (button.dataset.action === 'message') {
      handleMessage(button.dataset.userId, requestId);
    } else if (button.dataset.action === 'view-profile') {
      viewProfile(button.dataset.userId);
    }
  });
  fetchAllTabs();
}

window.addEventListener('DOMContentLoaded', initPage);
