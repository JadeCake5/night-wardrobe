(function (global) {
  var SETTINGS_URL = "/api/copilot/settings";
  var MODELS_URL = "/api/copilot/models";
  var TEST_URL = "/api/copilot/test";
  var state = { enabled: true, hasKey: false, loading: false };
  var busyCount = 0;

  function readUrls() {
    var root = document.querySelector("[data-copilot-settings]");
    if (!root) return;
    SETTINGS_URL = root.getAttribute("data-settings-url") || SETTINGS_URL;
    MODELS_URL = root.getAttribute("data-models-url") || MODELS_URL;
    TEST_URL = root.getAttribute("data-test-url") || TEST_URL;
  }

  function $(id) {
    return document.getElementById(id);
  }

  function notify(message, type) {
    if (global.WorkshopAPI && typeof global.WorkshopAPI.toast === "function") {
      global.WorkshopAPI.toast(message, type);
      return;
    }
    if (typeof global.toast === "function") global.toast(message, type);
  }

  function setError(text) {
    var el = $("wsLlmSettingsError");
    if (!el) return;
    if (!text) {
      el.hidden = true;
      el.textContent = "";
      return;
    }
    el.hidden = false;
    el.textContent = text;
  }

  function setBusy(busy) {
    // 保存与测试连接/拉模型会嵌套 busy：用计数避免内层 finally 提前解锁按钮
    if (busy) busyCount += 1;
    else if (busyCount > 0) busyCount -= 1;
    var locked = busyCount > 0;
    state.loading = locked;
    ["wsLlmSaveBtn", "wsLlmTestBtn", "wsLlmFetchModelsBtn", "wsLlmEnabledBtn"].forEach(function (id) {
      var el = $(id);
      if (el) el.disabled = locked;
    });
  }

  function renderStatus() {
    var box = $("wsLlmSettingsStatus");
    var label = $("wsLlmStatusLabel");
    var hint = $("wsLlmStatusHint");
    if (!box || !label || !hint) return;
    var baseUrl = ($("wsLlmBaseUrl") && $("wsLlmBaseUrl").value.trim()) || "";
    var model = ($("wsLlmModel") && $("wsLlmModel").value.trim()) || "";
    var typedKey = ($("wsLlmApiKey") && $("wsLlmApiKey").value.trim()) || "";
    var hasKey = state.hasKey || !!typedKey;
    var ready = state.enabled && hasKey && baseUrl && model;
    var mode = !state.enabled ? "off" : ready ? "ready" : "missing";
    box.dataset.state = mode;
    if (mode === "off") {
      label.textContent = "已关闭";
      hint.textContent = "助手已停用，连接配置仍会保留";
    } else if (mode === "ready") {
      label.textContent = "已配置";
      hint.textContent = model ? ("当前模型 " + model) : "可以测试连接";
    } else {
      label.textContent = hasKey ? "未完成" : "未配置";
      hint.textContent = "请填写 Base URL、API Key 和模型后保存";
    }
  }

  function setEnabled(on) {
    state.enabled = !!on;
    var btn = $("wsLlmEnabledBtn");
    if (btn) btn.setAttribute("aria-checked", state.enabled ? "true" : "false");
    renderStatus();
  }

  function applySettings(data) {
    data = data || {};
    state.hasKey = !!data.has_key;
    setEnabled(data.enabled !== false);
    if ($("wsLlmBaseUrl")) $("wsLlmBaseUrl").value = data.base_url || "";
    if ($("wsLlmModel")) $("wsLlmModel").value = data.model || "";
    if ($("wsLlmSystemPrompt")) $("wsLlmSystemPrompt").value = data.default_system_prompt || "";
    if ($("wsLlmApiKey")) {
      $("wsLlmApiKey").value = "";
      $("wsLlmApiKey").placeholder = state.hasKey ? "已保存，留空则保留原密钥" : "未配置";
    }
    renderStatus();
  }

  function currentPayload(includeKey) {
    var payload = {
      enabled: state.enabled,
      base_url: ($("wsLlmBaseUrl") && $("wsLlmBaseUrl").value) || "",
      model: ($("wsLlmModel") && $("wsLlmModel").value) || "",
      default_system_prompt: ($("wsLlmSystemPrompt") && $("wsLlmSystemPrompt").value) || "",
    };
    var key = ($("wsLlmApiKey") && $("wsLlmApiKey").value) || "";
    if (includeKey && key.trim()) payload.api_key = key.trim();
    return payload;
  }

  function readJson(response) {
    return response.json().catch(function () { return {}; }).then(function (data) {
      if (!response.ok) {
        var detail = typeof data.error === "string" ? data.error : (data.error && data.error.message);
        throw new Error(detail || ("请求失败: " + response.status));
      }
      return data;
    });
  }

  function loadSettings() {
    setError("");
    return fetch(SETTINGS_URL, { headers: { Accept: "application/json" } })
      .then(readJson)
      .then(applySettings)
      .catch(function (err) {
        setError(err.message || "读取设置失败");
        notify(err.message || "读取设置失败", "error");
      });
  }

  function openSettings() {
    var dialog = $("wsLlmSettingsDialog");
    if (!dialog) return;
    if (typeof dialog.showModal === "function" && !dialog.open) dialog.showModal();
    loadSettings().then(function () {
      if ($("wsLlmBaseUrl")) $("wsLlmBaseUrl").focus();
    });
  }

  function saveSettings(showToast) {
    setBusy(true);
    setError("");
    return fetch(SETTINGS_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(currentPayload(true)),
    })
      .then(readJson)
      .then(function (data) {
        applySettings(data.settings || data);
        if ($("wsLlmApiKey")) $("wsLlmApiKey").value = "";
        if (showToast !== false) notify("助手设置已保存", "success");
        return data;
      })
      .catch(function (err) {
        setError(err.message || "保存失败");
        notify(err.message || "保存失败", "error");
        throw err;
      })
      .finally(function () { setBusy(false); });
  }

  function testConnection() {
    setBusy(true);
    setError("");
    return saveSettings(false)
      .then(function () {
        return fetch(TEST_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: "{}",
        }).then(readJson);
      })
      .then(function () {
        notify("API 连接成功", "success");
      })
      .catch(function (err) {
        setError(err.message || "连接失败");
        notify("连接失败: " + (err.message || "未知错误"), "error");
      })
      .finally(function () { setBusy(false); });
  }

  function renderModels(models) {
    var list = $("wsLlmModelList");
    if (!list) return;
    list.innerHTML = "";
    if (!models || !models.length) {
      list.hidden = true;
      return;
    }
    var current = ($("wsLlmModel") && $("wsLlmModel").value) || "";
    models.forEach(function (name) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = name;
      if (name === current) btn.className = "is-active";
      btn.onclick = function () {
        if ($("wsLlmModel")) $("wsLlmModel").value = name;
        Array.prototype.forEach.call(list.querySelectorAll("button"), function (item) {
          item.classList.toggle("is-active", item.textContent === name);
        });
        renderStatus();
      };
      list.appendChild(btn);
    });
    list.hidden = false;
  }

  function fetchModels() {
    setBusy(true);
    setError("");
    return saveSettings(false)
      .then(function () {
        return fetch(MODELS_URL, { headers: { Accept: "application/json" } }).then(readJson);
      })
      .then(function (data) {
        var models = data.models || [];
        renderModels(models);
        if (models.length) notify("获取到 " + models.length + " 个模型", "success");
        else notify("未返回模型列表", "warning");
      })
      .catch(function (err) {
        setError(err.message || "获取模型失败");
        notify(err.message || "获取模型失败", "error");
      })
      .finally(function () { setBusy(false); });
  }

  function bind() {
    readUrls();
    var openers = ["wsLlmSettingsBtn", "wsCopilotSettingsBtn"];
    openers.forEach(function (id) {
      var el = $(id);
      if (el) el.onclick = openSettings;
    });
    var enabledBtn = $("wsLlmEnabledBtn");
    if (enabledBtn) {
      enabledBtn.onclick = function () { setEnabled(!state.enabled); };
    }
    var saveBtn = $("wsLlmSaveBtn");
    if (saveBtn) saveBtn.onclick = function () { saveSettings(true); };
    var testBtn = $("wsLlmTestBtn");
    if (testBtn) testBtn.onclick = testConnection;
    var fetchBtn = $("wsLlmFetchModelsBtn");
    if (fetchBtn) fetchBtn.onclick = fetchModels;
    ["wsLlmBaseUrl", "wsLlmModel", "wsLlmApiKey"].forEach(function (id) {
      var el = $(id);
      if (el) el.oninput = renderStatus;
    });
  }

  global.CopilotSettings = {
    bind: bind,
    open: openSettings,
    load: loadSettings,
  };
})(window);
