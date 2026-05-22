// ============================================
//  SkillFlow – script.js
// ============================================

/**
 * Redirect user to login page on "Get Started" click.
 * Called by both navbar and hero buttons via onclick="handleGetStarted()"
 */
function handleGetStarted() {
  window.location.href = "/auth";
}

// ── Scroll-reveal for feature cards ──────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {

  // Intersection Observer – fade-in cards as they enter the viewport
  const cards = document.querySelectorAll(".step-card, .feature-box, .price-card, .security-item");

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.style.animation = "fadeSlideUp 0.6s ease forwards";
          observer.unobserve(entry.target);
        }
      });
    },
    { threshold: 0.15 }
  );

  cards.forEach((card) => {
    // Pause animation until card enters viewport
    card.style.opacity = "0";
    observer.observe(card);
  });

  // ── Navbar shadow on scroll ───────────────────────────────────────────────
  const navbar = document.querySelector(".navbar");
  const backToTop = document.querySelector(".back-to-top");

  window.addEventListener("scroll", () => {
    if (window.scrollY > 10) {
      navbar.style.boxShadow = "0 4px 24px rgba(37,99,235,0.12)";
    } else {
      navbar.style.boxShadow = "0 2px 20px rgba(37,99,235,0.06)";
    }

    if (backToTop) {
      backToTop.classList.toggle("is-visible", window.scrollY > 360);
    }
  });

  if (backToTop) {
    backToTop.addEventListener("click", () => {
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  }

  // ── Button ripple effect ──────────────────────────────────────────────────
  const buttons = document.querySelectorAll(".btn-hero, .btn-nav");

  buttons.forEach((btn) => {
    btn.addEventListener("click", function (e) {
      const ripple = document.createElement("span");
      const rect = btn.getBoundingClientRect();

      Object.assign(ripple.style, {
        position:     "absolute",
        borderRadius: "50%",
        width:        "0px",
        height:       "0px",
        left:         `${e.clientX - rect.left}px`,
        top:          `${e.clientY - rect.top}px`,
        background:   "rgba(255,255,255,0.35)",
        transform:    "translate(-50%, -50%)",
        animation:    "rippleOut 0.5s ease forwards",
        pointerEvents:"none",
      });

      btn.style.position = "relative";
      btn.style.overflow = "hidden";
      btn.appendChild(ripple);

      setTimeout(() => ripple.remove(), 550);
    });
  });

  // Inject ripple keyframe once
  if (!document.getElementById("ripple-style")) {
    const style = document.createElement("style");
    style.id = "ripple-style";
    style.textContent = `
      @keyframes rippleOut {
        to { width: 200px; height: 200px; opacity: 0; }
      }
    `;
    document.head.appendChild(style);
  }

});
