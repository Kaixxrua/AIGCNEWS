/* Pure, optional progressive-detail status. Load meadow-progressive.css too.
 * window.meadowDetailStatus.create(container = document.body) returns:
 *   {element, loading(progress?), applying(done,total), complete(), fail(retry), destroy()}
 * loading: a finite fraction 0..1, or {loaded,total} in the same units; invalid
 * /unknown totals show no percentage. applying: nonnegative safe integer counts.
 * 100% download, done==total and resolved retry promises NEVER imply complete.
 * Main owns requests, attempt cancellation, actual apply and core-ready timing;
 * create is hidden/idle. Start showing it only after the core is genuinely live.
 * Retry clicks are single-flight; rejection/throw restores error unless a newer
 * fail/complete/destroy superseded it. Explicit complete is terminal.
 * Return the actual attempt promise from retry to retain its single-flight lock.
 * No canvas/loader/engine access, requests, timers, focus moves or ready flags.
 */
(function (root, factory) {
  "use strict";
  const api = factory(root);
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.meadowDetailStatus = api;
})(typeof window === "object" ? window : globalThis, function (root) {
  "use strict";
  const isCount = value => Number.isSafeInteger(value) && value >= 0;
  const isFraction = value => typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1;
  const words = { loading: "场景细节加载中…", applying: "正在应用场景细节…", retrying: "正在重试场景细节…",
    error: "场景细节加载失败", complete: "场景细节已加载" };

  function create(container = root.document?.body) {
    if (container?.nodeType !== 1 || !container.ownerDocument?.createElement) throw new TypeError("A DOM container is required");
    const document = container.ownerDocument;
    const element = document.createElement("div");
    element.className = "meadow-detail-status";
    element.setAttribute("role", "group");
    element.setAttribute("aria-label", "场景细节");
    element.hidden = true;
    const message = document.createElement("p");
    message.className = "meadow-detail-status__message";
    message.setAttribute("role", "status");
    message.setAttribute("aria-live", "polite");
    message.setAttribute("aria-atomic", "true");
    const count = document.createElement("span");
    count.className = "meadow-detail-status__count";
    count.setAttribute("aria-hidden", "true");
    const progress = document.createElement("progress");
    progress.className = "meadow-detail-status__progress";
    progress.max = 1;
    progress.value = 0;
    progress.hidden = true; // Never display an animated native indeterminate bar.
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "meadow-detail-status__retry";
    retry.textContent = "重试";
    retry.setAttribute("aria-label", "重试加载场景细节");
    retry.hidden = true;
    element.append(message, count, progress, retry);
    container.append(element);
    let phase = "idle", generation = 0, attempts = 0, flight = null, retryCallback = null;
    element.dataset.detailPhase = phase;
    element.dataset.detailRetryCount = "0";
    element.dataset.detailRetryPending = "false";
    const active = () => phase !== "destroyed" && phase !== "complete";

    function renderRetry() {
      element.dataset.detailRetryPending = String(flight !== null);
      retry.hidden = !(phase === "retrying" || (phase === "error" && retryCallback));
      retry.disabled = phase !== "error" || flight !== null;
      retry.textContent = phase === "retrying" ? "重试中…" : "重试";
    }
    function render(next, fraction = null, counts = {}) {
      phase = next;
      element.dataset.detailPhase = phase;
      element.hidden = false;
      // Phase text is the sole live region; do not announce every byte/percent.
      if (message.textContent !== words[phase]) message.textContent = words[phase];
      for (const key of ["detailProgress", "detailLoaded", "detailDone", "detailTotal"]) delete element.dataset[key];
      Object.assign(element.dataset, counts);
      progress.hidden = fraction === null;
      progress.setAttribute("aria-label", phase === "applying" ? "场景细节应用进度" : "场景细节下载进度");
      if (fraction !== null) { progress.value = fraction; element.dataset.detailProgress = String(fraction); }
      count.textContent = counts.detailDone !== undefined ? `${counts.detailDone} / ${counts.detailTotal}`
        : fraction !== null ? `${Math.floor(fraction * 100)}%` : "";
      renderRetry();
    }
    function fail(callback) {
      if (!active()) return false;
      generation++;
      retryCallback = typeof callback === "function" ? callback : null;
      render("error");
      return true;
    }
    function finishRetry(ticket, failed) {
      if (flight !== ticket) return;
      flight = null;
      if (!active()) return;
      if (failed && generation === ticket.generation) fail(ticket.callback);
      else renderRetry(); // A resolved promise is not an applied-detail signal.
    }
    function onRetry() {
      if (phase !== "error" || flight || !retryCallback) return;
      const ticket = { generation, callback: retryCallback };
      flight = ticket;
      element.dataset.detailRetryCount = String(++attempts);
      render("retrying");
      Promise.resolve().then(() => {
        if (active() && flight === ticket && generation === ticket.generation) return Reflect.apply(ticket.callback, undefined, []);
      }).then(() => finishRetry(ticket, false), () => finishRetry(ticket, true));
    }
    retry.addEventListener("click", onRetry);

    return Object.freeze({
      element,
      loading(value) {
        if (!active()) return false;
        let fraction = isFraction(value) ? value : null, counts = {};
        if (value && typeof value === "object" && isCount(value.loaded) && isCount(value.total)
            && value.total > 0 && value.loaded <= value.total) {
          fraction = value.loaded / value.total;
          counts = { detailLoaded: String(value.loaded), detailTotal: String(value.total) };
        }
        render("loading", fraction, counts);
        return true;
      },
      applying(done, total) {
        if (!active()) return false;
        const valid = isCount(done) && isCount(total) && done <= total;
        render("applying", valid && total > 0 ? done / total : null,
          valid ? { detailDone: String(done), detailTotal: String(total) } : {});
        return true;
      },
      complete() {
        if (!active()) return false;
        generation++;
        flight = retryCallback = null;
        render("complete");
        return true;
      },
      fail,
      destroy() {
        if (phase === "destroyed") return false;
        generation++;
        phase = "destroyed";
        flight = retryCallback = null;
        element.dataset.detailPhase = phase;
        element.dataset.detailRetryPending = "false";
        retry.disabled = true;
        retry.removeEventListener("click", onRetry);
        element.remove();
        return true;
      }
    });
  }
  return Object.freeze({ create });
});
