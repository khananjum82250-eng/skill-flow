// SkillFlow Requests Page JavaScript

const requestsApi = {
  incoming: '/api/request/incoming',
  sent: '/api/request/sent',
  accept: '/api/request/accept',
  reject: '/api/request/reject',
  matches: '/api/matches',
  removeMatch: '/api/matches/remove',
  cancel: '/api/request/cancel'
};

const removeMatchState = {
  actionType: 'unfollow',
  matchId: null,
  requestId: null,
  card: null
};

const requestsState = {
  incoming: null,
  sent: null,
  matches: null
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

function parseSkillList(value) {
  return String(value || '')
    .split(',')
    .map((skill) => skill.trim().toLowerCase())
    .filter(Boolean);
}

function hasSkillOverlap(firstValue, secondValue) {
  const first = parseSkillList(firstValue);
  const second = parseSkillList(secondValue);
  return first.some((skill) => second.includes(skill));
}

function getSkillMatchState(item, fallbackMatched = false) {
  const percentage = Number(item.match_percentage ?? (fallbackMatched ? 100 : 0));
  const isMatched = percentage > 0;
  const variant = percentage >= 100 ? 'full' : (percentage > 0 ? 'partial' : 'none');
  return {
    isMatched,
    variant,
    label: `${percentage}% Match`,
    icon: percentage >= 100 ? 'fa-solid fa-check' : (percentage > 0 ? 'fa-solid fa-link' : 'fa-solid fa-xmark')
  };
}

function buildSkillMatchBadge(item, fallbackMatched = false) {
  const match = getSkillMatchState(item, fallbackMatched);
  return `
    <span class="skill-match-badge skill-match-${match.variant}">
      <i class="${match.icon}"></i>
      ${match.label}
    </span>
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

function currentTabKey() {
  return document.querySelector('.tab-link.active')?.dataset.tab || 'incoming';
}

function currentStatusFilter() {
  return document.querySelector('.request-status-tab.active')?.dataset.statusFilter || 'all';
}

function filteredByStatus(items, type) {
  const filter = currentStatusFilter();
  if (filter === 'all') return items;
  if (type === 'matches') return filter === 'accepted' ? items : [];
  return items.filter((item) => (item.status || 'pending') === filter);
}

function emptyStateHtml(icon = 'fa-solid fa-inbox') {
  return `
    <div class="premium-empty-state">
      <i class="${icon}"></i>
      <h3>No matching requests found.</h3>
      <p>Try another request type or status filter.</p>
    </div>
  `;
}

function buildRequestCard(request, type = 'incoming') {
  const avatar = request.avatar_url || '';
  const timeLabel = formatRelativeTime(request.created_at);
  const usernameHtml = request.username ? `<span class="req-username">@${request.username}</span>` : '';
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
        <button class="btn-remove-match btn-cancel-request" data-action="open-remove-match" data-action-type="cancel_request" data-request-id="${request.id}">
          <i class="fa-solid fa-ban"></i> Cancel Request
        </button>
      `;
    }
  } else if (request.status === 'accepted') {
    actionHtml = `<span class="badge-accepted"><i class="fa-solid fa-check"></i> Accepted</span>`;
  } else if (request.status === 'rejected') {
    actionHtml = `<span class="badge-rejected"><i class="fa-solid fa-xmark"></i> Declined</span>`;
  }

  let wantsToLearn = request.learns ? request.learns.split(',').map(s => `<span class="req-tag learn">${s.trim()}</span>`).join('') : '<span class="req-tag learn">None</span>';
  let offersToTeach = request.teaches ? request.teaches.split(',').map(s => `<span class="req-tag teach">${s.trim()}</span>`).join('') : '<span class="req-tag teach">None</span>';
  const matchBadgeHtml = buildSkillMatchBadge(request);

  return `
    <div class="req-card req-card-request" data-status="${request.status || 'pending'}">
      <div class="req-main">
        <div class="req-user">
            <img src="${avatar}" alt="${request.name}" class="req-avatar">
            <div class="req-user-info">
                <h4>${request.name}</h4>
                ${usernameHtml}
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
            <div class="req-match-indicator">
                ${matchBadgeHtml}
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
  const usernameHtml = match.username ? `<span class="req-username">@${match.username}</span>` : '';
  const matchedDate = match.matched_at ? new Date(match.matched_at) : null;
  const timeDate = matchedDate && !Number.isNaN(matchedDate.getTime())
    ? matchedDate.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
    : 'Recently';
  const locationHtml = match.location && match.location !== 'Remote' ? `<span class="req-loc"><i class="fa-solid fa-location-dot"></i> ${match.location}</span>` : '<span class="req-loc"><i class="fa-solid fa-globe"></i> Remote</span>';
  const requestId = match.request_id || '';

  // For matches, 'exchange' string usually comes back from backend like "Their Skill <=> My Skill"
  // But let's build the UI matching the image
  // Let's assume match object has some data, but since api returns 'exchange' as string, we'll parse it simply or fall back
  let parts = match.exchange ? match.exchange.split(/\s*(?:<=>|↔|â†”|→|->)\s*/) : ['Your Skill', 'Their Skill'];
  let youLearn = parts[1] ? parts[1].trim() : 'Skill';
  let theyLearn = parts[0] ? parts[0].trim() : 'Skill';
  const matchBadgeHtml = buildSkillMatchBadge(match, true);

  return `
    <div class="req-card req-card-match" data-match-card="${match.id}" data-status="accepted">
      <div class="req-user match-user">
          <img src="${avatar}" alt="${match.name}" class="req-avatar">
          <div class="req-user-info">
              <h4>${match.name}</h4>
              ${usernameHtml}
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
          <div class="req-match-indicator">
              ${matchBadgeHtml}
          </div>
      </div>
      <div class="req-actions match-actions">
          <div class="match-meta">
              <span>Matched on</span>
              <span class="match-date">${timeDate}</span>
          </div>
          <button class="btn-view-profile" data-action="view-profile" data-user-id="${match.other_id}"><i class="fa-regular fa-user"></i> View Profile</button>
          <button class="btn-outline-primary" data-action="message" data-user-id="${match.other_id}" data-request-id="${requestId}"><i class="fa-regular fa-message"></i> Message</button>
          <button class="btn-remove-match" data-action="open-remove-match" data-action-type="unfollow" data-match-id="${match.id}" data-request-id="${requestId}"><i class="fa-solid fa-user-minus"></i> Unfollow</button>
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

