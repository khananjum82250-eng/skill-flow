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
  const globalUnlockBtn = document.getElementById('globalUnlockBtn');
  const lockBanner = document.getElementById('lockBanner');
  const contactBox = document.getElementById('contactBox');
  const messagesContainer = document.getElementById('messagesContainer');
  const chatForm = document.getElementById('chatForm');
  const chatInput = document.getElementById('chatInput');
  const sendBtn = document.getElementById('sendBtn');

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
    chatCount.textContent = chats.length;
    if (!chats.length) {
      chatList.innerHTML = '<div class="chat-empty">No accepted chats yet. Accept a request to start.</div>';
      return;
    }

    chatList.innerHTML = chats.map((chat) => {
      const lockedIcon = chat.is_unlocked ? '<i class="fa-solid fa-unlock chat-list-lock"></i>' : '<i class="fa-solid fa-lock chat-list-lock"></i>';
      const statusText = chat.is_unlocked ? escapeHTML(chat.last_message || 'Chat Unlocked') : 'Chat Locked';
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
    activeStatus.textContent = chat.is_unlocked ? `Unlocked until ${chat.expiry_date ? new Date(chat.expiry_date).toLocaleDateString() : '90 days'}` : 'Chat Locked';
    activeStatus.classList.toggle('unlocked', chat.is_unlocked);
    unlockBtn.hidden = !locked;
    if (reportChatBtn) {
      reportChatBtn.hidden = false;
      reportChatBtn.dataset.reportUser = chat.other_id;
    }
    lockBanner.hidden = !locked;
    lockBanner.querySelector('span').textContent = expired
      ? 'Your chat access has expired. Please unlock again to continue'
      : 'Chat is locked. Unlock to start conversation';
    chatInput.disabled = locked;
    sendBtn.disabled = locked;
    chatInput.placeholder = locked ? 'Unlock chat to start typing' : 'Type your message...';
    chatForm.hidden = false;
    messagesContainer.hidden = locked;
    if (locked) {
      messagesContainer.innerHTML = '';
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
      messagesContainer.innerHTML = '';
      messagesContainer.hidden = true;
      return;
    }
    messagesContainer.hidden = false;

    fetch(`/api/chat/history?request_id=${encodeURIComponent(active.request_id)}`)
      .then((response) => response.json())
      .then((data) => {
        if (data.error) {
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
    if (!active || !content || !active.is_unlocked) return;

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

  chatForm.addEventListener('submit', (event) => {
    event.preventDefault();
    sendMessage();
  });
  unlockBtn.addEventListener('click', payToUnlock);
  if (reportChatBtn) {
    reportChatBtn.addEventListener('click', () => window.SkillFlowReport.open(reportChatBtn.dataset.reportUser));
  }
  globalUnlockBtn.addEventListener('click', unlockFirstAvailableChat);

  loadChats();
  pollTimer = window.setInterval(() => {
    if (active && active.is_unlocked) loadHistory();
  }, 5000);
  window.addEventListener('beforeunload', () => window.clearInterval(pollTimer));
});
