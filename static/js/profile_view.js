document.addEventListener('DOMContentLoaded', () => {
  const favoriteButton = document.getElementById('btnFavoriteProfile');
  const reviewForm = document.getElementById('reviewForm');

  favoriteButton?.addEventListener('click', () => {
    favoriteButton.disabled = true;
    fetch('/api/favorites/toggle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: favoriteButton.dataset.userId })
    })
      .then((res) => res.json())
      .then((data) => {
        if (!data.success) {
          SkillFlowUI.error(data.error || 'Unable to update saved profile.');
          return;
        }
        favoriteButton.dataset.saved = data.saved ? '1' : '0';
        favoriteButton.innerHTML = data.saved
          ? '<i class="fa-solid fa-bookmark"></i> Saved'
          : '<i class="fa-regular fa-bookmark"></i> Save';
        SkillFlowUI.success(data.saved ? 'Profile saved.' : 'Profile removed from saved users.');
      })
      .catch(() => SkillFlowUI.error('Failed to update saved profile.'))
      .finally(() => {
        favoriteButton.disabled = false;
      });
  });

  reviewForm?.addEventListener('submit', (event) => {
    event.preventDefault();
    const formData = new FormData(reviewForm);
    const submitButton = reviewForm.querySelector('button[type="submit"]');
    if (submitButton) submitButton.disabled = true;
    fetch('/api/reviews/submit', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        reviewed_user_id: reviewForm.dataset.reviewedUserId,
        rating: formData.get('rating'),
        experience_tag: formData.get('experience_tag'),
        feedback: formData.get('feedback')
      })
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.success) SkillFlowUI.success('Review saved.');
        else SkillFlowUI.error(data.error || 'Unable to save review.');
      })
      .catch(() => SkillFlowUI.error('Failed to save review.'))
      .finally(() => {
        if (submitButton) submitButton.disabled = false;
      });
  });
});
