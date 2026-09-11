(() => {
  const feedback = document.querySelector('.copy-feedback');
  document.querySelectorAll('[data-copy]').forEach((button) => {
    button.addEventListener('click', async () => {
      try {
        await navigator.clipboard.writeText(button.dataset.copy);
        if (feedback) feedback.textContent = 'Copied to clipboard.';
        const original = button.textContent;
        button.textContent = 'Copied';
        setTimeout(() => { button.textContent = original; }, 1600);
      } catch (_) {
        if (feedback) feedback.textContent = 'Copy was unavailable. Select and copy the reference manually.';
      }
    });
  });
  document.querySelectorAll('[data-print]').forEach((button) => button.addEventListener('click', () => window.print()));
})();
