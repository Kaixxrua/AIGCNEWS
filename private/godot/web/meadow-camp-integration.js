/* Trusted, same-origin iframe owner of the optional public presentation pack.
 * No account/API/reward logic. The generated config pins immutable local files.
 * Loading this helper alone cannot fetch anything or change scene readiness. */
(() => {
  'use strict';
  let current = null;
  const sha = value => typeof value === 'string' && /^[a-f0-9]{64}$/.test(value);
  const knownTiers = {original:'index.pck', balanced:'index-balanced.pck', lite:'index-lite.pck'};
  function validate(config) {
    if (config?.version !== 1 || config.source !== 'frozen-v153' || !config.optionalPack) throw Error('Unpinned camp integration');
    for (const [tier, file] of Object.entries(knownTiers)) {
      const item = config.bindings?.[tier], boot = item?.bootstrap, pack = item?.selectedPack;
      const variant = tier === 'lite' ? 'lite' : 'full';
      if (item?.mainPack !== file || pack?.file !== file || !sha(pack?.sha256) || pack.sha256 !== item.coreSha256
        || !Number.isSafeInteger(pack.bytes) || pack.bytes <= 0 || !sha(boot?.sha256)
        || !Number.isSafeInteger(boot?.bytes) || boot.bytes <= 0 || boot.bytes >= 128 * 1024
        || item.settingsVariant !== variant || boot.file !== `camp-bootstrap-${variant}-${boot.sha256.slice(0,12)}.pck`
        || item.progressive !== (tier === 'lite')) throw Error('Invalid selected pack binding');
    }
  }
  window.meadowCampIntegration = Object.freeze({
    initialize(config) {
      if (current) throw Error('Camp integration already initialized');
      // Query opts into a capability, but can never choose its authority/host.
      if (window.parent === window || new URLSearchParams(window.location.search).get('camp') !== '1') return false;
      validate(config);
      if (!window.MeadowCampBridge) throw Error('Camp presentation bridge missing');
      const mount = window.MeadowCampBridge.createMountClient({pack:config.optionalPack, actorShards:config.actorShards ?? []});
      const bridge = window.MeadowCampBridge.create({allowedParentOrigin:window.location.origin, assetIds:config.assetIds});
      window.meadowCampMount = mount;
      window.meadowCamp = bridge;
      current = {config, mount, bridge, engine:null, canvas:null, binding:null, presented:false, disposed:false,
        actors:null, runtimeLoaded:false};
      window.addEventListener('pagehide', () => {
        if (!current) return;
        current.disposed = true; current.actors?.dispose(); current.bridge.dispose(); current.mount.dispose();
      }, {once:true});
      window.addEventListener('pageshow', event => {
        // A restored page has a disposed engine bridge, not a fresh lease.
        if (event.persisted && current?.disposed) window.location.reload();
      });
      return true;
    },
    overrideChoice(tier, choice) {
      if (!current || current.disposed) return null;
      const binding = current.config.bindings[tier];
      if (!binding || choice.pack !== binding.mainPack || choice.bytes !== binding.selectedPack.bytes) throw Error('Selected camp scene mismatch');
      return {...choice, campPresentation:true, bootstrap:{...binding.bootstrap, kind:'camp-wrapper',
        coreSha256:binding.coreSha256, selectedPack:binding.selectedPack, settingsVariant:binding.settingsVariant}};
    },
    attachEngine(engine, config, canvas) {
      if (!current || current.engine || current.disposed || config.campPresentation !== true) throw Error('Camp engine must start once');
      const binding = Object.values(current.config.bindings).find(item => item.mainPack === config.mainPack);
      if (!binding || config.bootstrap?.sha256 !== binding.bootstrap.sha256 || config.bootstrap?.coreSha256 !== binding.coreSha256) throw Error('Camp engine binding mismatch');
      current.engine = engine; current.canvas = canvas; current.binding = binding;
    },
    corePresented() {
      const state = current;
      if (!state || state.disposed || state.presented || !state.engine) return;
      state.presented = true;
      state.bridge.corePresented();
      const nativeCore = state.mount.corePresented();
      const report = status => {
        if (state.disposed) return;
        state.bridge.report(status); state.canvas.dataset.campStatus = status;
        const retry = window.document?.getElementById('camp-assets-retry');
        if (retry) retry.hidden = !(state.runtimeLoaded && state.actors && status === 'error');
      };
      // loadPackAfterCore waits for the native host's acknowledgement, which can
      // only follow this actual core gate. Progress and rewards are not touched.
      const runtimeReady = window.MeadowCampBridge.loadPackAfterCore({pack:state.config.optionalPack,
        coreReady:nativeCore, engine:state.engine, mount:(path,digest) => state.mount.mount(path,digest), onStatus:report});
      if (state.config.actorShards?.length) {
        state.actors = window.MeadowCampBridge.createActorLoader({actorShards:state.config.actorShards,
          assetIds:state.config.assetIds, coreReady:nativeCore, runtimeReady, engine:state.engine,
          mountActor:(path,digest) => state.mount.mountActor(path,digest), onStatus:report});
        state.bridge.bindAssetLoader(state.actors.select);
      }
      void runtimeReady.then(() => { state.runtimeLoaded = true; })
        .catch(error => { report(error?.reloadRequired ? 'reload_required' : 'error'); console.warn('MEADOW_CAMP_PRESENTATION_FAILED', error?.message || 'unavailable'); });
    },
    retryActors() {
      if (!current?.actors || !current.runtimeLoaded || current.disposed) return false;
      void current.actors.retry().catch(error => {
        current.bridge.report(error?.reloadRequired ? 'reload_required' : 'error');
      });
      return true;
    }
  });
})();
