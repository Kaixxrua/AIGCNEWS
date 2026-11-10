"use strict";

(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.PortShelfTransfers = api;
})(globalThis, function () {
  const providers = { baidu: "百度网盘", quark: "夸克网盘" };
  const statusLabels = { queued: "排队中", running: "进行中", waiting_auth: "等待连接网盘", failed: "未完成", partial: "部分完成", done: "已完成", cancelled: "已取消", paused: "已暂停" };
  const stageLabels = { release: "核对 Windows 附件", download: "下载到本机", description: "准备中文简介", upload: "上传网盘", share: "创建分享", done: "处理完成" };
  const activeStatuses = new Set(["queued", "running"]);
  const retryStatuses = new Set(["waiting_auth", "failed", "partial", "cancelled", "paused"]);
  const cancelStatuses = new Set(["queued", "running", "waiting_auth", "paused", "failed", "partial"]);

  function uniqueRepos(values) {
    const seen = new Set();
    return (Array.isArray(values) ? values : []).filter((repo) => {
      if (typeof repo !== "string" || !/^[a-zA-Z0-9_.-]+\/[a-zA-Z0-9_.-]+$/.test(repo) || seen.has(repo.toLowerCase())) return false;
      seen.add(repo.toLowerCase());
      return true;
    });
  }

  function transferBatches(repos, options) {
    const selected = uniqueRepos(repos);
    if (!selected.length) throw new Error("请先选择至少一款游戏。");
    if (!["amd64", "arm64"].includes(options.arch)) throw new Error("请选择 x64 或 ARM64 架构。");
    const shareDays = Number(options.shareDays);
    if (![0, 1, 7, 30].includes(shareDays)) throw new Error("请选择有效的分享期限。");
    const selectedProviders = [...new Set(options.providers || [])];
    if (selectedProviders.some((provider) => !Object.hasOwn(providers, provider))) throw new Error("网盘选项无效，请重新选择。");
    const privateShare = selectedProviders.includes("baidu") || options.privateShare !== false;
    const shareCode = privateShare && selectedProviders.includes("baidu") ? String(options.shareCode || "").trim() : "";
    if (shareCode && !/^[a-zA-Z0-9]{4}$/.test(shareCode)) throw new Error("百度提取码需为 4 位字母或数字，或留空自动生成。");
    const batches = [];
    for (let offset = 0; offset < selected.length; offset += 100) {
      batches.push({ repos: selected.slice(offset, offset + 100), providers: selectedProviders, arch: options.arch, shareDays, shareCode, privateShare, enrich: Boolean(options.enrich) });
    }
    return batches;
  }

  function shareURL(value, provider) {
    try {
      if (typeof value !== "string" || value.length > 8192 || /[\u0000-\u0020\u007f\\]/.test(value)) return null;
      const hostname = provider === "baidu" ? "pan.baidu.com" : provider === "quark" ? "pan.quark.cn" : null;
      const parts = /^https:\/\/([^/?#]+)(\/[^?#]*)(?:\?[^#]*)?$/.exec(value);
      if (!hostname || !parts || parts[1] !== hostname || !/^\/s\/[a-zA-Z0-9_-]+$/.test(parts[2])) return null;
      const url = new URL(value);
      const maxIdentifierLength = provider === "baidu" ? 128 : 256;
      if (parts[2].slice(3).length > maxIdentifierLength || url.hash || url.port || url.username || url.password) return null;
      return url.href;
    } catch (_) { return null; }
  }

  function progressOf(job) {
    const completed = Number.isFinite(Number(job.completedBytes)) ? Math.max(0, Number(job.completedBytes)) : 0;
    const total = Number.isFinite(Number(job.totalBytes)) ? Math.max(0, Number(job.totalBytes)) : 0;
    return { completed, total, percent: total > 0 ? Math.min(100, Math.floor(completed / total * 100)) : null };
  }

  function systemsLabel(value) {
    const systems = Array.isArray(value) ? [...new Set(value.filter((item) => typeof item === "string" && item.trim()).map((item) => item.trim()))] : [];
    return systems.length ? "支持系统：" + systems.join("、") : "支持系统待核实";
  }

  function materialFor(job) {
    const lines = [String(job.name || job.repo || "开源游戏"), "项目：" + String(job.repo || "")];
    if (job.version) lines.push("版本：" + job.version);
    if (job.arch) lines.push("Windows 架构：" + (job.arch === "arm64" ? "ARM64" : job.arch === "amd64" ? "x64" : job.arch));
    lines.push(systemsLabel(job.supportedSystems));
    if (job.description) lines.push("", String(job.description), "");
    if (job.dataNote) lines.push("游戏素材：" + job.dataNote);
    if (job.guide) lines.push("使用说明：" + job.guide);
    for (const [id, name] of Object.entries(providers)) {
      const output = job.outputs?.[id];
      const url = shareURL(output?.share?.url, id);
      if (!url) continue;
      lines.push(name + "：" + url);
      if (output.share.code) lines.push("提取码：" + output.share.code);
      if (output.share.expiresAt) lines.push("有效期至：" + output.share.expiresAt);
    }
    if (uniqueRepos([job.repo]).length) lines.push("上游项目：https://github.com/" + job.repo);
    if (job.sha256) lines.push("SHA-256：" + job.sha256);
    if (job.localDeletedAt) lines.push("本地文件：双盘完成后已清理，网盘分享资料保留。");
    return lines.join("\n");
  }

  function create(context) {
    const $ = (id) => document.getElementById(id);
    const state = { selected: new Set(), jobs: [], jobCards: new Map(), providers: {}, visible: false, loaded: false, stopped: false, pollTimer: null, pollBusy: false, pollAgain: false, pollFailures: 0, cloudBusy: false, enqueueBusy: false, actions: new Set(), authBusy: new Set(), authLoaded: false, authRevision: 0, exportBusy: false, clearBusy: false, folderBusy: false, archSet: false, downloadDir: "" };
    function node(tag, className, text) { const el = document.createElement(tag); if (className) el.className = className; if (text !== undefined && text !== null) el.textContent = String(text); return el; }
    function button(text, action, className = "button button-secondary button-small") { const el = node("button", className, text); el.type = "button"; el.addEventListener("click", action); return el; }
    function message(id, text) { if (state.stopped) return; $(id).textContent = text || ""; $(id).hidden = !text; }
    function isStopped() { return state.stopped || context.isStopped(); }
    function selectedProviders() { return Object.keys(providers).filter((id) => $("transfer-" + id).checked); }
    function size(value) { if (value < 1024) return value + " B"; if (value < 1024 ** 2) return (value / 1024).toFixed(1) + " KB"; if (value < 1024 ** 3) return (value / 1024 ** 2).toFixed(1) + " MB"; return (value / 1024 ** 3).toFixed(2) + " GB"; }
    function date(value) { const d = new Date(value); return Number.isFinite(d.getTime()) && d.getFullYear() > 1970 ? d.toLocaleString("zh-CN") : ""; }
    function safeLink(text, href) { const link = node("a", "", text); link.href = href; link.target = "_blank"; link.rel = "noopener noreferrer"; return link; }

    function visibleGames() {
      const games = $("transfer-use-filters").checked ? context.getFilteredGames() : context.getGames();
      const query = $("transfer-search").value.trim().toLocaleLowerCase();
      return games.filter((game) => !query || [game.repo, game.name, game.subtitle].some((value) => String(value || "").toLocaleLowerCase().includes(query)));
    }

    function syncSelection() {
      const visible = visibleGames();
      const visibleKeys = new Set(visible.map((game) => game.repo.toLowerCase()));
      const hiddenCount = [...state.selected].filter((repo) => !visibleKeys.has(repo)).length;
      $("transfer-selection-count").textContent = "已选 " + state.selected.size + " 款" + (hiddenCount ? "（含筛选外 " + hiddenCount + " 款）" : "");
      $("transfer-filter-summary").textContent = "当前可选 " + visible.length + " 款 / 目录共 " + context.getGames().length + " 款。" + ($("transfer-use-filters").checked ? "名称、类型与 Stars 范围沿用目录设置。" : "显示完整目录。") + " 更改筛选会保留已选游戏。";
      $("transfer-submit").disabled = state.enqueueBusy || !state.selected.size;
      $("transfer-submit").textContent = state.enqueueBusy ? "正在加入队列…" : "加入队列（" + state.selected.size + " 款）";
      $("transfer-select-visible").disabled = state.enqueueBusy || !visible.length;
      $("transfer-clear-selection").disabled = state.enqueueBusy || !state.selected.size;
      const anyProvider = selectedProviders().length > 0;
      const baiduSelected = $("transfer-baidu").checked;
      if (baiduSelected) $("transfer-private-share").checked = true;
      $("transfer-share-days").disabled = state.enqueueBusy || !anyProvider;
      $("transfer-private-share").disabled = state.enqueueBusy || !anyProvider || baiduSelected;
      $("transfer-private-label").textContent = baiduSelected ? "百度使用提取码分享" : "分享链接需要提取码";
      $("transfer-share-code").disabled = state.enqueueBusy || !$("transfer-baidu").checked || !$("transfer-private-share").checked;
    }

    function renderSelection() {
      if (isStopped()) return;
      const existing = new Set(context.getGames().map((game) => game.repo.toLowerCase()));
      [...state.selected].forEach((repo) => { if (!existing.has(repo)) state.selected.delete(repo); });
      const entries = visibleGames().map((game) => {
        const label = node("label", "transfer-game");
        const input = node("input"); input.type = "checkbox"; input.value = game.repo; input.checked = state.selected.has(game.repo.toLowerCase()); input.disabled = state.enqueueBusy;
        input.addEventListener("change", () => { if (input.checked) state.selected.add(game.repo.toLowerCase()); else state.selected.delete(game.repo.toLowerCase()); syncSelection(); });
        const info = node("span", "transfer-game-info"); info.append(node("strong", "", game.name || game.repo), node("small", "", game.subtitle || game.repo));
        label.append(input, info); return label;
      });
      if (!entries.length) entries.push(node("p", "transfer-selection-empty", context.getGames().length ? "当前筛选没有游戏，试试取消沿用目录筛选。" : "目录暂无游戏，请先到“发现更多”添加项目。"));
      $("transfer-game-list").replaceChildren(...entries);
      syncSelection();
    }

    function syncProviderState() {
      for (const [id, name] of Object.entries(providers)) {
        const provider = state.providers[id];
        const status = provider?.configured ? "已连接" + (provider.account ? " · " + provider.account : "") : state.authLoaded ? "未连接 · 可在设置中配置" : "尚未读取连接状态";
        $("transfer-" + id + "-state").textContent = status;
        const label = $("cloud-" + id + "-state");
        if (label) label.textContent = name + "：" + status;
        const clear = $("cloud-" + id + "-clear");
        if (clear) clear.disabled = state.authBusy.has(id) || !provider?.configured;
      }
    }

    async function loadProviders() {
      if (state.cloudBusy || isStopped()) return;
      state.cloudBusy = true;
      const revision = state.authRevision;
      try {
        const result = await context.api("/api/cloud", undefined, 20000);
        if (isStopped()) return;
        if (revision === state.authRevision) {
          for (const provider of result.providers || []) if (Object.hasOwn(providers, provider.id)) state.providers[provider.id] = provider;
          state.authLoaded = true;
        }
        if (result.downloadDir) state.downloadDir = String(result.downloadDir);
        syncProviderState(); renderDirectory(); message("cloud-settings-error", "");
      } catch (error) { message("cloud-settings-error", "网盘连接状态读取失败：" + error.message); }
      finally { state.cloudBusy = false; }
    }

    function renderDirectory() { if (!isStopped()) $("transfer-download-dir").textContent = state.downloadDir ? "本地下载目录：" + state.downloadDir : "本地下载目录待确认"; }

    async function copyText(value, trigger) {
      if (trigger.disabled) return;
      const original = trigger.textContent; trigger.disabled = true;
      try {
        if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(value);
        else {
          const input = node("textarea", "sr-only", value); input.readOnly = true; document.body.append(input); input.select();
          const copied = document.execCommand("copy"); input.remove(); if (!copied) throw new Error("copy failed"); trigger.focus();
        }
        trigger.textContent = "已复制"; context.notify("已复制，可粘贴到分享资料中。");
        setTimeout(() => { if (trigger.isConnected) trigger.textContent = original; }, 1600);
      } catch (_) { context.notify("浏览器未允许复制，请展开任务资料后手动选择复制。", true); }
      finally { trigger.disabled = false; }
    }

    function outputView(provider, output) {
      const row = node("div", "transfer-output");
      const head = node("div", "transfer-output-heading");
      const states = { uploaded: "已上传", share_failed: "分享未完成", shared: "已分享", done: "已完成", waiting_auth: "等待连接", failed: "未完成", skipped: "已跳过", running: "处理中", uploading: "上传中", pending: "等待处理", queued: "排队中" };
      head.append(node("strong", "", providers[provider]), node("span", "", states[output.status] || output.status || "等待处理")); row.append(head);
      const url = shareURL(output.share?.url, provider);
      if (url) {
        const share = node("div", "transfer-share"); share.append(safeLink("打开分享链接 ↗", url));
        const copy = button("复制链接与提取码", () => copyText(url + (output.share.code ? "\n提取码：" + output.share.code : ""), copy), "text-button"); share.append(copy); row.append(share);
        row.append(node("p", "transfer-share-url", url));
        if (output.share.code) row.append(node("p", "", "提取码：" + output.share.code));
        const expires = date(output.share.expiresAt); if (expires) row.append(node("p", "", "有效期至：" + expires));
      } else if (output.share?.url) row.append(node("p", "transfer-error", "分享地址不属于此网盘的可信域名，未提供可点击链接。"));
      if (output.file?.name || output.file?.path) row.append(node("p", "transfer-file-path", output.file.path || output.file.name));
      if (output.error) row.append(node("p", "transfer-error", output.error));
      return row;
    }

    function jobCard(job, openDetails) {
      const card = node("article", "transfer-job"); card.dataset.jobId = job.id;
      const heading = node("div", "transfer-job-heading");
      const title = node("div"); title.append(node("h3", "", job.name || job.repo), node("p", "transfer-job-meta", [job.repo, job.version, job.arch === "amd64" ? "Windows x64" : job.arch === "arm64" ? "Windows ARM64" : job.arch].filter(Boolean).join(" · ")));
      const status = node("span", "transfer-status", statusLabels[job.status] || "未知状态"); status.dataset.status = job.status; heading.append(title, status); card.append(heading);
      card.append(node("p", "transfer-systems", systemsLabel(job.supportedSystems)));
      const automatic = globalThis.PortShelfAutomation?.taskNotice(job);
      if (automatic) {
        const automation = node("div", "transfer-automation"); automation.dataset.kind = automatic.kind;
        automation.append(node("span", "tag", "自动任务"), node("span", "", automatic.attempts));
        if (automatic.text) automation.append(node("p", "", automatic.text));
        card.append(automation);
      }
      const currentStage = job.status === "waiting_auth" ? "等待连接网盘" : stageLabels[job.stage] || "等待处理";
      const stage = node("p", "transfer-stage", currentStage + (providers[job.provider] ? " · " + providers[job.provider] : "")); card.append(stage);
      if (["download", "upload"].includes(job.stage) && job.status === "running") {
        const data = progressOf(job); const meter = node("progress", "transfer-progress"); meter.max = data.total || 1; if (data.total) meter.value = Math.min(data.completed, data.total);
        meter.setAttribute("aria-label", currentStage + "进度");
        card.append(meter, node("p", "transfer-progress-text", data.total ? data.percent + "% · " + size(data.completed) + " / " + size(data.total) : size(data.completed) + " · 总大小待确认"));
      }
      if (job.error) card.append(node("p", "transfer-error", job.error));
      if (Array.isArray(job.warnings) && job.warnings.length) { const warnings = node("ul", "transfer-warnings"); job.warnings.forEach((warning) => warnings.append(node("li", "", warning))); card.append(warnings); }
      if (job.localDeletedAt) card.append(node("p", "transfer-local-path", "本地文件已自动清理 · 百度与夸克分享资料保留"));
      else if (job.downloadPath) card.append(node("p", "transfer-local-path", "已下载：" + job.downloadPath));
      if (!job.localDeletedAt && job.localCleanupError) card.append(node("p", "transfer-error", "本地清理：" + job.localCleanupError));
      else if (!job.localDeletedAt && job.localCleanupPending && ["done", "partial"].includes(job.status)) card.append(node("p", "transfer-local-path", "两盘已完成，正在核对并清理本地文件…"));
      const outputs = node("div", "transfer-outputs");
      for (const provider of Object.keys(providers)) if (job.outputs?.[provider]) outputs.append(outputView(provider, job.outputs[provider]));
      if (outputs.childElementCount) card.append(outputs);
      const details = node("details", "transfer-material"); details.open = openDetails;
      details.append(node("summary", "", "查看中文资料与校验信息"), node("pre", "", materialFor(job))); card.append(details);
      const actions = node("div", "transfer-job-actions");
      const copying = button("复制分享资料", () => copyText(materialFor(job), copying)); actions.append(copying);
      if (job.downloadPath && !job.localDeletedAt) { const folder = button("打开所在目录", () => openFolder(job.id)); folder.disabled = state.folderBusy; actions.append(folder); }
      if (job.status === "waiting_auth") actions.append(button("配置网盘连接", openSettings));
      if (retryStatuses.has(job.status)) { const retry = button(state.actions.has(job.id) ? "处理中…" : ["paused", "waiting_auth"].includes(job.status) ? "继续任务" : "重试任务", () => jobAction(job.id, "retry")); retry.disabled = state.actions.has(job.id); actions.append(retry); }
      if (cancelStatuses.has(job.status)) { const cancel = button(state.actions.has(job.id) ? "处理中…" : "取消任务", () => jobAction(job.id, "cancel"), "text-button"); cancel.disabled = state.actions.has(job.id); actions.append(cancel); }
      card.append(actions);
      const updated = date(job.updatedAt); if (updated) card.append(node("p", "transfer-job-time", "更新于 " + updated));
      return card;
    }

    function renderJobs() {
      if (isStopped()) return;
      const active = state.jobs.filter((job) => activeStatuses.has(job.status)).length;
      const finished = state.jobs.filter((job) => job.status === "done").length;
      const attention = state.jobs.filter((job) => ["failed", "partial", "waiting_auth", "paused"].includes(job.status)).length;
      $("cloud-nav-count").textContent = active || state.jobs.length;
      $("transfer-queue-summary").textContent = "共 " + state.jobs.length + " 项 · 处理中 " + active + " · 已完成 " + finished + " · 待处理 " + attention + (active ? " · 每 2 秒更新" : "");
      const container = $("transfer-jobs");
      const keep = new Set(state.jobs.map((job) => job.id));
      for (const [id, cached] of state.jobCards) if (!keep.has(id)) { cached.card.remove(); state.jobCards.delete(id); }
      state.jobs.forEach((job, index) => {
        const previous = state.jobCards.get(job.id);
        const signature = JSON.stringify([job, state.actions.has(job.id), state.folderBusy]);
        let card = previous?.card;
        if (!previous || previous.signature !== signature) {
          const focusIndex = card?.contains(document.activeElement) ? [...card.querySelectorAll("button,a,summary")].indexOf(document.activeElement) : -1;
          const replacement = jobCard(job, Boolean(card?.querySelector("details")?.open));
          if (card?.isConnected) card.replaceWith(replacement);
          card = replacement;
          state.jobCards.set(job.id, { card, signature });
          if (focusIndex >= 0) card.querySelectorAll("button,a,summary")[focusIndex]?.focus({ preventScroll: true });
        }
        if (container.children[index] !== card) container.insertBefore(card, container.children[index] || null);
      });
      $("transfer-empty").hidden = state.jobs.length > 0 || !state.loaded;
      $("transfer-export").disabled = state.exportBusy || !state.jobs.some((job) => job.downloadPath || Object.values(job.outputs || {}).some((output) => output?.file?.id || output?.share?.url));
      $("transfer-clear-history").disabled = state.clearBusy || !state.jobs.some((job) => ["done", "cancelled"].includes(job.status));
      renderDirectory();
    }

    function schedulePoll() {
      clearTimeout(state.pollTimer); state.pollTimer = null;
      if (isStopped() || !state.visible || document.hidden || state.pollBusy || state.pollFailures >= 3 || !state.jobs.some((job) => activeStatuses.has(job.status) || globalThis.PortShelfAutomation?.taskNotice(job)?.pendingRetry || job.localCleanupPending && !job.localDeletedAt && !job.localCleanupError && ["done", "partial"].includes(job.status))) return;
      state.pollTimer = setTimeout(loadJobs, 2000);
    }

    async function loadJobs() {
      clearTimeout(state.pollTimer); state.pollTimer = null;
      if (isStopped()) return;
      if (state.pollBusy) { state.pollAgain = true; return; }
      state.pollBusy = true; $("transfer-refresh").disabled = true;
      try {
        const result = await context.api("/api/transfers", undefined, 20000);
        if (isStopped()) return;
        state.jobs = Array.isArray(result.jobs) ? result.jobs.filter((job) => job && typeof job.id === "string") : [];
        state.downloadDir = String(result.downloadDir || state.downloadDir);
        state.loaded = true; state.pollFailures = 0;
        message("transfer-poll-error", ""); message("transfer-store-error", result.storeError ? "任务记录保存异常：" + result.storeError + "。已完成结果仍会显示，请及时导出。" : ""); renderJobs();
      } catch (error) { state.pollFailures++; message("transfer-poll-error", "任务状态读取失败，已保留上次结果。" + error.message + (state.pollFailures >= 3 ? " 请点击“刷新任务”重试。" : "")); }
      finally {
        state.pollBusy = false;
        if (!isStopped()) $("transfer-refresh").disabled = false;
        if (state.pollAgain && !isStopped()) { state.pollAgain = false; loadJobs(); }
        else schedulePoll();
      }
    }

    async function enqueue(event) {
      event.preventDefault(); if (state.enqueueBusy || isStopped()) return;
      let batches;
      try {
        const repos = context.getGames().filter((game) => state.selected.has(game.repo.toLowerCase())).map((game) => game.repo);
        batches = transferBatches(repos, { providers: selectedProviders(), arch: $("transfer-arch").value, shareDays: $("transfer-share-days").value, shareCode: $("transfer-share-code").value, privateShare: $("transfer-private-share").checked, enrich: $("transfer-enrich").checked });
      } catch (error) { message("transfer-enqueue-error", error.message); return; }
      state.enqueueBusy = true; message("transfer-enqueue-error", "");
      $("transfer-form").querySelectorAll("input,select,button").forEach((input) => { input.disabled = true; }); syncSelection();
      let added = 0; let skipped = 0; let processed = 0;
      try {
        for (const batch of batches) {
          if (isStopped()) break;
          message("transfer-enqueue-note", "正在提交 " + (processed + 1) + "–" + (processed + batch.repos.length) + " 款…");
          const result = await context.api("/api/transfers", batch);
          if (!Array.isArray(result.added) || !Array.isArray(result.skipped)) throw new Error("队列响应无效，请刷新任务核对已加入的项目。");
          added += result.added.length; skipped += result.skipped.length; processed += batch.repos.length;
          batch.repos.forEach((repo) => state.selected.delete(repo.toLowerCase()));
        }
        message("transfer-enqueue-note", "已加入 " + added + " 项，跳过已有任务 " + skipped + " 项。下载与分享会在工具运行期间继续处理。");
      } catch (error) { message("transfer-enqueue-error", "本次已加入 " + added + " 项，跳过 " + skipped + " 项，其余选择已保留。" + error.message); }
      finally {
        state.enqueueBusy = false;
        if (!isStopped()) { $("transfer-form").querySelectorAll("input,select,button").forEach((input) => { input.disabled = false; }); renderSelection(); await loadJobs(); }
      }
    }

    async function jobAction(id, action) {
      if (state.actions.has(id) || isStopped()) return;
      state.actions.add(id); renderJobs();
      try { await context.api("/api/transfers/" + encodeURIComponent(id) + "/" + action, {}); await loadJobs(); context.notify(action === "cancel" ? "已请求取消任务，已完成的下载和分享记录会保留。" : "任务已重新排队。"); }
      catch (error) { context.notify(error.message, true); }
      finally { state.actions.delete(id); renderJobs(); schedulePoll(); }
    }

    async function openFolder(id) {
      if (state.folderBusy || isStopped()) return;
      state.folderBusy = true; $("transfer-open-folder").disabled = true; renderJobs();
      try { await context.api("/api/transfers/open", id ? { id } : {}, 15000); }
      catch (error) { context.notify("无法打开下载目录：" + error.message, true); }
      finally { state.folderBusy = false; if (!isStopped()) $("transfer-open-folder").disabled = false; renderJobs(); }
    }

    async function exportArtifacts() {
      if (state.exportBusy || isStopped()) return;
      state.exportBusy = true; renderJobs();
      try { await context.exportFile($("transfer-export-format").value); context.notify("分享资料已导出，包含已完成的本地文件与网盘结果。"); }
      catch (error) { context.notify("导出失败：" + error.message, true); }
      finally { state.exportBusy = false; renderJobs(); }
    }

    async function clearHistory() {
      if (state.clearBusy || isStopped()) return;
      state.clearBusy = true; renderJobs();
      try { await context.api("/api/transfers/clear", {}); await loadJobs(); context.notify("已清理完成和取消的任务记录，本地文件与网盘文件仍保留。"); }
      catch (error) { context.notify("清理历史失败：" + error.message, true); }
      finally { state.clearBusy = false; renderJobs(); }
    }

    function clearCredentials() {
      document.querySelectorAll("#cloud-provider-settings input").forEach((input) => { input.value = ""; });
      const authorization = $("cloud-quark-authorization"); if (authorization) authorization.replaceChildren();
    }

    function openSettings() {
      context.openSettings();
      $("cloud-settings").scrollIntoView({ block: "start" });
      $("cloud-baidu-credential")?.focus({ preventScroll: true });
    }

    async function saveProvider(id, clear = false) {
      if (state.authBusy.has(id) || isStopped()) return;
      const input = $("cloud-" + id + "-credential");
      const value = clear ? "" : input.value.trim();
      if (!clear && !value) { message("cloud-" + id + "-error", "请填写" + (id === "baidu" ? " Cookie" : "授权码") + "，或点击清除连接。"); return; }
      state.authBusy.add(id); message("cloud-" + id + "-error", "");
      state.authRevision++;
      const form = $("cloud-" + id + "-form"); form.querySelectorAll("button,input").forEach((item) => { item.disabled = true; });
      $("cloud-" + id + "-submit").textContent = clear ? "正在清除…" : "正在验证…";
      try {
        const result = await context.api("/api/cloud/" + id, clear ? { cookie: "", accessToken: "", authCode: "" } : id === "baidu" ? { cookie: value } : { authCode: value });
        if (isStopped()) return;
        state.providers[id] = result.provider || result; state.authLoaded = true;
        input.value = "";
        if (id === "quark") $("cloud-quark-authorization").replaceChildren();
        context.notify(clear ? providers[id] + "凭据已清除。" : providers[id] + "连接已验证，凭据按无人值守设置保管。");
        await loadJobs();
      } catch (error) { message("cloud-" + id + "-error", error.message); }
      finally {
        input.value = ""; state.authBusy.delete(id);
        form.querySelectorAll("button,input").forEach((item) => { item.disabled = false; }); $("cloud-" + id + "-submit").textContent = "验证并连接"; syncProviderState();
      }
    }

    async function authorizeQuark() {
      const trigger = $("cloud-quark-authorize"); if (trigger.disabled || isStopped()) return;
      trigger.disabled = true; message("cloud-quark-error", "");
      try {
        const result = await context.api("/api/cloud/quark/authorize", {}, 35000);
        if (isStopped() || !$("settings-dialog").open) return;
        const url = authorizationURL(result.url);
        if (!url) throw new Error("授权地址不是受信任的夸克官方页面，请重新获取。");
        $("cloud-quark-authorization").replaceChildren(safeLink("打开夸克官方授权页 ↗", url), node("p", "field-help", "授权后复制页面提供的授权码，回到下方粘贴。"));
      } catch (error) { message("cloud-quark-error", error.message); }
      finally { trigger.disabled = false; }
    }

    function renderAuthForms() {
      const forms = Object.entries(providers).map(([id, name]) => {
        const form = node("form", "cloud-provider-form"); form.id = "cloud-" + id + "-form";
        const status = node("div", "token-state"); status.id = "cloud-" + id + "-state";
        form.append(node("h4", "", name), status);
        if (id === "baidu") {
          form.append(safeLink("打开百度网盘网页登录 ↗", "https://pan.baidu.com/disk/main"));
          const guide = node("details", "credential-guide"); guide.append(node("summary", "", "如何在本机获取 Cookie"));
          const steps = node("ol");
          ["在自己的浏览器中打开并登录百度网盘网页版。", "按 F12 打开开发者工具，选择“网络 / Network”，刷新网盘页面。", "选择发送到 pan.baidu.com 的已登录请求，在“请求标头 / Request Headers”中复制 Cookie 的值。", "只把值粘贴到下方本地输入框并连接。不要发送到聊天、截图或分享资料中。"].forEach((step) => steps.append(node("li", "", step)));
          guide.append(steps); form.append(guide);
        } else {
          const auth = button("获取夸克官方授权页", authorizeQuark); auth.id = "cloud-quark-authorize";
          const target = node("div", "cloud-authorization"); target.id = "cloud-quark-authorization"; form.append(auth, target);
        }
        const label = node("label", "field-label", id === "baidu" ? "百度网盘 Cookie" : "夸克官方授权码 AuthCode"); label.htmlFor = "cloud-" + id + "-credential";
        const input = node("input"); input.id = label.htmlFor; input.type = "password"; input.autocomplete = "off"; input.spellcheck = false; input.maxLength = 12000; input.placeholder = id === "baidu" ? "仅在本机粘贴 Cookie" : "粘贴授权页提供的 AuthCode";
        const error = node("p", "form-error"); error.id = "cloud-" + id + "-error"; error.setAttribute("role", "alert"); error.hidden = true;
        const actions = node("div", "dialog-actions"); const clear = button("清除连接", () => saveProvider(id, true)); clear.id = "cloud-" + id + "-clear";
        const submit = node("button", "button button-primary", "验证并连接"); submit.type = "submit"; submit.id = "cloud-" + id + "-submit"; actions.append(clear, submit);
        form.append(label, input, node("p", "field-help", "保存后清空输入，不存浏览器。默认仅在进程内存保留；Windows 可在无人值守设置中启用 DPAPI 本机加密保存。"), error, actions);
        form.addEventListener("submit", (event) => { event.preventDefault(); saveProvider(id); });
        return form;
      });
      $("cloud-provider-settings").replaceChildren(...forms); syncProviderState();
    }

    $("transfer-search").addEventListener("input", renderSelection);
    $("transfer-use-filters").addEventListener("change", renderSelection);
    $("transfer-select-visible").addEventListener("click", () => { visibleGames().forEach((game) => state.selected.add(game.repo.toLowerCase())); renderSelection(); });
    $("transfer-clear-selection").addEventListener("click", () => { state.selected.clear(); renderSelection(); });
    ["transfer-baidu", "transfer-quark", "transfer-private-share"].forEach((id) => $(id).addEventListener("change", syncSelection));
    $("transfer-form").addEventListener("submit", enqueue);
    $("transfer-auth-open").addEventListener("click", openSettings);
    $("transfer-refresh").addEventListener("click", () => { state.pollFailures = 0; loadJobs(); loadProviders(); });
    $("transfer-open-folder").addEventListener("click", () => openFolder());
    $("transfer-export").addEventListener("click", exportArtifacts);
    $("transfer-clear-history").addEventListener("click", clearHistory);
    document.addEventListener("visibilitychange", () => { if (!document.hidden && state.visible) loadJobs(); else { clearTimeout(state.pollTimer); state.pollTimer = null; } });
    renderAuthForms();
    return {
      setVisible(visible) { state.visible = visible; clearTimeout(state.pollTimer); state.pollTimer = null; if (visible && !isStopped()) { renderSelection(); state.pollFailures = 0; loadJobs(); loadProviders(); } },
      updateLibrary() { if (!state.archSet && context.getArch()) { $("transfer-arch").value = context.getArch() === "arm64" ? "arm64" : "amd64"; state.archSet = true; } if (state.visible) renderSelection(); },
      settingsOpened() { if (!isStopped()) loadProviders(); },
      refresh() { if (state.visible && !isStopped()) loadJobs(); },
      clearCredentials,
      stop() { state.stopped = true; clearTimeout(state.pollTimer); state.pollTimer = null; clearCredentials(); },
    };
  }

  function authorizationURL(value) {
    try {
      if (typeof value !== "string" || value.length > 8192 || /[\u0000-\u0020\u007f\\]/.test(value)) return null;
      if (!/^https:\/\/pan\.quark\.cn\/open\/v1\/oauth\/agent(?:\?[^#]*)?(?:#(?:\/agent-oauth)?)?$/.test(value)) return null;
      const url = new URL(value);
      if (url.protocol !== "https:" || url.hostname !== "pan.quark.cn" || url.pathname !== "/open/v1/oauth/agent" || url.port || url.username || url.password || (url.hash && url.hash !== "#/agent-oauth") || !url.searchParams.get("page_code")) return null;
      const keys = [...url.searchParams.keys()];
      if (new Set(keys).size !== keys.length || keys.some((key) => !["device_id", "device_name", "agent_id", "page_code"].includes(key))) return null;
      return url.href;
    } catch (_) { return null; }
  }

  return { uniqueRepos, transferBatches, shareURL, authorizationURL, progressOf, systemsLabel, materialFor, create };
});
