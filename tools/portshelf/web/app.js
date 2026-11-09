"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const state = {
    games: [], snapshots: {}, category: "all", query: "", sort: "stars", view: "grid", minStars: null, maxStars: null,
    page: "library", hasToken: false, hasAigcToken: false, descriptions: {}, refreshing: false, polling: null, pollBusy: false,
    selected: null, allAssets: false, searchResults: [], searchBusy: false, stopped: false,
    discovery: { range: null, nextPage: 1, page: 0, hasMore: false, totalCandidates: 0, incomplete: false, limitReached: false, error: "", lastAdded: 0 },
    batch: null, singleAdds: new Set(), manualAddBusy: false, confirmedGames: new Map(),
    descriptionRequests: new Set(), descriptionReadQueue: new Set(), descriptionReadBusy: false, descriptionPollTargets: new Map(), descriptionPollTimer: null, descriptionPollAfter: 3, descriptionBatch: null,
    loaded: false, toastTimer: null, activeRefresh: null,
  };
  const numberFormat = new Intl.NumberFormat("zh-CN");
  const colors = new Set(["forest", "violet", "coral", "red", "ember", "teal", "slate", "sand", "ochre"]);
  let sessionToken = "";

  function readSession() {
    const hash = location.hash.slice(1);
    try { sessionToken = sessionStorage.getItem("portshelf-session") || ""; } catch (_) { /* Memory remains available. */ }
    if (!/^[a-f0-9]{48}$/.test(sessionToken)) sessionToken = "";
    const candidate = hash.startsWith("token=") ? new URLSearchParams(hash).get("token") || "" : hash;
    if (/^[a-f0-9]{48}$/.test(candidate)) {
      sessionToken = candidate;
      try { sessionStorage.setItem("portshelf-session", sessionToken); } catch (_) { /* Opening the executable supplies a fresh session. */ }
      history.replaceState(null, "", location.pathname + location.search);
    }
  }

  function element(tag, className, content) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (content !== undefined && content !== null) node.textContent = String(content);
    return node;
  }

  function descriptionOf(game) {
    const record = state.descriptions[repositoryKey(game.repo)];
    const enriched = record?.status === "ready" && record.descriptionZh ? { ...game, descriptionZh: record.descriptionZh, descriptionSource: "aigcnews" } : game;
    try {
      const description = globalThis.PortShelfDescriptions?.describe(enriched);
      if (description && typeof description.text === "string" && description.text.trim()) {
        return { text: description.text, source: description.source, original: typeof description.original === "string" ? description.original : "" };
      }
    } catch (_) { /* The directory remains usable if description enrichment is unavailable. */ }
    if (enriched.descriptionZh) return { text: enriched.descriptionZh, source: "aigcnews", original: typeof game.description === "string" ? game.description : "" };
    const original = typeof game.description === "string" ? game.description : "";
    if (/[\u3400-\u9fff]/.test(original)) return { text: original, source: "upstream", original: "" };
    return { text: "中文简介待补充，可查看上游项目了解游戏内容。", source: "unknown", original };
  }

  function descriptionSource(description) {
    if (description.source === "aigcnews") return "AIGCNEWS 中文简介";
    if (description.source === "summary") return "按上游信息整理";
    if (description.source === "unknown") return "信息待补充";
    return "";
  }

  function descriptionNodes(game, className, showOriginal = false) {
    const description = descriptionOf(game);
    const nodes = [element("p", className, description.text)];
    const source = descriptionSource(description);
    if (source) nodes.push(element("span", "description-source", source));
    const record = state.descriptions[repositoryKey(game.repo)];
    if (record?.status === "ready" && record.error) nodes.push(element("span", "description-error", "暂用已缓存的中文简介：" + record.error));
    if (showOriginal && description.original.trim() && description.original.trim() !== description.text.trim()) {
      const original = element("details", "original-description");
      original.append(element("summary", "", "查看上游原文"), element("p", "", description.original));
      nodes.push(original);
    }
    const control = descriptionControl(game);
    if (control) nodes.push(control);
    return nodes;
  }

  function repositoryKey(repo) { return String(repo || "").toLowerCase(); }
  function isInLibrary(repo) { return state.games.some((game) => repositoryKey(game.repo) === repositoryKey(repo)); }

  function rememberGames(repos) {
    const candidates = new Map(state.searchResults.map((game) => [repositoryKey(game.repo), game]));
    const known = new Set(state.games.map((game) => repositoryKey(game.repo)));
    for (const repo of repos) {
      const key = repositoryKey(repo);
      const game = candidates.get(key);
      if (!game) continue;
      state.confirmedGames.set(key, game);
      if (!known.has(key)) { state.games.push(game); known.add(key); }
    }
  }

  function needsDescription(game) {
    const record = state.descriptions[repositoryKey(game.repo)];
    if (record?.status === "ready" && record.descriptionZh) return false;
    return descriptionOf(game).source === "unknown";
  }

  function descriptionControl(game, compact = false) {
    if (!needsDescription(game)) return null;
    const key = repositoryKey(game.repo);
    const record = state.descriptions[key];
    const pending = record?.status === "pending";
    const requesting = state.descriptionRequests.has(key);
    const wrapper = element("span", "description-control" + (compact ? " compact" : ""));
    const button = element("button", "description-button", requesting ? "正在提交…" : pending ? "核对生成进度" : record?.status === "failed" ? "重试中文简介" : "生成中文简介");
    button.type = "button";
    button.dataset.descriptionRepo = key;
    button.disabled = requesting || Boolean(state.descriptionBatch?.running);
    if (pending) wrapper.append(element("span", "description-pending", "中文简介生成中"));
    button.addEventListener("click", () => {
      if (state.descriptionRequests.has(key) || state.descriptionBatch?.running) return;
      if (pending) { queueDescriptionRead([game.repo], true); return; }
      if (!state.hasAigcToken) { openAigcSettings(); return; }
      generateDescription(game);
    });
    wrapper.append(button);
    if (!compact && record?.error) wrapper.append(element("span", "description-error", record.error));
    return wrapper;
  }

  function descriptionNotice(message) {
    if (state.stopped) return;
    $("description-notice").textContent = message;
    $("description-notice").hidden = !message;
  }

  function descriptionError(error) {
    const explanations = { 401: "请设置或更新 AIGCNEWS MCP Token。", 403: "此 AIGCNEWS Token 暂无中文简介生成权限。", 429: "AIGCNEWS 额度或请求频率已达限制，已停止后续提交。", 404: "AIGCNEWS 中文简介服务暂未开放，请稍后重试。", 503: "AIGCNEWS 中文简介服务暂不可用，请稍后重试。" };
    return (explanations[error.status] || "") + (error.message || "中文简介请求未完成，请稍后重试。");
  }

  function openAigcSettings() {
    showError("aigc-token-error", "请先设置独立的 AIGCNEWS MCP Token，再生成中文简介。");
    $("aigc-token-input").value = "";
    renderStats();
    if (!$("settings-dialog").open) $("settings-dialog").showModal();
    $("aigc-token-input").focus();
  }

  function mergeDescriptions(items) {
    if (!Array.isArray(items)) return;
    for (const item of items) {
      if (!item || !repoURL(item.repo) || !["ready", "pending", "missing", "failed"].includes(item.status)) continue;
      const key = repositoryKey(item.repo);
      const previous = state.descriptions[key];
      if (previous?.status === "ready" && previous.descriptionZh && item.status !== "ready") {
        if (item.error) state.descriptions[key] = { ...previous, error: String(item.error) };
        continue;
      }
      if (previous?.status === "pending" && item.status === "missing") continue;
      state.descriptions[key] = { ...item, descriptionZh: typeof item.descriptionZh === "string" ? item.descriptionZh : "", error: typeof item.error === "string" ? item.error : "" };
      if (item.status === "pending") {
        if (!state.descriptionPollTargets.has(key)) state.descriptionPollTargets.set(key, 0);
      } else state.descriptionPollTargets.delete(key);
    }
  }

  function updateDescriptionViews() {
    if (state.stopped) return;
    if (state.loaded) renderGames();
    if (state.selected) renderDetails();
    if (state.discovery.range) renderSearchResults();
    syncDiscoveryControls();
  }

  function queueDescriptionRead(repos, resetPoll = false) {
    if (state.stopped) return;
    for (const repo of repos) {
      if (!repoURL(repo)) continue;
      const key = repositoryKey(repo);
      if (resetPoll && state.descriptionPollTargets.has(key)) state.descriptionPollTargets.set(key, 0);
      state.descriptionReadQueue.add(key);
    }
    if (!state.descriptionReadBusy) drainDescriptionReads();
  }

  async function drainDescriptionReads() {
    if (state.descriptionReadBusy || state.stopped) return;
    state.descriptionReadBusy = true;
    try {
      while (state.descriptionReadQueue.size && !state.stopped) {
        const repos = Array.from(state.descriptionReadQueue).slice(0, 50);
        repos.forEach((repo) => state.descriptionReadQueue.delete(repo));
        const result = await api("/api/descriptions?repos=" + encodeURIComponent(repos.join(",")), undefined, 30000);
        if (state.stopped) return;
        mergeDescriptions(result.items);
        state.descriptionPollAfter = Math.min(15, Math.max(3, Number(result.pollAfter) || 3));
        updateDescriptionViews();
      }
    } catch (error) {
      state.descriptionReadQueue.clear();
      descriptionNotice("已有中文简介读取未完成，不影响游戏浏览。" + descriptionError(error));
    } finally {
      state.descriptionReadBusy = false;
      scheduleDescriptionPoll();
    }
  }

  function scheduleDescriptionPoll() {
    if (state.stopped || state.descriptionPollTimer || state.descriptionReadBusy) return;
    const pending = Array.from(state.descriptionPollTargets).filter(([repo, attempts]) => attempts < 20 && state.descriptions[repo]?.status === "pending" && repo !== state.descriptionBatch?.waiting);
    if (!pending.length) {
      if (Array.from(state.descriptionPollTargets.values()).some((attempts) => attempts >= 20)) descriptionNotice("部分中文简介仍在生成，自动核对已暂歇。可点击游戏旁的“核对生成进度”继续查看。");
      return;
    }
    state.descriptionPollTimer = setTimeout(() => {
      state.descriptionPollTimer = null;
      const repos = [];
      for (const [repo, attempts] of state.descriptionPollTargets) {
        if (attempts < 20 && state.descriptions[repo]?.status === "pending" && repo !== state.descriptionBatch?.waiting) { state.descriptionPollTargets.set(repo, attempts + 1); repos.push(repo); }
      }
      queueDescriptionRead(repos);
    }, state.descriptionPollAfter * 1000);
  }

  async function requestDescription(game) {
    const key = repositoryKey(game.repo);
    state.descriptionRequests.add(key);
    updateDescriptionViews();
    try {
      const result = await api("/api/descriptions", { repo: game.repo });
      if (state.stopped) return;
      mergeDescriptions(result.items);
      state.descriptionPollAfter = Math.min(15, Math.max(3, Number(result.pollAfter) || 3));
      const record = state.descriptions[key];
      if (!record || record.status === "missing") throw new Error("服务未确认中文简介任务，请稍后重试。");
      return record;
    } catch (error) {
      if (!state.stopped && state.descriptions[key]?.status !== "ready") state.descriptions[key] = { repo: game.repo, status: "failed", error: descriptionError(error) };
      throw error;
    } finally {
      state.descriptionRequests.delete(key);
      updateDescriptionViews();
      scheduleDescriptionPoll();
    }
  }

  async function generateDescription(game) {
    if (state.stopped || state.descriptionRequests.has(repositoryKey(game.repo)) || state.descriptionBatch?.running) return;
    if (!needsDescription(game)) return;
    if (state.descriptions[repositoryKey(game.repo)]?.status === "pending") { queueDescriptionRead([game.repo], true); return; }
    if (!state.hasAigcToken) { openAigcSettings(); return; }
    try {
      const record = await requestDescription(game);
      if (state.stopped) return;
      if (record.status === "failed") { descriptionNotice(record.error || "中文简介生成未完成，可稍后重试。"); notify(record.error || "中文简介生成未完成，可稍后重试。", true); }
      else { descriptionNotice(""); notify(record.status === "ready" ? "AIGCNEWS 中文简介已更新。" : "已提交中文简介生成，完成后会自动显示。"); }
    } catch (error) { descriptionNotice(descriptionError(error)); notify(descriptionError(error), true); }
  }

  function renderDescriptionProgress() {
    const batch = state.descriptionBatch;
    $("description-progress-panel").hidden = !batch;
    if (!batch) return;
    $("description-progress-label").textContent = (batch.running ? batch.stopRequested ? "等待当前提交结束" : "正在补全中文简介" : batch.stopRequested ? "已停止提交" : batch.interrupted ? "中文简介提交已中断" : "中文简介提交完成") + " · 已处理 " + batch.done + " / " + batch.total + " · 已接受 " + batch.accepted + " · 失败 " + batch.failed;
    $("description-progress-note").textContent = batch.note || "已有中文或正在生成的项目自动跳过。生成由 AIGCNEWS 完成，列表会自动核对进度。";
    $("descriptions-stop").hidden = !batch.running;
    $("descriptions-stop").disabled = batch.stopRequested;
  }

  async function waitForQueuedDescription(game, batch) {
    const key = repositoryKey(game.repo);
    batch.waiting = key;
    try {
      for (let attempt = 0; attempt < 20; attempt++) {
        if (batch.stopRequested || state.stopped) return state.descriptions[key];
        await new Promise((resolve) => setTimeout(resolve, state.descriptionPollAfter * 1000));
        if (batch.stopRequested || state.stopped) return state.descriptions[key];
        const result = await api("/api/descriptions?repos=" + encodeURIComponent(game.repo), undefined, 30000);
        if (state.stopped) return state.descriptions[key];
        mergeDescriptions(result.items);
        const record = state.descriptions[key];
        state.descriptionPollTargets.set(key, attempt + 1);
        if (record?.status !== "pending") state.descriptionPollTargets.delete(key);
        updateDescriptionViews();
        if (record?.status !== "pending") return record;
      }
      return state.descriptions[key];
    } finally {
      batch.waiting = null;
      scheduleDescriptionPoll();
    }
  }

  async function fillDescriptions() {
    if (state.descriptionBatch?.running || state.batch?.running || state.searchBusy || state.descriptionRequests.size || !state.searchResults.length || state.stopped) return;
    if (!state.hasAigcToken) { openAigcSettings(); return; }
    const pending = state.searchResults.filter((game) => needsDescription(game) && state.descriptions[repositoryKey(game.repo)]?.status !== "pending");
    const batch = { running: true, stopRequested: false, interrupted: false, waiting: null, total: pending.length, done: 0, accepted: 0, failed: 0, note: "" };
    state.descriptionBatch = batch;
    descriptionNotice("");
    syncDiscoveryControls();
    try {
      for (const game of pending) {
        if (batch.stopRequested || state.stopped) break;
        if (!needsDescription(game) || state.descriptions[repositoryKey(game.repo)]?.status === "pending") { batch.done++; continue; }
        let submitted = false;
        try {
          let record = await requestDescription(game);
          if (state.stopped) return;
          batch.done++;
          submitted = true;
          if (record.status === "ready" || record.status === "pending") batch.accepted++;
          if (record.status === "pending") {
            batch.note = "正在等待 " + game.repo + " 的中文简介完成，再提交下一个项目。";
            renderDescriptionProgress();
            record = await waitForQueuedDescription(game, batch);
            if (state.stopped) return;
          }
          if (record?.status === "failed") batch.failed++;
          if (record?.status === "pending" && !batch.stopRequested) {
            batch.interrupted = true;
            batch.note = game.repo + " 仍在生成，已暂停后续提交。可稍后核对进度，再补全剩余简介。";
            break;
          }
          batch.note = "";
        } catch (error) {
          if (!submitted) { batch.done++; batch.failed++; }
          batch.interrupted = true;
          batch.note = descriptionError(error) + " 已接受的生成任务仍会继续，后续项目尚未提交。";
          descriptionNotice(batch.note);
          break;
        }
        renderDescriptionProgress();
      }
    } finally {
      batch.running = false;
      if (!state.stopped) updateDescriptionViews();
    }
  }

  function githubURL(value) {
    try {
      const url = new URL(value);
      if (url.protocol !== "https:" || url.hostname !== "github.com" || url.port || url.username || url.password) return null;
      return url.href;
    } catch (_) { return null; }
  }

  function repoURL(repo, suffix = "") {
    if (typeof repo !== "string" || !/^[a-zA-Z0-9_.-]+\/[a-zA-Z0-9_.-]+$/.test(repo)) return null;
    return githubURL("https://github.com/" + repo + suffix);
  }

  function externalLink(label, url, className = "") {
    const href = githubURL(url);
    if (!href) return element("span", className, label + "（地址不可用）");
    const link = element("a", className, label);
    link.href = href;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    return link;
  }

  async function api(path, body, timeout = 70000) {
    if (state.stopped) throw new Error("PortShelf 已退出，请重新打开工具。");
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    const headers = { Authorization: "Bearer " + sessionToken };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    try {
      const response = await fetch(path, {
        method: body === undefined ? "GET" : "POST", headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal, credentials: "omit", cache: "no-store", redirect: "error",
      });
      let data;
      try { data = await response.json(); } catch (_) { throw new Error("工具返回了无效资料，请重新打开 PortShelf。"); }
      if (!response.ok) { const error = new Error(data.error || "请求失败，请稍后重试。"); error.status = response.status; throw error; }
      return data;
    } catch (error) {
      if (error.name === "AbortError") throw new Error("GitHub 响应超时，请稍后重试。已缓存的资料仍可浏览。");
      if (error instanceof TypeError) throw new Error("无法连接本地工具。请确认 PortShelf 正在运行，或重新双击打开。");
      throw error;
    } finally { clearTimeout(timer); }
  }

  function snapshot(game) { return state.snapshots[String(game.repo).toLowerCase()] || null; }
  function starValue(game, useSnapshot = true) {
    const record = useSnapshot ? snapshot(game) : null;
    const value = record?.starsCheckedAt ? record.stars : game.stars;
    return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
  }
  function stars(game, useSnapshot = true) {
    const value = starValue(game, useSnapshot);
    const node = element("span", "star-count" + (value === null ? " unknown" : ""));
    const symbol = element("span", "star-symbol", "☆");
    symbol.setAttribute("aria-hidden", "true");
    node.append(symbol, element("span", "", value === null ? "待核对" : numberFormat.format(value)));
    node.setAttribute("aria-label", value === null ? "GitHub Stars 待核对" : numberFormat.format(value) + " GitHub Stars");
    return node;
  }

  function rangeLabel(range) {
    if (range.min === null && range.max === null) return "Stars 不限";
    if (range.min === null) return "Stars ≤ " + numberFormat.format(range.max);
    if (range.max === null) return "Stars ≥ " + numberFormat.format(range.min);
    return "Stars " + numberFormat.format(range.min) + "–" + numberFormat.format(range.max);
  }

  function readStarsRange(prefix) {
    const range = { min: null, max: null };
    let error = "";
    for (const [bound, label] of [["min", "最低"], ["max", "最高"]]) {
      const input = $(prefix + "-" + bound + "-stars");
      const raw = input.value.trim();
      const value = raw === "" ? null : Number(raw);
      const invalid = input.validity.badInput || (raw !== "" && (!/^\d+$/.test(raw) || !Number.isSafeInteger(value) || value < 0 || value > 1000000000));
      input.setAttribute("aria-invalid", String(invalid));
      if (invalid && !error) error = label + " Stars 必须是 0–1,000,000,000 之间的整数，或留空表示不限。";
      range[bound] = value;
    }
    if (!error && range.min !== null && range.max !== null && range.min > range.max) {
      error = "最低 Stars 不能大于最高 Stars。";
      $(prefix + "-min-stars").setAttribute("aria-invalid", "true");
      $(prefix + "-max-stars").setAttribute("aria-invalid", "true");
    }
    showError(prefix + "-range-error", error ? (prefix === "library" ? "筛选未更新：" : "") + error : "");
    return error ? null : range;
  }

  function updateLibraryRange() {
    const range = readStarsRange("library");
    if (!range) return;
    state.minStars = range.min;
    state.maxStars = range.max;
    $("library-range-summary").textContent = rangeLabel(range) + (range.min !== null || range.max !== null ? " · 未核对 Stars 已隐藏" : " · 留空表示不限");
    renderGames();
  }

  function updateDiscoverRange() {
    const range = readStarsRange("discover");
    const changed = range && state.discovery.range && (range.min !== state.discovery.range.min || range.max !== state.discovery.range.max);
    $("discover-range-summary").textContent = range ? (changed ? "待查找范围：" : "当前范围：") + rangeLabel(range) + (changed ? " · 点击查找后生效" : "") : "请修正 Stars 范围后再查找。";
    document.querySelectorAll("[data-min-stars]").forEach((button) => {
      const value = button.dataset.minStars === "" ? null : Number(button.dataset.minStars);
      const selected = Boolean(range && range.min === value && (value !== null || range.max === null));
      button.setAttribute("aria-pressed", String(selected));
    });
    return range;
  }

  function clearLibraryFilters() {
    state.query = "";
    $("library-search").value = "";
    $("library-min-stars").value = "";
    $("library-max-stars").value = "";
    updateLibraryRange();
    chooseCategory("all");
  }

  function timestamp(value) { const result = Date.parse(value); return Number.isFinite(result) ? result : 0; }
  function date(value, withTime = false) {
    if (!timestamp(value)) return "待核对";
    const options = { year: "numeric", month: "2-digit", day: "2-digit" };
    if (withTime) Object.assign(options, { hour: "2-digit", minute: "2-digit", hour12: false });
    return new Intl.DateTimeFormat("zh-CN", options).format(new Date(value));
  }
  function assetList(record) { return Array.isArray(record?.release?.assets) ? record.release.assets : []; }
  function hasWindows(record) { return assetList(record).some((asset) => asset.windows === true && githubURL(asset.browser_download_url)); }
  function mark(game) { return element("span", "game-mark" + (colors.has(game.color) ? " " + game.color : ""), game.mark || String(game.name || game.repo || "?").slice(0, 2)); }
  function tag(text, className = "") { return element("span", "tag" + (className ? " " + className : ""), text); }
  function busy(button, value, loading, normal) { if (!button) return; button.disabled = value; button.textContent = value ? loading : normal; }
  function showError(id, message) { if (!$(id)) return; $(id).textContent = message; $(id).hidden = !message; }
  function notify(message, error = false) {
    if (state.stopped) return;
    clearTimeout(state.toastTimer);
    $("toast").textContent = message;
    $("toast").classList.toggle("error", error);
    $("toast").hidden = false;
    state.toastTimer = setTimeout(() => { $("toast").hidden = true; }, error ? 7000 : 4000);
  }
  function notice(message, error = false) {
    if (state.stopped || !$("notice")) return;
    $("notice").textContent = message;
    $("notice").classList.toggle("error", error);
    $("notice").hidden = !message;
  }

  function renderCategories() {
    const counts = new Map();
    state.games.forEach((game) => counts.set(game.category || "其他项目", (counts.get(game.category || "其他项目") || 0) + 1));
    const categories = [["all", state.games.length], ...Array.from(counts).sort((a, b) => b[1] - a[1])];
    if (!categories.some(([name]) => name === state.category)) state.category = "all";
    $("categories").replaceChildren();
    $("category-select").replaceChildren();
    categories.forEach(([name, count]) => {
      const label = name === "all" ? "全部游戏" : name;
      const button = element("button", "category-button");
      button.dataset.category = name;
      button.append(element("span", "", label), element("span", "", count));
      button.addEventListener("click", () => chooseCategory(name));
      $("categories").append(button);
      const option = element("option", "", name === "all" ? "全部类型" : name);
      option.value = name;
      $("category-select").append(option);
    });
    updateCategorySelection();
  }
  function updateCategorySelection() {
    $("categories").querySelectorAll("button").forEach((button) => {
      button.classList.toggle("active", button.dataset.category === state.category);
      button.setAttribute("aria-pressed", String(button.dataset.category === state.category));
    });
    $("category-select").value = state.category;
  }
  function chooseCategory(category) {
    state.category = category;
    updateCategorySelection();
    changePage("library");
    renderGames();
  }

  function renderStats() {
    if (state.stopped) return;
    $("nav-count").textContent = state.games.length;
    $("game-count").textContent = state.games.length;
    $("windows-count").textContent = state.games.filter((game) => hasWindows(snapshot(game))).length;
    const checked = state.games.map((game) => snapshot(game)?.starsCheckedAt).filter(timestamp).sort((a, b) => timestamp(b) - timestamp(a));
    $("checked-label").textContent = checked.length ? "最近核对于 " + date(checked[0]) : "尚未核对 · 点击刷新资料";
    $("connection-label").textContent = state.hasToken ? "GitHub Token 已设置" : "GitHub 公开访问";
    $("token-state").textContent = state.hasToken ? "当前已使用 Token，仅保留在本次进程内存中。" : "当前使用 GitHub 公开访问，未设置 Token。";
    $("aigc-token-state").textContent = state.hasAigcToken ? "已设置 AIGCNEWS MCP Token，仅在本次运行中保存。" : "尚未设置 AIGCNEWS MCP Token；仍可读取已有中文简介。";
  }

  function availability(game) {
    const record = snapshot(game);
    if (hasWindows(record)) return tag("Windows 附件", "tag-windows");
    if (record?.error) return tag("核对失败", "tag-warning");
    if (!record?.releaseCheckedAt) return tag("下载待核对");
    return tag(record.release ? "暂无 Windows 附件" : "暂无 Release");
  }

  function gameCard(game) {
    const card = element("article", "game-card");
    const id = "game-" + game.repo.replace(/[^a-zA-Z0-9_-]/g, "-");
    card.setAttribute("aria-labelledby", id);
    const top = element("div", "card-top");
    top.append(mark(game), stars(game));
    const title = element("h3", "card-title", game.name || game.repo);
    title.id = id;
    const tags = element("div", "card-tags");
    tags.append(tag(game.category || "其他项目"), availability(game));
    const description = descriptionOf(game);
    if (descriptionSource(description)) tags.append(tag(descriptionSource(description)));
    const descriptionAction = descriptionControl(game, true);
    if (descriptionAction) tags.append(descriptionAction);
    const bottom = element("div", "card-bottom");
    const download = element("button", "button button-subtle button-small", "查看下载 ↗");
    download.setAttribute("aria-label", "查看 " + (game.name || game.repo) + " 的下载");
    download.addEventListener("click", () => openDetails(game));
    bottom.append(externalLink("GitHub ↗", repoURL(game.repo), "repository-link"), download);
    const record = snapshot(game);
    let checked = record?.starsCheckedAt ? "Stars 核对于 " + date(record.starsCheckedAt) : "Stars 尚未核对";
    if (record?.error && record?.starsCheckedAt) checked += " · 暂用缓存";
    card.append(top, title, element("p", "card-subtitle", game.subtitle || game.repo), element("p", "card-description", description.text), tags, bottom, element("div", "card-checked", checked));
    return card;
  }

  function renderGames() {
    const query = state.query.trim().toLocaleLowerCase();
    const hasStarRange = state.minStars !== null || state.maxStars !== null;
    const games = state.games.filter((game) => {
      if (state.category !== "all" && (game.category || "其他项目") !== state.category) return false;
      if (hasStarRange) {
        const value = starValue(game);
        if (value === null || (state.minStars !== null && value < state.minStars) || (state.maxStars !== null && value > state.maxStars)) return false;
      }
      return !query || [game.name, game.subtitle, descriptionOf(game).text, game.description, game.repo, game.category].some((value) => String(value || "").toLocaleLowerCase().includes(query));
    });
    games.sort((a, b) => {
      if (state.sort === "stars") return (starValue(b) ?? -1) - (starValue(a) ?? -1) || String(a.name).localeCompare(String(b.name));
      if (state.sort === "updated") return timestamp(snapshot(b)?.pushedAt) - timestamp(snapshot(a)?.pushedAt) || String(a.name).localeCompare(String(b.name));
      return String(a.name || a.repo).localeCompare(String(b.name || b.repo));
    });
    $("game-grid").classList.toggle("list-mode", state.view === "list");
    $("game-grid").setAttribute("aria-busy", "false");
    $("game-grid").replaceChildren(...games.map(gameCard));
    $("library-empty").hidden = games.length > 0 || !state.loaded;
    $("results-title").textContent = state.category === "all" ? "全部游戏" : state.category;
    $("result-count").textContent = query || state.category !== "all" || hasStarRange ? "找到 " + games.length + " 款 / 共 " + state.games.length + " 款" : "共 " + games.length + " 款游戏";
  }

  async function loadLibrary() {
    const data = await api("/api/library");
    if (state.stopped) return;
    state.games = Array.isArray(data.games) ? data.games : [];
    const known = new Set(state.games.map((game) => repositoryKey(game.repo)));
    for (const [key, game] of state.confirmedGames) {
      if (!known.has(key)) { state.games.push(game); known.add(key); }
    }
    state.snapshots = data.snapshots && typeof data.snapshots === "object" ? data.snapshots : {};
    state.hasToken = Boolean(data.hasToken);
    state.hasAigcToken = Boolean(data.hasAigcToken);
    if (data.descriptions && typeof data.descriptions === "object") {
      mergeDescriptions(Object.entries(data.descriptions).map(([repo, item]) => ({ ...item, repo, status: item.status || "ready" })));
    }
    state.loaded = true;
    $("version-label").textContent = "PortShelf " + (data.version ? "v" + data.version : "");
    renderCategories(); renderStats(); renderGames();
    if (state.selected) renderDetails();
    if (state.discovery.range) renderSearchResults();
    syncDiscoveryControls();
  }

  function changePage(page) {
    if (state.stopped) return;
    state.page = page;
    $("library-view").hidden = page !== "library";
    $("discover-view").hidden = page !== "discover";
    $("library-nav").classList.toggle("active", page === "library");
    $("discover-nav").classList.toggle("active", page === "discover");
    $("library-nav").removeAttribute("aria-current");
    $("discover-nav").removeAttribute("aria-current");
    $(page === "library" ? "library-nav" : "discover-nav").setAttribute("aria-current", "page");
    $("page-title").replaceChildren(document.createTextNode(page === "library" ? "移植游戏目录" : "发现更多游戏"), element("span", "heading-dot", "."));
    $("page-eyebrow").textContent = page === "library" ? "给经典一个新入口" : "开源世界，继续探索";
    $("page-description").textContent = page === "library" ? "找到熟悉的游戏，看看社区的更新，获取 Windows 下载地址。" : "从 GitHub 的社区项目里，发现你的下一款收藏。";
  }

  function setRefreshState(running, status) {
    if (state.stopped) return;
    state.refreshing = running;
    busy($("refresh-button"), running, "正在刷新…", "刷新资料");
    $("refresh-progress").hidden = !running;
    if (running) {
      const total = Number(status?.total) || state.games.length || 1;
      const done = Number(status?.done) || 0;
      $("refresh-label").textContent = "正在核对 GitHub 资料 · " + done + " / " + total;
      $("refresh-meter").max = Math.max(1, total);
      $("refresh-meter").value = Math.min(done, total);
    }
    const button = $("detail-refresh");
    if (button) busy(button, running, "正在核对…", "重新核对");
  }

  function schedulePoll() {
    clearTimeout(state.polling);
    if (!state.stopped) state.polling = setTimeout(pollStatus, 1500);
  }
  async function pollStatus() {
    if (state.pollBusy || state.stopped) return;
    state.pollBusy = true;
    try {
      const status = await api("/api/status", undefined, 15000);
      if (state.stopped) return;
      if (status.running) { setRefreshState(true, status); schedulePoll(); }
      else {
        state.activeRefresh = null;
        await loadLibrary();
        setRefreshState(false, status);
        if (state.selected) renderDetails();
        const errors = Array.isArray(status.errors) ? status.errors : [];
        if (errors.length) notice("本次有 " + errors.length + " 个项目未能完成核对。已保留可用的缓存资料；打开对应游戏可查看原因。GitHub 额度不足时可在左下角设置 Token。");
        else { notice(""); notify("资料已更新，Windows 下载地址已完成核对。"); }
      }
    } catch (error) {
      setRefreshState(false);
      state.activeRefresh = null;
      notice(error.message, true);
    } finally { state.pollBusy = false; }
  }
  async function refresh(repo) {
    if (state.refreshing || state.stopped) return;
    notice("");
    state.activeRefresh = repo || "all";
    setRefreshState(true, { total: repo ? 1 : state.games.length, done: 0 });
    try {
      await api("/api/refresh", repo ? { repo } : {});
      if (state.selected) renderDetails();
      await pollStatus();
    } catch (error) {
      setRefreshState(false);
      state.activeRefresh = null;
      notice(error.message, true);
      notify(error.message, true);
    }
  }

  function humanSize(value) {
    const size = Number(value);
    if (!Number.isFinite(size) || size < 0) return "大小未知";
    if (size < 1024) return size + " B";
    if (size < 1024 ** 2) return (size / 1024).toFixed(1) + " KB";
    if (size < 1024 ** 3) return (size / 1024 ** 2).toFixed(1) + " MB";
    return (size / 1024 ** 3).toFixed(2) + " GB";
  }
  function architecture(value) {
    const labels = { amd64: "x64", x64: "x64", x86_64: "x64", arm64: "ARM64", aarch64: "ARM64", "386": "x86 · 32 位", x86: "x86 · 32 位", universal: "通用架构", any: "通用架构", unknown: "架构未标注" };
    return labels[value] || (value ? String(value) : "架构未标注");
  }
  async function copyAddress(url, button) {
    const safeURL = githubURL(url);
    if (!safeURL) { notify("该附件没有有效的 GitHub 下载地址。", true); return; }
    try {
      if (navigator.clipboard?.writeText) await navigator.clipboard.writeText(safeURL);
      else {
        const input = element("textarea", "sr-only", safeURL);
        input.readOnly = true;
        ($("detail-dialog").open ? $("detail-dialog") : document.body).append(input);
        input.select();
        const copied = document.execCommand("copy");
        input.remove();
        button.focus();
        if (!copied) throw new Error("copy unavailable");
      }
      const old = button.textContent;
      button.textContent = "已复制";
      notify("已复制 GitHub 下载地址。");
      setTimeout(() => { if (button.isConnected) button.textContent = old; }, 2000);
    } catch (_) { notify("浏览器未允许复制，可右键“下载”按钮复制链接地址。", true); }
  }

  function renderAsset(asset) {
    const item = element("div", "asset-row" + (asset.windows === true ? "" : " non-windows"));
    const info = element("div", "asset-info");
    info.append(tag(asset.windows === true ? "Windows" : "非 Windows / 未识别", asset.windows === true ? "tag-windows" : ""), element("span", "", architecture(asset.arch)), element("span", "", humanSize(asset.size)));
    if (asset.recommended && asset.windows === true) info.append(tag("优先查看", "tag-windows"));
    const actions = element("div", "asset-actions");
    const copy = element("button", "button button-secondary button-small", "复制地址");
    copy.disabled = !githubURL(asset.browser_download_url);
    copy.addEventListener("click", () => copyAddress(asset.browser_download_url, copy));
    actions.append(copy, externalLink(asset.windows === true ? "下载 ↗" : "上游附件 ↗", asset.browser_download_url, "button button-primary button-small"));
    item.append(element("div", "asset-name", asset.name || "未命名附件"), info, actions);
    return item;
  }

  function renderDetails() {
    const game = state.games.find((item) => item.repo.toLowerCase() === state.selected?.toLowerCase());
    if (!game) return;
    const container = $("detail-content");
    const originalOpen = Boolean(container.querySelector(".original-description[open]"));
    const previousFocus = document.activeElement;
    const previousID = container.contains(previousFocus) ? previousFocus.id : "";
    container.replaceChildren();
    const record = snapshot(game);
    const header = element("div", "detail-header");
    const heading = element("div");
    const title = element("h2", "", game.name || game.repo);
    title.id = "detail-title";
    heading.append(title, element("p", "detail-subtitle", game.subtitle || game.category || "开源项目"), externalLink(game.repo + " ↗", repoURL(game.repo), "detail-repo"));
    header.append(mark(game), heading);
    const meta = element("div", "detail-meta");
    meta.append(stars(game), element("span", "", game.category || "其他项目"), element("span", "", "项目更新 " + date(record?.pushedAt)));
    container.append(header, ...descriptionNodes(game, "detail-description", true), meta);
    if (originalOpen && container.querySelector(".original-description")) container.querySelector(".original-description").open = true;
    if (game.dataNote) {
      const note = element("div", "data-note");
      note.append(element("strong", "", "开始之前"), document.createTextNode(game.dataNote));
      container.append(note);
    }
    const section = element("section", "detail-section");
    const sectionHeading = element("div", "detail-section-heading");
    const reload = element("button", "button button-secondary button-small", "重新核对");
    reload.id = "detail-refresh";
    reload.addEventListener("click", () => refresh(game.repo));
    busy(reload, state.refreshing, "正在核对…", "重新核对");
    sectionHeading.append(element("h3", "", "最新 Release 与下载"), reload);
    section.append(sectionHeading);
    if (record?.error) section.append(element("div", "detail-error", "最近核对未完成：" + record.error + (record.release ? " 下方继续显示上次成功核对的附件，下载前可查看上游发布页。" : " 可重新核对，或前往 GitHub 发布页查看。")));
    const release = record?.release;
    if (release) {
      const summary = element("div", "release-summary");
      const releaseLabel = release.name || release.tag_name || "最新发布";
      summary.append(externalLink(releaseLabel + " ↗", release.html_url || repoURL(game.repo, "/releases"), "release-title"));
      const tagText = release.tag_name && release.tag_name !== releaseLabel ? release.tag_name + " · " : "";
      summary.append(element("p", "release-date", tagText + "发布于 " + date(release.published_at)));
      section.append(summary);
      const assets = assetList(record);
      const windows = assets.filter((asset) => asset.windows === true);
      const toolbar = element("div", "asset-toolbar");
      const switcher = element("div", "view-switch");
      switcher.setAttribute("role", "group");
      switcher.setAttribute("aria-label", "附件平台筛选");
      const windowsButton = element("button", "", "Windows " + windows.length);
      windowsButton.id = "windows-assets";
      windowsButton.setAttribute("aria-pressed", String(!state.allAssets));
      windowsButton.addEventListener("click", () => { state.allAssets = false; renderDetails(); });
      const allButton = element("button", "", "全部附件 " + assets.length);
      allButton.id = "all-assets";
      allButton.setAttribute("aria-pressed", String(state.allAssets));
      allButton.addEventListener("click", () => { state.allAssets = true; renderDetails(); });
      switcher.append(windowsButton, allButton);
      toolbar.append(switcher, element("span", "", "GitHub 官方附件"));
      section.append(toolbar);
      section.append(element("p", "detail-cache", "平台与架构按文件名识别，请以上游说明为准。"));
      const visible = (state.allAssets ? assets : windows).slice().sort((a, b) => Number(Boolean(b.recommended)) - Number(Boolean(a.recommended)) || Number(b.windows === true) - Number(a.windows === true));
      if (visible.length) {
        const list = element("div", "asset-list");
        list.append(...visible.map(renderAsset));
        section.append(list);
      } else {
        const empty = element("div", "detail-empty");
        empty.append(element("strong", "", !assets.length ? "这个 Release 没有下载附件" : "这个 Release 暂无可识别的 Windows 附件"), document.createTextNode(!assets.length ? "上游可能通过项目主页提供构建版本。可查看 README 与发布说明。" : "可以切换“全部附件”核对文件名，或到上游发布页寻找 Windows 版本。"));
        section.append(empty);
      }
    } else {
      const empty = element("div", "detail-empty");
      const loading = state.refreshing && (state.activeRefresh === game.repo || state.activeRefresh === "all" || !state.activeRefresh);
      const title = loading ? "正在核对最新发布资料…" : record?.releaseCheckedAt && !record?.error ? "这个项目还没有 GitHub Release" : record?.error ? "暂时无法获取发布资料" : "下载资料尚未核对";
      empty.append(element("strong", "", title), document.createTextNode(loading ? "GitHub 请求可能需要一点时间，完成后会自动显示附件。" : record?.releaseCheckedAt && !record?.error ? "项目可能使用其他方式发布 Windows 版本，查看上游 README 了解获取方式。" : "点击“重新核对”获取最新附件，也可以直接查看 GitHub 发布页。"), externalLink("查看上游发布页 ↗", repoURL(game.repo, "/releases"), "button button-secondary button-small"));
      section.append(empty);
    }
    section.append(element("p", "detail-cache", "Stars 核对：" + date(record?.starsCheckedAt, true) + " · 下载核对：" + date(record?.releaseCheckedAt, true)));
    container.append(section);
    const footer = element("div", "detail-footer");
    footer.append(element("span", "", "点击下载将在浏览器中打开 GitHub 附件地址。"), externalLink("上游 README ↗", githubURL(game.guide) || repoURL(game.repo, "#readme")));
    container.append(footer);
    if (previousID && $(previousID)) $(previousID).focus({ preventScroll: true });
  }

  function openDetails(game) {
    state.selected = game.repo;
    state.allAssets = false;
    renderDetails();
    $("detail-dialog").showModal();
    $("detail-dialog").scrollTop = 0;
    const record = snapshot(game);
    queueDescriptionRead([game.repo]);
    if (!record?.releaseCheckedAt && !record?.error && !state.refreshing) refresh(game.repo);
  }

  function renderSearchResults() {
    if (state.stopped) return;
    const expanded = new Set(Array.from($("discover-results").querySelectorAll(".original-description[open]")).map((node) => node.closest("[data-repository]")?.dataset.repository));
    $("discover-results").replaceChildren();
    if (!state.searchResults.length) {
      if (!state.searchBusy && state.discovery.page > 0) {
        const empty = element("div", "empty-state");
        empty.append(element("h3", "", state.discovery.hasMore ? "已读取的候选页尚未筛选出游戏" : "当前查询未发现匹配的游戏项目"), element("p", "", state.discovery.hasMore ? "后面还有候选页，可以点击“加载更多”继续查找。" : "可调整 Stars 范围重新查找；上游候选数量不等于游戏数量。"));
        $("discover-results").append(empty);
      }
      syncDiscoveryControls();
      return;
    }
    state.searchResults.forEach((game) => {
      const row = element("article", "search-result");
      row.dataset.repository = repositoryKey(game.repo);
      const info = element("div", "search-result-info");
      const heading = element("h3");
      heading.append(externalLink(game.name || game.repo, repoURL(game.repo)));
      info.append(heading, element("div", "repo-path", game.repo), ...descriptionNodes(game, "search-description", true));
      if (expanded.has(repositoryKey(game.repo)) && info.querySelector("details")) info.querySelector("details").open = true;
      const actions = element("div", "search-result-actions");
      actions.append(stars(game, false));
      const added = isInLibrary(game.repo);
      const button = element("button", "button " + (added ? "button-secondary" : "button-subtle") + " button-small", added ? "已加入 · 查看下载" : "＋ 加入目录");
      button.dataset.resultRepo = repositoryKey(game.repo);
      button.addEventListener("click", async () => {
        if (isInLibrary(game.repo)) {
          openDetails(state.games.find((item) => repositoryKey(item.repo) === repositoryKey(game.repo)));
          return;
        }
        const key = repositoryKey(game.repo);
        if (state.batch?.running || state.singleAdds.has(key)) return;
        state.singleAdds.add(key);
        syncDiscoveryControls();
        try {
          const addedGame = await api("/api/games", { repo: game.repo });
          state.confirmedGames.set(repositoryKey(addedGame.repo), addedGame);
          rememberGames([game.repo]);
          await loadLibrary();
          notify("已将 " + (game.name || game.repo) + " 加入目录。");
        } catch (error) { notify(error.message, true); }
        finally { state.singleAdds.delete(key); syncDiscoveryControls(); }
      });
      actions.append(button);
      row.append(mark(game), info, actions);
      $("discover-results").append(row);
    });
    syncDiscoveryControls();
  }

  function syncDiscoveryControls() {
    if (state.stopped) return;
    const discovery = state.discovery;
    const batchRunning = Boolean(state.batch?.running);
    const descriptionRunning = Boolean(state.descriptionBatch?.running);
    const discoveryLocked = batchRunning || descriptionRunning;
    const known = new Set(state.games.map((game) => repositoryKey(game.repo)));
    const pending = state.searchResults.filter((game) => !known.has(repositoryKey(game.repo))).length;
    $("discover-submit").disabled = state.searchBusy || discoveryLocked;
    $("discover-submit").textContent = state.searchBusy ? "正在查找…" : "按 Stars 查找";
    $("discover-min-stars").disabled = discoveryLocked;
    $("discover-max-stars").disabled = discoveryLocked;
    document.querySelectorAll("[data-min-stars]").forEach((button) => { button.disabled = discoveryLocked; });
    $("add-open").disabled = batchRunning;
    $("add-submit").disabled = batchRunning || state.manualAddBusy;
    $("discover-results").setAttribute("aria-busy", String(state.searchBusy));
    $("batch-toolbar").hidden = state.searchResults.length === 0;
    $("batch-selection-label").textContent = "当前已加载 " + state.searchResults.length + " 个游戏项目 · 待添加 " + pending + " 个";
    $("batch-add").disabled = state.searchBusy || discoveryLocked || state.singleAdds.size > 0 || state.manualAddBusy || pending === 0;
    $("batch-add").textContent = batchRunning ? "正在批量添加…" : pending === 0 ? "当前结果已全部加入" : "一键添加当前结果";
    const missingDescriptions = state.searchResults.filter((game) => needsDescription(game) && state.descriptions[repositoryKey(game.repo)]?.status !== "pending").length;
    const pendingDescriptions = state.searchResults.some((game) => state.descriptions[repositoryKey(game.repo)]?.status === "pending");
    $("descriptions-fill").disabled = state.searchBusy || discoveryLocked || state.descriptionRequests.size > 0 || missingDescriptions === 0;
    $("descriptions-fill").textContent = descriptionRunning ? "正在补全中文简介…" : missingDescriptions === 0 ? pendingDescriptions ? "中文简介生成中" : "当前中文简介已齐全" : "补全当前中文简介";
    $("discover-results").querySelectorAll("[data-result-repo]").forEach((button) => {
      const added = known.has(button.dataset.resultRepo);
      const adding = state.singleAdds.has(button.dataset.resultRepo);
      button.disabled = !added && (batchRunning || adding);
      button.textContent = added ? "已加入 · 查看下载" : adding ? "正在添加…" : "＋ 加入目录";
      button.classList.toggle("button-secondary", added);
      button.classList.toggle("button-subtle", !added);
    });
    if (discovery.range) {
      $("discover-count").textContent = "结果范围：" + rangeLabel(discovery.range) + " · 已发现 " + state.searchResults.length + " 个游戏项目";
      const details = [];
      if (discovery.page) details.push("已读取第 " + discovery.page + " 页候选");
      if (discovery.page) details.push("上游候选 " + numberFormat.format(discovery.totalCandidates) + " 项，需进一步筛选");
      if (state.searchBusy) details.push("正在加载第 " + discovery.nextPage + " 页…");
      else if (discovery.error) details.push("第 " + discovery.nextPage + " 页未完成，可重试");
      else if (discovery.page && discovery.lastAdded === 0 && discovery.hasMore) details.push("本页没有新增游戏，可继续加载");
      else if (discovery.page && !discovery.hasMore) details.push("本次查询已无可读取的后续页");
      $("discovery-page-summary").textContent = details.join(" · ");
    }
    $("discovery-pagination").hidden = !discovery.range;
    $("discover-more").hidden = !discovery.hasMore && !discovery.error;
    $("discover-more").disabled = state.searchBusy || discoveryLocked;
    $("discover-more").textContent = state.searchBusy ? "正在加载…" : discovery.error ? "重试第 " + discovery.nextPage + " 页" : "加载更多";
    showError("discover-error", discovery.error ? discovery.error + " 已加载的结果仍保留，点击下方按钮重试当前页。" : "");
    const warnings = [];
    if (discovery.incomplete) warnings.push("GitHub 本次返回的候选结果不完整，当前列表不能视为全部结果。");
    if (discovery.limitReached) warnings.push("已达到 GitHub 对此查询开放的前 1,000 个候选限制。");
    if (warnings.length) warnings.push("请收窄 Stars 范围继续查找。");
    $("discover-limit-notice").textContent = warnings.join(" ");
    $("discover-limit-notice").hidden = warnings.length === 0;
    renderBatchProgress();
    renderDescriptionProgress();
  }

  async function loadDiscoveryPage() {
    if (state.searchBusy || state.batch?.running || state.descriptionBatch?.running || !state.discovery.range || state.stopped) return;
    const discovery = state.discovery;
    const page = discovery.nextPage;
    if (!Number.isInteger(page) || page < 1) return;
    const params = new URLSearchParams({ page: String(page) });
    if (discovery.range.min !== null) params.set("minStars", String(discovery.range.min));
    if (discovery.range.max !== null) params.set("maxStars", String(discovery.range.max));
    state.searchBusy = true;
    discovery.error = "";
    let pageRepos = [];
    syncDiscoveryControls();
    try {
      const result = await api("/api/discover?" + params.toString());
      if (state.stopped) return;
      if (!result || !Array.isArray(result.items) || result.page !== page || !Number.isInteger(result.nextPage) || result.nextPage < 0 || (result.hasMore && result.nextPage <= page)) {
        throw new Error("分页结果无效，请重试当前页。");
      }
      const merged = new Map(state.searchResults.map((game) => [repositoryKey(game.repo), game]));
      const before = merged.size;
      for (const game of result.items) {
        if (game && repoURL(game.repo)) merged.set(repositoryKey(game.repo), game);
      }
      state.searchResults = Array.from(merged.values()).sort((a, b) => (starValue(b, false) ?? -1) - (starValue(a, false) ?? -1) || repositoryKey(a.repo).localeCompare(repositoryKey(b.repo)));
      discovery.lastAdded = merged.size - before;
      discovery.page = page;
      discovery.nextPage = result.hasMore ? result.nextPage : 0;
      discovery.hasMore = Boolean(result.hasMore && result.nextPage > 0);
      discovery.totalCandidates = Number.isFinite(result.totalCandidates) && result.totalCandidates >= 0 ? result.totalCandidates : 0;
      discovery.incomplete = discovery.incomplete || Boolean(result.incomplete);
      discovery.limitReached = discovery.limitReached || Boolean(result.limitReached);
      pageRepos = result.items.filter((game) => game && repoURL(game.repo)).map((game) => game.repo);
    } catch (error) {
      if (!state.stopped) discovery.error = error.message;
    } finally {
      state.searchBusy = false;
      if (!state.stopped) { renderSearchResults(); queueDescriptionRead(pageRepos); }
    }
  }

  async function searchGitHub(event) {
    event.preventDefault();
    if (state.searchBusy || state.batch?.running || state.descriptionBatch?.running) return;
    const range = updateDiscoverRange();
    if (!range) {
      $("discover-form").querySelector('[aria-invalid="true"]')?.focus();
      return;
    }
    state.searchResults = [];
    state.discovery = { range: { ...range }, nextPage: 1, page: 0, hasMore: true, totalCandidates: 0, incomplete: false, limitReached: false, error: "", lastAdded: 0 };
    state.batch = null;
    state.descriptionBatch = null;
    updateDiscoverRange();
    $("discover-results").replaceChildren();
    await loadDiscoveryPage();
  }

  function renderBatchProgress() {
    const batch = state.batch;
    $("batch-progress-panel").hidden = !batch;
    if (!batch) return;
    let label = batch.running ? (batch.checking ? "正在核对已加入的项目" : batch.stopRequested ? "等待当前批次结束后停止" : "正在批量添加") : batch.stopRequested ? "已停止批量添加" : batch.interrupted ? "批量添加已中断" : "本次批量处理完成";
    label += " · 已处理 " + batch.completed + " / " + batch.total + " · 新增 " + batch.added + " · 已存在 " + batch.skipped + " · 失败 " + batch.failed.length;
    $("batch-progress-label").textContent = label;
    $("batch-progress-meter").max = Math.max(1, batch.total);
    $("batch-progress-meter").value = batch.completed;
    $("batch-stop").hidden = !batch.running;
    $("batch-stop").disabled = batch.stopRequested;
    $("batch-stop").textContent = batch.stopRequested ? "等待本批结束…" : "停止添加";
    $("batch-note").textContent = batch.note || "只添加当前已加载的结果，已有项目自动跳过；下载资料在打开游戏详情时核对。";
    $("batch-failures").hidden = batch.failed.length === 0;
    $("batch-failures-summary").textContent = "未能添加的 " + batch.failed.length + " 个项目（可再次添加重试）";
    $("batch-failure-list").replaceChildren(...batch.failed.map((failure) => {
      const item = element("li");
      item.append(element("strong", "", failure.repo), element("span", "", failure.error));
      return item;
    }));
  }

  async function addCurrentResults() {
    if (state.batch?.running || state.descriptionBatch?.running || state.searchBusy || state.singleAdds.size || state.manualAddBusy || !state.searchResults.length || state.stopped) return;
    const batch = { running: true, checking: true, stopRequested: false, interrupted: false, total: 0, completed: 0, added: 0, skipped: 0, failed: [], note: "" };
    state.batch = batch;
    syncDiscoveryControls();
    try {
      // A retry first reads persisted state, including successes from a lost response.
      await loadLibrary();
      if (state.stopped) return;
      const pending = state.searchResults.filter((game) => !isInLibrary(game.repo)).map((game) => game.repo);
      batch.total = pending.length;
      batch.checking = false;
      syncDiscoveryControls();
      for (let index = 0; index < pending.length && !batch.stopRequested; index += 50) {
        const repos = pending.slice(index, index + 50);
        try {
          const result = await api("/api/games/batch", { repos });
          if (state.stopped) return;
          if (!Array.isArray(result.added) || !Array.isArray(result.skipped) || !Array.isArray(result.failed)) throw new Error("批量返回结果无效，请重新核对目录后重试。");
          const added = new Set(result.added.map(repositoryKey));
          const skipped = new Set(result.skipped.map(repositoryKey));
          const failed = new Map(result.failed.map((entry) => [repositoryKey(entry.repo), String(entry.error || "添加未完成，请重试。") ]));
          const confirmed = [];
          for (const repo of repos) {
            const key = repositoryKey(repo);
            if (added.has(key)) { batch.added++; confirmed.push(repo); }
            else if (skipped.has(key)) { batch.skipped++; confirmed.push(repo); }
            else batch.failed.push({ repo, error: failed.get(key) || "本次请求未确认添加结果，可重试。" });
          }
          rememberGames(confirmed);
          batch.completed += repos.length;
          renderCategories(); renderStats(); renderGames(); renderSearchResults();
        } catch (error) {
          if (state.stopped) return;
          batch.failed.push(...repos.map((repo) => ({ repo, error: error.message })));
          batch.completed += repos.length;
          batch.interrupted = true;
          batch.note = "本批请求未完成，已停止后续批次。已成功保存的项目会保留；再次添加前会先核对目录。";
          break;
        }
      }
      try {
        await loadLibrary();
        const recovered = batch.failed.filter((failure) => isInLibrary(failure.repo)).length;
        batch.failed = batch.failed.filter((failure) => !isInLibrary(failure.repo));
        batch.skipped += recovered;
      } catch (error) {
        batch.note = "已确认添加的项目已保留，但目录同步未完成：" + error.message;
      }
      if (!batch.note) {
        const remaining = Math.max(0, batch.total - batch.completed);
        batch.note = "已完成的添加已保存。" + (remaining ? "还有 " + remaining + " 个未处理项目，" : "") + (remaining || batch.failed.length ? "再次点击会只补充尚未加入的项目。" : "打开游戏详情时再核对 Windows 下载附件。");
      }
    } catch (error) {
      batch.interrupted = true;
      batch.note = "无法核对当前目录，本次未发起批量添加：" + error.message;
    } finally {
      batch.running = false;
      batch.checking = false;
      if (!state.stopped) { renderSearchResults(); syncDiscoveryControls(); }
    }
  }

  function setupEvents() {
    $("library-nav").addEventListener("click", () => changePage("library"));
    $("discover-nav").addEventListener("click", () => { changePage("discover"); $("discover-min-stars").focus(); });
    document.querySelector(".brand").addEventListener("click", (event) => { event.preventDefault(); changePage("library"); });
    $("library-search").addEventListener("input", (event) => { state.query = event.target.value; renderGames(); });
    $("sort-select").addEventListener("change", (event) => { state.sort = event.target.value; renderGames(); });
    $("category-select").addEventListener("change", (event) => chooseCategory(event.target.value));
    ["library-min-stars", "library-max-stars"].forEach((id) => $(id).addEventListener("input", updateLibraryRange));
    ["discover-min-stars", "discover-max-stars"].forEach((id) => $(id).addEventListener("input", updateDiscoverRange));
    ["clear-filters", "clear-filters-top"].forEach((id) => $(id).addEventListener("click", () => { clearLibraryFilters(); $("library-search").focus(); }));
    document.querySelectorAll("[data-min-stars]").forEach((button) => button.addEventListener("click", () => {
      $("discover-min-stars").value = button.dataset.minStars;
      if (button.dataset.minStars === "") $("discover-max-stars").value = "";
      updateDiscoverRange();
    }));
    [["grid-view", "grid"], ["list-view", "list"]].forEach(([id, view]) => $(id).addEventListener("click", () => {
      state.view = view;
      $("grid-view").setAttribute("aria-pressed", String(view === "grid"));
      $("list-view").setAttribute("aria-pressed", String(view === "list"));
      renderGames();
    }));
    $("refresh-button").addEventListener("click", () => refresh());
    $("detail-close").addEventListener("click", () => $("detail-dialog").close());
    $("detail-dialog").addEventListener("close", () => { state.selected = null; });
    document.querySelectorAll("[data-close]").forEach((button) => button.addEventListener("click", () => $(button.dataset.close).close()));
    document.querySelectorAll("dialog").forEach((dialog) => dialog.addEventListener("click", (event) => {
      if (event.target !== dialog) return;
      const rect = dialog.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
    }));
    $("add-open").addEventListener("click", () => { showError("add-error", ""); $("add-dialog").showModal(); $("repo-input").focus(); });
    $("settings-open").addEventListener("click", () => { showError("token-error", ""); showError("aigc-token-error", ""); $("token-input").value = ""; $("aigc-token-input").value = ""; renderStats(); $("settings-dialog").showModal(); });
    $("settings-dialog").addEventListener("close", () => { $("token-input").value = ""; $("aigc-token-input").value = ""; });
    $("quit-open").addEventListener("click", () => { showError("quit-error", ""); $("quit-dialog").showModal(); });
    $("discover-form").addEventListener("submit", searchGitHub);
    $("discover-more").addEventListener("click", loadDiscoveryPage);
    $("batch-add").addEventListener("click", addCurrentResults);
    $("descriptions-fill").addEventListener("click", fillDescriptions);
    $("descriptions-stop").addEventListener("click", () => {
      if (!state.descriptionBatch?.running) return;
      state.descriptionBatch.stopRequested = true;
      renderDescriptionProgress();
    });
    $("batch-stop").addEventListener("click", () => {
      if (!state.batch?.running) return;
      state.batch.stopRequested = true;
      renderBatchProgress();
    });
    $("add-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = $("add-submit");
      if (button.disabled || state.batch?.running) return;
      const repo = $("repo-input").value.trim();
      if (!repo) return;
      showError("add-error", "");
      state.manualAddBusy = true;
      busy(button, true, "正在添加与核对…", "添加并核对资料");
      syncDiscoveryControls();
      try {
        const game = await api("/api/games", { repo });
        state.confirmedGames.set(repositoryKey(game.repo), game);
        await loadLibrary();
        if (state.stopped) return;
        $("add-dialog").close();
        $("repo-input").value = "";
        clearLibraryFilters();
        notify("已将 " + (game.name || game.repo || "项目") + " 加入目录。");
      } catch (error) { showError("add-error", error.message); }
      finally { state.manualAddBusy = false; busy(button, false, "", "添加并核对资料"); syncDiscoveryControls(); }
    });
    $("token-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = $("token-submit");
      if (button.disabled) return;
      showError("token-error", "");
      busy(button, true, "保存中…", "保存设置");
      try {
        const data = await api("/api/token", { token: $("token-input").value.trim() });
        state.hasToken = Boolean(data.hasToken);
        $("token-input").value = "";
        renderStats();
        $("settings-dialog").close();
        notify(state.hasToken ? "Token 已保留在本次进程内存中，可重新刷新资料。" : "Token 已清除，恢复 GitHub 公开访问。");
      } catch (error) { showError("token-error", error.message); }
      finally { busy(button, false, "", "保存设置"); }
    });
    $("aigc-token-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = $("aigc-token-submit");
      if (button.disabled) return;
      showError("aigc-token-error", "");
      busy(button, true, "保存中…", "保存 AIGCNEWS Token");
      try {
        const data = await api("/api/aigc-token", { token: $("aigc-token-input").value.trim() });
        state.hasAigcToken = Boolean(data.hasAigcToken ?? data.hasToken);
        $("aigc-token-input").value = "";
        renderStats();
        $("settings-dialog").close();
        notify(state.hasAigcToken ? "AIGCNEWS MCP Token 已仅保存在本次运行内存中。" : "AIGCNEWS MCP Token 已清除。");
        syncDiscoveryControls();
      } catch (error) { showError("aigc-token-error", descriptionError(error)); }
      finally { busy(button, false, "", "保存 AIGCNEWS Token"); }
    });
    $("quit-confirm").addEventListener("click", async () => {
      busy($("quit-confirm"), true, "正在退出…", "退出工具");
      try {
        await api("/api/quit", {});
        state.stopped = true;
        clearTimeout(state.polling); clearTimeout(state.toastTimer); clearTimeout(state.descriptionPollTimer);
        state.descriptionReadQueue.clear(); state.descriptionPollTargets.clear();
        sessionToken = "";
        try { sessionStorage.removeItem("portshelf-session"); } catch (_) { /* Storage may be disabled. */ }
        $("quit-dialog").close();
        const message = element("div", "stopped-message");
        message.append(element("h1", "", "下次，再来重温经典。"), element("p", "", "PortShelf 已退出，目录资料已保留。你可以关闭这个标签页，或双击 PortShelf 再次打开。"));
        $("main").replaceChildren(message);
        document.querySelectorAll(".sidebar button").forEach((button) => { button.disabled = true; });
        $("main").focus();
      } catch (error) { showError("quit-error", error.message); busy($("quit-confirm"), false, "", "退出工具"); }
    });
    document.addEventListener("keydown", (event) => {
      if (event.key !== "/" || event.ctrlKey || event.metaKey || event.altKey || document.querySelector("dialog[open]") || ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName) || state.stopped) return;
      event.preventDefault();
      $(state.page === "library" ? "library-search" : "discover-min-stars").focus();
    });
  }

  async function start() {
    readSession(); setupEvents();
    for (let i = 0; i < 6; i++) $("game-grid").append(element("div", "skeleton"));
    if (!sessionToken) {
      $("game-grid").replaceChildren();
      $("game-grid").setAttribute("aria-busy", "false");
      $("result-count").textContent = "尚未连接";
      notice("这个页面缺少本地访问凭据，请双击 PortShelf.exe 重新打开目录。", true);
      return;
    }
    try {
      await loadLibrary();
      queueDescriptionRead(state.games.filter(needsDescription).map((game) => game.repo));
      const status = await api("/api/status", undefined, 15000);
      if (status.running) { setRefreshState(true, status); schedulePoll(); }
    } catch (error) {
      if (!state.loaded) { $("game-grid").replaceChildren(); $("result-count").textContent = "暂时无法读取目录"; $("game-grid").setAttribute("aria-busy", "false"); }
      notice(error.message, true);
    }
  }
  start();
})();
