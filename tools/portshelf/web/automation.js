"use strict";

(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.PortShelfAutomation = api;
})(globalThis, function () {
  function defaultConfig(arch = "amd64") {
    return { enabled: false, intervalHours: 6, minStars: 10, maxStars: null, arch: arch === "arm64" ? "arm64" : "amd64", providers: ["baidu", "quark"], dailyLimit: 10, shareDays: 0, shareCode: "", privateShare: true, enrich: true, rememberCredentials: false, startOnLogin: false };
  }

  function integer(value, min, max, label, empty) {
    if (value === "" || value === null || value === undefined) {
      if (empty !== undefined) return empty;
      throw new Error("请填写" + label + "。");
    }
    if (!/^\d+$/.test(String(value)) || !Number.isSafeInteger(Number(value)) || Number(value) < min || Number(value) > max) throw new Error(label + "需为 " + min + "–" + max + " 的整数。");
    return Number(value);
  }

  function validateConfig(value, capabilities = {}) {
    const minStars = integer(value.minStars, 0, 1000000000, "最低 Stars", 0);
    const maxStars = integer(value.maxStars, 0, 1000000000, "最高 Stars", null);
    if (maxStars !== null && minStars > maxStars) throw new Error("最低 Stars 不能大于最高 Stars。");
    if (!["amd64", "arm64"].includes(value.arch)) throw new Error("请选择 x64 或 ARM64 架构。");
    if (!Array.isArray(value.providers) || value.providers.some((provider) => !["baidu", "quark"].includes(provider))) throw new Error("请选择支持的网盘。");
    const providers = [...new Set(value.providers)];
    if (!providers.length) throw new Error("无人值守模式请至少选择一个网盘；仅下载可使用下方手动队列。");
    const privateShare = providers.includes("baidu") || value.privateShare !== false;
    const shareCode = providers.includes("baidu") && privateShare ? String(value.shareCode || "").trim() : "";
    if (shareCode && !/^[a-zA-Z0-9]{4}$/.test(shareCode)) throw new Error("百度提取码需为 4 位字母或数字，或留空自动生成。");
    const shareDays = integer(value.shareDays, 0, 30, "分享有效期");
    if (![0, 1, 7, 30].includes(shareDays)) throw new Error("请选择永久或 1、7、30 天的分享期限。");
    return { enabled: Boolean(value.enabled), intervalHours: integer(value.intervalHours, 1, 168, "扫描周期"), minStars, maxStars, arch: value.arch, providers, dailyLimit: integer(value.dailyLimit, 1, 100, "每天最多游戏数"), shareDays, shareCode, privateShare, enrich: Boolean(value.enrich), rememberCredentials: Boolean(capabilities.credentialStorageSupported && value.rememberCredentials), startOnLogin: Boolean(capabilities.startOnLoginSupported && value.startOnLogin) };
  }

  function date(value) {
    const parsed = new Date(value);
    return Number.isFinite(parsed.getTime()) && parsed.getFullYear() > 1970 ? parsed.toLocaleString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "";
  }

  function taskNotice(job) {
    if (!job?.automatic) return null;
    const attempts = Number.isSafeInteger(job.attempts) && job.attempts > 0 ? "已尝试 " + job.attempts + " 次" : "尚未开始尝试";
    if (job.needsAttention) return { kind: "attention", text: "需要本人处理：" + (typeof job.needsAttention === "string" ? job.needsAttention : job.error || "请查看任务错误，处理后再继续。"), attempts, pendingRetry: false };
    if (job.status === "paused") return { kind: "paused", text: "自动任务已暂停，开启无人值守后继续。", attempts, pendingRetry: false };
    const retry = date(job.nextRetryAt);
    if (retry && !["done", "cancelled"].includes(job.status)) return { kind: "retry", text: "下次自动重试：" + retry, attempts, pendingRetry: true };
    return { kind: "automatic", text: ["failed", "partial"].includes(job.status) ? "尚未安排自动重试，请查看任务原因。" : "", attempts, pendingRetry: false };
  }

  function create(context) {
    const $ = (id) => document.getElementById(id);
    const state = { visible: false, stopped: false, status: null, initialized: false, dirty: false, busy: "", loading: false, loadAgain: false, failures: 0, revision: 0, timer: null };
    const inputIds = ["automation-min-stars", "automation-max-stars", "automation-interval", "automation-daily-limit", "automation-baidu", "automation-quark", "automation-arch", "automation-share-days", "automation-share-code", "automation-private-share", "automation-enrich", "automation-remember", "automation-start-on-login"];
    function stopped() { return state.stopped || context.isStopped(); }
    function show(id, message) { if (stopped()) return; $(id).textContent = message || ""; $(id).hidden = !message; }
    function enabled() { return Boolean(state.status?.config?.enabled); }
    function capabilities() { return { credentialStorageSupported: Boolean(state.status?.credentialStorageSupported), startOnLoginSupported: Boolean(state.status?.startOnLoginSupported) }; }

    function applyConfig(config) {
      const value = { ...defaultConfig(context.getArch()), ...config };
      $("automation-min-stars").value = value.minStars ?? 0;
      $("automation-max-stars").value = value.maxStars ?? "";
      $("automation-interval").value = value.intervalHours;
      $("automation-daily-limit").value = value.dailyLimit;
      $("automation-arch").value = value.arch === "arm64" ? "arm64" : "amd64";
      $("automation-baidu").checked = value.providers?.includes("baidu") || false;
      $("automation-quark").checked = value.providers?.includes("quark") || false;
      $("automation-share-days").value = String(value.shareDays);
      $("automation-share-code").value = value.shareCode || "";
      $("automation-private-share").checked = value.privateShare !== false;
      $("automation-enrich").checked = Boolean(value.enrich);
      $("automation-remember").checked = Boolean(value.rememberCredentials && state.status?.credentialStorageSupported);
      $("automation-start-on-login").checked = Boolean(value.startOnLogin && state.status?.startOnLoginSupported);
      state.dirty = false;
      syncControls();
    }

    function readConfig(targetEnabled) {
      const value = { enabled: targetEnabled, intervalHours: $("automation-interval").value, minStars: $("automation-min-stars").value, maxStars: $("automation-max-stars").value, arch: $("automation-arch").value, providers: ["baidu", "quark"].filter((provider) => $("automation-" + provider).checked), dailyLimit: $("automation-daily-limit").value, shareDays: $("automation-share-days").value, shareCode: $("automation-share-code").value, privateShare: $("automation-private-share").checked, enrich: $("automation-enrich").checked, rememberCredentials: $("automation-remember").checked, startOnLogin: $("automation-start-on-login").checked };
      for (const id of inputIds) if ($(id).validity?.badInput) throw new Error("请输入有效的整数设置。");
      return validateConfig(value, capabilities());
    }

    function syncControls() {
      if (stopped()) return;
      const busy = Boolean(state.busy);
      for (const id of inputIds) $(id).disabled = busy;
      const ready = Boolean(state.status);
      $("automation-toggle").disabled = busy || !ready;
      $("automation-toggle").textContent = state.busy === "pause" ? "正在暂停…" : state.busy === "enable" ? "正在开启…" : enabled() ? "暂停无人值守" : "开启无人值守";
      $("automation-toggle").classList.toggle("button-primary", !enabled());
      $("automation-toggle").classList.toggle("button-secondary", enabled());
      $("automation-save").disabled = busy || !ready || !state.dirty;
      $("automation-save").textContent = state.busy === "save" ? "保存中…" : "保存设置";
      $("automation-reset").disabled = busy || !state.dirty || !ready;
      $("automation-run").disabled = busy || !ready || !enabled() || state.dirty || Boolean(state.status?.running);
      $("automation-run").textContent = state.busy === "run" || state.status?.running ? "扫描进行中…" : "立即扫描";
      $("automation-run").title = state.dirty ? "请先保存设置，再立即扫描。" : !enabled() ? "先开启无人值守，再立即扫描。" : "使用已保存的配置立即扫描。";
      $("automation-open").disabled = busy || !state.status?.exportDir;
      $("automation-refresh").disabled = busy || state.loading;
      $("automation-dirty-note").textContent = state.dirty ? "有未保存的修改；当前任务继续使用已保存配置。" : ready ? "设置已保存到本机。" : "正在读取本机设置。";
      const baidu = $("automation-baidu").checked;
      const anyProvider = baidu || $("automation-quark").checked;
      if (baidu) $("automation-private-share").checked = true;
      $("automation-private-share").disabled = busy || !anyProvider || baidu;
      $("automation-private-label").textContent = baidu ? "百度使用提取码分享" : "分享链接需要提取码";
      $("automation-share-code").disabled = busy || !baidu || !$("automation-private-share").checked;
      $("automation-share-days").disabled = busy || !anyProvider;
      $("automation-remember").disabled = busy || !state.status?.credentialStorageSupported;
      $("automation-start-on-login").disabled = busy || !state.status?.startOnLoginSupported;
      if (ready && !state.status.credentialStorageSupported) $("automation-remember").checked = false;
      if (ready && !state.status.startOnLoginSupported) $("automation-start-on-login").checked = false;
    }

    function renderStatus() {
      if (!state.status || stopped()) return;
      const status = state.status;
      $("automation-status").textContent = status.running ? enabled() ? "正在扫描" : "正在暂停" : enabled() ? "已开启" : "已暂停";
      $("automation-status").dataset.state = enabled() ? "enabled" : "paused";
      $("automation-next-run").textContent = enabled() ? date(status.nextRun) || "正在安排" : "已暂停";
      $("automation-last-run").textContent = date(status.lastRun) || "尚未扫描";
      $("automation-counts").textContent = [status.discovered, status.queued, status.unsupported].map((value) => Number.isFinite(Number(value)) ? Math.max(0, Number(value)) : 0).join(" / ");
      show("automation-last-error", status.lastError ? "最近自动处理提示：" + status.lastError : "");
      show("automation-credential-error", status.credentialError ? "凭据需要处理：" + status.credentialError : "");
      $("automation-storage-help").textContent = status.credentialStorageSupported ? "开启后使用 Windows DPAPI 在本机加密保存凭据，仅当前 Windows 用户可解密。凭据不会写入浏览器存储。" : "当前平台不支持 Windows DPAPI，凭据仅保留在当前工具进程中；退出后需重新连接。";
      $("automation-startup-help").textContent = status.startOnLoginSupported ? "登录 Windows 时在后台启动，不弹出浏览器。电脑须开机联网；勾选“记住凭据”可恢复网盘连接。" : "当前平台不支持 Windows 登录启动，只在本次工具进程运行期间自动处理。";
      $("automation-export").textContent = status.exportDir ? "自动资料目录：" + status.exportDir + " · JSON / CSV / Markdown" + (date(status.exportedAt) ? " · 最近写入 " + date(status.exportedAt) : " · 首个成果完成后写入") : "自动生成的资料目录待确认。";
      syncControls();
    }

    function acceptStatus(value, apply = false) {
      state.status = { ...state.status, ...value };
      if (apply || (!state.initialized && !state.dirty)) applyConfig(state.status.config);
      state.initialized = true;
      renderStatus();
      context.onStatus?.(state.status);
    }

    function schedulePoll() {
      clearTimeout(state.timer); state.timer = null;
      if (stopped() || !state.visible || document.hidden || state.loading || state.busy || state.failures >= 3 || (!enabled() && !state.status?.running)) return;
      state.timer = setTimeout(loadStatus, 2000);
    }

    async function loadStatus() {
      clearTimeout(state.timer); state.timer = null;
      if (stopped()) return;
      if (state.loading) { state.loadAgain = true; return; }
      state.loading = true; syncControls();
      const revision = state.revision;
      try {
        const value = await context.api("/api/automation", undefined, 20000);
        if (stopped() || revision !== state.revision) return;
        if (!value || !value.config || typeof value.config !== "object") throw new Error("自动化配置返回异常，请刷新重试。");
        state.failures = 0; show("automation-load-error", ""); acceptStatus(value);
      } catch (error) {
        state.failures++;
        show("automation-load-error", "无人值守状态暂时无法读取，手动功能仍可使用。" + error.message + (state.failures >= 3 ? " 请点击“刷新状态”重试。" : ""));
      } finally {
        state.loading = false; syncControls();
        if (state.loadAgain && !stopped()) { state.loadAgain = false; loadStatus(); } else schedulePoll();
      }
    }

    async function save(mode) {
      if (state.busy || !state.status || stopped()) return;
      let config;
      try { config = mode === "pause" ? { ...state.status.config, enabled: false } : readConfig(mode === "enable" ? true : enabled()); }
      catch (error) { show("automation-form-error", error.message); return; }
      const keepDraft = mode === "pause" && state.dirty;
      state.busy = mode; state.revision++; clearTimeout(state.timer); state.timer = null; syncControls();
      show("automation-form-error", ""); show("automation-save-note", "");
      try {
        const result = await context.api("/api/automation", config);
        if (stopped()) return;
        acceptStatus(result?.config ? result : { config }, !keepDraft);
        show("automation-save-note", mode === "pause" ? "无人值守已暂停，当前自动任务暂停，手动任务继续。" + (keepDraft ? " 未保存的编辑仍已保留。" : "") : mode === "enable" ? "无人值守已开启。首次请完成网盘授权，之后可关闭浏览器，保持工具运行。" : "配置已保存，后续自动处理使用此设置。");
        state.failures = 0;
        await loadStatus();
      } catch (error) { show("automation-form-error", "设置未能保存：" + error.message); }
      finally { state.busy = ""; syncControls(); schedulePoll(); }
    }

    async function action(name) {
      if (state.busy || !state.status || stopped()) return;
      if (name === "run" && (state.dirty || !enabled() || state.status.running)) return;
      state.busy = name; syncControls(); show("automation-form-error", "");
      try {
        const result = await context.api("/api/automation/" + name, {}, 30000);
        if (stopped()) return;
        if (name === "run") {
          if (result?.config) acceptStatus(result);
          show("automation-save-note", "已请求立即扫描。自动发现的游戏会加入目录和任务队列。"); await loadStatus();
        }
      } catch (error) { show("automation-form-error", (name === "open" ? "资料目录暂时无法打开：" : "扫描请求未完成：") + error.message); }
      finally { state.busy = ""; syncControls(); schedulePoll(); }
    }

    $("automation-form").addEventListener("submit", (event) => { event.preventDefault(); save("save"); });
    $("automation-form").addEventListener("input", () => { state.dirty = true; show("automation-save-note", ""); syncControls(); });
    $("automation-form").addEventListener("change", () => { state.dirty = true; show("automation-save-note", ""); syncControls(); });
    $("automation-toggle").addEventListener("click", () => save(enabled() ? "pause" : "enable"));
    $("automation-reset").addEventListener("click", () => { if (!state.busy && state.status) { applyConfig(state.status.config); show("automation-form-error", ""); } });
    $("automation-run").addEventListener("click", () => action("run"));
    $("automation-open").addEventListener("click", () => action("open"));
    $("automation-connections").addEventListener("click", () => context.openSettings());
    $("automation-refresh").addEventListener("click", () => { state.failures = 0; loadStatus(); });
    document.addEventListener("visibilitychange", () => { if (state.visible && !document.hidden && !stopped()) loadStatus(); else { clearTimeout(state.timer); state.timer = null; } });
    applyConfig(defaultConfig(context.getArch()));
    return {
      setVisible(visible) { state.visible = visible; clearTimeout(state.timer); state.timer = null; if (visible && !stopped()) { if (!state.initialized && !state.dirty) applyConfig(defaultConfig(context.getArch())); state.failures = 0; loadStatus(); } },
      refresh() { if (!stopped()) loadStatus(); },
      stop() { state.stopped = true; clearTimeout(state.timer); state.timer = null; },
    };
  }
  return { defaultConfig, validateConfig, taskNotice, create };
});
