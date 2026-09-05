(function (global) {
  var SETTINGS_URL = "/api/copilot/settings";
  var MODELS_URL = "/api/copilot/models";
  var TEST_URL = "/api/copilot/test";

  // 服务商预设：对齐抽卡界 static/gacha/index.html 的 API_PROVIDERS
  var API_PROVIDERS = {
    siliconflow: { id: "siliconflow", name: "硅基流动", defaultBaseUrl: "https://api.siliconflow.cn/v1", defaultModel: "Qwen/Qwen2.5-7B-Instruct" },
    deepseek: { id: "deepseek", name: "DeepSeek", defaultBaseUrl: "https://api.deepseek.com/v1", defaultModel: "deepseek-chat" },
    openai: { id: "openai", name: "OpenAI 兼容", defaultBaseUrl: "https://api.openai.com/v1", defaultModel: "gpt-4o-mini" },
  };
  var DEFAULT_TIMEOUT = 60000;
  var DEFAULT_RETRIES = 3;

  // 按服务商分别记忆的 localStorage 键：风格对齐抽卡 sd_api_base_<provider>，用 copilot 前缀避免冲突
  var LS_PROVIDER = "copilot_api_provider";
  var LS_KEYS = "copilot_api_keys";
  function lsBaseKey(provider) { return "copilot_api_base_" + provider; }
  function lsModelKey(provider) { return "copilot_api_model_" + provider; }

  var state = { enabled: true, hasKey: false, loading: false, connected: false, provider: "openai" };
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

  function readApiKeys() {
    try {
      var saved = global.localStorage && localStorage.getItem(LS_KEYS);
      var parsed = saved ? JSON.parse(saved) : {};
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch (e) {
      return {};
    }
  }

  function writeApiKeys(keys) {
    try { localStorage.setItem(LS_KEYS, JSON.stringify(keys)); } catch (e) {}
  }

  // 按服务端 base_url 反推服务商，匹配不到时回退到 OpenAI 兼容
  function inferProvider(baseUrl) {
    var url = (baseUrl || "").trim();
    var ids = Object.keys(API_PROVIDERS);
    for (var i = 0; i < ids.length; i++) {
      if (url && url.indexOf(API_PROVIDERS[ids[i]].defaultBaseUrl) === 0) return ids[i];
    }
    return "openai";
  }

  function inputValue(id) {
    var el = $(id);
    return el ? el.value.trim() : "";
  }

  function timeoutMs() {
    var seconds = parseInt(inputValue("wsLlmTimeout"), 10);
    if (!seconds || seconds <= 0) return DEFAULT_TIMEOUT;
    return seconds * 1000;
  }

  function retriesCount() {
    var retries = parseInt(inputValue("wsLlmRetries"), 10);
    if (isNaN(retries) || retries < 0) return DEFAULT_RETRIES;
    return Math.min(retries, 10);
  }

  function markDisconnected() {
    state.connected = false;
    renderStatus();
  }

  function renderStatus() {
    var box = $("wsLlmSettingsStatus");
    var label = $("wsLlmStatusLabel");
    var hint = $("wsLlmStatusHint");
    if (!box || !label || !hint) return;
    var baseUrl = inputValue("wsLlmBaseUrl");
    var model = inputValue("wsLlmModel");
    var typedKey = inputValue("wsLlmApiKey");
    var hasKey = state.hasKey || !!typedKey;
    var ready = state.enabled && hasKey && baseUrl && model;
    var mode = !state.enabled ? "off" : state.connected && ready ? "connected" : ready ? "ready" : "missing";
    var providerName = (API_PROVIDERS[state.provider] || {}).name || "";
    box.dataset.state = mode;
    if (mode === "off") {
      label.textContent = "已关闭";
      hint.textContent = "助手已停用，连接配置仍会保留";
    } else if (mode === "connected") {
      label.textContent = "已连接";
      hint.textContent = providerName + (model ? (" · " + model) : "");
    } else if (mode === "ready") {
      label.textContent = "已配置";
      hint.textContent = model ? ("当前模型 " + model + "，尚未测试连接") : "可以测试连接";
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

  // 切换/载入服务商：优先读该服务商的本地记忆，其次用服务端配置（服务商匹配时），最后回退预设默认值
  function applyProvider(providerId, serverData) {
    if (!API_PROVIDERS[providerId]) providerId = "openai";
    state.provider = providerId;
    try { localStorage.setItem(LS_PROVIDER, providerId); } catch (e) {}
    var select = $("wsLlmProvider");
    if (select) select.value = providerId;
    var preset = API_PROVIDERS[providerId];
    var url = null;
    var model = null;
    try {
      url = localStorage.getItem(lsBaseKey(providerId));
      model = localStorage.getItem(lsModelKey(providerId));
    } catch (e) {}
    if (url === null && serverData && serverData.base_url && inferProvider(serverData.base_url) === providerId) {
      url = serverData.base_url;
      if (model === null) model = serverData.model || preset.defaultModel;
    }
    if (url === null || url === "") url = preset.defaultBaseUrl;
    if (model === null || model === "") model = preset.defaultModel;
    if ($("wsLlmBaseUrl")) $("wsLlmBaseUrl").value = url;
    if ($("wsLlmModel")) $("wsLlmModel").value = model;
    var keyInput = $("wsLlmApiKey");
    if (keyInput) {
      var localKey = readApiKeys()[providerId] || "";
      keyInput.value = localKey;
      keyInput.placeholder = localKey || state.hasKey ? "已保存，留空则保留原密钥" : "未配置";
    }
  }

  function applySettings(data) {
    data = data || {};
    state.hasKey = !!data.has_key;
    state.connected = false;
    setEnabled(data.enabled !== false);
    if ($("wsLlmTimeout")) $("wsLlmTimeout").value = Math.round((data.timeout || DEFAULT_TIMEOUT) / 1000);
    if ($("wsLlmRetries")) $("wsLlmRetries").value = data.retries != null ? data.retries : DEFAULT_RETRIES;
    var savedProvider = null;
    try { savedProvider = localStorage.getItem(LS_PROVIDER); } catch (e) {}
    applyProvider(API_PROVIDERS[savedProvider] ? savedProvider : inferProvider(data.base_url), data);
    renderStatus();
  }

  function currentPayload(includeKey) {
    var payload = {
      enabled: state.enabled,
      base_url: ($("wsLlmBaseUrl") && $("wsLlmBaseUrl").value) || "",
      model: ($("wsLlmModel") && $("wsLlmModel").value) || "",
      default_system_prompt: ($("wsLlmSystemPrompt") && $("wsLlmSystemPrompt").value) || "",
      timeout: timeoutMs(),
      retries: retriesCount(),
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
        // 后端会按重试次数多次尝试，前端中断时间要覆盖全部尝试
        var controller = new AbortController();
        var waitMs = timeoutMs() * (retriesCount() + 1) + 5000;
        var timer = setTimeout(function () { controller.abort(); }, waitMs);
        return fetch(TEST_URL, {
          method: "POST",
          headers: { "Content-Type": "application/json", Accept: "application/json" },
          body: "{}",
          signal: controller.signal,
        })
          .then(readJson)
          .finally(function () { clearTimeout(timer); });
      })
      .then(function () {
        state.connected = true;
        renderStatus();
        notify("API 连接成功", "success");
      })
      .catch(function (err) {
        state.connected = false;
        renderStatus();
        var message = err && err.name === "AbortError" ? "连接超时" : (err.message || "连接失败");
        setError(message);
        notify("连接失败: " + message, "error");
      })
      .finally(function () { setBusy(false); });
  }

  function setModelValue(name) {
    if ($("wsLlmModel")) $("wsLlmModel").value = name;
    try { localStorage.setItem(lsModelKey(state.provider), name); } catch (e) {}
    markDisconnected();
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
        setModelValue(name);
        Array.prototype.forEach.call(list.querySelectorAll("button"), function (item) {
          item.classList.toggle("is-active", item.textContent === name);
        });
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
    var providerSelect = $("wsLlmProvider");
    if (providerSelect) {
      providerSelect.onchange = function () {
        applyProvider(providerSelect.value, null);
        markDisconnected();
      };
    }
    var baseUrlInput = $("wsLlmBaseUrl");
    if (baseUrlInput) {
      baseUrlInput.oninput = function () {
        try { localStorage.setItem(lsBaseKey(state.provider), baseUrlInput.value); } catch (e) {}
        markDisconnected();
      };
    }
    var modelInput = $("wsLlmModel");
    if (modelInput) {
      modelInput.oninput = function () {
        try { localStorage.setItem(lsModelKey(state.provider), modelInput.value); } catch (e) {}
        markDisconnected();
      };
    }
    var keyInput = $("wsLlmApiKey");
    if (keyInput) {
      keyInput.oninput = function () {
        var keys = readApiKeys();
        keys[state.provider] = keyInput.value;
        writeApiKeys(keys);
        markDisconnected();
      };
    }
    ["wsLlmTimeout", "wsLlmRetries"].forEach(function (id) {
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