function getRemoveMatchElements() {
  return {
    modal: document.getElementById('removeMatchModal'),
    form: document.getElementById('removeMatchForm'),
    reason: document.getElementById('removeMatchReason'),
    otherField: document.getElementById('removeMatchOtherField'),
    other: document.getElementById('removeMatchOther'),
    confirmButton: document.querySelector('#removeMatchForm .btn-remove-confirm')
  };
}

function openRemoveMatchModal(button) {
  const elements = getRemoveMatchElements();
  if (!elements.modal || !elements.form) return;

  removeMatchState.matchId = button.dataset.matchId;
  removeMatchState.requestId = button.dataset.requestId;
  removeMatchState.actionType = button.dataset.actionType || 'unfollow';
  removeMatchState.card = button.closest('.req-card');

  elements.form.reset();
  elements.otherField.hidden = true;
  elements.other.required = false;
  elements.modal.hidden = false;
  document.body.classList.add('modal-open');
  requestAnimationFrame(() => elements.modal.classList.add('is-open'));
  elements.reason.focus();
}

function closeRemoveMatchModal() {
  const elements = getRemoveMatchElements();
  if (!elements.modal) return;

  elements.modal.classList.remove('is-open');
  document.body.classList.remove('modal-open');
  window.setTimeout(() => {
    elements.modal.hidden = true;
  }, 180);
}

