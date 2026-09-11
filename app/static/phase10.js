document.querySelectorAll("[data-service-form]").forEach((form) => {
  const reason = form.querySelector("[data-service-reason]");
  const other = form.querySelector("[data-service-other]");
  if (!reason || !other) return;
  const input = other.querySelector("input");
  const update = () => {
    const visible = reason.value === "OTHER";
    other.hidden = !visible;
    input.required = visible;
    if (!visible) input.value = "";
  };
  reason.addEventListener("change", update);
  update();
});
