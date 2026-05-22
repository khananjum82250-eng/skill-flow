(function () {
  const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const lenisCdn = 'https://unpkg.com/lenis@1.3.16/dist/lenis.min.js';

  function loadLenis() {
    if (typeof window.Lenis === 'function') return Promise.resolve();
    if (window.SkillFlowLenisLoading) return window.SkillFlowLenisLoading;

    window.SkillFlowLenisLoading = new Promise((resolve) => {
      const script = document.createElement('script');
      script.src = lenisCdn;
      script.async = true;
      script.onload = resolve;
      script.onerror = resolve;
      document.head.appendChild(script);
    });

    return window.SkillFlowLenisLoading;
  }

  function initSkillFlowMotion() {
    const scrollContainer = document.querySelector('body.app-layout > .main-content');
    const isTouchPrimary = window.matchMedia('(hover: none) and (pointer: coarse)').matches;
    let lenis = null;
    let rafId = null;

    document.querySelectorAll([
      'body.app-layout > .sidebar',
      '.messages',
      '.chat-list',
      '.profile-modal-content',
      '.admin-table-wrap',
      '.search-results',
      'textarea',
      'select'
    ].join(',')).forEach((element) => {
      element.setAttribute('data-lenis-prevent', '');
    });

    function shouldSkipSmoothScroll() {
      return prefersReducedMotion.matches || typeof window.Lenis !== 'function';
    }

    function createLenis() {
      if (shouldSkipSmoothScroll()) return null;

      const baseOptions = {
        duration: 1.05,
        easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
        smoothWheel: true,
        syncTouch: true,
        touchMultiplier: 1.25,
        wheelMultiplier: 0.95,
        infinite: false,
        autoResize: true
      };

      if (scrollContainer) {
        return new window.Lenis({
          ...baseOptions,
          wrapper: scrollContainer,
          content: scrollContainer
        });
      }

      return new window.Lenis(baseOptions);
    }

    function startRaf(instance) {
      const raf = (time) => {
        instance.raf(time);
        rafId = window.requestAnimationFrame(raf);
      };

      rafId = window.requestAnimationFrame(raf);
    }

    function stopMotion() {
      if (rafId) {
        window.cancelAnimationFrame(rafId);
        rafId = null;
      }

      if (lenis) {
        lenis.destroy();
        lenis = null;
        window.SkillFlowLenis = null;
      }
    }

    function startMotion() {
      stopMotion();
      try {
        lenis = createLenis();
      } catch (error) {
        lenis = null;
        return;
      }
      if (!lenis) return;
      window.SkillFlowLenis = lenis;
      document.documentElement.classList.add('sf-motion-ready');
      startRaf(lenis);
    }

    function getAnchorTarget(link) {
      if (!link.hash || link.hash === '#') return null;
      try {
        const linkUrl = new URL(link.href, window.location.href);
        if (linkUrl.pathname !== window.location.pathname || linkUrl.origin !== window.location.origin) return null;
        return document.getElementById(decodeURIComponent(link.hash.slice(1)));
      } catch (error) {
        return null;
      }
    }

    document.addEventListener('click', (event) => {
      const link = event.target.closest('a[href*="#"]');
      if (!link) return;

      const target = getAnchorTarget(link);
      if (!target) return;

      event.preventDefault();

      if (lenis) {
        lenis.scrollTo(target, {
          offset: -8,
          duration: isTouchPrimary ? 0.9 : 1.15,
          easing: (t) => 1 - Math.pow(1 - t, 3)
        });
      } else {
        target.scrollIntoView({ behavior: prefersReducedMotion.matches ? 'auto' : 'smooth', block: 'start' });
      }

      if (history.pushState) history.pushState(null, '', link.hash);
    });

    const revealTargets = document.querySelectorAll([
      'section',
      '.card',
      '.feature-card',
      '.step-card',
      '.skill-card',
      '.dashboard-card',
      '.request-card',
      '.profile-card',
      '.admin-card',
      '.admin-chart',
      '.admin-table-wrap',
      '.login-panel'
    ].join(','));

    if ('IntersectionObserver' in window && !prefersReducedMotion.matches) {
      const revealObserver = new IntersectionObserver((entries, observer) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          entry.target.classList.add('sf-revealed');
          observer.unobserve(entry.target);
        });
      }, {
        root: scrollContainer || null,
        threshold: 0.08,
        rootMargin: '0px 0px -8% 0px'
      });

      revealTargets.forEach((element) => {
        element.classList.add('sf-reveal');
        revealObserver.observe(element);
      });
    } else {
      revealTargets.forEach((element) => element.classList.add('sf-revealed'));
    }

    const handleMotionPreferenceChange = () => {
      if (prefersReducedMotion.matches) {
        stopMotion();
        return;
      }
      loadLenis().then(startMotion);
    };

    if (typeof prefersReducedMotion.addEventListener === 'function') {
      prefersReducedMotion.addEventListener('change', handleMotionPreferenceChange);
    } else if (typeof prefersReducedMotion.addListener === 'function') {
      prefersReducedMotion.addListener(handleMotionPreferenceChange);
    }

    window.addEventListener('beforeunload', stopMotion);
    if (!prefersReducedMotion.matches) loadLenis().then(startMotion);
  }

  const icons = {
    success: 'fa-solid fa-check',
    error: 'fa-solid fa-xmark',
    warning: 'fa-solid fa-triangle-exclamation',
    info: 'fa-solid fa-circle-info',
    confirm: 'fa-solid fa-question',
    input: 'fa-solid fa-key'
  };

  function ensureToastStack() {
    let stack = document.querySelector('.sf-toast-stack');
    if (!stack) {
      stack = document.createElement('div');
      stack.className = 'sf-toast-stack';
      document.body.appendChild(stack);
    }
    return stack;
  }

  function closeWithAnimation(element, removeDelay = 180) {
    element.classList.add('is-leaving');
    window.setTimeout(() => element.remove(), removeDelay);
  }

  function toast(message, type = 'info', options = {}) {
    const stack = ensureToastStack();
    const toastEl = document.createElement('div');
    const title = options.title || {
      success: 'Success',
      error: 'Error',
      warning: 'Attention',
      info: 'SkillFlow'
    }[type] || 'SkillFlow';

    toastEl.className = `sf-toast ${type}`;
    toastEl.innerHTML = `
      <span class="sf-toast-icon"><i class="${icons[type] || icons.info}"></i></span>
      <span>
        <strong class="sf-toast-title">${escapeHTML(title)}</strong>
        <p class="sf-toast-message">${escapeHTML(message)}</p>
      </span>
      <button class="sf-toast-close" type="button" aria-label="Close"><i class="fa-solid fa-xmark"></i></button>
    `;
    stack.appendChild(toastEl);

    const close = () => closeWithAnimation(toastEl);
    toastEl.querySelector('.sf-toast-close').addEventListener('click', close);
    if (options.autoClose !== false) {
      window.setTimeout(close, options.duration || 2800);
    }
    return toastEl;
  }

  function modal({
    type = 'info',
    title = 'SkillFlow',
    message = '',
    confirmText = 'OK',
    cancelText = '',
    danger = false,
    fields = []
  } = {}) {
    return new Promise((resolve) => {
      const overlay = document.createElement('div');
      const fieldHtml = fields.length
        ? `<div class="sf-modal-fields">${fields.map((field) => `
            <div class="sf-field">
              <label for="sf-${field.name}">${escapeHTML(field.label || field.name)}</label>
              <input id="sf-${field.name}" name="${escapeHTML(field.name)}" type="${escapeHTML(field.type || 'text')}" placeholder="${escapeHTML(field.placeholder || '')}" ${field.required ? 'required' : ''}>
            </div>
          `).join('')}</div>`
        : '';

      overlay.className = 'sf-modal-overlay';
      overlay.innerHTML = `
        <div class="sf-modal ${type}" role="dialog" aria-modal="true">
          <button class="sf-modal-close" type="button" aria-label="Close"><i class="fa-solid fa-xmark"></i></button>
          <span class="sf-modal-icon"><i class="${icons[type] || icons.info}"></i></span>
          <h2 class="sf-modal-title">${escapeHTML(title)}</h2>
          ${message ? `<p class="sf-modal-message">${escapeHTML(message)}</p>` : ''}
          ${fieldHtml}
          <div class="sf-modal-actions">
            ${cancelText ? `<button class="sf-btn sf-btn-secondary" data-sf-cancel type="button">${escapeHTML(cancelText)}</button>` : ''}
            <button class="sf-btn ${danger ? 'sf-btn-danger' : 'sf-btn-primary'}" data-sf-confirm type="button">
              <i class="${danger ? 'fa-solid fa-trash' : 'fa-solid fa-check'}"></i>
              ${escapeHTML(confirmText)}
            </button>
          </div>
        </div>
      `;
      document.body.appendChild(overlay);

      const close = (value) => {
        closeWithAnimation(overlay, 160);
        resolve(value);
      };

      overlay.querySelector('.sf-modal-close').addEventListener('click', () => close(false));
      overlay.querySelector('[data-sf-cancel]')?.addEventListener('click', () => close(false));
      overlay.addEventListener('click', (event) => {
        if (event.target === overlay) close(false);
      });
      overlay.querySelector('[data-sf-confirm]').addEventListener('click', () => {
        if (!fields.length) {
          close(true);
          return;
        }

        const values = {};
        let valid = true;
        fields.forEach((field) => {
          const input = overlay.querySelector(`[name="${field.name}"]`);
          if (field.required && !input.value.trim()) valid = false;
          values[field.name] = input.value;
        });
        if (!valid) {
          toast('Please fill all required fields.', 'warning', { autoClose: true });
          return;
        }
        close(values);
      });

      const firstInput = overlay.querySelector('input');
      firstInput?.focus();
    });
  }

  function escapeHTML(value) {
    const div = document.createElement('div');
    div.textContent = value == null ? '' : String(value);
    return div.innerHTML;
  }

  function readCookie(name) {
    return document.cookie.split(';').map((part) => part.trim()).reduce((value, part) => {
      if (value || !part.startsWith(`${name}=`)) return value;
      return decodeURIComponent(part.slice(name.length + 1));
    }, '');
  }

  function getCSRFToken() {
    return document.querySelector('meta[name="csrf-token"]')?.content
      || document.querySelector('input[name="csrf_token"]')?.value
      || readCookie('sf_csrf_token');
  }

  function isUnsafeMethod(method) {
    return ['POST', 'PUT', 'PATCH', 'DELETE'].includes(String(method || 'GET').toUpperCase());
  }

  function installCSRFFetchGuard() {
    if (window.SkillFlowCSRFFetchGuard || typeof window.fetch !== 'function') return;
    const nativeFetch = window.fetch.bind(window);
    window.fetch = (resource, options = {}) => {
      const requestUrl = typeof resource === 'string' ? resource : resource?.url;
      const method = options.method || (typeof resource !== 'string' ? resource?.method : 'GET') || 'GET';
      let sameOrigin = true;
      try {
        sameOrigin = new URL(requestUrl, window.location.href).origin === window.location.origin;
      } catch (error) {
        sameOrigin = true;
      }
      if (sameOrigin && isUnsafeMethod(method)) {
        const token = getCSRFToken();
        if (token) {
          const headers = new Headers(options.headers || (typeof resource !== 'string' ? resource.headers : undefined) || {});
          if (!headers.has('X-CSRFToken')) headers.set('X-CSRFToken', token);
          options = { ...options, headers };
        }
      }
      return nativeFetch(resource, options);
    };
    window.SkillFlowCSRFFetchGuard = true;
  }

  function attachCSRFToForms() {
    const token = getCSRFToken();
    if (!token) return;
    document.querySelectorAll('form').forEach((form) => {
      form.addEventListener('submit', () => {
        const method = (form.getAttribute('method') || 'GET').toUpperCase();
        if (!isUnsafeMethod(method)) return;
        let input = form.querySelector('input[name="csrf_token"]');
        if (!input) {
          input = document.createElement('input');
          input.type = 'hidden';
          input.name = 'csrf_token';
          form.appendChild(input);
        }
        input.value = getCSRFToken() || token;
      });
    });
  }

  installCSRFFetchGuard();

  window.SkillFlowUI = {
    toast,
    success(message, options) {
      return toast(message, 'success', options);
    },
    error(message, options = {}) {
      return toast(message, 'error', { autoClose: false, ...options });
    },
    info(message, options) {
      return toast(message, 'info', options);
    },
    show(message, type = 'info', title) {
      return modal({ type, title: title || (type === 'error' ? 'Something went wrong' : 'SkillFlow'), message });
    },
    confirmDialog(message, options = {}) {
      return modal({
        type: options.type || 'warning',
        title: options.title || 'Are you sure?',
        message,
        confirmText: options.confirmText || 'Confirm',
        cancelText: options.cancelText || 'Cancel',
        danger: Boolean(options.danger)
      });
    },
    input(options = {}) {
      return modal({
        type: 'input',
        title: options.title || 'Enter details',
        message: options.message || '',
        confirmText: options.confirmText || 'Submit',
        cancelText: options.cancelText || 'Cancel',
        fields: options.fields || []
      });
    }
  };

  document.addEventListener('DOMContentLoaded', () => {
    initSkillFlowMotion();
    attachCSRFToForms();

    if (document.body.classList.contains('app-layout') && document.querySelector('body.app-layout > .sidebar')) {
      let menuButton = document.querySelector('.sf-mobile-menu-toggle');
      let overlay = document.querySelector('.sf-mobile-sidebar-overlay');
      if (!menuButton) {
        menuButton = document.createElement('button');
        menuButton.className = 'sf-mobile-menu-toggle';
        menuButton.type = 'button';
        menuButton.setAttribute('aria-label', 'Open navigation');
        menuButton.innerHTML = '<i class="fa-solid fa-bars"></i>';
        document.body.appendChild(menuButton);
      }
      if (!overlay) {
        overlay = document.createElement('div');
        overlay.className = 'sf-mobile-sidebar-overlay';
        document.body.appendChild(overlay);
      }
      const closeSidebar = () => document.body.classList.remove('user-sidebar-open', 'dashboard-sidebar-open');
      menuButton.addEventListener('click', () => {
        document.body.classList.toggle('user-sidebar-open');
      });
      overlay.addEventListener('click', closeSidebar);
      document.querySelectorAll('body.app-layout > .sidebar a').forEach((link) => {
        link.addEventListener('click', closeSidebar);
      });
      window.addEventListener('resize', () => {
        if (window.innerWidth > 768) closeSidebar();
      });
    }

    document.querySelectorAll('.flash-message, .flash').forEach((messageEl) => {
      const message = messageEl.textContent.trim();
      if (!message) return;
      const type = messageEl.classList.contains('success') ? 'success'
        : messageEl.classList.contains('error') ? 'error'
        : messageEl.classList.contains('danger') ? 'error'
        : 'info';
      toast(message, type, { autoClose: type !== 'error' });
      messageEl.remove();
    });

    document.querySelectorAll('.flash-messages').forEach((wrapper) => {
      if (!wrapper.children.length) wrapper.remove();
    });
  });
}());
