// SkillFlow Search Page JavaScript

document.addEventListener('DOMContentLoaded', () => {
  const searchInput = document.getElementById('searchInput');
  const searchResults = document.getElementById('searchResults');
  const resultCount = document.getElementById('resultCount');
  const mainContent = document.querySelector('.search-page .main-content');

  if (!searchInput || !searchResults) return;

  let debounceTimer;
  let activeController = null;
  let pageScrollbar = null;
  let pageScrollbarThumb = null;

  function ensurePageScrollbar() {
    document.querySelectorAll('.custom-page-scrollbar').forEach((scrollbar) => scrollbar.remove());
    return;
  }

  function updatePageScrollbar() {
    return;
  }

  function escapeHTML(value) {
    const div = document.createElement('div');
    div.textContent = value || '';
    return div.innerHTML;
  }

  function setCount(count) {
    if (resultCount) resultCount.textContent = count;
  }

  function showState(type, message, icon) {
    setCount(0);
    searchResults.innerHTML = `
      <div class="search-${type}">
        <i class="${icon}"></i>
        <p>${escapeHTML(message)}</p>
      </div>
    `;
  }

  function showRequestStatusToast(status, label) {
    const messages = {
      pending: 'You already sent a request to this user.',
      accepted: 'Chat access is available for this matched user.',
      matched: 'Your request was accepted. You are already matched with this user.',
      unlocked: 'Chat is already unlocked for this matched user.'
    };
    if (window.SkillFlowUI && typeof SkillFlowUI.success === 'function') {
      const message = label === 'Request Pending'
        ? 'A request with this user is already pending.'
        : (messages[status] || 'This request status is already updated.');
      SkillFlowUI.success(message);
    }
  }

  function renderTags(value, modifier = '') {
    const skills = String(value || '')
      .split(',')
      .map((skill) => skill.trim())
      .filter(Boolean);

    if (!skills.length) {
      return '<span class="search-tag">Not added yet</span>';
    }

    return skills.map((skill) => `<span class="search-tag ${modifier}">${escapeHTML(skill)}</span>`).join('');
  }

  function buildUserCard(user) {
    const name = user.name || user.username || 'SkillFlow User';
    const avatar = user.avatar_url || '';
    const location = user.location || 'Remote';
    const username = user.username ? `@${user.username}` : '';
    const relationship = user.relationship || { status: 'none', label: 'Send Request', can_request: true };
    const canRequest = relationship.can_request !== false;
    const statusLabel = relationship.status === 'matched'
      ? 'Already Matched'
      : relationship.status === 'unlocked'
        ? 'Unlocked'
      : relationship.status === 'accepted'
        ? 'Accepted'
      : (relationship.label || 'Request Pending');
    const matchLabel = user.match_badge_label || (user.match_percentage != null ? `${user.match_percentage}% Skill Match` : '');
    const videoHtml = user.video_url
      ? `<a href="${escapeHTML(user.video_url)}" target="_blank" rel="noopener noreferrer" class="search-video-link"><i class="fa-brands fa-youtube"></i> Demo Video</a>`
      : '';
    const matchHtml = matchLabel
      ? `<span class="search-tag wanted"><i class="fa-solid fa-circle-check"></i> ${escapeHTML(matchLabel)}</span>`
      : '';
    const categoryHtml = Array.isArray(user.categories) && user.categories.length
      ? user.categories.map((category) => `<span class="search-tag">${escapeHTML(category)}</span>`).join('')
      : '';
    const requestFieldsHtml = canRequest ? `
          <input type="text" name="skill_requested" placeholder="What do you want to learn?">
          <input type="text" name="skill_offered" placeholder="What can you teach in return?">` : '';
    const requestButtonHtml = canRequest ? `
            <button class="btn-primary" type="submit">
              <i class="fa-solid fa-paper-plane"></i>
              Send Request
            </button>` : `
            <button class="btn-primary request-status-button" type="button" data-request-status="${escapeHTML(relationship.status || 'pending')}" data-request-label="${escapeHTML(statusLabel)}">
              <i class="fa-solid fa-circle-check"></i>
              ${escapeHTML(statusLabel)}
            </button>`;

    return `
      <article class="search-user-card">
        <div class="search-user-main">
          <div class="search-user-top">
            <img class="search-avatar" src="${escapeHTML(avatar)}" alt="${escapeHTML(name)} avatar">
            <div>
              <h3 class="search-user-name">${escapeHTML(name)}</h3>
              <div class="search-user-meta">
                ${username ? `<span><i class="fa-solid fa-at"></i> ${escapeHTML(username)}</span>` : ''}
                <span><i class="fa-solid fa-location-dot"></i> ${escapeHTML(location)}</span>
                ${videoHtml}
              </div>
            </div>
          </div>

          <div class="search-skill-grid">
            <div class="search-skill-block">
              <span class="search-skill-label">Can Teach</span>
              <div class="search-tags">${renderTags(user.skills_offered || user.skills)}</div>
            </div>
            <div class="search-skill-block">
              <span class="search-skill-label">Wants To Learn</span>
              <div class="search-tags">${renderTags(user.skills_wanted, 'wanted')}</div>
            </div>
          </div>
          ${(matchHtml || categoryHtml) ? `<div class="search-tags">${matchHtml}${categoryHtml}</div>` : ''}
        </div>

        <form class="search-request-box" data-receiver-id="${user.id}">
          <p class="search-request-title">${canRequest ? 'Send a Swap Request' : escapeHTML(statusLabel)}</p>
          ${requestFieldsHtml}
          <div class="search-request-actions">
            <a class="btn-view-profile-search" href="/profile/${encodeURIComponent(user.id)}">
              <i class="fa-regular fa-user"></i>
              View Profile
            </a>
            ${requestButtonHtml}
          </div>
        </form>
      </article>
    `;
  }

  function bindRequestForms() {
    searchResults.querySelectorAll('.search-request-box').forEach((form) => {
      form.addEventListener('submit', (event) => {
        event.preventDefault();
        sendRequest(form);
      });
    });
    searchResults.querySelectorAll('.request-status-button').forEach((button) => {
      button.addEventListener('click', () => showRequestStatusToast(button.dataset.requestStatus, button.dataset.requestLabel));
    });
  }

  function renderResults(users) {
    if (!users.length) {
      showState('empty', 'No users found for this skill', 'fa-solid fa-user-slash');
      return;
    }

    setCount(users.length);
    searchResults.innerHTML = users.map((user) => buildUserCard(user)).join('');
    bindRequestForms();
    requestAnimationFrame(updatePageScrollbar);
  }

  function searchUsers(query) {
    if (activeController) activeController.abort();
    activeController = new AbortController();

    showState('loading', 'Searching users...', 'fa-solid fa-spinner fa-spin');

    fetch(`/api/search?q=${encodeURIComponent(query)}`, { signal: activeController.signal })
      .then((response) => response.json())
      .then((data) => {
        if (data.error) {
          showState('error', data.error, 'fa-solid fa-circle-exclamation');
          return;
        }

        renderResults(data.users || []);
      })
      .catch((error) => {
        if (error.name === 'AbortError') return;
        showState('error', 'Error fetching results.', 'fa-solid fa-circle-exclamation');
      });
  }

  searchInput.addEventListener('input', (event) => {
    clearTimeout(debounceTimer);
    const query = event.target.value.trim();

    if (!query) {
      if (activeController) activeController.abort();
      showState('empty', 'Start typing to search users', 'fa-solid fa-keyboard');
      return;
    }

    debounceTimer = setTimeout(() => searchUsers(query), 250);
  });

  window.sendRequest = function sendRequest(formOrReceiverId) {
    const form = typeof formOrReceiverId === 'object'
      ? formOrReceiverId
      : document.querySelector(`.search-request-box[data-receiver-id="${formOrReceiverId}"]`);

    if (!form) return;

    const receiverId = form.dataset.receiverId;
    const skillRequested = form.elements.skill_requested ? form.elements.skill_requested.value.trim() : '';
    const skillOffered = form.elements.skill_offered ? form.elements.skill_offered.value.trim() : '';
    const button = form.querySelector('button');

    if (!skillRequested || !skillOffered) {
      SkillFlowUI.error('Please fill out both skill fields to send a request.');
      return;
    }

    button.disabled = true;
    button.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Sending...';

    fetch('/api/request/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        receiver_id: receiverId,
        skill_requested: skillRequested,
        skill_offered: skillOffered
      })
    })
      .then((response) => response.json())
      .then((data) => {
        if (data.success) {
          const relationship = data.relationship || {};
          const label = relationship.status === 'matched'
            ? 'Already Matched'
            : relationship.status === 'unlocked'
              ? 'Unlocked'
            : relationship.status === 'accepted'
              ? 'Accepted'
            : (relationship.label || data.message || 'Request Sent');
          button.innerHTML = `<i class="fa-solid fa-check"></i> ${escapeHTML(label)}`;
          button.disabled = false;
          button.type = 'button';
          button.classList.add('request-status-button');
          button.dataset.requestStatus = relationship.status || 'pending';
          button.dataset.requestLabel = label;
          button.addEventListener('click', () => showRequestStatusToast(button.dataset.requestStatus, button.dataset.requestLabel));
          form.querySelector('.search-request-title').textContent = label;
          form.querySelectorAll('input').forEach((input) => input.remove());
          if (!data.already_exists) SkillFlowUI.success('Request sent successfully!');
        } else {
          SkillFlowUI.error(data.error || 'Unable to send request.');
          button.disabled = false;
          button.innerHTML = '<i class="fa-solid fa-paper-plane"></i> Send Request';
        }
      })
      .catch(() => {
        SkillFlowUI.error('Failed to send request.');
        button.disabled = false;
        button.innerHTML = '<i class="fa-solid fa-paper-plane"></i> Send Request';
      });
  };

  ensurePageScrollbar();
  showState('empty', 'Start typing to search users', 'fa-solid fa-keyboard');
  requestAnimationFrame(updatePageScrollbar);
});
