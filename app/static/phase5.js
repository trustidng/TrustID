(() => {
  const operator = document.querySelector('[data-age-operator]');
  if (!operator) return;

  const primaryLabel = document.querySelector('[data-age-primary-label]');
  const maximum = document.querySelector('[data-age-maximum]');
  const maximumInput = maximum.querySelector('input');
  const labels = {
    MINIMUM: 'Minimum age',
    MAXIMUM: 'Maximum age',
    EXACT: 'Exact age',
    RANGE: 'Minimum age'
  };

  const updateAgeFields = () => {
    const isRange = operator.value === 'RANGE';
    primaryLabel.textContent = labels[operator.value] || 'Age';
    maximum.hidden = !isRange;
    maximumInput.required = isRange;
    if (!isRange) maximumInput.value = '';
  };

  operator.addEventListener('change', updateAgeFields);
  updateAgeFields();
})();
