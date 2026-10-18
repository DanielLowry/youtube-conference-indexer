(() => {
  let theme;
  try { theme = localStorage.getItem('extractor-theme'); } catch (_) { /* Storage can be unavailable. */ }
  document.documentElement.dataset.theme = theme === 'light' || theme === 'dark' ? theme : (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
})();
