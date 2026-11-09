"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const state = {
    games: [], snapshots: {}, category: "all", query: "", sort: "stars", view: "grid",
    page: "library", hasToken: false, refreshing: false, polling: null, pollBusy: false,
    selected: null, allAssets: false, searchResults: [], searchBusy: false, stopped: false,
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
      if (!response.ok) throw new Error(data.error || "请求失败，请稍后重试。");
      return data;
    } catch (error) {
      if (error.name === "AbortError") throw new Error("GitHub 响应超时，请稍后重试。已缓存的资料仍可浏览。");
      if (error instanceof TypeError) throw new Error("无法连接本地工具。请确认 PortShelf 正在运行，或重新双击打开。");
      throw error;
    } finally { clearTimeout(timer); }
  }

  function snapshot(game) { return state.snapshots[String(game.repo).toLowerCase()] || null; }
  function starValue(game) {
    const record = snapshot(game);
    const value = record?.starsCheckedAt ? record.stars : game.stars;
    return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
  }
  function stars(game) {
    const value = starValue(game);
    const node = element("span", "star-count" + (value === null ? " unknown" : ""));
    const symbol = element("span", "star-symbol", "☆");
    symbol.setAttribute("aria-hidden", "true");
    node.append(symbol, element("span", "", value === null ? "待核对" : numberFormat.format(value)));
    node.setAttribute("aria-label", value === null ? "GitHub Stars 待核对" : numberFormat.format(value) + " GitHub Stars");
    return node;
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
    const bottom = element("div", "card-bottom");
    const download = element("button", "button button-subtle button-small", "查看下载 ↗");
    download.setAttribute("aria-label", "查看 " + (game.name || game.repo) + " 的下载");
    download.addEventListener("click", () => openDetails(game));
    bottom.append(externalLink("GitHub ↗", repoURL(game.repo), "repository-link"), download);
    const record = snapshot(game);
    let checked = record?.starsCheckedAt ? "Stars 核对于 " + date(record.starsCheckedAt) : "Stars 尚未核对";
    if (record?.error && record?.starsCheckedAt) checked += " · 暂用缓存";
    card.append(top, title, element("p", "card-subtitle", game.subtitle || game.repo), element("p", "card-description", game.description || "上游尚未填写简介，查看 GitHub 项目了解详情。"), tags, bottom, element("div", "card-checked", checked));
    return card;
  }

  function renderGames() {
    const query = state.query.trim().toLocaleLowerCase();
    const games = state.games.filter((game) => {
      if (state.category !== "all" && (game.category || "其他项目") !== state.category) return false;
      return !query || [game.name, game.subtitle, game.description, game.repo, game.category].some((value) => String(value || "").toLocaleLowerCase().includes(query));
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
    $("result-count").textContent = query || state.category !== "all" ? "找到 " + games.length + " 款 / 共 " + state.games.length + " 款" : "共 " + games.length + " 款游戏";
  }

  async function loadLibrary() {
    const data = await api("/api/library");
    if (state.stopped) return;
    state.games = Array.isArray(data.games) ? data.games : [];
    state.snapshots = data.snapshots && typeof data.snapshots === "object" ? data.snapshots : {};
    state.hasToken = Boolean(data.hasToken);
    state.loaded = true;
    $("version-label").textContent = "PortShelf " + (data.version ? "v" + data.version : "");
    renderCategories(); renderStats(); renderGames();
    if (state.selected) renderDetails();
    if (state.searchResults.length) renderSearchResults();
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
    container.append(header, element("p", "detail-description", game.description || "上游尚未填写简介，可在 GitHub 查看项目说明。"), meta);
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
    if (!record?.releaseCheckedAt && !record?.error && !state.refreshing) refresh(game.repo);
  }

  function renderSearchResults() {
    if (state.stopped) return;
    $("discover-results").replaceChildren();
    if (!state.searchResults.length) {
      const empty = element("div", "empty-state");
      empty.append(element("h3", "", "没有找到匹配的项目"), element("p", "", "试试英文游戏名称，或使用 topic:source-port。"));
      $("discover-results").append(empty);
      return;
    }
    state.searchResults.forEach((game) => {
      const row = element("article", "search-result");
      const info = element("div", "search-result-info");
      const heading = element("h3");
      heading.append(externalLink(game.name || game.repo, repoURL(game.repo)));
      info.append(heading, element("div", "repo-path", game.repo), element("p", "", game.description || "上游尚未填写简介，可前往 GitHub 查看项目详情。"));
      const actions = element("div", "search-result-actions");
      actions.append(stars(game));
      const added = state.games.some((item) => item.repo.toLowerCase() === String(game.repo).toLowerCase());
      const button = element("button", "button " + (added ? "button-secondary" : "button-subtle") + " button-small", added ? "已加入 · 查看下载" : "＋ 加入目录");
      button.addEventListener("click", async () => {
        if (state.games.some((item) => item.repo.toLowerCase() === String(game.repo).toLowerCase())) {
          openDetails(state.games.find((item) => item.repo.toLowerCase() === String(game.repo).toLowerCase()));
          return;
        }
        busy(button, true, "正在添加…", "＋ 加入目录");
        try { await api("/api/games", { repo: game.repo }); await loadLibrary(); notify("已将 " + (game.name || game.repo) + " 加入目录。"); }
        catch (error) { notify(error.message, true); busy(button, false, "", "＋ 加入目录"); }
      });
      actions.append(button);
      row.append(mark(game), info, actions);
      $("discover-results").append(row);
    });
  }

  async function searchGitHub(event) {
    event.preventDefault();
    if (state.searchBusy) return;
    const query = $("discover-search").value.trim();
    if (!query) return;
    state.searchBusy = true;
    busy($("discover-submit"), true, "搜索中…", "搜索 GitHub");
    $("discover-count").textContent = "正在搜索 GitHub…";
    $("discover-results").setAttribute("aria-busy", "true");
    try {
      const results = await api("/api/search?q=" + encodeURIComponent(query));
      if (state.stopped) return;
      state.searchResults = Array.isArray(results) ? results : [];
      renderSearchResults();
      $("discover-count").textContent = "找到 " + state.searchResults.length + " 个项目";
    } catch (error) {
      if (state.stopped) return;
      $("discover-count").textContent = "搜索未完成";
      $("discover-results").replaceChildren(element("div", "notice error", error.message));
    } finally {
      state.searchBusy = false;
      busy($("discover-submit"), false, "", "搜索 GitHub");
      if ($("discover-results")) $("discover-results").setAttribute("aria-busy", "false");
    }
  }

  function setupEvents() {
    $("library-nav").addEventListener("click", () => changePage("library"));
    $("discover-nav").addEventListener("click", () => { changePage("discover"); $("discover-search").focus(); });
    document.querySelector(".brand").addEventListener("click", (event) => { event.preventDefault(); changePage("library"); });
    $("library-search").addEventListener("input", (event) => { state.query = event.target.value; renderGames(); });
    $("sort-select").addEventListener("change", (event) => { state.sort = event.target.value; renderGames(); });
    $("category-select").addEventListener("change", (event) => chooseCategory(event.target.value));
    $("clear-filters").addEventListener("click", () => { state.query = ""; $("library-search").value = ""; chooseCategory("all"); $("library-search").focus(); });
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
    $("settings-open").addEventListener("click", () => { showError("token-error", ""); $("token-input").value = ""; renderStats(); $("settings-dialog").showModal(); });
    $("settings-dialog").addEventListener("close", () => { $("token-input").value = ""; });
    $("quit-open").addEventListener("click", () => { showError("quit-error", ""); $("quit-dialog").showModal(); });
    $("discover-form").addEventListener("submit", searchGitHub);
    $("add-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = $("add-submit");
      if (button.disabled) return;
      const repo = $("repo-input").value.trim();
      if (!repo) return;
      showError("add-error", "");
      busy(button, true, "正在添加与核对…", "添加并核对资料");
      try {
        const game = await api("/api/games", { repo });
        await loadLibrary();
        if (state.stopped) return;
        $("add-dialog").close();
        $("repo-input").value = "";
        state.query = ""; $("library-search").value = ""; chooseCategory("all");
        notify("已将 " + (game.name || game.repo || "项目") + " 加入目录。");
      } catch (error) { showError("add-error", error.message); }
      finally { busy(button, false, "", "添加并核对资料"); }
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
    $("quit-confirm").addEventListener("click", async () => {
      busy($("quit-confirm"), true, "正在退出…", "退出工具");
      try {
        await api("/api/quit", {});
        state.stopped = true;
        clearTimeout(state.polling); clearTimeout(state.toastTimer);
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
      $(state.page === "library" ? "library-search" : "discover-search").focus();
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
      const status = await api("/api/status", undefined, 15000);
      if (status.running) { setRefreshState(true, status); schedulePoll(); }
    } catch (error) {
      if (!state.loaded) { $("game-grid").replaceChildren(); $("result-count").textContent = "暂时无法读取目录"; $("game-grid").setAttribute("aria-busy", "false"); }
      notice(error.message, true);
    }
  }
  start();
})();
