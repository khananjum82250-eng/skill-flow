document.addEventListener('DOMContentLoaded', () => {
  const app = document.getElementById('chatApp');
  if (!app) return;

  const currentUserId = Number(app.dataset.userId);
  const chatList = document.getElementById('chatList');
  const chatCount = document.getElementById('chatCount');
  const emptyState = document.getElementById('emptyState');
  const activeChat = document.getElementById('activeChat');
  const activeAvatar = document.getElementById('activeAvatar');
  const activeName = document.getElementById('activeName');
  const activeStatus = document.getElementById('activeStatus');
  const unlockBtn = document.getElementById('unlockBtn');
  const reportChatBtn = document.getElementById('reportChatBtn');
  const unfollowChatBtn = document.getElementById('unfollowChatBtn');
  const globalUnlockBtn = document.getElementById('globalUnlockBtn');
  const lockBanner = document.getElementById('lockBanner');
  const contactBox = document.getElementById('contactBox');
  const messagesContainer = document.getElementById('messagesContainer');
  const chatForm = document.getElementById('chatForm');
  const chatInput = document.getElementById('chatInput');
  const sendBtn = document.getElementById('sendBtn');
  const emojiBtn = document.getElementById('emojiBtn');
  const attachBtn = document.getElementById('attachBtn');
  const emojiPicker = document.getElementById('emojiPicker');
  const chatFileInput = document.getElementById('chatFileInput');
  const selectedFilePreview = document.getElementById('selectedFilePreview');
  const selectedFileName = document.getElementById('selectedFileName');
  const removeSelectedFile = document.getElementById('removeSelectedFile');

  let chats = [];
  let active = null;
  let pollTimer = null;
  let selectedFile = null;
  const emojiCategories = {
    recent: [],
    smileys: ['😀', '😁', '😂', '😊', '😍', '😎', '🥳', '😇', '😉', '😌', '🤩', '😄'],
    hearts: ['💜', '💙', '💕', '💖', '💗', '💘', '💝', '❤️', '🩷', '💛', '💚', '🫶'],
    gestures: ['👍', '🙏', '👏', '🙌', '🤝', '👋', '👌', '✌️', '🤞', '💪', '🫰', '🤟'],
    objects: ['📚', '💬', '🎯', '💡', '📝', '📎', '💻', '🎨', '🎵', '📷', '🏆', '🚀'],
    symbols: ['✅', '✨', '🔥', '⭐', '⚡', '🔒', '🔗', '💫', '🌟', '🎉', '📌', '🟣']
  };
  const emojiLabels = {
    recent: 'Recent',
    smileys: 'Smileys',
    hearts: 'Hearts',
    gestures: 'Gestures',
    objects: 'Objects',
    symbols: 'Symbols'
  };
  let activeEmojiCategory = 'smileys';

  const paymentStatus = new URLSearchParams(window.location.search).get('payment_status');
  if (paymentStatus === 'success') {
    SkillFlowUI.success('Chat unlocked successfully.');
    window.history.replaceState({}, '', window.location.pathname + window.location.search.replace(/([?&])payment_status=success&?/, '$1').replace(/[?&]$/, ''));
  } else if (paymentStatus === 'failed') {
    SkillFlowUI.error('Payment failed. Please try again.');
    window.history.replaceState({}, '', window.location.pathname + window.location.search.replace(/([?&])payment_status=failed&?/, '$1').replace(/[?&]$/, ''));
  }

  function avatarFor(chat) {
    return chat.avatar_url || '';
  }

  function escapeHTML(value) {
    const div = document.createElement('div');
    div.textContent = value || '';
    return div.innerHTML;
  }

  function formatTime(value) {
    if (!value) return '';
    const date = new Date(value);
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  function updateSelectedFilePreview() {
    if (!selectedFile) {
      selectedFilePreview.hidden = true;
      selectedFileName.textContent = '';
      return;
    }
    selectedFileName.textContent = selectedFile.name;
    selectedFilePreview.hidden = false;
  }

  function clearSelectedFile() {
    selectedFile = null;
    if (chatFileInput) chatFileInput.value = '';
    updateSelectedFilePreview();
  }

  function insertEmoji(emoji) {
    if (!chatInput || chatInput.disabled) return;
    const start = chatInput.selectionStart || 0;
    const end = chatInput.selectionEnd || 0;
    chatInput.value = `${chatInput.value.slice(0, start)}${emoji}${chatInput.value.slice(end)}`;
    chatInput.focus();
    const nextPosition = start + emoji.length;
    chatInput.setSelectionRange(nextPosition, nextPosition);
    saveRecentEmoji(emoji);
  }

  function getRecentEmojis() {
    try {
      return JSON.parse(localStorage.getItem('skillflowRecentEmojis') || '[]').slice(0, 16);
    } catch (_) {
      return [];
    }
  }

  function saveRecentEmoji(emoji) {
    const recent = [emoji, ...getRecentEmojis().filter((item) => item !== emoji)].slice(0, 16);
    localStorage.setItem('skillflowRecentEmojis', JSON.stringify(recent));
  }

  function renderEmojiPicker(category = activeEmojiCategory) {
    if (!emojiPicker) return;
    emojiCategories.recent = getRecentEmojis();
    activeEmojiCategory = category === 'recent' && !emojiCategories.recent.length ? 'smileys' : category;
    const tabs = Object.keys(emojiCategories).map((key) => `
      <button type="button" class="emoji-tab ${key === activeEmojiCategory ? 'active' : ''}" data-category="${key}">
        ${emojiLabels[key]}
      </button>
    `).join('');
    const emojis = (emojiCategories[activeEmojiCategory] || emojiCategories.smileys).map((emoji) => `
      <button type="button" class="emoji-option" data-emoji="${emoji}">${emoji}</button>
    `).join('');

    emojiPicker.innerHTML = `
      <div class="emoji-tabs">${tabs}</div>
      <div class="emoji-grid">${emojis}</div>
    `;

    emojiPicker.querySelectorAll('.emoji-tab').forEach((button) => {
      button.addEventListener('click', () => renderEmojiPicker(button.dataset.category));
    });
    emojiPicker.querySelectorAll('.emoji-option').forEach((button) => {
      button.addEventListener('click', () => {
        insertEmoji(button.dataset.emoji);
        renderEmojiPicker('recent');
      });
    });
  }

  function isImageAttachment(message) {
    const type = String(message.attachment_type || '').toLowerCase();
    const name = String(message.attachment_name || '').toLowerCase();
    return type.startsWith('image/') || /\.(png|jpe?g|gif|webp)$/.test(name);
  }

  function uniqueChatsByUser(chatRows) {
    const byUser = new Map();
    (chatRows || []).forEach((chat) => {
      const key = String(chat.other_id || chat.username || chat.request_id);
      const existing = byUser.get(key);
      if (!existing) {
        byUser.set(key, chat);
        return;
      }

      const existingTime = new Date(existing.last_message_at || existing.unlock_date || 0).getTime();
      const nextTime = new Date(chat.last_message_at || chat.unlock_date || 0).getTime();
      if ((chat.is_unlocked && !existing.is_unlocked) || nextTime > existingTime) {
        byUser.set(key, chat);
      }
    });
    return Array.from(byUser.values());
  }

  function renderChatList() {
    chatCount.textContent = chats.length;
    if (!chats.length) {
      chatList.innerHTML = '<div class="chat-empty">No accepted chats yet. Accept a request to start.</div>';
      return;
    }

    chatList.innerHTML = chats.map((chat) => {
      const lockedIcon = chat.is_unlocked ? '<i class="fa-solid fa-unlock chat-list-lock"></i>' : '<i class="fa-solid fa-lock chat-list-lock"></i>';
      const statusText = escapeHTML(chat.status_label || (chat.is_unlocked ? 'Unlocked' : 'Locked'));
      return `
        <button class="chat-list-item ${active && active.request_id === chat.request_id ? 'active' : ''}" type="button" data-request-id="${chat.request_id}">
          <img class="chat-list-avatar" src="${avatarFor(chat)}" alt="${escapeHTML(chat.name)}">
          <span>
            <span class="chat-list-name">${escapeHTML(chat.name)}</span>
            <span class="chat-list-preview">${statusText}</span>
          </span>
          ${lockedIcon}
        </button>
      `;
    }).join('');

    chatList.querySelectorAll('.chat-list-item').forEach((button) => {
      button.addEventListener('click', () => openChat(button.dataset.requestId));
    });
  }

  function setChatState(chat) {
    active = chat;
    emptyState.hidden = true;
    activeChat.hidden = false;
    activeAvatar.src = avatarFor(chat);
    activeName.textContent = chat.name;

    const expired = chat.payment_status === 'expired';
    const locked = !chat.is_unlocked;
    const lockedMessage = expired
      ? 'Your chat access has expired. Please unlock again to continue.'
      : (chat.lock_message || 'Chat locked. Complete payment to unlock chat.');
    activeStatus.textContent = chat.is_unlocked ? `Premium Active${chat.expiry_date ? ` until ${new Date(chat.expiry_date).toLocaleDateString()}` : ''}` : 'Locked';
    activeStatus.classList.toggle('unlocked', chat.is_unlocked);
    unlockBtn.hidden = !locked;
    if (reportChatBtn) {
      reportChatBtn.hidden = false;
      reportChatBtn.dataset.reportUser = chat.other_id;
    }
    if (unfollowChatBtn) {
      unfollowChatBtn.hidden = false;
      unfollowChatBtn.dataset.requestId = chat.request_id;
    }
    lockBanner.hidden = !locked;
    if (locked) {
      lockBanner.querySelector('span').textContent = lockedMessage;
    }
    chatInput.disabled = locked;
    sendBtn.disabled = locked;
    if (emojiBtn) emojiBtn.disabled = locked;
    if (attachBtn) attachBtn.disabled = locked;
    sendBtn.setAttribute('aria-disabled', String(locked));
    chatInput.placeholder = locked ? '' : 'Type your message...';
    chatForm.hidden = locked;
    messagesContainer.hidden = locked;
    if (locked) {
      messagesContainer.innerHTML = '';
      chatInput.value = '';
      clearSelectedFile();
      if (emojiPicker) emojiPicker.hidden = true;
    }

    if (chat.is_unlocked && (chat.phone || chat.email)) {
      const phoneHtml = chat.phone ? `<p><i class="fa-solid fa-phone"></i> ${escapeHTML(chat.phone)}</p>` : '';
      const emailHtml = chat.email ? `<p><i class="fa-solid fa-envelope"></i> ${escapeHTML(chat.email)}</p>` : '';
      contactBox.innerHTML = `${phoneHtml}${emailHtml}`;
      contactBox.hidden = false;
    } else {
      contactBox.innerHTML = '';
      contactBox.hidden = true;
    }

    renderChatList();
    if (locked) return;
    loadHistory();
  }

  function openChat(requestId) {
    const chat = chats.find((item) => String(item.request_id) === String(requestId));
    if (!chat) return;
    setChatState(chat);
    const url = new URL(window.location.href);
    url.searchParams.set('request_id', chat.request_id);
    url.searchParams.set('user_id', chat.other_id);
    window.history.replaceState({}, '', url);
  }

  function renderMessages(messages) {
    if (!messages.length) {
      messagesContainer.innerHTML = '<div class="chat-empty">No messages yet.</div>';
      return;
    }

    messagesContainer.innerHTML = messages.map((message) => {
      const isSent = Number(message.sender_id) === currentUserId;
      return `
        <div class="message ${isSent ? 'sent' : 'received'}">
          <div class="message-bubble">
            ${message.message_text || message.content ? `<div class="message-text">${escapeHTML(message.message_text || message.content)}</div>` : ''}
            ${message.attachment_url ? `
              <div class="message-attachment-card">
                ${isImageAttachment(message) ? `<img class="message-image-preview" src="${escapeHTML(message.attachment_url)}" alt="${escapeHTML(message.attachment_name || 'Attachment preview')}">` : ''}
                <a class="message-attachment" href="${escapeHTML(message.attachment_url)}" target="_blank" rel="noopener noreferrer">
                  <i class="fa-solid fa-file-arrow-down"></i>
                  <span>${escapeHTML(message.attachment_name || 'Attachment')}</span>
                  <strong>Open</strong>
                </a>
              </div>
            ` : ''}
            <span class="message-time">${formatTime(message.created_at)}</span>
          </div>
        </div>
      `;
    }).join('');
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }

  function loadHistory() {
    if (!active) return;
    if (!active.is_unlocked) {
      messagesContainer.innerHTML = '';
      messagesContainer.hidden = true;
      return;
    }
    messagesContainer.hidden = false;

    fetch(`/api/chat/history?request_id=${encodeURIComponent(active.request_id)}`)
      .then((response) => response.json())
      .then((data) => {
        if (data.error) {
          if (data.is_unlocked === false || data.payment_status || data.request_status) {
            active = {
              ...active,
              is_unlocked: false,
              request_status: data.request_status || active.request_status,
              payment_status: data.payment_status || active.payment_status,
              lock_message: data.error
            };
            setChatState(active);
            return;
          }
          messagesContainer.innerHTML = `<div class="chat-empty">${escapeHTML(data.error)}</div>`;
          return;
        }
        renderMessages(data.messages || []);
      })
      .catch(() => {
        messagesContainer.innerHTML = '<div class="chat-empty">Unable to load messages.</div>';
      });
  }

  function loadChats() {
    fetch('/api/chat/list')
      .then((response) => response.json())
      .then((data) => {
        if (data.error) {
          chatList.innerHTML = `<div class="chat-empty">${escapeHTML(data.error)}</div>`;
          return;
        }

        chats = uniqueChatsByUser(data.chats || []);
        renderChatList();
        const selectedRequestId = app.dataset.selectedRequestId;
        const selectedUserId = app.dataset.selectedUserId;
        const selectedChat = chats.find((chat) => (
          selectedRequestId && String(chat.request_id) === String(selectedRequestId)
        ) || (
          selectedUserId && String(chat.other_id) === String(selectedUserId)
        ));

        if (!active && selectedChat) {
          setChatState(selectedChat);
          return;
        }

        if (active) {
          const refreshedActive = chats.find((chat) => String(chat.request_id) === String(active.request_id));
          if (refreshedActive) {
            active = refreshedActive;
            setChatState(refreshedActive);
            return;
          }
        }

        active = null;
        activeChat.hidden = true;
        emptyState.hidden = false;
      })
      .catch(() => {
        chatList.innerHTML = '<div class="chat-empty">Unable to load accepted chats.</div>';
      });
  }

  function sendMessage() {
    const content = chatInput.value.trim();
    if (!active || (!content && !selectedFile)) return;
    if (!active.is_unlocked) {
      SkillFlowUI.error(active.lock_message || 'Chat locked. Complete payment to unlock chat.');
      return;
    }

    const formData = new FormData();
    formData.append('request_id', active.request_id);
    formData.append('receiver_id', active.other_id);
    formData.append('content', content);
    if (selectedFile) {
      formData.append('attachment', selectedFile);
    }

    fetch('/api/chat/send', {
      method: 'POST',
      body: formData
    })
      .then((response) => response.json())
      .then((data) => {
        if (data.success) {
          chatInput.value = '';
          clearSelectedFile();
          if (emojiPicker) emojiPicker.hidden = true;
          loadHistory();
          loadChats();
        } else {
          SkillFlowUI.error(data.error || 'Failed to send message');
          if (data.is_unlocked === false || data.payment_status || data.request_status) {
            active = {
              ...active,
              is_unlocked: false,
              request_status: data.request_status || active.request_status,
              payment_status: data.payment_status || active.payment_status,
              lock_message: data.error || active.lock_message
            };
          }
          loadChats();
        }
      })
      .catch(() => SkillFlowUI.error('Failed to send message'));
  }

  function payToUnlock() {
    if (!active) return;

    function paymentErrorMessage(data) {
      if (!data) return 'Payment initialization failed.';
      if (data.details && data.details.phonepe_response) return data.details.phonepe_response;
      if (data.details && data.details.exception) return data.details.exception;
      return data.error || 'Payment initialization failed.';
    }

    fetch('/api/payment/create', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ request_id: active.request_id })
    })
      .then((response) => response.json())
      .then((data) => {
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

        SkillFlowUI.error('Payment initialization failed.');
      })
      .catch(() => SkillFlowUI.error('Payment initialization failed.'));
  }

  function unlockFirstAvailableChat() {
    const lockedChat = chats.find((chat) => !chat.is_unlocked);
    if (!lockedChat) {
      SkillFlowUI.info(chats.length ? 'All accepted chats are already unlocked.' : 'No accepted chats available to unlock yet.');
      return;
    }

    setChatState(lockedChat);
    const url = new URL(window.location.href);
    url.searchParams.set('request_id', lockedChat.request_id);
    url.searchParams.set('user_id', lockedChat.other_id);
    window.history.replaceState({}, '', url);
    payToUnlock();
  }

  function requestUnfollowReason() {
    return new Promise((resolve) => {
      const overlay = document.createElement('div');
      overlay.className = 'sf-modal-overlay';
      overlay.innerHTML = `
        <div class="sf-modal warning" role="dialog" aria-modal="true">
          <button class="sf-modal-close" type="button" aria-label="Close"><i class="fa-solid fa-xmark"></i></button>
          <span class="sf-modal-icon"><i class="fa-solid fa-user-minus"></i></span>
          <h2 class="sf-modal-title">Unfollow Skill Partner</h2>
          <p class="sf-modal-message">Please select a reason before ending this skill exchange.</p>
          <div class="sf-modal-fields">
            <div class="sf-field">
              <label for="unfollowReason">Reason</label>
              <select id="unfollowReason" name="reason" required>
                <option value="">Select reason</option>
                <option>Teaching style not helpful</option>
                <option>Skill mismatch</option>
                <option>Not active</option>
                <option>Communication issue</option>
                <option>Other</option>
              </select>
            </div>
            <div class="sf-field" id="unfollowOtherWrap" hidden>
              <label for="unfollowOther">Other reason</label>
              <textarea id="unfollowOther" name="custom_reason" rows="3" placeholder="Enter reason"></textarea>
            </div>
          </div>
          <div class="sf-modal-actions">
            <button class="sf-btn sf-btn-secondary" data-sf-cancel type="button">Cancel</button>
            <button class="sf-btn sf-btn-danger" data-sf-confirm type="button">
              <i class="fa-solid fa-user-minus"></i>
              Unfollow
            </button>
          </div>
        </div>
      `;
      document.body.appendChild(overlay);

      const reasonInput = overlay.querySelector('#unfollowReason');
      const otherWrap = overlay.querySelector('#unfollowOtherWrap');
      const otherInput = overlay.querySelector('#unfollowOther');
      const close = (value) => {
        overlay.remove();
        resolve(value);
      };

      reasonInput.addEventListener('change', () => {
        otherWrap.hidden = reasonInput.value !== 'Other';
      });
      overlay.querySelector('.sf-modal-close').addEventListener('click', () => close(null));
      overlay.querySelector('[data-sf-cancel]').addEventListener('click', () => close(null));
      overlay.addEventListener('click', (event) => {
        if (event.target === overlay) close(null);
      });
      overlay.querySelector('[data-sf-confirm]').addEventListener('click', () => {
        const reason = reasonInput.value.trim();
        const customReason = otherInput.value.trim();
        if (!reason || (reason === 'Other' && !customReason)) {
          SkillFlowUI.info('Please select or enter a reason before unfollowing.');
          return;
        }
        close({ reason, custom_reason: customReason });
      });
      reasonInput.focus();
    });
  }

  function clearActiveChatView() {
    active = null;
    activeChat.hidden = true;
    emptyState.hidden = false;
    messagesContainer.innerHTML = '';
    chatInput.value = '';
    const url = new URL(window.location.href);
    url.searchParams.delete('request_id');
    url.searchParams.delete('user_id');
    window.history.replaceState({}, '', url);
  }

  async function unfollowActiveChat() {
    if (!active) return;
    const reasonData = await requestUnfollowReason();
    if (!reasonData) return;

    const requestId = active.request_id;
    const otherUserId = active.other_id;
    const payload = {
      request_id: requestId,
      user_id: otherUserId,
      action_type: 'unfollow',
      reason: reasonData.reason,
      custom_reason: reasonData.custom_reason
    };

    if (!requestId || !otherUserId) {
      console.error('Unable to unfollow: missing chat details.');
      SkillFlowUI.error('Unable to unfollow: missing chat details.');
      return;
    }

    const originalHtml = unfollowChatBtn ? unfollowChatBtn.innerHTML : '';
    if (unfollowChatBtn) {
      unfollowChatBtn.disabled = true;
      unfollowChatBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Unfollowing...';
    }

    async function postUnfollow(url) {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(payload)
      });
      const text = await response.text();
      let data = {};
      if (text) {
        try {
          data = JSON.parse(text);
        } catch (error) {
          data = { error: text.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim() || response.statusText };
        }
      }
      return { response, data };
    }

    try {
      const result = await postUnfollow('/api/chat/unfollow');
      const { response, data } = result;
      if (!response.ok || !data.success) {
        throw new Error(data.error || `Unfollow failed with status ${response.status}`);
      }

      chats = chats.filter((chat) => String(chat.request_id) !== String(requestId));
      SkillFlowUI.success(data.message || 'User unfollowed successfully');
      clearActiveChatView();
      renderChatList();
      loadChats();
    } catch (error) {
      console.error('[Unfollow] failed:', error);
      SkillFlowUI.error(error.message || 'Unable to unfollow this user.');
    } finally {
      if (unfollowChatBtn) {
        unfollowChatBtn.disabled = false;
        unfollowChatBtn.innerHTML = originalHtml;
      }
    }
  }

  chatForm.addEventListener('submit', (event) => {
    event.preventDefault();
    sendMessage();
  });

  renderEmojiPicker();

  if (emojiBtn && emojiPicker) {
    emojiBtn.addEventListener('click', (event) => {
      event.stopPropagation();
      emojiPicker.hidden = !emojiPicker.hidden;
    });
  }

  if (attachBtn && chatFileInput) {
    attachBtn.addEventListener('click', () => chatFileInput.click());
    chatFileInput.addEventListener('change', () => {
      selectedFile = chatFileInput.files && chatFileInput.files[0] ? chatFileInput.files[0] : null;
      updateSelectedFilePreview();
    });
  }

  if (removeSelectedFile) {
    removeSelectedFile.addEventListener('click', clearSelectedFile);
  }

  document.addEventListener('click', (event) => {
    if (!emojiPicker || emojiPicker.hidden) return;
    if (emojiPicker.contains(event.target) || (emojiBtn && emojiBtn.contains(event.target))) return;
    emojiPicker.hidden = true;
  });
  unlockBtn.addEventListener('click', payToUnlock);
  if (reportChatBtn) {
    reportChatBtn.addEventListener('click', () => window.SkillFlowReport.open(reportChatBtn.dataset.reportUser));
  }
  if (unfollowChatBtn) {
    unfollowChatBtn.addEventListener('click', unfollowActiveChat);
  }
  globalUnlockBtn?.addEventListener('click', unlockFirstAvailableChat);

  loadChats();
  pollTimer = window.setInterval(() => {
    if (active && active.is_unlocked) loadHistory();
  }, 5000);
  window.addEventListener('beforeunload', () => window.clearInterval(pollTimer));
});
