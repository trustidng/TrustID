document.addEventListener("DOMContentLoaded", () => {
  document.querySelector("[data-phone-home]")?.addEventListener("dblclick", () => window.location.assign("/"));
  const dialer = document.querySelector("[data-dialer]");
  if (dialer) {
    const input = dialer.querySelector("#service-code");
    dialer.querySelectorAll("[data-key]").forEach((key) => key.addEventListener("click", () => {
      input.value += key.dataset.key;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.focus();
    }));
    dialer.querySelector("[data-delete]")?.addEventListener("click", () => {
      input.value = input.value.slice(0, -1);
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.focus();
    });
  }
  document.querySelectorAll(".result-pill").forEach((pill) => {
    if (/not confirmed|not met/i.test(pill.textContent || "")) pill.classList.add("not-met");
  });
  document.querySelectorAll("form").forEach((form) => {
    const password = form.querySelector("[data-password-field]");
    const confirmation = form.querySelector("[data-confirm-password]");
    const message = form.querySelector("[data-match-message]");
    if (!password || !confirmation) return;
    const update = () => {
      const longEnough = password.value.length >= 10;
      password.setCustomValidity(longEnough || !password.value ? "" : "Password must contain at least 10 characters.");
      const matches = confirmation.value === password.value;
      confirmation.setCustomValidity(matches || !confirmation.value ? "" : "Passwords do not match.");
      if (message) {
        message.textContent = confirmation.value && matches ? "Passwords match." : "Enter the same password again.";
        message.classList.toggle("validation-success", Boolean(confirmation.value && matches));
      }
    };
    password.addEventListener("input", update);
    confirmation.addEventListener("input", update);
  });
  const evidenceForm = document.querySelector("[data-evidence-form]");
  if (evidenceForm) {
    const select = evidenceForm.querySelector("[data-category-select]");
    const updateEvidence = () => {
      evidenceForm.querySelectorAll("[data-category-panel]").forEach((panel) => {
        const shown = panel.dataset.categoryPanel === select.value;
        panel.hidden = !shown;
        panel.querySelectorAll("input").forEach((input) => {
          input.disabled = !shown;
          if (input.type === "file") input.required = shown && input.hasAttribute("data-required-file");
        });
      });
    };
    select.addEventListener("change", updateEvidence);
    updateEvidence();
  }
  document.querySelectorAll('a.primary-action[href^="#review-"]').forEach((link) => {
    const id = link.getAttribute("href").replace("#review-", "");
    link.href = `/admin/organisations/${id}/review`;
  });
  document.querySelectorAll(".organization-table tbody tr").forEach((row) => {
    const badge = row.querySelector(".status-badge");
    const actions = row.querySelector(".organization-actions");
    const history = actions?.querySelector('a[href*="/verifications"]');
    if (badge?.textContent.trim() === "Needs Information" && history) {
      const match = history.href.match(/organisations\/(\d+)\//);
      if (match) {
        const review = document.createElement("a");
        review.className = "row-action primary-action";
        review.href = `/admin/organisations/${match[1]}/review`;
        review.textContent = "Continue review";
        actions.appendChild(review);
      }
    }
  });
  document.querySelectorAll('select[name="status_filter"]').forEach((select) => {
    if (!select.querySelector('option[value="NEEDS_INFORMATION"]')) {
      const option = document.createElement("option");
      option.value = "NEEDS_INFORMATION";
      option.textContent = "Needs information";
      if (new URLSearchParams(window.location.search).get("status_filter") === option.value) option.selected = true;
      select.insertBefore(option, select.querySelector('option[value="APPROVED"]'));
    }
  });
  const reviewBadge = document.querySelector(".review-hero .status-badge");
  const decisionCard = document.querySelector(".decision-card");
  if (reviewBadge && decisionCard && ["Approved", "Rejected", "Suspended"].includes(reviewBadge.textContent.trim())) {
    const status = reviewBadge.textContent.trim();
    const id = window.location.pathname.match(/organisations\/(\d+)\/review/)?.[1];
    decisionCard.innerHTML = `<p class="eyebrow">Decision recorded</p><div class="decision-mark">${status === "Approved" ? "✓" : "!"}</div><h2>${status === "Approved" ? "Organization approved" : `Application ${status.toLowerCase()}`}</h2><p>This application and its submitted evidence remain available here as a permanent review record.</p>${id ? `<a class="button secondary" href="/admin/organisations/${id}/verifications">View verification history</a>` : ""}`;
    document.querySelectorAll(".assessment-form").forEach((form) => form.hidden = true);
  }
  if (window.location.pathname === "/admin/administrators" && new URLSearchParams(window.location.search).has("error")) {
    window.location.hash = "create-administrator";
  }
  const categoryList = document.querySelector(".category-list");
  if (categoryList) {
    const cards = [...categoryList.querySelectorAll(":scope > .category-policy")];
    const toolbar = document.createElement("div");
    toolbar.className = "category-toolbar";
    toolbar.innerHTML = `<label>Find a category<input type="search" placeholder="Search categories"></label><span>${cards.length} categories</span>`;
    categoryList.before(toolbar);
    const search = toolbar.querySelector("input");
    cards.forEach((card) => {
      const details = document.createElement("details");
      details.className = "category-accordion";
      const name = card.querySelector("h2")?.textContent || "Category";
      const count = card.querySelector(".category-heading p:last-child")?.textContent || "";
      const active = card.querySelector('input[name="active"]')?.checked;
      const summary = document.createElement("summary");
      const identity = document.createElement("span");
      const title = document.createElement("strong");
      const assigned = document.createElement("small");
      const state = document.createElement("span");
      title.textContent = name;
      assigned.textContent = count;
      state.className = `category-summary-state ${active ? "active" : "inactive"}`;
      state.textContent = active ? "Active" : "Inactive";
      identity.append(title, assigned);
      summary.append(identity, state);
      details.append(summary, card.cloneNode(true));
      card.replaceWith(details);
    });
    search.addEventListener("input", () => {
      const value = search.value.trim().toLowerCase();
      categoryList.querySelectorAll(".category-accordion").forEach((item) => item.hidden = !item.textContent.toLowerCase().includes(value));
    });
  }
});
