(() => {
  const root = document.documentElement;
  const button = document.getElementById('theme-toggle');
  const stored = localStorage.getItem('orgforms-theme');
  const preferred = 'light';

  function setTheme(theme) {
    root.dataset.theme = theme;
    if (button) {
      const dark = theme === 'dark';
      button.setAttribute('aria-label', `Switch to ${dark ? 'light' : 'dark'} mode`);
      button.title = `Switch to ${dark ? 'light' : 'dark'} mode`;
      button.innerHTML = `<span aria-hidden="true">${dark ? '☼' : '◐'}</span>`;
    }
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#191715' : '#f4efe9');
  }

  setTheme(stored || preferred);
  button?.addEventListener('click', () => {
    const next = root.dataset.theme === 'dark' ? 'light' : 'dark';
    localStorage.setItem('orgforms-theme', next);
    setTheme(next);
  });

  const localDateFormatter = new Intl.DateTimeFormat(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
  });
  const localTimeFormatter = new Intl.DateTimeFormat(undefined, {
    hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
  });
  document.querySelectorAll('time[data-local-time]').forEach((element) => {
    const date = new Date(element.dateTime);
    if (Number.isNaN(date.getTime())) return;
    const dateLabel = element.querySelector('[data-local-date]');
    const timeLabel = element.querySelector('[data-local-clock]');
    if (dateLabel) dateLabel.textContent = localDateFormatter.format(date);
    if (timeLabel) timeLabel.textContent = localTimeFormatter.format(date);
    element.dateTime = date.toISOString();
  });

  document.querySelectorAll('[data-toast]').forEach((toast) => {
    const dismissButton = toast.querySelector('[data-toast-dismiss]');
    let timer;
    const dismiss = () => {
      if (toast.classList.contains('is-dismissing')) return;
      clearTimeout(timer);
      toast.classList.add('is-dismissing');
      window.setTimeout(() => toast.remove(), 200);
    };
    const scheduleDismissal = () => {
      clearTimeout(timer);
      timer = window.setTimeout(dismiss, toast.dataset.kind?.includes('error') ? 10000 : 6500);
    };
    dismissButton?.addEventListener('click', dismiss);
    toast.addEventListener('pointerenter', () => clearTimeout(timer));
    toast.addEventListener('pointerleave', scheduleDismissal);
    toast.addEventListener('focusin', () => clearTimeout(timer));
    toast.addEventListener('focusout', (event) => {
      if (!toast.contains(event.relatedTarget)) scheduleDismissal();
    });
    scheduleDismissal();
  });

  const workspacePicker = document.querySelector('.workspace-picker');
  document.addEventListener('pointerdown', (event) => {
    if (workspacePicker?.open && !workspacePicker.contains(event.target)) workspacePicker.open = false;
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && workspacePicker?.open) workspacePicker.open = false;
  });

  const shortcutDialog = document.getElementById('shortcuts-dialog');
  const shortcutOpen = document.getElementById('shortcuts-open');
  const shortcutClose = document.getElementById('shortcuts-close');
  const modifierHint = document.getElementById('shortcut-modifier');
  const isMac = /Mac|iPhone|iPad/.test(navigator.platform);
  if (modifierHint) modifierHint.textContent = isMac ? '⌘' : 'Ctrl';

  shortcutOpen?.addEventListener('click', () => shortcutDialog?.showModal());
  shortcutClose?.addEventListener('click', () => shortcutDialog?.close());
  shortcutDialog?.addEventListener('click', (event) => {
    if (event.target === shortcutDialog) shortcutDialog.close();
  });

  function isTypingTarget(target) {
    return target instanceof HTMLElement && (
      target.isContentEditable ||
      target.matches('input, textarea, select')
    );
  }

  let navigationPrefix = false;
  let navigationTimer = null;

  document.addEventListener('keydown', (event) => {
    if (event.key === '?' && !event.ctrlKey && !event.metaKey && !isTypingTarget(event.target)) {
      event.preventDefault();
      shortcutDialog?.showModal();
      return;
    }

    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
      const form = event.target instanceof HTMLElement ? event.target.closest('form') : null;
      if (form) {
        event.preventDefault();
        form.requestSubmit();
      }
    }
    if (isTypingTarget(event.target) || event.altKey || event.ctrlKey || event.metaKey || shortcutDialog?.open) return;
    if (event.key.toLowerCase() === 'g') {
      navigationPrefix = true;
      clearTimeout(navigationTimer);
      navigationTimer = window.setTimeout(() => { navigationPrefix = false; }, 900);
      return;
    }
    if (!navigationPrefix) return;
    navigationPrefix = false;
    clearTimeout(navigationTimer);
    const routes = {
      d: document.querySelector('.top-nav a[href*="dashboard"]')?.href,
      f: document.querySelector('.top-nav a[href*="#organization-forms"]')?.href,
      s: document.querySelector('.top-nav a[href*="submissions"]')?.href,
      p: document.querySelector('.top-nav a[href*="people"]')?.href,
      a: document.querySelector('.top-nav a[href*="_chat"]')?.href,
    };
    const route = routes[event.key.toLowerCase()];
    if (route) window.location.assign(route);
  });

  const profileLibraryNode = document.getElementById('organization-profile-library');
  if (profileLibraryNode) {
    const profileLibrary = JSON.parse(profileLibraryNode.textContent);
    for (const profileForm of document.querySelectorAll('[data-profile-form]')) {
      const profileType = profileForm.querySelector('[data-profile-type]');
      const profileFields = profileForm.querySelector('[data-profile-fields]');
      const profileOutput = profileForm.querySelector('input[name="profile_data"]');
      if (!profileType || !profileFields || !profileOutput) continue;
      let profileValues = {};
      try { profileValues = JSON.parse(profileForm.dataset.profileInitial || '{}'); } catch (_) { profileValues = {}; }
      const customCategoryField = profileForm.querySelector('[data-custom-category-field]');
      const customCategoryInput = profileForm.querySelector('[data-custom-category]');
      let customCategorySelected = Boolean(profileValues.custom_category);
      const syncCategoryChoices = () => profileForm.querySelectorAll('[data-org-type-choice]').forEach((choice) => {
        const selected = choice.dataset.orgTypeChoice === 'custom'
          ? customCategorySelected
          : !customCategorySelected && choice.dataset.orgTypeChoice === profileType.value;
        choice.classList.toggle('selected', selected);
      });
      if (customCategoryField && customCategoryInput) {
        customCategoryInput.value = profileValues.custom_category || '';
        customCategoryInput.required = customCategorySelected;
        customCategoryField.hidden = !customCategorySelected;
        customCategoryInput.addEventListener('input', () => { profileValues.custom_category = customCategoryInput.value; });
      }
      const explicitAddress = profileForm.querySelector('[data-profile-address]');
      if (explicitAddress) {
        explicitAddress.value = profileValues.address || '';
        explicitAddress.addEventListener('input', () => { profileValues.address = explicitAddress.value; });
      }
      profileForm.querySelectorAll('[data-org-type-choice]').forEach((choice) => {
        choice.addEventListener('click', () => {
          if (choice.dataset.orgTypeChoice === 'custom') {
            customCategorySelected = true;
            profileType.value = 'generic';
            if (customCategoryField) customCategoryField.hidden = false;
            if (customCategoryInput) { customCategoryInput.required = true; customCategoryInput.focus(); }
          } else {
            customCategorySelected = false;
            delete profileValues.custom_category;
            profileType.value = choice.dataset.orgTypeChoice;
            if (customCategoryField) customCategoryField.hidden = true;
            if (customCategoryInput) customCategoryInput.required = false;
          }
          profileType.dispatchEvent(new Event('change', { bubbles: true }));
          syncCategoryChoices();
        });
      });

      function renderProfileFields() {
        profileFields.replaceChildren();
        const fields = profileLibrary[profileType.value] || profileLibrary.generic || [];
        for (const definition of fields) {
          if (definition.key === 'address' && explicitAddress) continue;
          const wrapper = document.createElement('div');
          wrapper.className = 'field';
          const inputId = `${profileType.id}-${definition.key}`;
          const label = document.createElement('label');
          label.htmlFor = inputId;
          label.textContent = definition.label;
          const input = document.createElement('input');
          input.id = inputId;
          input.type = definition.type || 'text';
          input.placeholder = definition.placeholder || '';
          input.value = profileValues[definition.key] || '';
          input.dataset.profileKey = definition.key;
          input.addEventListener('input', () => { profileValues[definition.key] = input.value; });
          wrapper.append(label, input);
          profileFields.append(wrapper);
        }
      }

      profileType.addEventListener('change', () => {
        if (profileType.value !== 'generic') {
          customCategorySelected = false;
          delete profileValues.custom_category;
          if (customCategoryField) customCategoryField.hidden = true;
          if (customCategoryInput) customCategoryInput.required = false;
        }
        renderProfileFields();
        syncCategoryChoices();
      });
      syncCategoryChoices();
      profileForm.addEventListener('submit', () => { profileOutput.value = JSON.stringify(profileValues); });
      renderProfileFields();
    }
  }

  document.querySelectorAll('.initial-form-options').forEach((options) => {
    options.querySelectorAll('.initial-form-option').forEach((option) => option.addEventListener('click', () => {
      options.querySelectorAll('.initial-form-option').forEach((item) => {
        const selected = item === option;
        item.classList.toggle('selected', selected);
        item.setAttribute('aria-pressed', String(selected));
      });
    }));
  });

  function openDialog(dialog) {
    if (dialog instanceof HTMLDialogElement && !dialog.open) dialog.showModal();
  }
  const workflowDialog = document.getElementById('form-workflow-dialog');
  const workflowFrame = document.getElementById('form-workflow-frame');
  const workflowLoading = document.getElementById('form-workflow-loading');
  let workflowReturnDialog = null;
  let workflowUrl = null;
  const restoreManageDialogId = sessionStorage.getItem('orgforms-restore-form-dialog');
  if (restoreManageDialogId) {
    sessionStorage.removeItem('orgforms-restore-form-dialog');
    openDialog(document.getElementById(restoreManageDialogId));
  }

  function openFormWorkflow(href, title, sourceDialog = null) {
    if (!workflowDialog || !workflowFrame) return;
    const url = new URL(href, location.origin);
    if (url.origin !== location.origin) return;
    url.searchParams.set('dialog', '1');
    workflowUrl = href;
    workflowReturnDialog = sourceDialog;
    if (sourceDialog?.open) sourceDialog.close();
    document.getElementById('form-workflow-title').textContent = title || 'Form';
    workflowFrame.title = title || 'Form';
    workflowFrame.hidden = true;
    workflowLoading.textContent = 'Loading…';
    workflowLoading.hidden = false;
    workflowFrame.src = url.href;
    openDialog(workflowDialog);
  }

  workflowFrame?.addEventListener('load', () => {
    if (!workflowDialog.open) return;
    try {
      if (!workflowFrame.contentDocument?.querySelector('.embedded-main')) throw new Error('Unavailable');
      workflowLoading.hidden = true;
      workflowFrame.hidden = false;
    } catch (_) {
      workflowLoading.textContent = 'This view could not load. Your session or access may have changed. ';
      const fallback = document.createElement('a');
      fallback.href = workflowUrl;
      fallback.textContent = 'Open the page';
      workflowLoading.append(fallback);
    }
  });
  workflowDialog?.addEventListener('close', () => {
    workflowFrame.src = 'about:blank';
    workflowFrame.hidden = true;
    const previous = workflowReturnDialog;
    workflowReturnDialog = null;
    if (previous) openDialog(previous);
  });
  window.addEventListener('message', (event) => {
    if (event.origin !== location.origin) return;
    if (workflowDialog?.open && event.source === workflowFrame?.contentWindow) {
      if (event.data?.type === 'orgforms:close') workflowDialog.close();
      if (event.data?.type === 'orgforms:saved') window.location.reload();
      return;
    }
    const editorFrame = [...document.querySelectorAll('[data-form-editor-frame]')].find((frame) => frame.contentWindow === event.source);
    if (editorFrame && event.data?.type === 'orgforms:saved') {
      sessionStorage.setItem('orgforms-restore-form-dialog', editorFrame.closest('[data-form-dialog]').id);
      window.location.reload();
    }
  });
  document.querySelectorAll('[data-form-popup-url]').forEach((card) => {
    card.addEventListener('click', (event) => {
      if (event.target.closest('a, button, input, select, textarea, label, form')) return;
      openFormWorkflow(card.dataset.formPopupUrl, card.dataset.popupTitle);
    });
  });
  document.querySelectorAll('[data-card-url]').forEach((card) => {
    card.addEventListener('click', (event) => {
      if (event.target.closest('a, button, input, select, textarea, label, form')) return;
      window.location.assign(card.dataset.cardUrl);
    });
  });
  const submissionSearch = document.querySelector('[data-submission-search]');
  if (submissionSearch) {
    const submissionCards = [...document.querySelectorAll('[data-submission-card], [data-submission-row]')];
    const noResults = document.querySelector('[data-submission-no-results]');
    submissionSearch.addEventListener('input', () => {
      const query = submissionSearch.value.trim().toLowerCase();
      let visibleCount = 0;
      submissionCards.forEach((card) => {
        const visible = card.dataset.searchText.toLowerCase().includes(query);
        card.hidden = !visible;
        if (visible) visibleCount += 1;
      });
      if (noResults) noResults.hidden = visibleCount > 0 || !query;
    });
  }
  document.querySelectorAll('[data-auto-submit]').forEach((select) => {
    select.addEventListener('change', () => select.form.requestSubmit());
    const submit = select.form.querySelector('.filter-submit');
    if (submit) submit.hidden = true;
  });
  const formSearch = document.querySelector('[data-form-search]');
  const formStatusButtons = [...document.querySelectorAll('button[data-form-status]')];
  let selectedFormStatus = '';
  if (formSearch) {
    const formCards = [...document.querySelectorAll('[data-form-card]')];
    const noResults = document.querySelector('[data-form-no-results]');
    const count = document.querySelector('[data-form-count]');
    const applyFormFilters = () => {
      const query = formSearch.value.trim().toLowerCase();
      let visibleCount = 0;
      formCards.forEach((card) => {
        const visible = card.dataset.searchText.toLowerCase().includes(query) && (!selectedFormStatus || card.dataset.formStatusValue === selectedFormStatus);
        card.hidden = !visible;
        if (visible) visibleCount += 1;
      });
      if (count) count.textContent = `${visibleCount} of ${formCards.length} forms`;
      if (noResults) noResults.hidden = visibleCount > 0 || formCards.length === 0;
    };
    formSearch.addEventListener('input', applyFormFilters);
    formStatusButtons.forEach((button) => button.addEventListener('click', () => {
      selectedFormStatus = button.dataset.formStatus;
      formStatusButtons.forEach((option) => option.setAttribute('aria-pressed', String(option === button)));
      applyFormFilters();
    }));
  }
  const peopleTabs = [...document.querySelectorAll('[data-people-tab]')];
  if (peopleTabs.length) {
    const peopleTools = document.querySelector('[data-people-tools]');
    const activatePeopleTab = (name) => {
      const selectedName = peopleTabs.some((tab) => tab.dataset.peopleTab === name) ? name : 'members';
      peopleTabs.forEach((tab) => {
        const selected = tab.dataset.peopleTab === selectedName;
        tab.setAttribute('aria-selected', String(selected));
        tab.tabIndex = selected ? 0 : -1;
      });
      document.querySelectorAll('[data-people-panel]').forEach((panel) => { panel.hidden = panel.dataset.peoplePanel !== selectedName; });
      if (peopleTools) peopleTools.hidden = selectedName !== 'members';
    };
    peopleTabs.forEach((tab) => tab.addEventListener('click', () => {
      activatePeopleTab(tab.dataset.peopleTab);
      history.replaceState(null, '', `#${tab.dataset.peopleTab}`);
    }));
    activatePeopleTab(window.location.hash.slice(1));
    window.addEventListener('hashchange', () => activatePeopleTab(window.location.hash.slice(1)));
    const search = document.querySelector('[data-people-search]');
    const roleButtons = [...document.querySelectorAll('button[data-people-role]')];
    let selectedRole = '';
    const rows = [...document.querySelectorAll('[data-people-member]')];
    const applyPeopleFilters = () => {
      const query = search.value.trim().toLowerCase();
      let count = 0;
      rows.forEach((row) => {
        row.hidden = !(row.dataset.searchText.toLowerCase().includes(query) && (!selectedRole || row.dataset.role === selectedRole));
        if (!row.hidden) count += 1;
      });
      document.querySelector('[data-people-count]').textContent = `${count} member${count === 1 ? '' : 's'}`;
      document.querySelector('[data-people-no-results]').hidden = count > 0;
    };
    search.addEventListener('input', applyPeopleFilters);
    roleButtons.forEach((button) => button.addEventListener('click', () => {
      selectedRole = button.dataset.peopleRole;
      roleButtons.forEach((option) => option.setAttribute('aria-pressed', String(option === button)));
      applyPeopleFilters();
    }));
  }
  document.addEventListener('click', (event) => {
    const workflowLink = event.target.closest('a[data-workflow-popup]');
    if (workflowLink && workflowDialog && !event.ctrlKey && !event.metaKey && !event.shiftKey && !event.altKey) {
      event.preventDefault();
      openFormWorkflow(workflowLink.href, workflowLink.dataset.popupTitle, workflowLink.closest('dialog'));
      return;
    }
    const openCreate = event.target.closest('[data-open-dialog]');
    if (openCreate) openDialog(document.getElementById(openCreate.dataset.openDialog));
    const openManage = event.target.closest('[data-open-manage]');
    if (openManage) openDialog(document.getElementById(`manage-${openManage.dataset.openManage}`));
    const openFormManage = event.target.closest('[data-open-form-manage]');
    if (openFormManage) {
      const dialog = document.getElementById(`form-manage-${openFormManage.dataset.openFormManage}`);
      if (dialog) activateFormTab(dialog, 'details');
      openDialog(dialog);
    }
    const close = event.target.closest('[data-close-dialog]');
    if (close) close.closest('dialog')?.close();
    const copyButton = event.target.closest('[data-copy-url]');
    if (copyButton) {
      const url = new URL(copyButton.dataset.copyUrl, window.location.origin).href;
      copyButton.dataset.copyLabel ||= copyButton.textContent;
      if (navigator.clipboard?.writeText) {
        navigator.clipboard.writeText(url).then(() => {
          copyButton.textContent = 'Copied';
          window.setTimeout(() => { copyButton.textContent = copyButton.dataset.copyLabel; }, 1400);
        }).catch(() => { window.prompt('Copy this form link:', url); });
      } else {
        window.prompt('Copy this form link:', url);
      }
    }
  });
  document.querySelectorAll('dialog').forEach((dialog) => {
    dialog.addEventListener('click', (event) => { if (event.target === dialog) dialog.close(); });
  });

  function activateManageTab(dialog, tabName) {
    const validTab = dialog.querySelector(`[data-manage-panel="${tabName}"]`) ? tabName : 'details';
    dialog.querySelectorAll('[data-manage-tab]').forEach((tab) => {
      const selected = tab.dataset.manageTab === validTab;
      tab.setAttribute('aria-selected', String(selected));
      tab.tabIndex = selected ? 0 : -1;
    });
    dialog.querySelectorAll('[data-manage-panel]').forEach((panel) => {
      panel.hidden = panel.dataset.managePanel !== validTab;
    });
  }
  document.querySelectorAll('[data-manage-dialog]').forEach((dialog) => {
    dialog.addEventListener('close', () => {
      const url = new URL(window.location.href);
      if (url.searchParams.get('manage') !== dialog.dataset.manageDialog) return;
      url.searchParams.delete('manage');
      url.searchParams.delete('tab');
      window.history.replaceState(window.history.state, '', url);
    });
    dialog.querySelectorAll('[data-manage-tab]').forEach((tab) => {
      tab.addEventListener('click', () => activateManageTab(dialog, tab.dataset.manageTab));
    });
    dialog.querySelectorAll('[data-organization-details-form]').forEach((form) => {
      const returnTo = form.dataset.returnTo || form.querySelector('[name="return_to"]')?.value;
      if (!['dashboard', 'organization'].includes(returnTo)) return;
      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        const button = form.querySelector('[type="submit"]');
        const feedback = form.querySelector('[data-settings-feedback]');
        const originalLabel = button?.textContent || 'Save details';
        if (button) { button.disabled = true; button.textContent = 'Saving…'; }
        if (feedback) { feedback.hidden = true; feedback.textContent = ''; }
        try {
          const response = await fetch(form.action, {
            method: 'POST',
            body: new FormData(form),
            headers: { 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json' },
          });
          const result = await response.json();
          if (!response.ok || !result.ok) {
            if (feedback) {
              feedback.textContent = result.message || 'Could not save these organization details. Check the fields and try again.';
              feedback.hidden = false;
            }
            return;
          }

          const organization = result.organization || {};
          const card = [...document.querySelectorAll('[data-organization-card]')]
            .find((item) => item.dataset.organizationCard === organization.slug);
          if (card) {
            const title = card.querySelector('.org-card-title-link');
            const description = card.querySelector('.org-card-identity > div > p');
            const category = card.querySelector('.org-card-category');
            const monogram = card.querySelector('.org-card-monogram');
            if (title) title.textContent = organization.name;
            if (description) description.textContent = organization.description;
            if (category) category.textContent = organization.category;
            if (monogram) monogram.textContent = organization.name?.trim().charAt(0).toUpperCase() || 'O';
          }
          const organizationHeading = document.querySelector('.organization-banner h1');
          const organizationDescription = document.querySelector('.organization-banner .lede');
          const settingsHeading = dialog.querySelector('.dialog-heading h2');
          if (organizationHeading) organizationHeading.textContent = organization.name;
          if (organizationDescription) organizationDescription.textContent = organization.description;
          if (settingsHeading) settingsHeading.textContent = organization.name;
          const workspaceName = document.querySelector('.workspace-picker .workspace-name');
          if (workspaceName) workspaceName.textContent = organization.name;
          const noticeSelector = returnTo === 'organization'
            ? '[data-organization-notice]'
            : '[data-dashboard-notice]';
          const notice = document.querySelector(noticeSelector)
            || document.querySelector('[data-dashboard-notice], [data-organization-notice]');
          if (notice) {
            notice.textContent = result.message || 'Organization details saved.';
            notice.dataset.kind = 'success';
            notice.hidden = false;
          }
          const url = new URL(window.location.href);
          url.searchParams.delete('manage');
          url.searchParams.delete('tab');
          window.history.replaceState(window.history.state, '', url);
          if (dialog.open) dialog.close();
        } catch (_) {
          if (feedback) {
            feedback.textContent = 'Could not save these organization details. Check your connection and try again.';
            feedback.hidden = false;
          }
        } finally {
          if (button) { button.disabled = false; button.textContent = originalLabel; }
        }
      });
    });
  });

  function activateFormTab(dialog, tabName) {
    const validTab = dialog.querySelector(`[data-form-panel="${tabName}"]`) ? tabName : 'details';
    dialog.querySelectorAll('[data-form-tab]').forEach((tab) => {
      const selected = tab.dataset.formTab === validTab;
      tab.setAttribute('aria-selected', String(selected));
      tab.tabIndex = selected ? 0 : -1;
    });
    dialog.querySelectorAll('[data-form-panel]').forEach((panel) => {
      panel.hidden = panel.dataset.formPanel !== validTab;
    });
    if (validTab === 'edit') {
      const frame = dialog.querySelector('[data-form-editor-frame]');
      if (frame && frame.src === 'about:blank') frame.src = frame.dataset.src;
    }
  }
  document.querySelectorAll('[data-form-dialog]').forEach((dialog) => {
    dialog.querySelectorAll('[data-form-tab]').forEach((tab) => {
      tab.addEventListener('click', () => activateFormTab(dialog, tab.dataset.formTab));
    });
  });
  document.querySelectorAll('[data-form-tab-jump]').forEach((button) => {
    button.addEventListener('click', () => activateFormTab(button.closest('[data-form-dialog]'), button.dataset.formTabJump));
  });
  document.querySelectorAll('[data-form-access]').forEach((form) => {
    const visibility = form.querySelector('[name="visibility"]');
    const accounts = form.querySelector('[data-access-accounts]');
    const status = form.querySelector('[data-form-access-status]');
    const syncAudience = () => { accounts.hidden = visibility.value !== 'restricted'; };
    visibility.addEventListener('change', syncAudience);
    syncAudience();
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const button = form.querySelector('[type="submit"]');
      button.disabled = true;
      status.textContent = 'Saving access settings…';
      const emails = form.querySelector('[name="access_emails"]')?.value.split(/[\s,;]+/).map((email) => email.trim()).filter(Boolean) || [];
      const groups = form.querySelector('[name="access_groups"]')?.value.split(/[\s,;]+/).map((alias) => alias.replace(/^@/, '').trim()).filter(Boolean) || [];
      try {
        const response = await fetch(form.dataset.apiUrl, {
          method: 'PATCH',
          headers: {'Content-Type': 'application/json', 'X-CSRFToken': form.querySelector('[name="csrfmiddlewaretoken"]').value},
          body: JSON.stringify({visibility: visibility.value, access_emails: emails, access_groups: groups}),
        });
        const result = await response.json();
        if (!response.ok) throw new Error(Object.values(result).flat().join(' ') || 'Could not save access settings.');
        status.textContent = 'Access settings saved.';
        const dialog = form.closest('[data-form-dialog]');
        const audienceLabel = dialog.querySelector('[data-form-audience]');
        if (audienceLabel) audienceLabel.textContent = ({public: 'Anyone with the link', organization: 'Organization members', restricted: 'Specific accounts'})[visibility.value];
      } catch (error) {
        status.textContent = error.message;
      } finally {
        button.disabled = false;
      }
    });
  });
  document.querySelectorAll('[data-form-editors]').forEach((form) => {
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const button = form.querySelector('[type="submit"]');
      const status = form.querySelector('[data-form-editors-status]');
      const editors = [...form.querySelectorAll('[name="editors"]:checked')].map((input) => Number(input.value));
      button.disabled = true;
      status.textContent = 'Saving form editors…';
      try {
        const response = await fetch(form.dataset.apiUrl, {
          method: 'PUT',
          headers: {'Content-Type': 'application/json', 'X-CSRFToken': form.querySelector('[name="csrfmiddlewaretoken"]').value},
          body: JSON.stringify({editors}),
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || 'Could not save the editor list.');
        status.textContent = result.editors.length ? `Edit access saved for ${result.editors.join(', ')}.` : 'Edit access is limited to organization admins and managers.';
      } catch (error) {
        status.textContent = error.message;
      } finally {
        button.disabled = false;
      }
    });
  });
  document.querySelectorAll('[data-form-transfer]').forEach((form) => {
    const organization = form.querySelector('[data-transfer-org]');
    const owner = form.querySelector('[data-transfer-owner]');
    const status = form.querySelector('[data-form-transfer-status]');
    const syncOwners = () => {
      [...owner.options].forEach((option) => { option.hidden = option.dataset.organization !== organization.value; option.disabled = option.hidden; });
      if (owner.selectedOptions[0]?.disabled) owner.value = [...owner.options].find((option) => !option.disabled)?.value || '';
    };
    organization.addEventListener('change', syncOwners);
    syncOwners();
    form.addEventListener('submit', async (event) => {
      event.preventDefault();
      const button = form.querySelector('[type="submit"]');
      button.disabled = true;
      status.textContent = 'Updating form ownership…';
      const currentOrganization = form.closest('[data-form-dialog]').dataset.formOrganization;
      try {
        const response = await fetch(form.dataset.apiUrl, {
          method: 'POST',
          headers: {'Content-Type': 'application/json', 'X-CSRFToken': form.querySelector('[name="csrfmiddlewaretoken"]').value},
          body: JSON.stringify({organization: organization.value, owner_membership: owner.value}),
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || 'Could not update ownership.');
        if (organization.value !== currentOrganization) {
          status.textContent = `Form and response history moved to ${result.organization}. Opening that organization…`;
          window.setTimeout(() => { window.location.assign(`/org/${organization.value}/`); }, 500);
        } else {
          const ownerLabel = form.closest('[data-form-dialog]').querySelector('[data-form-owner]');
          if (ownerLabel) ownerLabel.textContent = result.owner;
          status.textContent = `Form owner updated to ${result.owner}.`;
        }
      } catch (error) {
        status.textContent = error.message;
      } finally {
        button.disabled = false;
      }
    });
  });
  document.querySelectorAll('[role="tablist"]').forEach((tablist) => {
    tablist.addEventListener('keydown', (event) => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      const tabs = [...tablist.querySelectorAll('[role="tab"]')];
      const index = tabs.indexOf(document.activeElement);
      if (index < 0) return;
      event.preventDefault();
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
      tabs[next].click();
      tabs[next].focus();
    });
  });

  const previewTabs = document.querySelectorAll('[data-preview-tab]');
  previewTabs.forEach((tab) => {
    tab.addEventListener('click', () => {
      const selectedView = tab.dataset.previewTab;
      previewTabs.forEach((item) => {
        const selected = item.dataset.previewTab === selectedView;
        item.classList.toggle('active', selected);
        item.setAttribute('aria-selected', String(selected));
      });
      document.querySelectorAll('[data-preview-panel]').forEach((panel) => {
        panel.hidden = panel.dataset.previewPanel !== selectedView;
      });
    });
  });

  const query = new URLSearchParams(window.location.search);
  const manageSlug = query.get('manage');
  if (manageSlug) {
    const dialog = document.getElementById(`manage-${manageSlug}`);
    if (dialog) {
      activateManageTab(dialog, query.get('tab') || 'details');
      openDialog(dialog);
    }
  } else {
    const createDialog = document.querySelector('#create-workspace-dialog[data-open-on-load="true"]');
    if (createDialog) openDialog(createDialog);
  }
})();
