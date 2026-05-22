document.addEventListener('DOMContentLoaded', () => {
  const menuButton = document.querySelector('[data-user-menu]');
  const overlay = document.querySelector('[data-user-sidebar-overlay]');

  const closeSidebar = () => document.body.classList.remove('user-sidebar-open');

  menuButton?.addEventListener('click', () => {
    document.body.classList.toggle('user-sidebar-open');
  });

  overlay?.addEventListener('click', closeSidebar);

  window.addEventListener('resize', () => {
    if (window.innerWidth > 768) closeSidebar();
  });

  document.querySelectorAll('[data-filter-chip]').forEach((chip) => {
    chip.addEventListener('click', () => {
      document.querySelectorAll('[data-filter-chip]').forEach((item) => item.classList.remove('active'));
      chip.classList.add('active');
    });
  });
});
