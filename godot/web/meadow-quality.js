/* One chosen pack per page. Changing quality navigates once to a fresh engine.
 * prepare_web_build.py injects MEADOW_QUALITY (available packs) and
 * MEADOW_QUALITY_SHARED (shared WASM, engine JS and referenced UI scripts/styles).
 * Size totals count shared files once plus the chosen pack; HTML/headers and
 * cache savings are not included. Prepared encodings do not imply live support.
 * Runtime contract: OS.get_cmdline_user_args() receives exactly one
 * --meadow-quality=original|balanced|lite after the Godot "--" separator.
 * The scene owns internal resolution/detail; this helper never resizes canvas.
 * The existing canvas.dataset.textureQuality remains available for inspection.
 */
(() => {
  "use strict";
  const preferenceKey = "meadow-texture-quality-v1";
  const labels = { lite: "极速", balanced: "均衡", original: "原画" };
  const modes = Object.keys(labels);
  const known = bytes => Number.isSafeInteger(bytes) && bytes >= 0;
  const totals = records => Object.fromEntries(["bytes", "gzipBytes"].flatMap(key =>
    records.length && records.every(record => known(record?.[key]))
      ? [[key, records.reduce((sum, record) => sum + record[key], 0)]] : []));
  const sizeText = record => [
    known(record?.gzipBytes) ? `gzip ${(record.gzipBytes / 1_000_000).toFixed(1)} MB` : null,
    known(record?.bytes) ? `未压缩 ${(record.bytes / 1_000_000).toFixed(1)} MB` : null
  ].filter(Boolean).join(" · ") || "大小待生成";
  const text = (id, value) => { const node = document.getElementById(id); if (node) node.textContent = value; };
  let mounted = false;
  window.meadowQuality = {
    mount(config) {
      if (mounted) return;
      mounted = true;
      const dialog = document.getElementById("quality-dialog");
      const enter = document.getElementById("quality-enter");
      const cancel = document.getElementById("quality-cancel");
      const trigger = document.getElementById("quality-control");
      const notice = document.getElementById("quality-notice");
      const radios = [...document.querySelectorAll('input[name="quality"]')];
      const defaultPack = config.mainPack || `${config.executable}.pck`;
      // An unprepared shell only proves the exported default pack exists.
      const choices = window.MEADOW_QUALITY ?? {
        original: { pack: defaultPack, bytes: config.fileSizes?.[defaultPack] }
      };
      const engineFiles = [`${config.executable}.wasm`, `${config.executable}.js`];
      const shared = window.MEADOW_QUALITY_SHARED ?? Object.fromEntries(
        engineFiles.map(name => [name, { bytes: config.fileSizes?.[name] }]));
      const sharedRecords = engineFiles.every(name => shared[name]) ? Object.values(shared) : [];
      const available = value => modes.includes(value) && typeof choices[value]?.pack === "string"
        && choices[value].pack.length > 0 && radios.some(radio => radio.value === value);
      let active = null;
      let started = false;
      let navigating = false;
      const select = value => radios.forEach(radio => { radio.checked = radio.value === value; });
      const remember = value => { try { window.localStorage.setItem(preferenceKey, value); } catch {} };
      const selected = () => radios.find(radio => radio.checked && !radio.disabled && available(radio.value))?.value;
      for (const radio of radios) {
        radio.disabled = !available(radio.value);
        radio.addEventListener("change", updateSummary);
        text(`quality-${radio.value}-size`, radio.disabled
          ? "此版本暂未提供" : choices[radio.value].details
            ? `首屏素材 · ${sizeText(choices[radio.value])}；后续细节 · ${sizeText(choices[radio.value].details)}`
            : `素材包 · ${sizeText(choices[radio.value])}`);
      }
      if (choices.lite?.details) text("quality-lite-description", "先进入低细节的真实场景，高清纹理、植被与精细地形随后补齐；最终场景不删减");
      const recommendation = document.getElementById("quality-recommended");
      if (recommendation) recommendation.hidden = !available("lite");
      text("quality-shared-size", `共享引擎与界面 · ${sizeText(totals(sharedRecords))}`);
      function updateSummary() {
        const value = selected();
        enter.disabled = !value || navigating;
        text("quality-total-size", value
          ? `${labels[value]}${choices[value].details ? "首屏下载" : "下载合计"} · ${sizeText(sharedRecords.length ? totals([...sharedRecords, choices[value], ...(choices[value].bootstrap ? [choices[value].bootstrap] : [])]) : {})}`
          : "暂无可用画质，请稍后重新载入。");
      }
      function show() {
        if (navigating) return;
        select(active || selected());
        cancel.hidden = !started;
        enter.textContent = started ? "应用画质" : "进入原野";
        notice.textContent = started
          ? "更换画质会重新载入场景，下载所选素材包；共享引擎可复用缓存。"
          : "确认后才下载所选素材包。会记住本次选择，下次直接进入；可从右上角“画质”更改。";
        updateSummary();
        if (!dialog.open) dialog.showModal();
        (radios.find(radio => radio.checked && !radio.disabled) || dialog).focus();
      }
      function start(value) {
        if (started || !available(value)) return;
        active = value;
        started = true;
        select(value);
        remember(value);
        const baseChoice = choices[value];
        const choice = window.meadowCampIntegration?.overrideChoice(value, baseChoice) || baseChoice;
        document.getElementById("loading-progress").hidden = false;
        document.getElementById("loading").setAttribute("aria-busy", "true");
        const fileSizes = Object.fromEntries(Object.entries(config.fileSizes || {})
          .filter(([name]) => !/\.pck(?:[?#]|$)/i.test(name)));
        if (known(choice.bytes)) fileSizes[choice.pack] = choice.bytes;
        if (choice.bootstrap) fileSizes[choice.bootstrap.file] = choice.bootstrap.bytes;
        const args = (config.args || []).filter(arg => !arg.startsWith("--meadow-quality="));
        if (!args.includes("--")) args.push("--");
        args.push(`--meadow-quality=${value}`);
        document.getElementById("canvas").dataset.textureQuality = value;
        trigger.textContent = `画质 · ${labels[value]}`;
        updateSummary();
        dialog.close();
        window.meadowTimeUI.start({ ...config, ...(choice.details ? {progressive: true} : {}),
          ...(choice.campPresentation ? {campPresentation: true} : {}),
          ...(choice.bootstrap ? {bootstrap:choice.bootstrap} : {}), args, fileSizes, mainPack: choice.pack });
      }
      trigger.addEventListener("click", show);
      cancel.addEventListener("click", () => dialog.close());
      dialog.addEventListener("cancel", event => { if (!started) event.preventDefault(); });
      dialog.addEventListener("close", () => { if (started && !navigating) trigger.focus(); });
      enter.addEventListener("click", () => {
        const value = selected();
        if (!value || navigating) return;
        if (!started) {
          start(value);
        } else if (value === active) {
          dialog.close();
        } else {
          navigating = true;
          enter.disabled = true;
          remember(value);
          const destination = new URL(window.location.href);
          destination.searchParams.set("quality", value);
          window.location.assign(destination.href);
        }
      });
      const requested = new URL(window.location.href).searchParams.get("quality");
      let saved;
      try { saved = window.localStorage.getItem(preferenceKey); } catch {}
      const initial = available(requested) ? requested : available(saved) ? saved : null;
      if (initial) start(initial);
      else {
        select(modes.find(available));
        document.getElementById("loading").setAttribute("aria-busy", "false");
        document.getElementById("loading-message").textContent = "选择画质后进入原野。";
        document.getElementById("loading-progress").hidden = true;
        show();
      }
    }
  };
})();
