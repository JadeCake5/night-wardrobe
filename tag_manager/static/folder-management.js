(() => {
  if (window.__folderManagementBound) return;
  window.__folderManagementBound = true;

  const getManager = () => document.querySelector('main [data-folder-manager]');
  const closeMenus = except => {
    document.querySelectorAll('[data-folder-card-menu]').forEach(menu => {
      if (menu !== except) menu.hidden = true;
    });
    document.querySelectorAll('[data-folder-menu-toggle]').forEach(button => {
      const menu = button.closest('[data-folder-card]')?.querySelector('[data-folder-card-menu]');
      button.setAttribute('aria-expanded', String(Boolean(menu && !menu.hidden)));
    });
  };
  const count = (button, key) => Number.parseInt(button.dataset[key] || '0', 10) || 0;

  function readOptions(manager) {
    try {
      return JSON.parse(manager.querySelector('[data-folder-options]').textContent);
    } catch (error) {
      return [];
    }
  }

  function updateMovePreview(dialog) {
    const source = dialog.querySelector('[data-folder-source]').value;
    const name = source.split('/').pop() || source;
    const destination = dialog.querySelector('[data-folder-destination]').value;
    const target = destination ? destination + '/' + name : name;
    dialog.querySelector('[data-folder-move-preview]').textContent = `移动后位置：${target}`;
  }

  function openMove(button) {
    const manager = getManager();
    if (!manager) return;
    const dialog = manager.querySelector('[data-folder-move-dialog]');
    const source = button.dataset.folderPath || '';
    const name = button.dataset.folderName || source.split('/').pop() || '';
    const parent = source.includes('/') ? source.slice(0, source.lastIndexOf('/')) : '';
    const select = dialog.querySelector('[data-folder-destination]');

    dialog.querySelector('[data-folder-source]').value = source;
    dialog.querySelector('[data-folder-move-name]').textContent = name;
    select.replaceChildren();
    readOptions(manager)
      .filter(option => option.path !== source && !option.path.startsWith(source + '/') && option.path !== parent)
      .forEach(option => {
        const element = document.createElement('option');
        element.value = option.path;
        element.textContent = option.label;
        select.append(element);
      });

    const confirm = dialog.querySelector('[data-folder-move-confirm]');
    confirm.disabled = select.options.length === 0;
    if (select.options.length === 0) {
      const option = document.createElement('option');
      option.textContent = '没有可用的目标文件夹';
      option.value = '';
      select.append(option);
    }
    updateMovePreview(dialog);
    closeMenus();
    dialog.showModal();
  }

  function openDelete(button) {
    const manager = getManager();
    if (!manager) return;
    const dialog = manager.querySelector('[data-folder-delete-dialog]');
    const folderCount = count(button, 'folderCount');
    const trackedCount = count(button, 'folderTrackedCount');
    const otherCount = count(button, 'folderOtherCount');
    const nonEmpty = folderCount + trackedCount + otherCount > 0;
    const recursive = dialog.querySelector('[data-folder-recursive]');

    dialog.querySelector('[data-folder-delete-path]').value = button.dataset.folderPath || '';
    dialog.querySelector('[data-folder-delete-name]').textContent = button.dataset.folderName || '';
    dialog.querySelector('[data-folder-count]').textContent = String(folderCount);
    dialog.querySelector('[data-folder-tracked-count]').textContent = String(trackedCount);
    dialog.querySelector('[data-folder-other-count]').textContent = String(otherCount);
    dialog.querySelector('[data-folder-recursive-wrap]').hidden = !nonEmpty;
    recursive.checked = false;
    recursive.disabled = !nonEmpty;
    dialog.querySelector('[data-folder-delete-confirm]').disabled = nonEmpty;
    closeMenus();
    dialog.showModal();
  }

  const closePops = () => {
    document.querySelectorAll('.icon-pop').forEach(pop => { pop.hidden = true; });
  };

  document.addEventListener('click', event => {
    const popToggle = event.target.closest('[data-pop-toggle]');
    if (popToggle) {
      const pop = document.getElementById(popToggle.dataset.popToggle);
      const willOpen = pop && pop.hidden;
      closePops();
      if (pop && willOpen) {
        pop.hidden = false;
        const input = pop.querySelector('input[name="name"]');
        if (input) input.focus();
      }
      return;
    }

    const toggle = event.target.closest('[data-folder-menu-toggle]');
    if (toggle) {
      const menu = toggle.closest('[data-folder-card]')?.querySelector('[data-folder-card-menu]');
      if (!menu) return;
      const opening = menu.hidden;
      closeMenus(menu);
      menu.hidden = !opening;
      toggle.setAttribute('aria-expanded', String(opening));
      return;
    }

    const move = event.target.closest('[data-folder-move]');
    if (move) {
      openMove(move);
      return;
    }

    const remove = event.target.closest('[data-folder-delete]');
    if (remove) {
      openDelete(remove);
      return;
    }

    const close = event.target.closest('[data-folder-dialog-close]');
    if (close) {
      close.closest('dialog')?.close();
      return;
    }

    if (!event.target.closest('[data-folder-card-menu]')) closeMenus();
    if (!event.target.closest('.icon-pop-wrap')) closePops();
  });

  document.addEventListener('change', event => {
    if (event.target.matches('[data-folder-destination]')) {
      updateMovePreview(event.target.closest('dialog'));
    }
    if (event.target.matches('[data-folder-recursive]')) {
      event.target.closest('dialog').querySelector('[data-folder-delete-confirm]').disabled = !event.target.checked;
    }
  });
})();
