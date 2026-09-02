(() => {
  if (window.__galleryImagesBound) return;
  window.__galleryImagesBound = true;

  const IDS_MIME = 'application/x-gallery-ids';
  const getManager = () => document.querySelector('main [data-gallery-image-manager]');
  const getFolderManager = () => document.querySelector('main [data-folder-manager]');

  function readFolderOptions() {
    const manager = getFolderManager();
    if (!manager) return [];
    try {
      return JSON.parse(manager.querySelector('[data-folder-options]').textContent);
    } catch (error) {
      return [];
    }
  }

  const closeImageMenus = except => {
    document.querySelectorAll('[data-image-card-menu]').forEach(menu => {
      if (menu !== except) menu.hidden = true;
    });
    document.querySelectorAll('[data-image-menu-toggle]').forEach(button => {
      const menu = button.closest('[data-image-card]')?.querySelector('[data-image-card-menu]');
      button.setAttribute('aria-expanded', String(Boolean(menu && !menu.hidden)));
    });
  };

  const selectedIds = () =>
    Array.from(document.querySelectorAll('[data-image-select]:checked')).map(input => Number(input.value));

  function cardName(id) {
    const card = document.querySelector(`[data-image-card][data-image-id="${id}"]`);
    return (card && card.dataset.imageName) || String(id);
  }

  function updateSelectionBar() {
    const bar = document.querySelector('[data-image-selection-bar]');
    if (!bar) return;
    const count = selectedIds().length;
    bar.hidden = count === 0;
    bar.querySelector('[data-image-selected-count]').textContent = String(count);
  }

  function fillIds(container, ids) {
    container.replaceChildren(...ids.map(id => {
      const input = document.createElement('input');
      input.type = 'hidden';
      input.name = 'ids';
      input.value = String(id);
      return input;
    }));
  }

  function updateMovePreview(dialog) {
    const destination = dialog.querySelector('[data-image-move-destination]').value;
    dialog.querySelector('[data-image-move-preview]').textContent =
      destination ? `移动后位置：${destination}/…` : '移动后位置：根目录';
  }

  function openMoveDialog(ids) {
    const manager = getManager();
    if (!manager || !ids.length) return;
    const dialog = manager.querySelector('[data-image-move-dialog]');
    fillIds(dialog.querySelector('[data-image-move-ids]'), ids);
    dialog.querySelector('[data-image-move-name]').textContent =
      ids.length === 1 ? cardName(ids[0]) : `${ids.length} 张图片`;
    const select = dialog.querySelector('[data-image-move-destination]');
    select.replaceChildren();
    readFolderOptions().forEach(option => {
      const element = document.createElement('option');
      element.value = option.path;
      element.textContent = option.label;
      select.append(element);
    });
    updateMovePreview(dialog);
    closeImageMenus();
    dialog.showModal();
  }

  function openDeleteDialog(ids) {
    const manager = getManager();
    if (!manager || !ids.length) return;
    const dialog = manager.querySelector('[data-image-delete-dialog]');
    fillIds(dialog.querySelector('[data-image-delete-ids]'), ids);
    dialog.querySelector('[data-image-delete-count]').textContent = String(ids.length);
    const names = ids.map(cardName);
    dialog.querySelector('[data-image-delete-names]').textContent =
      names.slice(0, 8).join('、') + (names.length > 8 ? ` 等 ${names.length} 张` : '');
    closeImageMenus();
    dialog.showModal();
  }

  function postImageAction(action, ids, destination) {
    const manager = getManager();
    const form = document.createElement('form');
    form.method = 'POST';
    form.action = action;
    const current = document.createElement('input');
    current.type = 'hidden';
    current.name = 'current';
    current.value = manager ? manager.dataset.currentFolder || '' : '';
    form.append(current);
    ids.forEach(id => {
      const input = document.createElement('input');
      input.type = 'hidden';
      input.name = 'ids';
      input.value = String(id);
      form.append(input);
    });
    if (destination !== undefined) {
      const target = document.createElement('input');
      target.type = 'hidden';
      target.name = 'destination';
      target.value = destination;
      form.append(target);
    }
    document.body.append(form);
    form.submit();
  }

  document.addEventListener('click', event => {
    const toggle = event.target.closest('[data-image-menu-toggle]');
    if (toggle) {
      const menu = toggle.closest('[data-image-card]')?.querySelector('[data-image-card-menu]');
      if (!menu) return;
      const opening = menu.hidden;
      closeImageMenus(menu);
      menu.hidden = !opening;
      toggle.setAttribute('aria-expanded', String(opening));
      return;
    }
    const move = event.target.closest('[data-image-move]');
    if (move) {
      const card = move.closest('[data-image-card]');
      if (card) openMoveDialog([Number(card.dataset.imageId)]);
      return;
    }
    const remove = event.target.closest('[data-image-delete]');
    if (remove) {
      const card = remove.closest('[data-image-card]');
      if (card) openDeleteDialog([Number(card.dataset.imageId)]);
      return;
    }
    if (event.target.closest('[data-image-move-selected]')) {
      openMoveDialog(selectedIds());
      return;
    }
    if (event.target.closest('[data-image-delete-selected]')) {
      openDeleteDialog(selectedIds());
      return;
    }
    if (event.target.closest('[data-image-select-all]')) {
      document.querySelectorAll('[data-image-select]').forEach(input => { input.checked = true; });
      updateSelectionBar();
      return;
    }
    if (event.target.closest('[data-image-select-none]')) {
      document.querySelectorAll('[data-image-select]').forEach(input => { input.checked = false; });
      updateSelectionBar();
      return;
    }
    if (!event.target.closest('[data-image-card-menu]')) closeImageMenus();
  });

  document.addEventListener('change', event => {
    if (event.target.matches('[data-image-select]')) updateSelectionBar();
    if (event.target.matches('[data-image-move-destination]')) {
      updateMovePreview(event.target.closest('dialog'));
    }
  });

  // ─── 拖拽移动到文件夹 / 面包屑 ───
  let dropTarget = null;
  const clearDropTarget = () => {
    if (dropTarget) dropTarget.classList.remove('drop-target');
    dropTarget = null;
  };

  document.addEventListener('dragstart', event => {
    const card = event.target.closest?.('[data-image-card]');
    if (!card) return;
    const id = Number(card.dataset.imageId);
    const selected = selectedIds();
    const ids = selected.includes(id) ? selected : [id];
    event.dataTransfer.setData(IDS_MIME, JSON.stringify(ids));
    event.dataTransfer.effectAllowed = 'move';
    card.classList.add('dragging');
  });

  document.addEventListener('dragend', event => {
    event.target.closest?.('[data-image-card]')?.classList.remove('dragging');
    clearDropTarget();
  });

  document.addEventListener('dragover', event => {
    const target = event.target.closest?.('[data-drop-folder]');
    if (!target) return;
    if (!Array.from(event.dataTransfer.types).includes(IDS_MIME)) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
    if (dropTarget !== target) {
      clearDropTarget();
      dropTarget = target;
      target.classList.add('drop-target');
    }
  });

  document.addEventListener('dragleave', event => {
    if (dropTarget && !dropTarget.contains(event.relatedTarget)) clearDropTarget();
  });

  document.addEventListener('drop', event => {
    const target = event.target.closest?.('[data-drop-folder]');
    if (!target) return;
    const raw = event.dataTransfer.getData(IDS_MIME);
    if (!raw) return;
    event.preventDefault();
    clearDropTarget();
    let ids = [];
    try {
      ids = JSON.parse(raw);
    } catch (error) {
      return;
    }
    if (ids.length) postImageAction('/gallery/images/move', ids, target.dataset.dropFolder || '');
  });
})();
