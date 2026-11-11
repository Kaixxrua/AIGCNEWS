"use strict";

(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.PortShelfMarketplace = api;
})(globalThis, function () {
  const PRICE_MAX = 9999999900;
  const STOCK_MAX = 399960;
  const activeStatuses = new Set(["queued", "creating", "created", "publishing", "confirming"]);
  const retryStatuses = new Set(["pending", "waiting_materials", "attention", "failed", "paused", "create_unknown"]);

  function defaultConfig() {
    return { enabled: false, shopUserName: "", itemBizType: 2, spBizType: 0, categoryId: "", properties: [], province: 0, city: 0, district: 0, priceFen: 0, stock: 0, titlePrefix: "" };
  }

  // Parse decimal money as text. Floating-point multiplication would change some prices.
  function priceToFen(value) {
    const text = String(value ?? "").trim();
    if (!text) return 0;
    if (!/^\d+(?:\.\d{1,2})?$/.test(text)) throw new Error("售价请填写元，最多保留两位小数。");
    const [whole, fraction = ""] = text.split(".");
    const fen = Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
    if (!Number.isSafeInteger(fen) || fen > PRICE_MAX) throw new Error("售价不能超过 99,999,999 元。");
    return fen;
  }

  function priceText(fen) {
    if (!Number.isSafeInteger(fen) || fen <= 0) return "";
    return Math.floor(fen / 100) + "." + String(fen % 100).padStart(2, "0");
  }

  function integer(value, max, label) {
    if (value === "" || value === undefined || value === null) return 0;
    if (!/^\d+$/.test(String(value)) || !Number.isSafeInteger(Number(value)) || Number(value) > max) throw new Error(label + "请填写 0–" + max + " 的整数。");
    return Number(value);
  }

  function text(value, max, label) {
    const result = String(value ?? "").trim();
    if ([...result].length > max || /[\u0000-\u001f\u007f]/.test(result)) throw new Error(label + "格式不正确或过长，请缩短后保存。");
    return result;
  }

  function validShop(shop) { return Boolean(shop && (shop.is_valid === true || Number(shop.is_valid) === 1)); }

  function validateConfig(value, status = {}, schemas = []) {
    const properties = [];
    const ids = new Set();
    for (const item of Array.isArray(value.properties) ? value.properties : []) {
      const property = Object.fromEntries(["property_id", "property_name", "value_id", "value_name"].map(key => [key, text(item?.[key], key.endsWith("_id") ? 128 : 100, "商品属性")]));
      if (Object.values(property).every(part => !part)) continue;
      if (Object.values(property).some(part => !part)) throw new Error("商品属性的编码、名称、值编码和值名称都需要填写。");
      if (ids.has(property.property_id)) throw new Error("同一个商品属性不能重复填写。");
      ids.add(property.property_id); properties.push(property);
    }
    if (properties.length > 40) throw new Error("商品属性不能超过 40 项。");
    const config = { enabled: Boolean(value.enabled), shopUserName: text(value.shopUserName, 128, "店铺"), itemBizType: 2,
      spBizType: integer(value.spBizType, 99, "商品行业"), categoryId: text(value.categoryId, 128, "类目编码"), properties,
      province: integer(value.province, 999999, "省份编码"), city: integer(value.city, 999999, "城市编码"), district: integer(value.district, 999999, "区县编码"),
      priceFen: integer(value.priceFen, PRICE_MAX, "售价（分）"), stock: integer(value.stock, STOCK_MAX, "库存"), titlePrefix: text(value.titlePrefix, 20, "标题前缀") };
    for (const field of ["province", "city", "district"]) if (config[field] && config[field] < 100000) throw new Error("省、市、区请填写六位行政区编码。");
    if (config.enabled) {
      if (!status.connected) throw new Error("请先保存闲管家应用凭据并检测连接。");
      const shop = (status.shops || []).find(item => String(item.user_name) === config.shopUserName);
      if (!config.shopUserName || !validShop(shop)) throw new Error("请先检测连接，并选择有效的发布店铺。");
      if (!config.spBizType || !config.categoryId) throw new Error("请选择已准入的商品行业和发布类目。");
      if (!config.province || !config.city || !config.district) throw new Error("请选择发布地址，或填写省、市、区行政区编码。");
      if (!config.priceFen) throw new Error("请先确定商品售价，最低为 0.01 元。");
      if (!config.stock) throw new Error("请先确定每款商品库存，至少为 1。");
      for (const schema of schemas) if (Number(schema.required) === 1 && !ids.has(String(schema.property_id))) throw new Error("请填写必填属性：" + (schema.property_name || schema.property_id) + "。");
    }
    return config;
  }

  function listingState(job) {
    const labels = { pending: "等待双盘与资料", waiting_materials: "等待双盘与资料", queued: "等待铺货", creating: "正在创建商品", create_unknown: "创建结果待核实", created: "商品已创建，等待上架", publishing: "正在提交上架", confirming: "正在核对上架", published: "已确认上架", attention: "需要处理", failed: "处理失败", paused: "已暂停" };
    const status = String(job?.status || "");
    return { label: labels[status] || "状态待核实", published: status === "published", retry: retryStatuses.has(status), reconcile: status === "create_unknown", active: activeStatuses.has(status) };
  }

  function safeItemURL(value) {
    try {
      const url = new URL(value);
      const host = url.hostname.toLowerCase();
      if (url.protocol !== "https:" || url.username || url.password || url.port || !(host === "goofish.com" || host.endsWith(".goofish.com") || host === "2.taobao.com")) return "";
      return url.href;
    } catch (_) { return ""; }
  }

  function date(value) {
    const parsed = new Date(value);
    return Number.isFinite(parsed.getTime()) && parsed.getFullYear() > 1970 ? parsed.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "";
  }

  function create(context) {
    const $ = id => document.getElementById(id);
    const state = { status: null, jobs: [], jobsFingerprint: "", schemas: [], properties: [], categories: [], addresses: [], propertyKey: "", propertyParents: new Map(), pendingProperties: new Map(), propertyQueries: new Set(), visible: false, stopped: false, initialized: false, dirty: false, busy: "", loading: false, again: false, revision: 0, timer: null, failures: 0 };
    const inputIds = ["marketplace-shop", "marketplace-biz", "marketplace-category-select", "marketplace-category", "marketplace-address-select", "marketplace-province", "marketplace-city", "marketplace-district", "marketplace-price", "marketplace-stock", "marketplace-title-prefix"];
    function stopped() { return state.stopped || context.isStopped(); }
    function enabled() { return Boolean(state.status?.config?.enabled); }
    function node(tag, className, content) {
      const value = document.createElement(tag);
      if (className) value.className = className;
      if (content !== undefined && content !== null) value.textContent = String(content);
      return value;
    }
    function show(id, message) { if (!stopped()) { $(id).textContent = message || ""; $(id).hidden = !message; } }
    function option(select, value, label, disabled = false) {
      const entry = node("option", "", label); entry.value = String(value); entry.disabled = disabled; select.append(entry);
    }
    function markDirty() { state.dirty = true; show("marketplace-save-note", ""); syncControls(); }
    function propertyKey() { return $("marketplace-biz").value + ":" + $("marketplace-category").value.trim(); }

    function renderShops(selected = $("marketplace-shop").value) {
      const select = $("marketplace-shop"); select.replaceChildren();
      option(select, "", state.status?.connected ? "请选择发布店铺" : "连接后检测店铺");
      for (const shop of state.status?.shops || []) {
        if (!shop?.user_name) continue;
        option(select, shop.user_name, (shop.shop_name || shop.user_nick || shop.user_name) + " · " + shop.user_name + (validShop(shop) ? "" : "（授权不可用）"), !validShop(shop));
      }
      if (selected && !Array.from(select.options).some(item => item.value === selected)) option(select, selected, selected + "（已保存，待检测）");
      select.value = selected;
    }

    function renderCategories() {
      const select = $("marketplace-category-select"); select.replaceChildren();
      option(select, "", state.categories.length ? "请选择发布类目" : "先选择行业并获取类目");
      for (const item of state.categories) {
        if (String(item.sp_biz_type) !== $("marketplace-biz").value || !item.channel_cat_id) continue;
        option(select, item.channel_cat_id, item.channel_cat_name || item.channel_cat_id);
      }
      select.value = $("marketplace-category").value;
      if (select.selectedIndex < 0) select.value = "";
    }

    function renderProperties() {
      const container = $("marketplace-properties"); container.replaceChildren();
      const known = new Set();
      for (const schema of state.schemas) {
        const id = String(schema.property_id || ""); if (!id || known.has(id)) continue; known.add(id);
        const label = node("label"); const title = node("span", "field-label", (schema.property_name || id) + (Number(schema.required) === 1 ? " · 必填" : ""));
        const select = node("select", "cloud-select"); select.dataset.propertyId = id;
        option(select, "", "请选择" + (schema.property_name || "属性值"));
        for (const item of schema.items || []) if (item.value_id !== undefined) option(select, item.value_id, item.value_name || item.value_id);
        const selected = state.properties.find(item => item.property_id === id);
        if (selected && !Array.from(select.options).some(item => item.value === selected.value_id)) option(select, selected.value_id, selected.value_name + "（已保存）");
        select.value = selected?.value_id || "";
        select.addEventListener("change", () => selectProperty(schema, select.value));
        label.append(title, select); container.append(label);
      }
      state.properties.forEach((property, index) => {
        if (known.has(property.property_id)) return;
        const row = node("fieldset", "marketplace-manual-property"); row.append(node("legend", "", property.property_name || "手动商品属性"));
        const fields = node("div", "marketplace-fields");
        for (const [key, title] of [["property_id", "属性编码"], ["property_name", "属性名称"], ["value_id", "值编码"], ["value_name", "值名称"]]) {
          const label = node("label"); label.append(node("span", "field-label", title));
          const input = node("input"); input.type = "text"; input.value = property[key] || ""; input.maxLength = 200; input.autocomplete = "off";
          input.dataset.manualProperty = index + ":" + key;
          input.addEventListener("input", () => { state.properties[index][key] = input.value; markDirty(); });
          label.append(input); fields.append(label);
        }
        const remove = node("button", "text-button", "移除此属性"); remove.type = "button";
        remove.addEventListener("click", () => { state.properties.splice(index, 1); renderProperties(); markDirty(); });
        row.append(fields, remove); container.append(row);
      });
      show("marketplace-properties-help", state.propertyKey === propertyKey() ? state.schemas.length ? "已读取类目属性；标为必填的项目需选择，关联属性会随选项继续读取。" : "该类目暂未返回根属性；可以按平台要求补充属性。" : "选择类目后读取该类目要求的商品属性。");
      syncControls();
    }

    function clearDescendants(parentId) {
      for (const [id, parent] of state.pendingProperties) if (parent === parentId) state.pendingProperties.delete(id);
      for (const [id, parent] of [...state.propertyParents]) if (parent === parentId) {
        clearDescendants(id); state.schemas = state.schemas.filter(item => String(item.property_id) !== id);
        state.properties = state.properties.filter(item => item.property_id !== id); state.propertyParents.delete(id);
      }
    }

    async function selectProperty(schema, value) {
      const id = String(schema.property_id); clearDescendants(id); state.propertyQueries.clear();
      state.properties = state.properties.filter(item => item.property_id !== id);
      const selected = (schema.items || []).find(item => String(item.value_id) === value);
      if (selected) state.properties.push({ property_id: id, property_name: String(schema.property_name || id), value_id: String(selected.value_id), value_name: String(selected.value_name || selected.value_id) });
      markDirty(); renderProperties();
      if (selected?.sub_property_id) await loadProperties(String(selected.sub_property_id), id);
    }

    function applyConfig(config) {
      const value = { ...defaultConfig(), ...config };
      renderShops(String(value.shopUserName || ""));
      const industry = $("marketplace-biz");
      if (value.spBizType && !Array.from(industry.options).some(item => item.value === String(value.spBizType))) option(industry, value.spBizType, "已保存行业 · " + value.spBizType);
      industry.value = value.spBizType || ""; $("marketplace-category").value = value.categoryId || "";
      for (const field of ["province", "city", "district"]) $("marketplace-" + field).value = value[field] || "";
      $("marketplace-price").value = priceText(value.priceFen); $("marketplace-stock").value = value.stock || ""; $("marketplace-title-prefix").value = value.titlePrefix || "";
      state.properties = Array.isArray(value.properties) ? value.properties.map(item => ({ ...item })) : [];
      if (state.propertyKey !== propertyKey()) { state.schemas = []; state.propertyParents.clear(); state.pendingProperties.clear(); state.propertyQueries.clear(); state.propertyKey = ""; }
      state.dirty = false; renderCategories(); renderProperties();
    }

    function readConfig(targetEnabled) {
      return validateConfig({ enabled: targetEnabled, shopUserName: $("marketplace-shop").value, spBizType: $("marketplace-biz").value, categoryId: $("marketplace-category").value,
        properties: state.properties, province: $("marketplace-province").value, city: $("marketplace-city").value, district: $("marketplace-district").value,
        priceFen: priceToFen($("marketplace-price").value), stock: $("marketplace-stock").value, titlePrefix: $("marketplace-title-prefix").value }, state.status, state.schemas);
    }

    function syncControls() {
      if (stopped()) return;
      const busy = Boolean(state.busy), ready = Boolean(state.status), connected = Boolean(state.status?.connected);
      for (const id of inputIds) $(id).disabled = busy || !ready;
      $("marketplace-properties").querySelectorAll("input,select,button").forEach(input => { input.disabled = busy || !ready; });
      $("marketplace-app-key").disabled = busy || !ready; $("marketplace-app-secret").disabled = busy || !ready;
      $("marketplace-connect").disabled = busy || !ready;
      $("marketplace-connect").textContent = state.busy === "connect" ? "正在保存…" : "保存应用凭据";
      $("marketplace-check").disabled = busy || !connected;
      $("marketplace-check").textContent = state.busy === "check" ? "正在检测…" : "检测连接并获取店铺";
      $("marketplace-disconnect").disabled = busy || !ready || !(connected || state.status?.credentialSaved);
      $("marketplace-save").disabled = busy || !ready || !state.dirty;
      $("marketplace-save").textContent = state.busy === "save" ? "保存中…" : "保存铺货设置";
      $("marketplace-reset").disabled = busy || !ready || !state.dirty;
      $("marketplace-toggle").disabled = busy || !ready;
      $("marketplace-toggle").textContent = state.busy === "pause" ? "正在暂停…" : state.busy === "enable" ? "正在开启…" : enabled() ? "暂停自动铺货" : "开启自动铺货";
      $("marketplace-toggle").classList.toggle("button-primary", !enabled()); $("marketplace-toggle").classList.toggle("button-secondary", enabled());
      $("marketplace-run").disabled = busy || !ready || !enabled() || state.dirty || Boolean(state.status?.running);
      $("marketplace-run").textContent = state.status?.running || state.busy === "run" ? "正在处理…" : "立即处理";
      $("marketplace-run").title = state.dirty ? "请先保存配置。" : !enabled() ? "请先开启自动铺货。" : "收集已完成分享并处理铺货队列。";
      $("marketplace-enqueue").disabled = busy || !ready || state.dirty;
      $("marketplace-enqueue").textContent = state.busy === "enqueue" ? "正在加入…" : "一键加入已完成分享";
      $("marketplace-refresh").disabled = busy || state.loading;
      $("marketplace-categories-load").disabled = busy || !connected || !$("marketplace-biz").value;
      $("marketplace-properties-load").disabled = busy || !connected || !$("marketplace-biz").value || !$("marketplace-category").value.trim();
      $("marketplace-property-add").disabled = busy || !ready;
      $("marketplace-addresses-load").disabled = busy || !connected;
      $("marketplace-dirty-note").textContent = state.dirty ? "有未保存的修改；自动铺货仍使用已保存设置。" : ready ? "配置已保存到本机；不会默认设置售价或开启铺货。" : "正在读取本机配置。";
      $("marketplace-jobs").querySelectorAll("button").forEach(button => { button.disabled = busy || !enabled() || state.dirty; });
    }

    function renderStatus() {
      if (!state.status || stopped()) return;
      const status = state.status;
      $("marketplace-status").textContent = status.running ? "正在处理" : enabled() ? "已开启" : "已暂停";
      $("marketplace-status").dataset.state = enabled() ? "enabled" : "paused";
      $("marketplace-connection-state").textContent = status.connected ? "应用凭据已连接。" + ((status.shops || []).length ? " 已取得 " + status.shops.length + " 个店铺，请选择发布店铺。" : " 请检测连接并获取店铺。") : "还未连接闲管家应用。";
      $("marketplace-credential-help").textContent = status.credentialSaved ? "应用凭据已加密保存在当前 Windows 用户的本机配置中，升级无需重填；不会存入浏览器。" : status.credentialStorageSupported ? "应用凭据尚未保存到本机。如需重启后保留授权，请在上方“无人值守”的高级设置中勾选“在此电脑记住凭据”；不会存入浏览器。" : "当前平台无法持久保存应用凭据，连接仅在本次工具运行期间有效；不会存入浏览器。";
      show("marketplace-service-error", status.error || ""); syncControls();
    }

    function acceptStatus(value, forceConfig = false) {
      if (!value || !value.config || typeof value.config !== "object") throw new Error("闲管家配置返回异常，请刷新状态核对。");
      state.status = value;
      if (!state.initialized || forceConfig || !state.dirty) applyConfig(value.config); else renderShops();
      if (!state.initialized && value.connected) $("marketplace-guide").open = false;
      state.initialized = true; renderStatus();
    }

    function renderJobs() {
      const container = $("marketplace-jobs");
      const openPreviews = new Set([...container.querySelectorAll(".marketplace-preview[open]")].map(detail => detail.closest("[data-marketplace-job]").dataset.marketplaceJob));
      container.replaceChildren();
      let published = 0, attention = 0;
      for (const job of state.jobs) {
        const info = listingState(job); if (info.published) published++; if (["attention", "failed", "create_unknown"].includes(job.status)) attention++;
        const card = node("article", "marketplace-job"); card.dataset.marketplaceJob = String(job.id || "");
        const heading = node("div", "marketplace-job-heading"); const title = node("div"); title.append(node("h4", "", job.title || job.repo || "未命名游戏"), node("p", "field-help", job.repo || ""));
        const badge = node("span", "transfer-status", info.label); badge.dataset.status = info.published ? "done" : info.active ? "running" : ["attention", "failed", "create_unknown"].includes(job.status) ? "failed" : job.status || "unknown";
        heading.append(title, badge); card.append(heading);
        const details = [job.shopUserName ? "店铺：" + job.shopUserName : "", priceText(job.priceFen) ? "售价：¥" + priceText(job.priceFen) : "", job.productId ? "商品编号：" + job.productId : "", job.itemId ? "闲鱼编号：" + job.itemId : ""].filter(Boolean);
        if (details.length) card.append(node("p", "marketplace-job-meta", details.join(" · ")));
        if (info.reconcile) card.append(node("p", "field-help", "创建请求的结果尚未确认，将先查询远端商品，避免重复创建。"));
        else if (job.status === "confirming") card.append(node("p", "field-help", "已提交上架，正在核对远端状态；确认前不会标为成功。"));
        if (job.error) card.append(node("p", "form-error", job.error));
        const retryAt = date(job.nextRunAt); if (retryAt && !info.published) card.append(node("p", "field-help", "下次处理：" + retryAt));
        if (job.content || job.posterUrl) {
          const preview = node("details", "marketplace-preview"); preview.open = openPreviews.has(String(job.id || "")); preview.append(node("summary", "", "查看商品文案与海报"));
          if (job.content) preview.append(node("pre", "", job.content));
          if (typeof job.posterUrl === "string" && /^https:\/\/aigcnews\.cn\/api\/media\/site\/game-posters\/[a-f0-9]{64}\.jpg$/.test(job.posterUrl)) {
            const poster = node("a", "", "查看发布海报 ↗"); poster.href = job.posterUrl; poster.target = "_blank"; poster.rel = "noopener noreferrer"; preview.append(poster);
          }
          card.append(preview);
        }
        const actions = node("div", "marketplace-job-actions"); const href = safeItemURL(job.itemUrl);
        if (href) { const link = node("a", "button button-secondary button-small", info.published ? "查看已上架商品 ↗" : "查看远端商品 ↗"); link.href = href; link.target = "_blank"; link.rel = "noopener noreferrer"; actions.append(link); }
        if (info.retry && job.id) { const retry = node("button", "button button-secondary button-small", info.reconcile ? "核对结果" : "重试此任务"); retry.type = "button"; retry.addEventListener("click", () => action("retry", String(job.id))); actions.append(retry); }
        if (actions.childNodes.length) card.append(actions);
        const updated = date(job.updatedAt); if (updated) card.append(node("p", "marketplace-job-time", "最近更新 " + updated));
        container.append(card);
      }
      $("marketplace-empty").hidden = state.jobs.length > 0;
      $("marketplace-queue-summary").textContent = state.jobs.length + " 个任务 · " + published + " 个已确认上架" + (attention ? " · " + attention + " 个需要核对或处理" : "");
      syncControls();
    }

    function schedule() {
      clearTimeout(state.timer); state.timer = null;
      if (stopped() || !state.visible || document.hidden || state.busy || state.loading || state.failures >= 3) return;
      if (enabled() || state.status?.running || state.jobs.some(job => activeStatuses.has(job.status))) state.timer = setTimeout(load, 2500);
    }

    async function load() {
      clearTimeout(state.timer); state.timer = null;
      if (stopped()) return;
      if (state.loading) { state.again = true; return; }
      state.loading = true; const revision = state.revision; syncControls();
      try {
        const results = await Promise.allSettled([context.api("/api/marketplace", undefined, 20000), context.api("/api/marketplace/jobs", undefined, 20000)]);
        if (stopped() || revision !== state.revision) return;
        const errors = [];
        if (results[0].status === "fulfilled") { try { acceptStatus(results[0].value); } catch (error) { errors.push(error.message); } }
        else errors.push(results[0].reason.message);
        if (results[1].status === "fulfilled" && Array.isArray(results[1].value?.jobs)) {
          const fingerprint = JSON.stringify(results[1].value.jobs);
          state.jobs = results[1].value.jobs;
          if (fingerprint !== state.jobsFingerprint) { state.jobsFingerprint = fingerprint; renderJobs(); }
          if (results[1].value.error) errors.push(results[1].value.error);
        } else errors.push(results[1].status === "rejected" ? results[1].reason.message : "铺货任务返回异常。");
        if (errors.length) state.failures++; else state.failures = 0;
        show("marketplace-load-error", errors.length ? "闲管家状态未能完整刷新，保留上次资料。" + errors.join(" ") + (state.failures >= 3 ? " 请点击刷新状态重试。" : "") : "");
      } finally {
        state.loading = false; syncControls();
        if (state.again && !state.busy && !stopped()) { state.again = false; load(); } else schedule();
      }
    }

    async function perform(name, operation, errorId = "marketplace-action-error") {
      if (state.busy || stopped() || !state.status) return;
      state.busy = name; state.revision++; clearTimeout(state.timer); state.timer = null;
      show(errorId, ""); syncControls();
      try { await operation(); state.failures = 0; }
      catch (error) { show(errorId, error.message || "请求未完成，请刷新状态核对。"); }
      finally { state.busy = ""; syncControls(); if (!stopped()) { state.again = false; await load(); } }
    }

    async function save(mode) {
      if (state.busy || !state.status || stopped()) return;
      let config;
      try {
        config = mode === "pause" ? { ...state.status.config, enabled: false } : readConfig(mode === "enable" || enabled());
        if (mode === "enable" && state.propertyKey !== propertyKey()) throw new Error("请先读取当前类目属性，确认必填项后再开启。");
        if (config.enabled && state.pendingProperties.size) throw new Error("关联属性尚未完整读取，请重新读取类目属性后再开启或保存。");
      } catch (error) { show("marketplace-form-error", error.message); $("marketplace-setup").open = true; return; }
      const keepDraft = mode === "pause" && state.dirty;
      await perform(mode, async () => {
        const result = await context.api("/api/marketplace/config", config, 30000);
        if (stopped()) return;
        acceptStatus(result, !keepDraft);
        show("marketplace-save-note", mode === "pause" ? "自动铺货已暂停，凭据和任务保留。" + (keepDraft ? " 未保存的修改仍已保留。" : "") : mode === "enable" ? "自动铺货已开启。之后双盘分享成功的任务会自动接续铺货。" : "铺货配置已保存。" + (!config.enabled ? " 当前保持暂停。" : " 修改只用于新入队任务。"));
      }, "marketplace-form-error");
    }

    async function connection(name) {
      let body = {};
      if (name === "connect") {
        const appKey = $("marketplace-app-key").value.trim(), appSecret = $("marketplace-app-secret").value.trim();
        if (!appKey || !appSecret) { show("marketplace-connect-error", "请同时填写应用 AppKey 和 AppSecret。"); return; }
        body = { appKey, appSecret };
      }
      if (state.busy || stopped() || !state.status) return;
      $("marketplace-app-key").value = ""; $("marketplace-app-secret").value = "";
      await perform(name, async () => {
        const result = await context.api("/api/marketplace/" + name, body, 30000);
        if (stopped()) return;
        if (result?.config) acceptStatus(result);
        if (name === "connect" && state.status?.connected) $("marketplace-guide").open = false;
        show("marketplace-save-note", name === "disconnect" ? "已断开并清除应用凭据，铺货任务记录保留。" : name === "check" ? "连接检测完成，请核对店铺状态并选择发布店铺。" : "应用凭据已保存，请检测连接并获取店铺。");
      }, "marketplace-connect-error");
    }

    async function loadProperties(subPropertyId = "", parentId = "") {
      const categoryId = $("marketplace-category").value.trim(), spBizType = Number($("marketplace-biz").value);
      if (!categoryId || !spBizType || state.busy || stopped()) return;
      if (subPropertyId) state.pendingProperties.set(subPropertyId, parentId);
      let loaded = null;
      await perform("properties", async () => {
        const result = await context.api("/api/marketplace/properties", { categoryId, spBizType, ...(subPropertyId ? { propertyId: subPropertyId } : {}) }, 30000);
        if (!Array.isArray(result?.items)) throw new Error("类目属性返回异常，请重试。");
        const items = result.items.filter(item => item && item.property_id !== undefined).map(item => ({ ...item, property_id: String(item.property_id) }));
        if (!subPropertyId) { state.schemas = items; state.propertyParents.clear(); state.pendingProperties.clear(); state.propertyQueries.clear(); state.propertyKey = propertyKey(); }
        else for (const item of items) {
          if (!state.schemas.some(existing => existing.property_id === item.property_id)) { state.schemas.push(item); state.propertyParents.set(item.property_id, parentId); }
        }
        state.pendingProperties.delete(subPropertyId); if (subPropertyId) state.propertyQueries.add(subPropertyId);
        loaded = items;
        renderProperties();
      }, "marketplace-form-error");
      if (!loaded || stopped()) return;
      for (const schema of loaded) {
        const selected = state.properties.find(item => item.property_id === schema.property_id);
        const child = (schema.items || []).find(item => String(item.value_id) === selected?.value_id)?.sub_property_id;
        if (!child || state.propertyQueries.has(String(child))) continue;
        if (state.propertyQueries.size >= 16) { state.pendingProperties.set(String(child), schema.property_id); show("marketplace-form-error", "该类目的关联属性层级过多，请核对类目后重试。"); return; }
        await loadProperties(String(child), schema.property_id);
      }
    }

    async function lookup(name) {
      await perform(name, async () => {
        const body = name === "categories" ? { itemBizType: 2, spBizType: Number($("marketplace-biz").value) } : {};
        const result = await context.api("/api/marketplace/" + name, body, 30000);
        if (!Array.isArray(result?.items)) throw new Error("闲管家返回的选项异常，请重试。");
        if (name === "categories") {
          state.categories = result.items;
          for (const item of state.categories) if (item.sp_biz_type && !Array.from($("marketplace-biz").options).some(existing => existing.value === String(item.sp_biz_type))) option($("marketplace-biz"), item.sp_biz_type, item.sp_biz_name || item.sp_biz_type);
          renderCategories();
          if (!result.items.length) show("marketplace-form-error", "当前行业没有返回可发布类目，请核对应用权限与店铺准入情况。");
        } else {
          state.addresses = result.items; const select = $("marketplace-address-select"); select.replaceChildren(); option(select, "", "选择已保存的发布地址");
          state.addresses.forEach((item, index) => option(select, index, item.region || [item.province, item.city, item.district].join(" / ")));
          if (!result.items.length) show("marketplace-form-error", "还没有可用地址，请先在闲管家保存发布地址，或填写行政区编码。");
        }
      }, "marketplace-form-error");
    }

    async function action(name, id) {
      if ((name === "run" || name === "retry") && (!enabled() || state.dirty) || name === "enqueue" && state.dirty) return;
      await perform(name, async () => {
        const path = name === "retry" ? "/api/marketplace/jobs/" + encodeURIComponent(id) + "/retry" : "/api/marketplace/" + name;
        const result = await context.api(path, {}, 30000);
        if (stopped()) return;
        if (result?.config) acceptStatus(result);
        show("marketplace-action-note", name === "enqueue" ? "已请求加入完成双盘分享的任务；已有任务会保留，结果以队列为准。" + (!enabled() ? " 自动铺货仍保持暂停。" : "") : name === "retry" ? "已请求继续处理，请以队列中的核对结果为准。" : "已请求处理铺货队列，商品确认上架后才显示成功。");
      });
    }

    $("marketplace-connect-form").addEventListener("submit", event => { event.preventDefault(); connection("connect"); });
    $("marketplace-check").addEventListener("click", () => connection("check"));
    $("marketplace-disconnect").addEventListener("click", () => connection("disconnect"));
    $("marketplace-form").addEventListener("submit", event => { event.preventDefault(); save("save"); });
    $("marketplace-form").addEventListener("input", markDirty);
    $("marketplace-form").addEventListener("change", event => {
      const id = event.target.id;
      if (["marketplace-biz", "marketplace-category"].includes(id)) {
        if (id === "marketplace-biz") { $("marketplace-category").value = ""; state.categories = []; }
        state.propertyKey = ""; state.schemas = []; state.properties = []; state.propertyParents.clear(); state.pendingProperties.clear(); state.propertyQueries.clear(); renderCategories(); renderProperties();
      }
      markDirty();
    });
    $("marketplace-category-select").addEventListener("change", () => {
      $("marketplace-category").value = $("marketplace-category-select").value; state.propertyKey = ""; state.schemas = []; state.properties = []; state.propertyParents.clear(); state.pendingProperties.clear(); state.propertyQueries.clear(); renderProperties(); markDirty();
    });
    $("marketplace-address-select").addEventListener("change", () => {
      const selected = $("marketplace-address-select").value; if (selected === "") return;
      const item = state.addresses[Number(selected)]; if (!item) return;
      for (const field of ["province", "city", "district"]) $("marketplace-" + field).value = item[field] || "";
      markDirty();
    });
    $("marketplace-categories-load").addEventListener("click", () => lookup("categories"));
    $("marketplace-addresses-load").addEventListener("click", () => lookup("addresses"));
    $("marketplace-properties-load").addEventListener("click", () => loadProperties());
    $("marketplace-property-add").addEventListener("click", () => { state.properties.push({ property_id: "", property_name: "", value_id: "", value_name: "" }); renderProperties(); markDirty(); });
    $("marketplace-toggle").addEventListener("click", () => save(enabled() ? "pause" : "enable"));
    $("marketplace-reset").addEventListener("click", () => { if (!state.busy && state.status) { applyConfig(state.status.config); show("marketplace-form-error", ""); } });
    $("marketplace-enqueue").addEventListener("click", () => action("enqueue"));
    $("marketplace-run").addEventListener("click", () => action("run"));
    $("marketplace-refresh").addEventListener("click", () => { state.failures = 0; load(); });
    document.addEventListener("visibilitychange", () => { if (state.visible && !document.hidden && !stopped()) load(); else { clearTimeout(state.timer); state.timer = null; } });
    applyConfig(defaultConfig());
    return {
      setVisible(visible) { state.visible = visible; clearTimeout(state.timer); state.timer = null; if (!visible) { $("marketplace-app-key").value = ""; $("marketplace-app-secret").value = ""; } else if (!stopped()) { state.failures = 0; load(); } },
      refresh() { if (!stopped()) load(); },
      stop() { state.stopped = true; clearTimeout(state.timer); state.timer = null; $("marketplace-app-key").value = ""; $("marketplace-app-secret").value = ""; },
    };
  }
  return { defaultConfig, priceToFen, priceText, validateConfig, listingState, safeItemURL, create };
});
