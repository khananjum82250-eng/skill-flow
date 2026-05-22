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
  const removeChatConnectionBtn = document.getElementById('removeChatConnectionBtn');
  const globalUnlockBtn = document.getElementById('globalUnlockBtn');
  const lockBanner = document.getElementById('lockBanner');
  const contactBox = document.getElementById('contactBox');
  const messagesContainer = document.getElementById('messagesContainer');
  const chatForm = document.getElementById('chatForm');
  const chatInput = document.getElementById('chatInput');
  const sendBtn = document.getElementById('sendBtn');
  const removeChatModal = document.getElementById('removeChatModal');
  const removeChatForm = document.getElementById('removeChatForm');
  const removeChatReason = document.getElementById('removeChatReason');
  const removeChatOtherField = document.getElementById('removeChatOtherField');
  const removeChatOther = document.getElementById('removeChatOther');

  let chats = [];
  let active = null;
  let pollTimer = null;

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

  function renderChatList() {
    if (chatCount) chatCount.textContent = chats.length;
    if (!chats.length) {
      chatList.innerHTML = '<div class="chat-empty">No accepted chats yet. Accept a request to start.</div>';
      syncGlobalUnlockButton();
      return;
    }

    chatList.innerHTML = chats.map((chat) => {
      const isUnlocked = Boolean(chat.is_unlocked);
      const statusText = escapeHTML(chat.status_label || (isUnlocked ? 'Unlocked' : 'Locked'));
      const usernameText = chat.username ? `@${escapeHTML(chat.username)} · ` : '';
      return `
        <button class="chat-list-item ${active && active.request_id === chat.request_id ? 'active' : ''}" type="button" data-request-id="${chat.request_id}">
          <img class="chat-list-avatar" src="${avatarFor(chat)}" alt="${escapeHTML(chat.name)}">
          <span class="chat-online-dot"></span>
          <span>
            <span class="chat-list-name">${escapeHTML(chat.name)}</span>
            <span class="chat-list-preview">${usernameText}${statusText}</span>
          </span>
        </button>
      `;
    }).join('');

    chatList.querySelectorAll('.chat-list-item').forEach((button) => {
      button.addEventListener('click', () => openChat(button.dataset.requestId));
    });
    syncGlobalUnlockButton();
  }

  function syncGlobalUnlockButton() {
    if (!globalUnlockBtn) return;
    const currentUserNeedsPayment = chats.some((chat) => !chat.current_user_paid);
    globalUnlockBtn.hidden = !currentUserNeedsPayment;
    globalUnlockBtn.disabled = !currentUserNeedsPayment;
  }

  function setChatState(chat) {
    active = chat;
    emptyState.hidden = true;
    activeChat.hidden = false;
    activeAvatar.src = avatarFor(chat);
    activeName.textContent = chat.name;

    const locked = !chat.is_unlocked;
    const canCurrentUserPay = !chat.current_user_paid;
    activeStatus.textContent = chat.status_label || (chat.is_unlocked ? 'Unlocked' : 'Locked');
    activeStatus.classList.toggle('unlocked', chat.is_unlocked);
    unlockBtn.hidden = !locked || !canCurrentUserPay;
    unlockBtn.disabled = !locked || !canCurrentUserPay;
    if (reportChatBtn) {
      reportChatBtn.hidden = false;
      reportChatBtn.dataset.reportUser = chat.other_id;
    }
    if (removeChatConnectionBtn) {
      removeChatConnectionBtn.hidden = false;
      removeChatConnectionBtn.dataset.requestId = chat.request_id;
    }
    lockBanner.hidden = true;
    chatInput.disabled = locked;
    sendBtn.disabled = locked;
    sendBtn.setAttribute('aria-disabled', String(locked));
    chatInput.placeholder = locked ? '' : 'Type your message...';
    chatForm.hidden = false;
    messagesContainer.hidden = false;
    if (locked) {
      messagesContainer.innerHTML = `
        <div class="premium-unlock-card">
          <i class="fa-solid fa-lock"></i>
          <h2>Unlock this chat</h2>
          <p>Complete the unlock step to message this skill partner and view shared contact details.</p>
        </div>
      `;
      chatInput.value = '';
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
      messagesContainer.innerHTML = `
        <div class="chat-empty">
          <div class="typing-dots" aria-hidden="true"><span></span><span></span><span></span></div>
          <p>No messages yet.</p>
        </div>
      `;
      return;
    }

    messagesContainer.innerHTML = messages.map((message) => {
      const isSent = Number(message.sender_id) === currentUserId;
      return `
        <div class="message ${isSent ? 'sent' : 'received'}">
          <div class="message-bubble">
            ${escapeHTML(message.message_text || message.content)}
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
      messagesContainer.innerHTML = `
        <div class="premium-unlock-card">
          <i class="fa-solid fa-lock"></i>
          <h2>Chat locked</h2>
          <p>Unlock this connection to continue the conversation.</p>
        </div>
      `;
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
              current_user_paid: data.current_user_paid ?? active.current_user_paid,
              other_user_paid: data.other_user_paid ?? active.other_user_paid,
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

        chats = data.chats || [];
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
    if (!active || !content) return;
    if (!active.is_unlocked) {
      return;
    }

    fetch('/api/chat/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        request_id: active.request_id,
        receiver_id: active.other_id,
        content
      })
    })
      .then((response) => response.json())
      .then((data) => {
        if (data.success) {
          chatInput.value = '';
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
              current_user_paid: data.current_user_paid ?? active.current_user_paid,
              other_user_paid: data.other_user_paid ?? active.other_user_paid,
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
    if (active.current_user_paid) {
      return;
    }

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

  function openRemoveChatModal() {
    if (!removeChatModal || !removeChatForm || !active) return;
    removeChatForm.reset();
    removeChatOtherField.hidden = true;
    removeChatOther.required = false;
    removeChatModal.hidden = false;
    document.body.classList.add('modal-open');
    requestAnimationFrame(() => removeChatModal.classList.add('is-open'));
    removeChatReason.focus();
  }

  function closeRemoveChatModal() {
    if (!removeChatModal) return;
    removeChatModal.classList.remove('is-open');
    document.body.classList.remove('modal-open');
    window.setTimeout(() => {
      removeChatModal.hidden = true;
    }, 180);
  }

  function submitRemoveChat(event) {
    event.preventDefault();
    if (!active) return;
    const reason = removeChatReason.value;
    const customReason = removeChatOther.value.trim();
    if (!reason) {
      SkillFlowUI.error('Please select a reason.');
      return;
    }
    if (reason === 'Other' && !customReason) {
      SkillFlowUI.error('Please add a reason in Other.');
      removeChatOther.focus();
      return;
    }

    const button = removeChatForm.querySelector('.btn-remove-confirm');
    button.disabled = true;
    button.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Removing...';
    fetch('/api/matches/remove', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        action_type: 'unfollow',
        request_id: active.request_id,
        reason,
        custom_reason: customReason
      })
    })
      .then((response) => response.json())
      .then((data) => {
        if (!data.success) {
          SkillFlowUI.error(data.error || 'Unable to remove connection.');
          return;
        }
        SkillFlowUI.success('Connection removed successfully.');
        closeRemoveChatModal();
        active = null;
        activeChat.hidden = true;
        emptyState.hidden = false;
        loadChats();
      })
      .catch(() => SkillFlowUI.error('Unable to remove connection.'))
      .finally(() => {
        button.disabled = false;
        button.innerHTML = '<i class="fa-solid fa-user-minus"></i> Confirm Remove';
      });
  }

  function unlockFirstAvailableChat() {
    const lockedChat = chats.find((chat) => !chat.current_user_paid);
    if (!lockedChat) {
      const unlockedChat = chats.find((chat) => chat.is_unlocked);
      if (unlockedChat) {
        openChat(unlockedChat.request_id);
        return;
      }
      SkillFlowUI.info('No accepted chats available to unlock yet.');
      return;
    }

    setChatState(lockedChat);
    const url = new URL(window.location.href);
    url.searchParams.set('request_id', lockedChat.request_id);
    url.searchParams.set('user_id', lockedChat.other_id);
    window.history.replaceState({}, '', url);
    payToUnlock();
  }

  chatForm.addEventListener('submit', (event) => {
    event.preventDefault();
    sendMessage();
  });
  unlockBtn.addEventListener('click', payToUnlock);
  if (reportChatBtn) {
    reportChatBtn.addEventListener('click', () => window.SkillFlowReport.open(reportChatBtn.dataset.reportUser));
  }
  removeChatConnectionBtn?.addEventListener('click', openRemoveChatModal);
  removeChatForm?.addEventListener('submit', submitRemoveChat);
  removeChatReason?.addEventListener('change', () => {
    const isOther = removeChatReason.value === 'Other';
    removeChatOtherField.hidden = !isOther;
    removeChatOther.required = isOther;
    if (isOther) removeChatOther.focus();
    else removeChatOther.value = '';
  });
  removeChatModal?.addEventListener('click', (event) => {
    if (event.target.closest('[data-chat-remove-close]')) closeRemoveChatModal();
  });
  globalUnlockBtn.addEventListener('click', unlockFirstAvailableChat);

  loadChats();
  pollTimer = window.setInterval(() => {
    if (active && active.is_unlocked) loadHistory();
  }, 5000);
  window.addEventListener('beforeunload', () => window.clearInterval(pollTimer));
});