function submitRemoveMatch(event) {
  event.preventDefault();
  const elements = getRemoveMatchElements();
  const reason = elements.reason.value;
  const customReason = elements.other.value.trim();

  if (!reason) {
    SkillFlowUI.error('Please select a reason.');
    return;
  }
  if (reason === 'Other' && !customReason) {
    SkillFlowUI.error('Please add a reason in Other.');
    elements.other.focus();
    return;
  }

  elements.confirmButton.disabled = true;
  const isCancel = removeMatchState.actionType === 'cancel_request';
  elements.confirmButton.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> ${isCancel ? 'Cancelling...' : 'Removing...'}`;

  fetch(isCancel ? requestsApi.cancel : requestsApi.removeMatch, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      action_type: removeMatchState.actionType,
      match_id: removeMatchState.matchId,
      request_id: removeMatchState.requestId,
      reason,
      custom_reason: customReason
    })
  })
    .then((resp) => resp.json())
    .then((data) => {
      if (!data.success) {
        SkillFlowUI.error(data.error || (isCancel ? 'Unable to cancel request.' : 'Unable to remove match.'));
        return;
      }

      closeRemoveMatchModal();
      if (removeMatchState.card) {
        removeMatchState.card.classList.add('is-removing');
        window.setTimeout(() => {
          removeMatchState.card.remove();
          const matchesList = document.querySelector('#matches .request-list');
          if (matchesList && !matchesList.querySelector('.req-card')) {
            document.getElementById('matches').innerHTML = '<p class="text-muted">No active matches at the moment.</p>';
          }
        }, 260);
      }
      SkillFlowUI.success(isCancel ? 'Request cancelled successfully.' : 'Match removed successfully.');
      fetch(requestsApi.incoming).then((res) => res.json()).then(renderIncomingRequests).catch(() => {});
      fetch(requestsApi.sent).then((res) => res.json()).then(renderSentRequests).catch(() => {});
      fetch(requestsApi.matches).then((res) => res.json()).then(renderMatches).catch(() => {});
    })
    .catch(() => SkillFlowUI.error(isCancel ? 'Unable to cancel request.' : 'Unable to remove match.'))
    .finally(() => {
      elements.confirmButton.disabled = false;
      elements.confirmButton.innerHTML = '<i class="fa-solid fa-user-minus"></i> Confirm Remove';
    });
}

function renderIncomingRequests(data) {
  const container = document.getElementById('incoming');
  const requests = Array.isArray(data?.requests) ? data.requests : [];
  requestsState.incoming = requests;
  const visibleRequests = filteredByStatus(requests, 'incoming');

  if (!visibleRequests.length) {
    container.innerHTML = emptyStateHtml('fa-solid fa-inbox');
    refreshRequestScrollbar(container);
    return;
  }
  container.innerHTML = `<div class="request-list">` + visibleRequests.map((item) => buildRequestCard(item, 'incoming')).join('') + `</div>`;
  refreshRequestScrollbar(container);
}

function renderSentRequests(data) {
  const container = document.getElementById('sent');
  const requests = Array.isArray(data?.requests) ? data.requests : [];
  requestsState.sent = requests;
  const visibleRequests = filteredByStatus(requests, 'sent');

  if (!visibleRequests.length) {
    container.innerHTML = emptyStateHtml('fa-regular fa-paper-plane');
    refreshRequestScrollbar(container);
    return;
  }
  container.innerHTML = `<div class="request-list">` + visibleRequests.map((item) => buildRequestCard(item, 'sent')).join('') + `</div>`;
  refreshRequestScrollbar(container);
}

function renderMatches(data) {
  const container = document.getElementById('matches');
  const matches = Array.isArray(data?.matches) ? data.matches : [];
  requestsState.matches = matches;
  const visibleMatches = filteredByStatus(matches, 'matches');

  if (!visibleMatches.length) {
    container.innerHTML = emptyStateHtml('fa-regular fa-heart');
    refreshRequestScrollbar(container);
    return;
  }
  container.innerHTML = `<div class="request-list">` + visibleMatches.map((item) => buildMatchCard(item)).join('') + `</div>`;
  refreshRequestScrollbar(container);
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
}

function renderActiveTabFromState() {
  const tabKey = currentTabKey();
  if (tabKey === 'sent' && requestsState.sent) {
    renderSentRequests({ requests: requestsState.sent });
    return true;
  }
  if (tabKey === 'matches' && requestsState.matches) {
    renderMatches({ matches: requestsState.matches });
    return true;
  }
  if (tabKey === 'incoming' && requestsState.incoming) {
    renderIncomingRequests({ requests: requestsState.incoming });
    return true;
  }
  return false;
}

function fetchActiveTab() {
  if (renderActiveTabFromState()) return;

  const tabKey = currentTabKey();
  const apiUrl = tabKey === 'sent'
    ? requestsApi.sent
    : tabKey === 'matches'
      ? requestsApi.matches
      : requestsApi.incoming;
  const renderer = tabKey === 'sent'
    ? renderSentRequests
    : tabKey === 'matches'
      ? renderMatches
      : renderIncomingRequests;

  fetch(apiUrl)
    .then((res) => res.json())
    .then(renderer)
    .catch(() => showToast('Unable to load requests.'));
}

function initPage() {
  const removeElements = getRemoveMatchElements();
  removeElements.form?.addEventListener('submit', submitRemoveMatch);
  removeElements.reason?.addEventListener('change', () => {
    const isOther = removeElements.reason.value === 'Other';
    removeElements.otherField.hidden = !isOther;
    removeElements.other.required = isOther;
    if (isOther) removeElements.other.focus();
    else removeElements.other.value = '';
  });

  document.querySelectorAll('.tab-link').forEach((button) => {
    button.addEventListener('click', (e) => {
        e.preventDefault();
        switchTab(button.dataset.tab);
        fetchActiveTab();
    });
  });
  document.querySelectorAll('.request-status-tab').forEach((button) => {
    button.addEventListener('click', () => {
      document.querySelectorAll('.request-status-tab').forEach((tab) => tab.classList.remove('active'));
      button.classList.add('active');
      renderActiveTabFromState() || fetchActiveTab();
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
    } else if (button.dataset.action === 'open-remove-match') {
      openRemoveMatchModal(button);
    } else if (button.dataset.action === 'close-remove-match') {
      closeRemoveMatchModal();
    }
  });
  document.getElementById('removeMatchModal')?.addEventListener('click', (event) => {
    const closeTrigger = event.target.closest('[data-action="close-remove-match"]');
    if (closeTrigger) closeRemoveMatchModal();
  });
  fetchAllTabs();
}

window.addEventListener('DOMContentLoaded', initPage);
