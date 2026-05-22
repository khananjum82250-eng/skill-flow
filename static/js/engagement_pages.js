document.addEventListener('DOMContentLoaded', () => {
  const claimRewardButton = document.getElementById('btnClaimReward');
  const reviewForm = document.getElementById('pageReviewForm');
  const reviewTabs = document.querySelectorAll('[data-review-tab]');
  const reviewPanes = document.querySelectorAll('[data-review-pane]');
  const activityFilters = document.querySelectorAll('[data-activity-filter]');
  const activityCards = document.querySelectorAll('[data-activity-type]');

  reviewTabs.forEach((tab) => {
    tab.addEventListener('click', () => {
      const target = tab.dataset.reviewTab;
      reviewTabs.forEach((item) => {
        const isActive = item === tab;
        item.classList.toggle('active', isActive);
        item.setAttribute('aria-selected', isActive ? 'true' : 'false');
      });
      reviewPanes.forEach((pane) => {
        const isActive = pane.dataset.reviewPane === target;
        pane.classList.toggle('active', isActive);
        pane.hidden = !isActive;
      });
    });
  });

  activityFilters.forEach((filter) => {
    filter.addEventListener('click', () => {
      const target = filter.dataset.activityFilter;
      activityFilters.forEach((item) => item.classList.toggle('active', item === filter));
      activityCards.forEach((card) => {
        card.hidden = target !== 'all' && card.dataset.activityType !== target;
      });
    });
  });

  claimRewardButton?.addEventListener('click', () => {
    const originalText = claimRewardButton.textContent;
    claimRewardButton.disabled = true;
    claimRewardButton.textContent = 'Claiming...';
    fetch('/api/reward/claim', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.success) {
          claimRewardButton.textContent = 'Claimed';
          SkillFlowUI.success(`Daily reward claimed. +${data.xp_awarded || 20} XP`);
        } else {
          claimRewardButton.disabled = false;
          claimRewardButton.textContent = originalText;
          SkillFlowUI.error(data.error || 'Unable to claim reward.');
        }
      })
      .catch(() => {
        claimRewardButton.disabled = false;
        claimRewardButton.textContent = originalText;
        SkillFlowUI.error('Failed to claim reward.');
      });
  });

  reviewForm?.addEventListener('submit', (event) => {
    event.preventDefault();
    const submitButton = reviewForm.querySelector('button[type="submit"]');
    const formData = new FormData(reviewForm);
    if (submitButton) submitButton.disabled = true;
    fetch('/api/reviews/submit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        reviewed_user_id: formData.get('reviewed_user_id'),
        rating: formData.get('rating'),
        experience_tag: formData.get('experience_tag'),
        feedback: formData.get('feedback')
      })
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.success) {
          SkillFlowUI.success('Review saved.');
          reviewForm.reset();
        } else {
          SkillFlowUI.error(data.error || 'Unable to save review.');
        }
      })
      .catch(() => SkillFlowUI.error('Failed to save review.'))
      .finally(() => {
        if (submitButton) submitButton.disabled = false;
      });
  });
});
