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
    if (!mainContent || pageScrollbar) return;
    pageScrollbar = document.createElement('div');
    pageScrollbar.className = 'custom-page-scrollbar';
    pageScrollbar.innerHTML = '<div class="custom-scrollbar-thumb"></div>';
    document.body.appendChild(pageScrollbar);
    pageScrollbarThumb = pageScrollbar.querySelector('.custom-scrollbar-thumb');
    mainContent.addEventListener('scroll', updatePageScrollbar);
    window.addEventListener('resize', updatePageScrollbar);
  }

  function updatePageScrollbar() {
    if (!mainContent || !pageScrollbar || !pageScrollbarThumb) return;

    const maxScroll = mainContent.scrollHeight - mainContent.clientHeight;
    pageScrollbar.style.display = maxScroll > 2 ? 'block' : 'none';
    if (maxScroll <= 2) return;

    const trackHeight = pageScrollbar.clientHeight;
    const thumbHeight = Math.max(54, (mainContent.clientHeight / mainContent.scrollHeight) * trackHeight);
    const maxThumbTop = trackHeight - thumbHeight;
    const thumbTop = (mainContent.scrollTop / maxScroll) * maxThumbTop;

    pageScrollbarThumb.style.height = `${thumbHeight}px`;
    pageScrollbarThumb.style.transform = `translateY(${thumbTop}px)`;
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
    const videoHtml = user.video_url
      ? `<a href="${escapeHTML(user.video_url)}" target="_blank" rel="noopener noreferrer" class="search-video-link"><i class="fa-brands fa-youtube"></i> Demo Video</a>`
      : '';

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
        </div>

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
          button.innerHTML = '<i class="fa-solid fa-check"></i> Request Sent';
          form.querySelectorAll('input').forEach((input) => {
            input.disabled = true;
          });
          SkillFlowUI.success('Request sent successfully!');
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
