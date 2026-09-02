/* 工坊 Copilot 壳（v1.18.0）
 *
 * 负责 docked 布局、overlay 降级、拖拽调宽、applyOperations，以及与 React Island 的 CustomEvent 桥。
 * 对话 UI 在 frontend/copilot/，构建产物 static/copilot/copilot.js。
 *
 * PromptRequest / PromptSuggestion / PromptOperation / Diagnostic / ExecutionStage
 * 契约与 v1.16.0 相同；customInstruction / operations / diagnostics / contexts / history 仍由 Island 使用。
 */
(function () {
  'use strict';

  var OVERLAY_MQ = '(max-width: 1199px)';
  var COPILOT_MIN_PX = 340;
  var COPILOT_MAX_PX = 520;
  var COPILOT_DEFAULT_PX = 380;
  var WORKSPACE_MIN_PX = 480;
  var WIDTH_KEY = 'wardrobe_ws_copilot_width';
  var EVT_CONTEXT = 'workshop:context-change';
  var EVT_APPLY = 'workshop:apply-prompt-operations';
  var EVT_HIGHLIGHT = 'workshop:highlight-tag';
  var EVT_TOAST = 'workshop:toast';

  function splitSegments(text) {
    if (!text) return [];
    return text.split(',').map(function (s) { return s.trim(); }).filter(Boolean);
  }

  // 按逗号整段匹配应用操作：split → trim → 精确匹配 → 重建；绝不对 (x:0.8) 权重段内部做字符串裁剪
  function applyOperations(text, operations) {
    var segments = splitSegments(text);
    var applied = [];
    var skipped = [];
    operations.forEach(function (op) {
      if (op.kind === 'add') {
        if (segments.indexOf(op.tag) === -1) {
          segments.push(op.tag);
          applied.push(op);
        } else {
          skipped.push(op);
        }
      } else if (op.kind === 'remove') {
        var ri = segments.indexOf(op.tag);
        if (ri !== -1) {
          segments.splice(ri, 1);
          applied.push(op);
        } else {
          skipped.push(op);
        }
      } else if (op.kind === 'replace') {
        var pi = segments.indexOf(op.from);
        if (pi !== -1) {
          segments[pi] = op.to;
          applied.push(op);
        } else {
          skipped.push(op);
        }
      }
    });
    return { text: segments.join(', '), applied: applied, skipped: skipped };
  }

  var els = null;
  var onEsc = null;
  var overlayQuery = null;
  var onOverlayChange = null;
  var onWinResize = null;
  var dragging = false;
  var dragStartX = 0;
  var dragStartWidth = 0;
  var islandMounted = false;

  function isOverlayMode() {
    return !!(overlayQuery && overlayQuery.matches);
  }

  function isOpen() {
    return !!(els && els.workbench && els.workbench.classList.contains('is-copilot-open'));
  }

  function currentWidth() {
    var raw = getComputedStyle(document.documentElement).getPropertyValue('--copilot-width');
    var n = parseInt(raw, 10);
    return isFinite(n) && n > 0 ? n : COPILOT_DEFAULT_PX;
  }

  function maxWidthNow() {
    if (!els || !els.workbench || isOverlayMode()) return COPILOT_MAX_PX;
    var recipe = els.workbench.querySelector('.ws-recipe-panel');
    var benchW = els.workbench.getBoundingClientRect().width;
    var recipeW = recipe ? recipe.getBoundingClientRect().width : 330;
    var available = benchW - recipeW - 16;
    return Math.max(COPILOT_MIN_PX, Math.min(COPILOT_MAX_PX, available - WORKSPACE_MIN_PX));
  }

  function setCopilotWidth(px, persist) {
    var max = maxWidthNow();
    var clamped = Math.max(COPILOT_MIN_PX, Math.min(max, px));
    document.documentElement.style.setProperty('--copilot-width', clamped + 'px');
    if (persist !== false) {
      try { localStorage.setItem(WIDTH_KEY, String(clamped)); } catch (err) { /* 私密模式忽略 */ }
    }
    return clamped;
  }

  function applyMode() {
    if (!els) return;
    var overlay = isOverlayMode();
    var open = isOpen();
    els.drawer.classList.toggle('open', open);
    els.drawer.setAttribute('aria-hidden', open ? 'false' : 'true');
    if (els.openBtn) els.openBtn.setAttribute('aria-pressed', open ? 'true' : 'false');
    if (els.resizer) els.resizer.hidden = overlay || !open;
    if (els.mask) {
      if (overlay && open) {
        els.mask.hidden = false;
        els.mask.classList.add('open');
      } else {
        els.mask.classList.remove('open');
        els.mask.hidden = true;
      }
    }
    if (open && !overlay) setCopilotWidth(currentWidth(), false);
  }

  function emitContext() {
    if (!window.WorkshopAPI) return;
    var payload = window.WorkshopAPI.getPromptPayload();
    var detail = {
      positivePrompt: payload.positive,
      negativePrompt: payload.negative,
      recipe: payload.recipe,
    };
    var target = els && els.island ? els.island : window;
    target.dispatchEvent(new CustomEvent(EVT_CONTEXT, { bubbles: true, detail: detail }));
  }

  function mountIsland() {
    if (islandMounted || !els || !els.island) return;
    if (window.WorkshopCopilotIsland && window.WorkshopCopilotIsland.mount) {
      window.WorkshopCopilotIsland.mount(els.island);
      islandMounted = true;
    }
  }

  function unmountIsland() {
    if (!islandMounted) return;
    if (window.WorkshopCopilotIsland && window.WorkshopCopilotIsland.unmount) {
      window.WorkshopCopilotIsland.unmount();
    }
    islandMounted = false;
  }

  function onApply(e) {
    var ops = e.detail && e.detail.operations;
    if (!ops || !ops.length || !window.WorkshopAPI) return;
    var payload = window.WorkshopAPI.getPromptPayload();
    var appliedCount = 0;
    ['positive', 'negative'].forEach(function (target) {
      var targetOps = ops.filter(function (op) { return (op.target || 'positive') === target; });
      if (!targetOps.length) return;
      var result = applyOperations(target === 'positive' ? payload.positive : payload.negative, targetOps);
      appliedCount += result.applied.length;
      window.WorkshopAPI.applyEdited(target, result.text);
    });
    window.WorkshopAPI.toast(appliedCount ? '已应用 ' + appliedCount + ' 项修改' : '操作均已存在或未命中，无需变更');
  }

  function onHighlight(e) {
    var d = e.detail || {};
    if (d.tag && window.WorkshopAPI) window.WorkshopAPI.highlightTag(d.target || 'positive', d.tag);
  }

  function onToast(e) {
    var msg = e.detail && e.detail.message;
    if (msg && window.WorkshopAPI) window.WorkshopAPI.toast(msg);
  }

  function init(refs) {
    destroy();
    els = {
      workbench: refs.workbench,
      drawer: refs.drawer,
      mask: refs.mask,
      openBtn: refs.openBtn,
      closeBtn: refs.closeBtn,
      resizer: refs.resizer,
      island: refs.island || document.getElementById('workshop-copilot-root'),
    };

    overlayQuery = window.matchMedia(OVERLAY_MQ);
    onOverlayChange = function () { applyMode(); };
    if (overlayQuery.addEventListener) overlayQuery.addEventListener('change', onOverlayChange);
    else overlayQuery.addListener(onOverlayChange);

    var saved = parseInt((function () {
      try { return localStorage.getItem(WIDTH_KEY); } catch (err) { return null; }
    })(), 10);
    setCopilotWidth(isFinite(saved) && saved > 0 ? saved : COPILOT_DEFAULT_PX, false);

    els.openBtn.addEventListener('click', toggleDrawer);
    els.closeBtn.addEventListener('click', closeDrawer);
    if (els.mask) els.mask.addEventListener('click', function () {
      if (isOverlayMode()) closeDrawer();
    });
    onEsc = function (e) {
      if (e.key === 'Escape' && isOverlayMode() && isOpen()) closeDrawer();
    };
    document.addEventListener('keydown', onEsc);

    if (els.resizer) els.resizer.addEventListener('pointerdown', onResizePointerDown);
    onWinResize = function () {
      if (isOpen() && !isOverlayMode()) setCopilotWidth(currentWidth(), false);
    };
    window.addEventListener('resize', onWinResize);

    document.addEventListener(EVT_APPLY, onApply);
    document.addEventListener(EVT_HIGHLIGHT, onHighlight);
    document.addEventListener(EVT_TOAST, onToast);

    applyMode();
  }

  function destroy() {
    if (onEsc) { document.removeEventListener('keydown', onEsc); onEsc = null; }
    if (overlayQuery && onOverlayChange) {
      if (overlayQuery.removeEventListener) overlayQuery.removeEventListener('change', onOverlayChange);
      else overlayQuery.removeListener(onOverlayChange);
    }
    onOverlayChange = null;
    overlayQuery = null;
    if (onWinResize) { window.removeEventListener('resize', onWinResize); onWinResize = null; }
    stopResizeDrag();
    document.removeEventListener(EVT_APPLY, onApply);
    document.removeEventListener(EVT_HIGHLIGHT, onHighlight);
    document.removeEventListener(EVT_TOAST, onToast);
    unmountIsland();
    if (els) {
      els.drawer.classList.remove('open');
      els.drawer.setAttribute('aria-hidden', 'true');
      if (els.workbench) els.workbench.classList.remove('is-copilot-open', 'is-resizing');
      if (els.mask) { els.mask.classList.remove('open'); els.mask.hidden = true; }
      if (els.openBtn) els.openBtn.setAttribute('aria-pressed', 'false');
    }
    els = null;
  }

  function toggleDrawer() {
    if (isOpen()) closeDrawer();
    else openDrawer();
  }

  function openDrawer() {
    els.workbench.classList.add('is-copilot-open');
    applyMode();
    mountIsland();
    emitContext();
  }

  function closeDrawer() {
    els.workbench.classList.remove('is-copilot-open');
    applyMode();
  }

  function onResizePointerDown(e) {
    if (!isOpen() || isOverlayMode()) return;
    dragging = true;
    dragStartX = e.clientX;
    dragStartWidth = currentWidth();
    els.workbench.classList.add('is-resizing');
    document.body.style.userSelect = 'none';
    document.addEventListener('pointermove', onResizePointerMove);
    document.addEventListener('pointerup', onResizePointerUp);
    e.preventDefault();
  }

  function onResizePointerMove(e) {
    if (!dragging) return;
    setCopilotWidth(dragStartWidth + (dragStartX - e.clientX), false);
  }

  function onResizePointerUp() {
    if (!dragging) return;
    stopResizeDrag();
    setCopilotWidth(currentWidth(), true);
  }

  function stopResizeDrag() {
    dragging = false;
    document.removeEventListener('pointermove', onResizePointerMove);
    document.removeEventListener('pointerup', onResizePointerUp);
    document.body.style.userSelect = '';
    if (els && els.workbench) els.workbench.classList.remove('is-resizing');
  }

  window.WorkshopCopilot = {
    init: init,
    destroy: destroy,
    applyOperations: applyOperations,
    emitContext: emitContext,
  };
})();
