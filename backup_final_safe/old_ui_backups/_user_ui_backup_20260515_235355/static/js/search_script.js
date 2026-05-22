// SkillFlow Search Page JavaScript

document.addEventListener('DOMContentLoaded', () => {
  const searchInput = document.getElementById('searchInput');
  const searchResults = document.getElementById('searchResults');
  const resultCount = document.getElementById('resultCount');
  const mainContent = document.querySelector('.search-page .main-content');
  const recommendationResults = document.getElementById('recommendationResults');
  const filterChips = Array.from(document.querySelectorAll('[data-filter-chip]'));
  const params = new URLSearchParams(window.location.search);
  const openedFromRecommendations = params.get('recommendations') === '1' || window.location.hash === '#recommendationResults';

  if (!searchInput || !searchResults) return;

  let debounceTimer;
  let activeController = null;
  const activeFilters = new Set();
  let pageScrollbar = null;
  let pageScrollbarThumb = null;

  function ensurePageScrollbar() {
    document.querySelector('.custom-page-scrollbar')?.remove();
  }

  function updatePageScrollbar() {
    document.querySelector('.custom-page-scrollbar')?.remove();
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
    if (type === 'loading') {
      searchResults.innerHTML = `
        <div class="search-skeleton-card"></div>
        <div class="search-skeleton-card"></div>
      `;
      return;
    }

    searchResults.innerHTML = `
      <div class="search-${type}">
        <i class="${icon}"></i>
        <p>${escapeHTML(message)}</p>
      </div>
    `;
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

  function relationshipIcon(status) {
    if (status === 'matched' || status === 'accepted') return 'fa-solid fa-check';
    if (status === 'rejected') return 'fa-solid fa-xmark';
    return 'fa-regular fa-hourglass-half';
  }

  function relationshipBadge(relationship) {
    const status = relationship?.status || 'pending';
    const label = relationship?.label || 'Request Sent';
    return `
      <div class="search-request-status search-request-status-${escapeHTML(status)}">
        <i class="${relationshipIcon(status)}"></i>
        <span>${escapeHTML(label)}</span>
      </div>
    `;
  }

  function matchBadgeVariant(percentage) {
    if (percentage >= 100) return 'full';
    if (percentage > 0) return 'partial';
    return 'none';
  }

  function buildUserCard(user) {
    const name = user.name || user.username || 'SkillFlow User';
    const avatar = user.avatar_url || '';
    const location = user.location || 'Remote';
    const username = user.username ? `@${user.username}` : '';
    const bio = user.bio || 'Ready to exchange skills and grow with the SkillFlow community.';
    const matchPercent = Number(user.match_percentage || 0);
    const matchVariant = user.match_badge_variant || matchBadgeVariant(matchPercent);
    const matchLabel = user.match_badge_label || `${matchPercent}% Match`;
    const videoHtml = user.video_url
      ? `<a href="${escapeHTML(user.video_url)}" target="_blank" rel="noopener noreferrer" class="search-video-link"><i class="fa-brands fa-youtube"></i> Demo Video</a>`
      : '';
    const relationship = user.relationship || { can_request: true };
    const requestBoxHtml = relationship.can_request === false
      ? `
        <div class="search-request-box search-request-box-status">
          <p class="search-request-title">Connection Status</p>
          ${relationshipBadge(relationship)}
          <a class="btn-view-profile-search" href="/profile/${encodeURIComponent(user.id)}">
            <i class="fa-regular fa-user"></i>
            View Profile
          </a>
        </div>
      `
      : `
        <form class="search-request-box" data-receiver-id="${user.id}">
          <p class="search-request-title">Send a Swap Request</p>
          <input type="text" name="skill_requested" placeholder="What do you want to learn?">
          <input type="text" name="skill_offered" placeholder="What can you teach in return?">
          <div class="search-request-actions">
            <a class="btn-view-profile-search" href="/profile/${encodeURIComponent(user.id)}">
              <i class="fa-regular fa-user"></i>
              View Profile
            </a>
            <button class="btn-primary" type="submit">
              <i class="fa-solid fa-paper-plane"></i>
              Send Request
            </button>
          </div>
        </form>
      `;

    return `
      <article class="search-user-card">
        <div class="search-user-main">
          <div class="search-user-top">
            <img class="search-avatar" src="${escapeHTML(avatar)}" alt="${escapeHTML(name)} avatar">
            <div>
              <div class="search-card-headline">
                <h3 class="search-user-name">${escapeHTML(name)}</h3>
                <span class="search-match-pill search-match-${escapeHTML(matchVariant)}">${escapeHTML(matchLabel)}</span>
              </div>
              <div class="search-user-meta">
                ${username ? `<span><i class="fa-solid fa-at"></i> ${escapeHTML(username)}</span>` : ''}
                <span><i class="fa-solid fa-location-dot"></i> ${escapeHTML(location)}</span>
                ${videoHtml}
              </div>
              <p class="search-user-bio">${escapeHTML(bio)}</p>
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
        </div>

        ${requestBoxHtml}
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
  }

  function renderResults(users) {
    if (!users.length) {
      showState('empty', 'No matching users found.', 'fa-solid fa-user-slash');
      return;
    }

    setCount(users.length);
    searchResults.innerHTML = users.map((user) => buildUserCard(user)).join('');
    bindRequestForms();
    requestAnimationFrame(updatePageScrollbar);
  }

  function selectedFilterParam() {
    return Array.from(activeFilters).join(',');
  }

  function syncFilterChips() {
    filterChips.forEach((chip) => {
      const value = chip.dataset.filterValue || '';
      chip.classList.toggle('active', value === 'all' ? activeFilters.size === 0 : activeFilters.has(value));
    });
  }

  function searchUsers(query = searchInput.value.trim()) {
    if (activeController) activeController.abort();
    activeController = new AbortController();

    showState('loading', 'Searching users...', 'fa-solid fa-spinner fa-spin');

    const searchParams = new URLSearchParams();
    if (query) searchParams.set('q', query);
    const filters = selectedFilterParam();
    if (filters) searchParams.set('filters', filters);

    fetch(`/api/search?${searchParams.toString()}`, { signal: activeController.signal })
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

  function focusRecommendationResults() {
    if (!openedFromRecommendations || !recommendationResults) return;

    recommendationResults.classList.add('is-recommendation-target');
    requestAnimationFrame(() => {
      recommendationResults.scrollIntoView({ behavior: 'smooth', block: 'start' });
      window.setTimeout(() => {
        recommendationResults.focus({ preventScroll: true });
      }, 420);
    });
  }

  searchInput.addEventListener('input', (event) => {
    clearTimeout(debounceTimer);
    const query = event.target.value.trim();

    if (!query && activeFilters.size === 0) {
      if (activeController) activeController.abort();
      showState('empty', 'Start typing to search users', 'fa-solid fa-keyboard');
      return;
    }

    debounceTimer = setTimeout(() => searchUsers(query), 250);
  });

  filterChips.forEach((chip) => {
    chip.addEventListener('click', () => {
      const value = chip.dataset.filterValue || '';
      if (value === 'all') {
        activeFilters.clear();
        searchInput.value = '';
      } else if (activeFilters.has(value)) {
        activeFilters.delete(value);
      } else {
        activeFilters.add(value);
      }

      syncFilterChips();
      clearTimeout(debounceTimer);
      searchUsers();
    });
  });

  window.sendRequest = function sendRequest(formOrReceiverId) {
    const form = typeof formOrReceiverId === 'object'
      ? formOrReceiverId
      : document.querySelector(`.search-request-box[data-receiver-id="${formOrReceiverId}"]`);

    if (!form) return;

    const receiverId = form.dataset.receiverId;
    const skillRequested = form.elements.skill_requested.value.trim();
    const skillOffered = form.elements.skill_offered.value.trim();
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
          form.replaceWith(statusBoxFromRelationship(data.relationship || { status: 'pending', label: 'Request Sent' }, receiverId));
          SkillFlowUI.success('Request sent successfully!');
        } else {
          SkillFlowUI.error(data.error || 'Unable to send request.');
          if (data.relationship) {
            form.replaceWith(statusBoxFromRelationship(data.relationship, receiverId));
          } else {
            button.disabled = false;
            button.innerHTML = '<i class="fa-solid fa-paper-plane"></i> Send Request';
          }
        }
      })
      .catch(() => {
        SkillFlowUI.error('Failed to send request.');
        button.disabled = false;
        button.innerHTML = '<i class="fa-solid fa-paper-plane"></i> Send Request';
      });
  };

  function statusBoxFromRelationship(relationship, receiverId) {
    const wrapper = document.createElement('div');
    wrapper.className = 'search-request-box search-request-box-status';
    wrapper.innerHTML = `
      <p class="search-request-title">Connection Status</p>
      ${relationshipBadge(relationship)}
      <a class="btn-view-profile-search" href="/profile/${encodeURIComponent(receiverId)}">
        <i class="fa-regular fa-user"></i>
        View Profile
      </a>
    `;
    return wrapper;
  }

  ensurePageScrollbar();
  const urlQuery = params.get('q') || '';
  const urlFilters = (params.get('filters') || '')
    .split(',')
    .map((filter) => filter.trim())
    .filter(Boolean);
  urlFilters.forEach((filter) => activeFilters.add(filter));
  syncFilterChips();
  const initialQuery = urlQuery;

  if (initialQuery.trim() || activeFilters.size > 0) {
    searchInput.value = initialQuery.trim();
    searchUsers(initialQuery.trim());
  } else if (openedFromRecommendations) {
    showState('empty', 'Start typing to search users', 'fa-solid fa-keyboard');
  } else {
    showState('empty', 'Start typing to search users', 'fa-solid fa-keyboard');
  }

  focusRecommendationResults();
  requestAnimationFrame(updatePageScrollbar);
});
