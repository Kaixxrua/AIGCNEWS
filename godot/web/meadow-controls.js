(() => {
  "use strict";
  const timeButton = document.getElementById("time-control");
  const motionButton = document.getElementById("motion-control");
  const timeLabel = document.getElementById("time-label");
  const motionIcon = document.getElementById("motion-icon");
  const state = document.getElementById("time-state");
  const canvas = document.getElementById("canvas");
  const loading = document.getElementById("loading");
  const message = document.getElementById("loading-message");
  const progress = document.getElementById("loading-progress");
  const retry = document.getElementById("retry");
  const motionPreference = window.matchMedia("(prefers-reduced-motion: reduce)");
  let callback = null;
  let lastAnnouncement = "";
  let failed = false;
  let engineStarted = false;
  let sceneReported = false;
  let readyScheduled = false;
  let loadStarted = 0;
  let timeRequestToken = 0;
  let finishVisibility = () => {};
  const now = () => window.performance?.now?.() ?? 0;

  function finishReady() {
    if (failed || !engineStarted || !sceneReported || readyScheduled) return;
    readyScheduled = true;
    // Engine.startGame resolves before the first rendered scene is necessarily
    // present. Wait for the actual Godot ready signal and two paint boundaries.
    window.requestAnimationFrame(() => window.requestAnimationFrame(() => {
      if (failed) return;
      canvas.dataset.loadMs = Math.round(now() - loadStarted).toString();
      // Navigation-relative, unlike loadMs which starts after the HTML/helpers.
      // The same real scene/engine/two-paint gate controls BOTH clocks.
      canvas.dataset.navigationReadyMs = Math.round(now()).toString();
      loading.hidden = true;
      loading.setAttribute("aria-busy", "false");
      finishVisibility();
      window.meadowLoader.report(canvas);
      window.meadowStartupTrace?.finish();
      window.meadowStream?.corePresented();
      // Optional presentation starts AFTER the same real gate; never delay or
      // replace readiness, and never allow an add-on failure to hide the world.
      window.meadowCampIntegration?.corePresented();
    }));
  }

  function send(command, ...args) {
    if (callback) {
      if (command === "time") {
        timeRequestToken++;
        canvas.dataset.timeSwitchRequestedAtMs = String(now());
        delete canvas.dataset.timeSwitchAckMs;
        delete canvas.dataset.timeSwitchPresentationMs;
      }
      callback(command, ...args);
    }
  }

  function fail(error) {
    failed = true;
    window.meadowStartupTrace?.finish("failed");
    finishVisibility();
    window.meadowTimeUI.unbind();
    loading.hidden = false;
    loading.setAttribute("aria-busy", "false");
    message.setAttribute("role", "alert");
    message.textContent = "场景未能载入。" + (error?.message || String(error));
    progress.hidden = true;
    retry.hidden = false;
    console.error(error);
  }

  timeButton.addEventListener("click", () => send("time"));
  motionButton.addEventListener("click", () => send("motion"));
  retry.addEventListener("click", () => window.location.reload());
  motionPreference.addEventListener("change", (event) => send("reduced_motion", event.matches));
  // Canvas input is handled by Godot. Only handle the same shortcuts outside it.
  document.addEventListener("keydown", (event) => {
    if (event.target === canvas || event.repeat || event.ctrlKey || event.altKey || event.metaKey) return;
    if (event.target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(event.target.tagName)) return;
    const command = event.code === "KeyN" ? "time" : event.code === "KeyP" ? "motion" : null;
    if (command && callback) {
      event.preventDefault();
      event.stopImmediatePropagation();
      send(command);
    }
  }, true);

  window.meadowTimeUI = {
    reportFps(value) {
      const readout = document.getElementById("scene-fps");
      if (!readout || failed || !Number.isFinite(value) || value < 0) return;
      readout.textContent = `${Math.round(value)} FPS`;
      readout.hidden = document.hidden;
    },
    sceneReady(sceneBuildMs) {
      sceneReported = true;
      canvas.dataset.sceneBuildMs = Math.round(sceneBuildMs).toString();
      canvas.dataset.sceneSignalMs = Math.round(now() - loadStarted).toString();
      window.meadowStartupTrace?.mark("sceneReady");
      message.textContent = "正在呈现草原…";
      finishReady();
    },
    bind(handler) {
      callback = handler;
      timeButton.disabled = false;
      motionButton.disabled = false;
      send("reduced_motion", motionPreference.matches);
    },
    unbind() {
      callback = null;
      timeButton.disabled = true;
      motionButton.disabled = true;
    },
    render(night, blend, moving, transitioning, clock) {
      document.body.dataset.night = String(night);
      // Small read-only DOM telemetry also makes Web/Godot bridge regressions testable.
      canvas.dataset.nightBlend = blend.toFixed(3);
      canvas.dataset.weatherClock = clock.toFixed(3);
      canvas.dataset.motion = String(moving);
      canvas.dataset.transitioning = String(transitioning);
      timeLabel.textContent = night ? "破晓" : "入夜";
      timeButton.setAttribute("aria-label", night ? "破晓，切换到白天" : "入夜，切换到夜晚");
      const motionLabel = moving ? "暂停环境动画" : "播放环境动画";
      motionButton.setAttribute("aria-label", motionLabel);
      motionButton.title = `${motionLabel} · P`;
      motionIcon.setAttribute("d", moving ? "M8 5v14M16 5v14" : "M8 5l11 7-11 7Z");
      if (!transitioning) {
        if (canvas.dataset.timeSwitchRequestedAtMs && !canvas.dataset.timeSwitchAckMs) {
          const requested = canvas.dataset.timeSwitchRequestedAtMs;
          const requestToken = timeRequestToken;
          canvas.dataset.timeSwitchAckMs = String(Math.round(now() - Number(requested)));
          window.requestAnimationFrame(() => window.requestAnimationFrame(() => {
            if (!failed && timeRequestToken === requestToken && canvas.dataset.timeSwitchRequestedAtMs === requested)
              canvas.dataset.timeSwitchPresentationMs = String(Math.round(now() - Number(requested)));
          }));
        }
        const description = `已切换到${night ? "夜晚" : "白天"}，环境动画${moving ? "正在播放" : "已暂停"}。`;
        if (description !== lastAnnouncement) {
          state.textContent = description;
          lastAnnouncement = description;
        }
        canvas.setAttribute("aria-label", `风起原野，${night ? "月夜" : "晴天"}草原场景`);
      }
    },
    start(config) {
      try {
        loadStarted = now();
        canvas.dataset.loadStartedPageMs = Math.round(loadStarted).toString();
        if (!window.meadowLoader) throw new Error("载入组件下载失败，请刷新重试。");
        finishVisibility = window.meadowLoader.observeVisibility(canvas);
        if (typeof Engine === "undefined") throw new Error("游戏引擎下载失败，请刷新重试。");
        const missing = Engine.getMissingFeatures({ threads: false });
        if (missing.length) throw new Error(`浏览器缺少：${missing.join("、")}。请使用支持 WebGL 2 的浏览器。`);
        window.meadowLoader.start(config, {
          focusCanvas: false,
          onProgress(current, total) {
            if (current > 0 && total > 0) {
              progress.max = total;
              progress.value = current;
              const mib = (bytes) => (bytes / 1048576).toFixed(1);
              message.textContent = `正在接收引擎与素材 · ${mib(current)} / ${mib(total)} MiB（解压后）`;
              if (current >= total) {
                canvas.dataset.downloadMs = Math.round(now() - loadStarted).toString();
                message.textContent = "下载完成，正在准备场景…";
              }
            } else {
              progress.removeAttribute("value");
              progress.removeAttribute("max");
            }
          },
          onExit(code) {
            fail(new Error(`场景已退出（${code}），可重新载入。`));
          }
        }, canvas).then(() => {
          engineStarted = true;
          finishReady();
        }, fail);
      } catch (error) {
        fail(error);
      }
    }
  };
})();
