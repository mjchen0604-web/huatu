(() => {
  const INPUT_STATE_KEY = "autofigure_input_state_v2";
  const DEFAULT_INPUT_CONFIG = {
    provider: "sub2api",
    apiKey: "",
    baseUrl: "http://localhost:8080/v1",
    imageModel: "gpt-image-2",
    svgModel: "gpt-5.5",
    reasoningEffort: "high",
    optimizeIterations: "0",
    imageSize: "4K",
    samBackend: "roboflow",
    samPrompt: "icon,person,robot,animal",
    samApiKey: "",
    rmbgBackend: "local",
    briaApiKey: "",
  };
  const PROVIDER_INPUT_DEFAULTS = {
    sub2api: {
      apiKey: "",
      baseUrl: "http://localhost:8080/v1",
      imageModel: "gpt-image-2",
      svgModel: "gpt-5.5",
      reasoningEffort: "high",
      imageSize: "4K",
    },
    gemini: {
      apiKey: "",
      baseUrl: "https://generativelanguage.googleapis.com/v1beta",
      imageModel: "gemini-3.1-flash-image-preview",
      svgModel: "gemini-3.1-pro-preview",
      reasoningEffort: "none",
      imageSize: "4K",
    },
    openrouter: {
      apiKey: "",
      baseUrl: "https://openrouter.ai/api/v1",
      imageModel: "google/gemini-3.1-flash-image-preview",
      svgModel: "google/gemini-3.1-pro-preview",
      reasoningEffort: "none",
      imageSize: "4K",
    },
    bianxie: {
      apiKey: "",
      baseUrl: "https://api.bianxie.ai/v1",
      imageModel: "gemini-3.1-flash-image-preview",
      svgModel: "gemini-3.1-pro-preview",
      reasoningEffort: "none",
      imageSize: "4K",
    },
    xai: {
      apiKey: "",
      baseUrl: "https://api.x.ai/v1",
      imageModel: "grok-imagine-image",
      svgModel: "grok-4.20-reasoning",
      reasoningEffort: "none",
      imageSize: "2K",
    },
  };

  const page = document.body.dataset.page;
  if (page === "input") {
    initInputPage();
  } else if (page === "canvas") {
    initCanvasPage();
  }

  function $(id) {
    return document.getElementById(id);
  }

  async function initInputPage() {
    const confirmBtn = $("confirmBtn");
    const errorMsg = $("errorMsg");
    const uploadZone = $("uploadZone");
    const referenceFile = $("referenceFile");
    const referencePreview = $("referencePreview");
    const referenceStatus = $("referenceStatus");
    const methodTextGroup = $("methodTextGroup");
    const sourceUploadZone = $("sourceUploadZone");
    const sourceFile = $("sourceFile");
    const sourcePreview = $("sourcePreview");
    const sourceStatus = $("sourceStatus");
    const sourceImageGroup = $("sourceImageGroup");
    const textModeBtn = $("textModeBtn");
    const imageModeBtn = $("imageModeBtn");
    const svgModeBtn = $("svgModeBtn");
    const psdModeBtn = $("psdModeBtn");
    const vectorModeBtn = $("vectorModeBtn");
    const historyList = $("historyList");
    const archiveList = $("archiveList");
    const archiveToggle = $("archiveToggle");
    const imageSizeGroup = $("imageSizeGroup");
    const imageSizeInput = $("imageSize");
    const reasoningEffortGroup = $("reasoningEffortGroup");
    const samBackend = $("samBackend");
    const samPrompt = $("samPrompt");
    const samApiKeyGroup = $("samApiKeyGroup");
    const samApiKeyInput = $("samApiKey");
    const rmbgBackend = $("rmbgBackend");
    const briaApiKeyGroup = $("briaApiKeyGroup");
    const briaApiKeyInput = $("briaApiKey");
    const saveConfigBtn = $("saveConfigBtn");
    const configStatus = $("configStatus");
    const adminConfigPanel = $("adminConfigPanel");
    const adminPassword = $("adminPassword");
    const adminUnlockBtn = $("adminUnlockBtn");
    const adminStatus = $("adminStatus");
    let defaults = { ...DEFAULT_INPUT_CONFIG };
    let inputMode = "text";
    let outputMode = "svg";
    let uploadedReferencePath = null;
    let uploadedSourcePath = null;
    let showArchive = false;
    let adminUnlocked = false;
    let adminAuthPassword = "";

    async function loadServerDefaults(adminPasswordValue = null) {
      try {
        const response = adminPasswordValue
          ? await fetch("/api/config/admin", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ password: adminPasswordValue }),
            })
          : await fetch("/api/config");
        if (!response.ok) {
          if (adminPasswordValue) {
            throw new Error("管理员密码不正确。");
          }
          return;
        }
        const config = await response.json();
        const incoming = config.defaults || {};
        defaults = {
          ...defaults,
          provider: incoming.provider || defaults.provider,
          apiKey: incoming.apiKey || defaults.apiKey,
          baseUrl: incoming.baseUrl || defaults.baseUrl,
          imageModel: incoming.imageModel || defaults.imageModel,
          imageSize: incoming.imageSize || defaults.imageSize,
          svgModel: incoming.svgModel || defaults.svgModel,
          reasoningEffort: incoming.reasoningEffort || defaults.reasoningEffort,
          optimizeIterations: incoming.optimizeIterations || defaults.optimizeIterations,
          samBackend: incoming.samBackend || defaults.samBackend,
          samPrompt: incoming.samPrompt || defaults.samPrompt,
          samApiKey: incoming.samApiKey || defaults.samApiKey,
          rmbgBackend: incoming.rmbgBackend || defaults.rmbgBackend,
          briaApiKey: incoming.briaApiKey || defaults.briaApiKey,
        };
        if (adminPasswordValue && adminConfigPanel) {
          adminUnlocked = true;
          adminConfigPanel.hidden = false;
          if (adminStatus) {
            adminStatus.textContent = "已解锁完整配置。";
          }
        }
        return true;
      } catch (_err) {
        if (adminPasswordValue && adminStatus) {
          adminStatus.textContent = _err.message || "解锁失败。";
        }
        // Defaults are best-effort; the app remains usable without them.
        return false;
      }
    }

    function getDefaultState() {
      return {
        methodText: "",
        ...defaults,
        inputMode: "text",
        outputMode: "svg",
        referencePath: null,
        referenceUrl: "",
        referenceStatus: "",
        sourcePath: null,
        sourceUrl: "",
        sourceStatus: "",
      };
    }

    function getProviderDefaults(provider) {
      const providerDefaults =
        PROVIDER_INPUT_DEFAULTS[provider] || PROVIDER_INPUT_DEFAULTS.sub2api;
      if (provider !== "sub2api") {
        return providerDefaults;
      }
      return {
        ...providerDefaults,
        apiKey: defaults.apiKey || providerDefaults.apiKey,
        baseUrl: defaults.baseUrl || providerDefaults.baseUrl,
        imageModel: defaults.imageModel || providerDefaults.imageModel,
        svgModel: defaults.svgModel || providerDefaults.svgModel,
        reasoningEffort: defaults.reasoningEffort || providerDefaults.reasoningEffort,
      };
    }

    function syncProviderFieldVisibility(persist = true) {
      const provider = $("provider")?.value ?? defaults.provider;
      const showImageSize = provider === "gemini" || provider === "xai";
      if (imageSizeGroup) {
        imageSizeGroup.hidden = !showImageSize;
      }
      if (reasoningEffortGroup) {
        reasoningEffortGroup.hidden = provider !== "sub2api";
      }
      if ($("reasoningEffort") && provider !== "sub2api") {
        $("reasoningEffort").value = "none";
      }
      if (imageSizeInput && provider === "xai" && imageSizeInput.value === "4K") {
        imageSizeInput.value = "2K";
      }
      if (persist) {
        saveInputState();
      }
    }

    function applyProviderDefaults(provider) {
      const providerDefaults = getProviderDefaults(provider);
      if ($("apiKey")) {
        $("apiKey").value = providerDefaults.apiKey;
      }
      if ($("baseUrl")) {
        $("baseUrl").value = providerDefaults.baseUrl;
      }
      if ($("imageModel")) {
        $("imageModel").value = providerDefaults.imageModel;
      }
      if ($("svgModel")) {
        $("svgModel").value = providerDefaults.svgModel;
      }
      if ($("reasoningEffort")) {
        $("reasoningEffort").value = providerDefaults.reasoningEffort;
      }
      if (imageSizeInput) {
        imageSizeInput.value = providerDefaults.imageSize;
      }
      syncProviderFieldVisibility(false);
      saveInputState();
    }

    function normalizeProviderState() {
      const provider = $("provider")?.value ?? defaults.provider;
      if (provider === "sub2api") {
        return;
      }
      const baseUrl = $("baseUrl")?.value.trim().toLowerCase() ?? "";
      const imageModel = $("imageModel")?.value.trim().toLowerCase() ?? "";
      const svgModel = $("svgModel")?.value.trim().toLowerCase() ?? "";
      const carriesSub2ApiDefaults =
        baseUrl.includes("sub2api") ||
        imageModel.startsWith("gpt-") ||
        svgModel.startsWith("gpt-");
      if (carriesSub2ApiDefaults) {
        applyProviderDefaults(provider);
      }
    }

    function loadInputState() {
      try {
        const raw = window.localStorage.getItem(INPUT_STATE_KEY);
        if (!raw) {
          return getDefaultState();
        }
        const parsed = JSON.parse(raw);
        if (!parsed || typeof parsed !== "object") {
          return getDefaultState();
        }
        const merged = { ...getDefaultState(), ...parsed };
        const configKeys = [
          "provider",
          "apiKey",
          "baseUrl",
          "imageModel",
          "imageSize",
          "svgModel",
          "reasoningEffort",
          "optimizeIterations",
          "samBackend",
          "samPrompt",
          "samApiKey",
          "rmbgBackend",
          "briaApiKey",
        ];
        for (const key of configKeys) {
          if (typeof merged[key] !== "string" || merged[key].trim() === "") {
            merged[key] = defaults[key];
          }
        }
        if (!adminUnlocked) {
          for (const key of configKeys) {
            if (key !== "samPrompt") {
              merged[key] = defaults[key];
            }
          }
        } else {
          for (const key of configKeys) {
            merged[key] = defaults[key];
          }
        }
        return merged;
      } catch (_err) {
        return getDefaultState();
      }
    }

    function saveInputState(showStatus = false) {
      const state = {
        methodText: $("methodText")?.value ?? "",
        provider: adminUnlocked ? $("provider")?.value ?? defaults.provider : defaults.provider,
        apiKey: adminUnlocked ? $("apiKey")?.value ?? "" : "",
        baseUrl: adminUnlocked ? $("baseUrl")?.value ?? "" : defaults.baseUrl,
        imageModel: adminUnlocked ? $("imageModel")?.value ?? "" : defaults.imageModel,
        svgModel: adminUnlocked ? $("svgModel")?.value ?? "" : defaults.svgModel,
        reasoningEffort: adminUnlocked
          ? $("reasoningEffort")?.value ?? defaults.reasoningEffort
          : defaults.reasoningEffort,
        inputMode,
        outputMode,
        optimizeIterations: $("optimizeIterations")?.value ?? "0",
        imageSize: adminUnlocked ? imageSizeInput?.value ?? "4K" : defaults.imageSize,
        samBackend: adminUnlocked ? samBackend?.value ?? "roboflow" : defaults.samBackend,
        samPrompt: samPrompt?.value ?? "icon,person,robot,animal",
        samApiKey: adminUnlocked ? samApiKeyInput?.value ?? "" : "",
        rmbgBackend: adminUnlocked ? rmbgBackend?.value ?? "local" : defaults.rmbgBackend,
        briaApiKey: adminUnlocked ? briaApiKeyInput?.value ?? "" : "",
        referencePath: uploadedReferencePath,
        referenceUrl: referencePreview?.src ?? "",
        referenceStatus: referenceStatus?.textContent ?? "",
        sourcePath: uploadedSourcePath,
        sourceUrl: sourcePreview?.src ?? "",
        sourceStatus: sourceStatus?.textContent ?? "",
      };
      try {
        window.localStorage.setItem(INPUT_STATE_KEY, JSON.stringify(state));
        if (showStatus && configStatus) {
          configStatus.textContent = "已保存，下次打开会自动填入。";
          window.setTimeout(() => {
            if (configStatus.textContent === "已保存，下次打开会自动填入。") {
              configStatus.textContent = "";
            }
          }, 2400);
        }
      } catch (_err) {
        if (showStatus && configStatus) {
          configStatus.textContent = "保存失败，浏览器禁止本地存储。";
        }
      }
    }

    function collectConfigState() {
      return {
        provider: $("provider")?.value ?? defaults.provider,
        apiKey: $("apiKey")?.value ?? "",
        baseUrl: $("baseUrl")?.value ?? defaults.baseUrl,
        imageModel: $("imageModel")?.value ?? defaults.imageModel,
        svgModel: $("svgModel")?.value ?? defaults.svgModel,
        reasoningEffort: $("reasoningEffort")?.value ?? defaults.reasoningEffort,
        optimizeIterations: $("optimizeIterations")?.value ?? defaults.optimizeIterations ?? "0",
        imageSize: imageSizeInput?.value ?? defaults.imageSize ?? "4K",
        samBackend: samBackend?.value ?? defaults.samBackend,
        samPrompt: samPrompt?.value ?? defaults.samPrompt,
        samApiKey: samApiKeyInput?.value ?? "",
        rmbgBackend: rmbgBackend?.value ?? defaults.rmbgBackend,
        briaApiKey: briaApiKeyInput?.value ?? "",
      };
    }

    async function saveServerConfig() {
      if (!adminUnlocked || !adminAuthPassword) {
        if (configStatus) {
          configStatus.textContent = "请先输入管理员密码解锁。";
        }
        return;
      }
      const configState = collectConfigState();
      if (configState.apiKey && configState.apiKey === adminAuthPassword) {
        if (configStatus) {
          configStatus.textContent = "API Key 不能填管理员密码，请改成 Sub2API 里生成的密钥。";
        }
        return;
      }
      if (configStatus) {
        configStatus.textContent = "正在保存到服务器...";
      }
      try {
        const response = await fetch("/api/config/save", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            password: adminAuthPassword,
            defaults: configState,
          }),
        });
        if (!response.ok) {
          throw new Error("服务器保存失败。");
        }
        const config = await response.json();
        defaults = { ...defaults, ...(config.defaults || {}) };
        saveInputState(false);
        if (configStatus) {
          configStatus.textContent = "已保存到服务器，刷新后仍会保留。";
        }
      } catch (_err) {
        if (configStatus) {
          configStatus.textContent = _err.message || "服务器保存失败。";
        }
      }
    }

    function applyInputState() {
      const state = loadInputState();
      if (typeof state.methodText === "string") {
        $("methodText").value = state.methodText;
      }
      if (typeof state.provider === "string" && $("provider")) {
        $("provider").value = state.provider;
      }
      if (typeof state.apiKey === "string") {
        $("apiKey").value = state.apiKey;
      }
      if (typeof state.baseUrl === "string" && $("baseUrl")) {
        $("baseUrl").value = state.baseUrl;
      }
      if (typeof state.imageModel === "string" && $("imageModel")) {
        $("imageModel").value = state.imageModel;
      }
      if (typeof state.svgModel === "string" && $("svgModel")) {
        $("svgModel").value = state.svgModel;
      }
      if (typeof state.reasoningEffort === "string" && $("reasoningEffort")) {
        $("reasoningEffort").value = state.reasoningEffort;
      }
      if (state.inputMode === "image" || state.inputMode === "text") {
        setInputMode(state.inputMode, false);
      }
      if (["psd", "svg", "vector"].includes(state.outputMode)) {
        setOutputMode(state.outputMode, false);
      }
      if (typeof state.optimizeIterations === "string" && $("optimizeIterations")) {
        $("optimizeIterations").value = state.optimizeIterations;
      }
      if (typeof state.imageSize === "string" && imageSizeInput) {
        imageSizeInput.value = state.imageSize;
      }
      if (typeof state.samBackend === "string" && samBackend) {
        samBackend.value = state.samBackend;
      }
      if (typeof state.samPrompt === "string" && samPrompt) {
        samPrompt.value = state.samPrompt;
      }
      if (typeof state.samApiKey === "string" && samApiKeyInput) {
        samApiKeyInput.value = state.samApiKey;
      }
      if (samApiKeyInput && defaults.samApiKey && !samApiKeyInput.value.trim()) {
        samApiKeyInput.value = defaults.samApiKey;
      }
      if (typeof state.rmbgBackend === "string" && rmbgBackend) {
        rmbgBackend.value = state.rmbgBackend;
      }
      if (typeof state.briaApiKey === "string" && briaApiKeyInput) {
        briaApiKeyInput.value = state.briaApiKey;
      }
      if (briaApiKeyInput && defaults.briaApiKey && !briaApiKeyInput.value.trim()) {
        briaApiKeyInput.value = defaults.briaApiKey;
      }
      if (typeof state.referencePath === "string" && state.referencePath) {
        uploadedReferencePath = state.referencePath;
      }
      if (typeof state.sourcePath === "string" && state.sourcePath) {
        uploadedSourcePath = state.sourcePath;
      }
      if (
        referencePreview &&
        typeof state.referenceUrl === "string" &&
        state.referenceUrl
      ) {
        referencePreview.src = state.referenceUrl;
        referencePreview.classList.add("visible");
      }
      if (
        referenceStatus &&
        typeof state.referenceStatus === "string" &&
        state.referenceStatus
      ) {
        referenceStatus.textContent = state.referenceStatus;
      }
      if (sourcePreview && typeof state.sourceUrl === "string" && state.sourceUrl) {
        sourcePreview.src = state.sourceUrl;
        sourcePreview.classList.add("visible");
      }
      if (sourceStatus && typeof state.sourceStatus === "string" && state.sourceStatus) {
        sourceStatus.textContent = state.sourceStatus;
      }
    }

    function setInputMode(mode, persist = true) {
      inputMode = mode === "image" ? "image" : "text";
      textModeBtn?.classList.toggle("active", inputMode === "text");
      imageModeBtn?.classList.toggle("active", inputMode === "image");
      if (methodTextGroup) {
        methodTextGroup.hidden = inputMode === "image";
      }
      if (sourceImageGroup) {
        sourceImageGroup.hidden = inputMode !== "image";
      }
      if ($("methodText")) {
        $("methodText").disabled = inputMode === "image";
        $("methodText").placeholder =
          inputMode === "image"
            ? "图片模式会直接使用上传的源图片。"
            : "粘贴论文方法段落，越结构化越容易生成干净的模板图。";
      }
      if (uploadZone) {
        uploadZone.closest(".field-group").hidden = inputMode !== "text";
      }
      if (persist) {
        saveInputState();
      }
    }

    function setOutputMode(mode, persist = true) {
      outputMode = ["psd", "vector"].includes(mode) ? mode : "svg";
      svgModeBtn?.classList.toggle("active", outputMode === "svg");
      psdModeBtn?.classList.toggle("active", outputMode === "psd");
      vectorModeBtn?.classList.toggle("active", outputMode === "vector");
      if (persist) {
        saveInputState();
      }
    }

    function syncImageSizeVisibility() {
      syncProviderFieldVisibility();
    }

    function syncSamApiKeyVisibility() {
      const shouldShow =
        samBackend &&
        (samBackend.value === "fal" || samBackend.value === "roboflow");
      if (samApiKeyGroup) {
        samApiKeyGroup.hidden = !shouldShow;
      }
      if (!shouldShow && samApiKeyInput) {
        samApiKeyInput.value = "";
      }
      saveInputState();
    }

    function syncRmbgApiKeyVisibility() {
      const shouldShow = rmbgBackend && rmbgBackend.value === "bria-api";
      if (briaApiKeyGroup) {
        briaApiKeyGroup.hidden = !shouldShow;
      }
      if (shouldShow && briaApiKeyInput && !briaApiKeyInput.value.trim() && defaults.briaApiKey) {
        briaApiKeyInput.value = defaults.briaApiKey;
      }
      if (!shouldShow && briaApiKeyInput) {
        briaApiKeyInput.value = "";
      }
      saveInputState();
    }

    await loadServerDefaults();
    applyInputState();
    normalizeProviderState();
    setInputMode(inputMode, false);
    loadJobHistory();

    textModeBtn?.addEventListener("click", () => setInputMode("text"));
    imageModeBtn?.addEventListener("click", () => setInputMode("image"));
    svgModeBtn?.addEventListener("click", () => setOutputMode("svg"));
    psdModeBtn?.addEventListener("click", () => setOutputMode("psd"));
    vectorModeBtn?.addEventListener("click", () => setOutputMode("vector"));
    archiveToggle?.addEventListener("click", () => {
      showArchive = !showArchive;
      if (archiveList) {
        archiveList.hidden = !showArchive;
      }
      if (archiveToggle) {
        archiveToggle.textContent = showArchive ? "隐藏存档" : "查看存档";
      }
      if (showArchive) {
        loadJobHistory();
      }
    });
    saveConfigBtn?.addEventListener("click", () => {
      saveInputState(false);
      saveServerConfig();
    });
    adminUnlockBtn?.addEventListener("click", async () => {
      const password = adminPassword?.value.trim() || "";
      if (!password) {
        if (adminStatus) {
          adminStatus.textContent = "请输入管理员密码。";
        }
        return;
      }
      adminUnlockBtn.disabled = true;
      if (adminStatus) {
        adminStatus.textContent = "正在验证...";
      }
      const unlocked = await loadServerDefaults(password);
      if (unlocked) {
        adminAuthPassword = password;
        applyInputState();
        normalizeProviderState();
        syncProviderFieldVisibility(false);
        syncSamApiKeyVisibility();
        syncRmbgApiKeyVisibility();
        if (adminPassword) {
          adminPassword.value = "";
        }
      }
      adminUnlockBtn.disabled = false;
    });
    adminPassword?.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        adminUnlockBtn?.click();
      }
    });

    if (samBackend) {
      samBackend.addEventListener("change", syncSamApiKeyVisibility);
      syncSamApiKeyVisibility();
    }
    if (rmbgBackend) {
      rmbgBackend.addEventListener("change", syncRmbgApiKeyVisibility);
      syncRmbgApiKeyVisibility();
    }
    for (const button of document.querySelectorAll("[data-secret-target]")) {
      button.addEventListener("click", () => {
        const target = $(button.dataset.secretTarget);
        if (!target) {
          return;
        }
        const visible = target.type === "text";
        target.type = visible ? "password" : "text";
        button.classList.toggle("is-visible", !visible);
        const label = visible ? "显示" : "隐藏";
        const fieldName = button.getAttribute("aria-label")?.replace(/^显示|^隐藏/, "") || "API Key";
        button.setAttribute("aria-label", `${label}${fieldName}`);
        button.setAttribute("title", `${label}${fieldName}`);
      });
    }
    if ($("provider")) {
      $("provider").addEventListener("change", () => {
        applyProviderDefaults($("provider").value);
      });
      syncProviderFieldVisibility(false);
    }

    if (uploadZone && referenceFile) {
      uploadZone.addEventListener("click", () => referenceFile.click());
      uploadZone.addEventListener("dragover", (event) => {
        event.preventDefault();
        uploadZone.classList.add("dragging");
      });
      uploadZone.addEventListener("dragleave", () => {
        uploadZone.classList.remove("dragging");
      });
      uploadZone.addEventListener("drop", async (event) => {
        event.preventDefault();
        uploadZone.classList.remove("dragging");
        const file = event.dataTransfer.files[0];
        if (file) {
          const uploadedRef = await uploadReference(file, confirmBtn, referencePreview, referenceStatus);
          if (uploadedRef) {
            uploadedReferencePath = uploadedRef.path;
            saveInputState();
          }
        }
      });
      referenceFile.addEventListener("change", async () => {
        const file = referenceFile.files[0];
        if (file) {
          const uploadedRef = await uploadReference(file, confirmBtn, referencePreview, referenceStatus);
          if (uploadedRef) {
            uploadedReferencePath = uploadedRef.path;
            saveInputState();
          }
        }
      });
    }

    if (sourceUploadZone && sourceFile) {
      sourceUploadZone.addEventListener("click", () => sourceFile.click());
      sourceUploadZone.addEventListener("dragover", (event) => {
        event.preventDefault();
        sourceUploadZone.classList.add("dragging");
      });
      sourceUploadZone.addEventListener("dragleave", () => {
        sourceUploadZone.classList.remove("dragging");
      });
      sourceUploadZone.addEventListener("drop", async (event) => {
        event.preventDefault();
        sourceUploadZone.classList.remove("dragging");
        const file = event.dataTransfer.files[0];
        if (file) {
          const uploaded = await uploadReference(file, confirmBtn, sourcePreview, sourceStatus, "正在上传源图片...");
          if (uploaded) {
            uploadedSourcePath = uploaded.path;
            saveInputState();
          }
        }
      });
      sourceFile.addEventListener("change", async () => {
        const file = sourceFile.files[0];
        if (file) {
          const uploaded = await uploadReference(file, confirmBtn, sourcePreview, sourceStatus, "正在上传源图片...");
          if (uploaded) {
            uploadedSourcePath = uploaded.path;
            saveInputState();
          }
        }
      });
    }

    const autoSaveFields = [
      $("methodText"),
      $("provider"),
      $("apiKey"),
      $("baseUrl"),
      $("imageModel"),
      $("svgModel"),
      $("reasoningEffort"),
      $("optimizeIterations"),
      $("imageSize"),
      samPrompt,
      samApiKeyInput,
      rmbgBackend,
      briaApiKeyInput,
    ];
    for (const field of autoSaveFields) {
      if (!field) {
        continue;
      }
      field.addEventListener("input", saveInputState);
      field.addEventListener("change", saveInputState);
    }

    confirmBtn.addEventListener("click", async () => {
      errorMsg.textContent = "";
      const methodText = $("methodText").value.trim();
      if (inputMode === "text" && !methodText) {
        errorMsg.textContent = "请先填写方法文本。";
        return;
      }
      if (inputMode === "image" && !uploadedSourcePath) {
        errorMsg.textContent = "请先上传源图片。";
        return;
      }

      confirmBtn.disabled = true;
      confirmBtn.textContent = "正在启动...";

      const payload = {
        input_mode: inputMode,
        psd_only: outputMode === "psd",
        vectorize_layers: outputMode === "vector",
        method_text: inputMode === "text" ? methodText : "",
        provider: $("provider").value || null,
        api_key: $("apiKey").value.trim() || null,
        base_url: $("baseUrl").value.trim() || null,
        image_model: $("imageModel").value.trim() || null,
        svg_model: $("svgModel").value.trim() || null,
        reasoning_effort:
          $("provider").value === "sub2api" ? $("reasoningEffort").value || null : null,
        optimize_iterations: parseInt($("optimizeIterations").value, 10),
        reference_image_path: uploadedReferencePath,
        sam_backend: $("samBackend").value,
        sam_prompt: $("samPrompt").value.trim() || null,
        sam_api_key: $("samApiKey").value.trim() || null,
        rmbg_backend: $("rmbgBackend").value,
        bria_api_key: $("briaApiKey").value.trim() || null,
        source_image_path: inputMode === "image" ? uploadedSourcePath : null,
      };
      if ($("provider").value === "gemini") {
        payload.image_size = imageSizeInput?.value || "4K";
      }
      if (payload.sam_backend === "local") {
        payload.sam_api_key = null;
      }
      if (payload.rmbg_backend !== "bria-api") {
        payload.bria_api_key = null;
      }
      saveInputState();

      try {
        const response = await fetch("/api/run", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });

        if (!response.ok) {
          const text = await response.text();
          throw new Error(text || "请求失败");
        }

        const data = await response.json();
        window.location.href = `/canvas.html?job=${encodeURIComponent(data.job_id)}`;
      } catch (err) {
        errorMsg.textContent = err.message || "启动任务失败";
        confirmBtn.disabled = false;
        confirmBtn.textContent = "进入智能画布";
      }
    });

    async function loadJobHistory() {
      if (!historyList || !archiveList) {
        return;
      }
      await renderJobs(historyList, "active");
      if (showArchive) {
        await renderJobs(archiveList, "archived");
      }
    }

    async function renderJobs(container, archived) {
      container.textContent = "加载中...";
      try {
        const response = await fetch(`/api/jobs?archived=${archived}`);
        if (!response.ok) {
          throw new Error(await response.text());
        }
        const data = await response.json();
        container.textContent = "";
        if (!data.jobs || data.jobs.length === 0) {
          container.textContent = archived === "archived" ? "还没有已存档任务。" : "还没有保存的任务。";
          return;
        }
        for (const job of data.jobs) {
          container.appendChild(createHistoryCard(job, archived === "archived"));
        }
      } catch (err) {
        container.textContent = err.message || "加载任务历史失败。";
      }
    }

    function createHistoryCard(job, archived) {
      const card = document.createElement("div");
      card.className = "history-item";
      card.addEventListener("click", () => {
        window.location.href = `/canvas.html?job=${encodeURIComponent(job.job_id)}`;
      });

      const preview = document.createElement(job.preview_url ? "img" : "div");
      preview.className = "history-preview";
      if (job.preview_url) {
        preview.src = job.preview_url;
        preview.alt = job.job_id;
      }

      const body = document.createElement("div");
      body.className = "history-body";
      const title = document.createElement("div");
      title.className = "history-title";
      title.textContent = job.job_id;
      const meta = document.createElement("div");
      meta.className = "history-meta";
      meta.textContent = `${formatInputMode(job.input_mode)} · ${job.provider || "未记录模型"} · ${formatJobState(job.state)}`;

      const actions = document.createElement("div");
      actions.className = "history-actions";

      const archiveBtn = document.createElement("button");
      archiveBtn.className = "ghost history-archive";
      archiveBtn.type = "button";
      archiveBtn.textContent = archived ? "取消存档" : "存档";
      archiveBtn.addEventListener("click", async (event) => {
        event.stopPropagation();
        archiveBtn.disabled = true;
        const response = await fetch(`/api/jobs/${encodeURIComponent(job.job_id)}/archive`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ archived: !archived }),
        });
        if (!response.ok) {
          archiveBtn.disabled = false;
          return;
        }
        await loadJobHistory();
      });

      const deleteBtn = document.createElement("button");
      deleteBtn.className = "ghost danger history-delete";
      deleteBtn.type = "button";
      deleteBtn.textContent = "删除";
      let deleteArmed = false;
      let deleteResetTimer = null;
      deleteBtn.addEventListener("click", async (event) => {
        event.stopPropagation();
        if (!deleteArmed) {
          deleteArmed = true;
          deleteBtn.textContent = "确认删除";
          deleteBtn.classList.add("armed");
          clearTimeout(deleteResetTimer);
          deleteResetTimer = setTimeout(() => {
            deleteArmed = false;
            deleteBtn.textContent = "删除";
            deleteBtn.classList.remove("armed");
          }, 6000);
          return;
        }
        clearTimeout(deleteResetTimer);
        deleteBtn.disabled = true;
        const response = await fetch(`/api/jobs/${encodeURIComponent(job.job_id)}`, {
          method: "DELETE",
        });
        if (!response.ok) {
          deleteBtn.disabled = false;
          return;
        }
        await loadJobHistory();
      });

      actions.appendChild(archiveBtn);
      actions.appendChild(deleteBtn);
      body.appendChild(title);
      body.appendChild(meta);
      body.appendChild(actions);
      card.appendChild(preview);
      card.appendChild(body);
      return card;
    }
  }

  async function uploadReference(file, confirmBtn, previewEl, statusEl, uploadingText = "正在上传参考图片...") {
    if (!file.type.startsWith("image/")) {
      statusEl.textContent = "仅支持图片文件。";
      return null;
    }

    confirmBtn.disabled = true;
    statusEl.textContent = uploadingText;

    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await fetch("/api/upload", {
        method: "POST",
        body: formData,
      });

      if (!response.ok) {
        const text = await response.text();
      throw new Error(text || "上传失败");
      }

      const data = await response.json();
      statusEl.textContent = `已上传：${data.name}`;
      if (previewEl) {
        previewEl.src = data.url || "";
        previewEl.classList.add("visible");
      }
      return {
        path: data.path || null,
        url: data.url || "",
        name: data.name || "",
      };
    } catch (err) {
      statusEl.textContent = err.message || "上传失败";
      return null;
    } finally {
      confirmBtn.disabled = false;
    }
  }

  async function initCanvasPage() {
    const params = new URLSearchParams(window.location.search);
    const jobId = params.get("job");
    const statusText = $("statusText");
    const jobIdEl = $("jobId");
    const artifactPanel = $("artifactPanel");
    const artifactList = $("artifactList");
    const toggle = $("artifactToggle");
    const logToggle = $("logToggle");
    const backToConfigBtn = $("backToConfigBtn");
    const pauseJobBtn = $("pauseJobBtn");
    const logPanel = $("logPanel");
    const logBody = $("logBody");
    const iframe = $("svgEditorFrame");
    const fallback = $("svgFallback");
    const fallbackObject = $("fallbackObject");
    const fallbackImage = $("fallbackImage");
    const fallbackTitle = $("fallbackTitle");
    const archiveJobBtn = $("archiveJobBtn");
    const deleteJobBtn = $("deleteJobBtn");
    const optimizeMoreBtn = $("optimizeMoreBtn");
    const optimizeMoreIterations = $("optimizeMoreIterations");

    if (!jobId) {
      statusText.textContent = "缺少任务 ID";
      return;
    }

    jobIdEl.textContent = jobId;

    toggle.addEventListener("click", () => {
      artifactPanel.classList.toggle("open");
    });

    logToggle.addEventListener("click", () => {
      logPanel.classList.toggle("open");
    });
    if (backToConfigBtn) {
      backToConfigBtn.addEventListener("click", () => {
        window.location.href = "/";
      });
    }
    if (archiveJobBtn) {
      archiveJobBtn.addEventListener("click", async () => {
        await fetch(`/api/jobs/${encodeURIComponent(jobId)}/archive`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ archived: archiveJobBtn.dataset.archived !== "true" }),
        });
        const nowArchived = archiveJobBtn.dataset.archived !== "true";
        archiveJobBtn.dataset.archived = String(nowArchived);
        archiveJobBtn.textContent = nowArchived ? "取消存档" : "存档";
      });
    }
    if (deleteJobBtn) {
      let deleteArmed = false;
      let deleteResetTimer = null;
      deleteJobBtn.addEventListener("click", async () => {
        if (!deleteArmed) {
          deleteArmed = true;
          deleteJobBtn.textContent = "确认删除";
          deleteJobBtn.classList.add("armed");
          clearTimeout(deleteResetTimer);
          deleteResetTimer = setTimeout(() => {
            deleteArmed = false;
            deleteJobBtn.textContent = "删除";
            deleteJobBtn.classList.remove("armed");
          }, 6000);
          return;
        }
        clearTimeout(deleteResetTimer);
        deleteJobBtn.disabled = true;
        const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, {
          method: "DELETE",
        });
        if (!response.ok) {
          const text = await response.text();
          statusText.textContent = text || "删除失败";
          deleteJobBtn.disabled = false;
          return;
        }
        window.location.href = "/";
      });
    }
    if (optimizeMoreBtn) {
      optimizeMoreBtn.addEventListener("click", async () => {
        const iterations = parseInt(optimizeMoreIterations?.value || "1", 10);
        optimizeMoreBtn.disabled = true;
        statusText.textContent = `追加优化中（${iterations} 次）`;
        try {
          const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}/optimize`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ iterations }),
          });
          if (!response.ok) {
            const text = await response.text();
            throw new Error(text || "继续优化失败");
          }
          window.location.reload();
        } catch (err) {
          statusText.textContent = err.message || "继续优化失败";
          optimizeMoreBtn.disabled = false;
        }
      });
    }

    let jobPaused = false;
    let jobFinished = false;
    let jobContinuable = false;
    function setJobControl(mode) {
      if (!pauseJobBtn) {
        return;
      }
      jobContinuable = mode === "continuable";
      jobPaused = mode === "paused";
      jobFinished = mode === "done";
      pauseJobBtn.textContent =
        mode === "continuable" ? "继续任务" : mode === "paused" ? "继续" : "暂停";
      pauseJobBtn.disabled = mode === "done";
    }
    if (pauseJobBtn) {
      pauseJobBtn.addEventListener("click", async () => {
        if (jobFinished) {
          return;
        }
        pauseJobBtn.disabled = true;
        const action = jobContinuable ? "continue" : jobPaused ? "resume" : "pause";
        try {
          const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}/${action}`, {
            method: "POST",
          });
          if (!response.ok) {
            const text = await response.text();
            throw new Error(text || "操作失败");
          }
          if (action === "continue") {
            statusText.textContent = "继续中";
            window.location.reload();
            return;
          }
          setJobControl(jobPaused ? "running" : "paused");
          statusText.textContent = jobPaused ? "已暂停" : "运行中";
        } catch (err) {
          statusText.textContent = err.message || "暂停/继续失败";
          pauseJobBtn.disabled = false;
        } finally {
          if (!jobFinished && !jobContinuable) {
            pauseJobBtn.disabled = false;
          }
        }
      });
    }

    let svgEditAvailable = false;
    let svgEditPath = null;
    try {
      const configRes = await fetch("/api/config");
      if (configRes.ok) {
        const config = await configRes.json();
        svgEditAvailable = Boolean(config.svgEditAvailable);
        svgEditPath = config.svgEditPath || null;
      }
    } catch (err) {
      svgEditAvailable = false;
    }

    iframe.style.display = "none";
    fallback.classList.add("active");
    if (!svgEditAvailable || !svgEditPath) {
      if (fallbackTitle) {
        fallbackTitle.textContent = "SVG-Edit 未安装";
      }
      fallback.classList.add("active");
    }

    const stepMap = {
      figure: { step: 1, label: "源图准备完成" },
      samed: { step: 2, label: "SAM3 分割完成" },
      icon_raw: { step: 3, label: "图标裁切完成" },
      icon_nobg: { step: 3, label: "去背景完成" },
      template_svg: { step: 4, label: "模板 SVG 已生成" },
      final_svg: { step: 5, label: "最终 SVG 已生成" },
      final_psd: { step: 5, label: "分层 PSD 已生成" },
      layers_zip: { step: 5, label: "图层包已生成" },
      optimized_template_svg: { step: 4, label: "优化 SVG 已生成" },
      vector_layer_svg: { step: 4, label: "矢量图层已生成" },
      raster_layers_zip: { step: 3, label: "栅格图层包已生成" },
    };

    let currentStep = 0;
    const artifactData = [];
    const stepPreference = {
      1: ["figure"],
      2: ["samed"],
      3: ["icon_nobg", "icon_raw"],
      4: ["vector_layer_svg", "optimized_template_svg", "template_svg"],
      5: ["final_svg", "final_psd", "vector_layer_svg", "optimized_template_svg", "template_svg", "figure"],
    };

    const artifacts = new Set();
    let isFinished = false;
    let svgLoadToken = 0;

    async function handleArtifact(data) {
      if (!artifacts.has(data.path)) {
        artifacts.add(data.path);
        artifactData.push(data);
        addArtifactCard(artifactList, data);
      }

      if (
        data.kind === "template_svg" ||
        data.kind === "optimized_template_svg" ||
        data.kind === "final_svg"
      ) {
        await loadSvgAsset(data.url);
      } else if (data.kind === "figure" && currentStep === 0) {
        showRasterPreview(data.url, "源图预览");
      } else if (data.kind === "final_psd") {
        const figure = [...artifactData].reverse().find((item) => item.kind === "figure");
        if (figure) {
          showRasterPreview(figure.url, "PSD 分层已生成（预览源图）");
        }
      }

      if (stepMap[data.kind] && stepMap[data.kind].step > currentStep) {
        currentStep = stepMap[data.kind].step;
        statusText.textContent = `步骤 ${currentStep}/5 · ${stepMap[data.kind].label}`;
      }
    }

    function handleStatus(data) {
      if (data.state === "started") {
        statusText.textContent = "运行中";
        setJobControl("running");
      } else if (data.state === "paused") {
        statusText.textContent = "已暂停";
        setJobControl("paused");
      } else if (data.state === "resumed") {
        statusText.textContent = "运行中";
        setJobControl("running");
      } else if (data.state === "saved" || data.state === "empty" || data.state === "failed") {
        statusText.textContent = data.state === "failed" ? "失败，可继续" : "未完成，可继续";
        setJobControl("continuable");
      } else if (data.state === "finished") {
        isFinished = true;
        if (typeof data.code === "number" && data.code !== 0) {
          statusText.textContent = `失败（代码 ${data.code}）`;
          setJobControl("continuable");
        } else {
          statusText.textContent = "完成";
          setJobControl("done");
        }
      }
    }

    async function loadSavedJobSnapshot() {
      try {
        const response = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`);
        if (!response.ok) {
          return;
        }
        const data = await response.json();
        if (Array.isArray(data.artifacts)) {
          for (const artifact of data.artifacts) {
            await handleArtifact(artifact);
          }
        }
        if (data.state === "done") {
          handleStatus({ state: "finished", code: 0 });
        } else if (data.state === "failed") {
          handleStatus({ state: "failed", code: data.return_code });
        } else {
          handleStatus({ state: data.state });
        }
      } catch (_err) {
        // The live event stream below is still the source of truth while a job runs.
      }
    }

    await loadSavedJobSnapshot();

    const eventSource = new EventSource(`/api/events/${jobId}`);

    eventSource.addEventListener("artifact", async (event) => {
      await handleArtifact(JSON.parse(event.data));
    });

    for (const button of document.querySelectorAll(".step-btn")) {
      button.addEventListener("click", () => {
        const step = Number(button.dataset.step || "0");
        previewStep(step);
      });
    }

    eventSource.addEventListener("status", (event) => {
      handleStatus(JSON.parse(event.data));
    });

    eventSource.addEventListener("log", (event) => {
      const data = JSON.parse(event.data);
      appendLogLine(logBody, data);
    });

    eventSource.onerror = async () => {
      await loadSavedJobSnapshot();
      if (isFinished) {
        eventSource.close();
        return;
      }
      statusText.textContent = "连接已断开";
    };

    function showSvgPreviewFallback(url, title = "SVG 预览") {
      iframe.style.display = "none";
      fallback.classList.add("active");
      if (fallbackTitle) {
        fallbackTitle.textContent = title;
      }
      if (fallbackImage) {
        fallbackImage.removeAttribute("src");
        fallbackImage.classList.remove("visible");
      }
      if (fallbackObject) {
        fallbackObject.data = url;
      }
    }

    function showRasterPreview(url, title = "图片预览") {
      iframe.style.display = "none";
      fallback.classList.add("active");
      if (fallbackTitle) {
        fallbackTitle.textContent = title;
      }
      if (fallbackObject) {
        fallbackObject.removeAttribute("data");
      }
      if (fallbackImage) {
        fallbackImage.src = url;
        fallbackImage.classList.add("visible");
      }
    }

    async function loadSvgAsset(url) {
      const loadToken = ++svgLoadToken;
      if (fallbackObject) {
        fallbackObject.data = url;
      }
      if (svgEditAvailable && svgEditPath) {
        fallback.classList.remove("active");
        iframe.style.display = "";
        if (fallbackImage) {
          fallbackImage.removeAttribute("src");
          fallbackImage.classList.remove("visible");
        }
        const absoluteUrl = new URL(url, window.location.origin).href;
        const editorExtensions = [
          "ext-connector",
          "ext-eyedropper",
          "ext-grid",
          "ext-markers",
          "ext-panning",
          "ext-shapes",
          "ext-polystar",
          "ext-layer_view",
        ];
        const params = new URLSearchParams({
          noStorageOnLoad: "true",
          noDefaultExtensions: "true",
          storagePrompt: "false",
          extensions: editorExtensions.join(","),
          url: absoluteUrl,
          t: String(Date.now()),
        });
        iframe.src = `${svgEditPath}?${params.toString()}`;
        window.setTimeout(() => {
          if (loadToken !== svgLoadToken) {
            return;
          }
          try {
            const doc = iframe.contentDocument;
            const hasEditor = doc?.querySelector("#svg_editor, #svgcanvas, #svgcontent");
            if (!hasEditor) {
              showSvgPreviewFallback(url, "SVG 预览（编辑器加载失败）");
            }
          } catch (_err) {
            showSvgPreviewFallback(url, "SVG 预览（编辑器加载失败）");
          }
        }, 3500);
      } else {
        showSvgPreviewFallback(url);
      }
    }

    function previewStep(step) {
      const preferences = stepPreference[step] || [];
      const artifact = [...artifactData].reverse().find((item) => preferences.includes(item.kind));
      if (!artifact) {
        statusText.textContent = `步骤 ${step}/5 · 暂无保存的产物`;
        return;
      }
      if (artifact.url.endsWith(".svg")) {
        loadSvgAsset(artifact.url);
      } else if (artifact.kind === "final_psd") {
        const figure = [...artifactData].reverse().find((item) => item.kind === "figure");
        showRasterPreview(figure?.url || artifact.url, "PSD 分层已生成（预览源图）");
      } else {
        showRasterPreview(artifact.url, `步骤 ${step} 预览`);
      }
      const meta = stepMap[artifact.kind];
      statusText.textContent = `步骤 ${step}/5 · ${meta ? meta.label : artifact.name}`;
    }
  }

  function appendLogLine(container, data) {
    const line = `[${data.stream}] ${data.line}`;
    const lines = container.textContent.split("\n").filter(Boolean);
    lines.push(line);
    if (lines.length > 200) {
      lines.splice(0, lines.length - 200);
    }
    container.textContent = lines.join("\n");
    container.scrollTop = container.scrollHeight;
  }

  function addArtifactCard(container, data) {
    const card = document.createElement("a");
    card.className = "artifact-card";
    card.href = data.url;
    card.target = "_blank";
    card.rel = "noreferrer";

    const preview = document.createElement("div");
    preview.className = "artifact-preview";
    const canPreview = /\.(png|jpe?g|webp|gif|svg)$/i.test(data.name || data.url || "");
    if (canPreview) {
      const img = document.createElement("img");
      img.src = data.url;
      img.alt = data.name;
      img.loading = "lazy";
      preview.appendChild(img);
    } else {
      preview.textContent = artifactExtension(data.name);
    }

    const meta = document.createElement("div");
    meta.className = "artifact-meta";

    const name = document.createElement("div");
    name.className = "artifact-name";
    name.textContent = data.name;

    const badge = document.createElement("div");
    badge.className = "artifact-badge";
    badge.textContent = formatKind(data.kind);

    meta.appendChild(name);
    meta.appendChild(badge);
    card.appendChild(preview);
    card.appendChild(meta);
    container.prepend(card);
  }

  function artifactExtension(name) {
    const ext = String(name || "").split(".").pop();
    return ext ? ext.toUpperCase() : "FILE";
  }

  function formatKind(kind) {
    switch (kind) {
      case "figure":
        return "源图";
      case "samed":
        return "分割图";
      case "icon_raw":
        return "原始图标";
      case "icon_nobg":
        return "透明图标";
      case "optimized_template_svg":
        return "优化模板";
      case "template_svg":
        return "模板";
      case "final_svg":
        return "最终图";
      case "final_psd":
        return "分层 PSD";
      case "layers_zip":
        return "图层包";
      case "raster_layers_zip":
        return "栅格图层包";
      case "vector_layer_svg":
        return "矢量图层";
      case "psd_layer":
        return "PSD 图层";
      case "log":
        return "日志";
      default:
        return "产物";
    }
  }

  function formatInputMode(mode) {
    if (mode === "image") {
      return "图片转画布";
    }
    if (mode === "text") {
      return "文本生成";
    }
    return "未记录模式";
  }

  function formatJobState(state) {
    switch (state) {
      case "done":
        return "完成";
      case "failed":
        return "失败";
      case "saved":
        return "已保存";
      case "empty":
        return "空任务";
      default:
        return state || "未知状态";
    }
  }
})();
