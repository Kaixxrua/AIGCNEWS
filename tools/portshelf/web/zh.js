/* Chinese descriptions are supplied by AIGCNEWS; upstream text stays available. */
(() => {
  'use strict';

  const string = (value) => typeof value === 'string' ? value : '';

  function isChinese(value) {
    // Han alone also matches Japanese. Require Chinese wording and reject kana.
    return !/[\u3040-\u30ff\uac00-\ud7af]/u.test(value)
      && /[\u3400-\u9fff]/u.test(value)
      && /游戏|遊戲|开源|開源|一款|一个|一個|这是|這是|支持|提供|需要|基于|基於|可以|运行|運行|重返|体验|體驗|让|讓|现代|現代|电脑|電腦|用于|用於|项目|項目|玩法/u.test(value);
  }

  function describe(value) {
    const game = value && typeof value === 'object' ? value : {};
    const original = string(game.description);
    const enriched = (string(game.descriptionZh) || string(game.description_zh)).trim();
    if (enriched && /[\u3400-\u9fff]/u.test(enriched) && !/[\u3040-\u30ff]/u.test(enriched)) {
      return { text: enriched, source: 'aigcnews', original };
    }
    if (isChinese(original)) {
      return { text: original.trim(), source: 'upstream', original };
    }
    return {
      text: original.trim() ? '中文简介待补充，可查看上游原文。' : '上游暂未提供简介，可查看项目说明。',
      source: 'unknown',
      original,
    };
  }

  function chineseName(value) {
    const text = string(value).trim();
    return text.length <= 160 && /[\u3400-\u9fff]/u.test(text) && !/[\u3040-\u30ff\uac00-\ud7af<>\r\n]/u.test(text) ? text : '';
  }

  function identity(game, record = {}) {
    game = game && typeof game === 'object' ? game : {};
    record = record && typeof record === 'object' ? record : {};
    const nameZh = chineseName(record.gameNameZh) || chineseName(game.gameNameZh) || chineseName(game.subtitle);
    const original = string(record.gameNameOriginal).trim() || string(game.gameNameOriginal).trim();
    const project = string(game.name).trim() || string(game.repo).trim() || '开源游戏';
    const secondary = [...new Set([original, project, string(game.repo)].filter(value => value && value !== nameZh))].join(' · ');
    return { title: nameZh || project, nameZh, original, project, secondary, pending: !nameZh };
  }

  function imageURL(value, source = false) {
    if (typeof value !== 'string' || /[\s\\\u0000-\u001f\u007f]/u.test(value)) return null;
    if (!source && typeof value === 'string' && /^https:\/\/aigcnews\.cn\/api\/media\/site\/game-posters\/[a-f0-9]{64}\.jpg$/.test(value)) return value;
    if (!/^https:\/\/(?:raw\.githubusercontent\.com|user-images\.githubusercontent\.com|github\.com|upload\.wikimedia\.org|en\.wikipedia\.org)\//i.test(value)) return null;
    try {
      const url = new URL(value);
      if (url.username || url.password || url.port || value.includes('?') || (!source && url.hash) || /(?:^|\/)\.{1,2}(?:\/|$)|%(?:2f|5c|0[0-9a-f]|7f)/i.test(value.slice(value.indexOf('/', 8)))) return null;
      if (url.hostname === 'github.com' && !source && !/^\/user-attachments\/assets\/[a-zA-Z0-9-]+$/.test(url.pathname)) return null;
      if (url.hostname === 'upload.wikimedia.org') {
        const pathname = decodeURIComponent(url.pathname);
        if (source || value.includes('#') || /[<>"\u0000-\u001f\u007f]|\.svg(?:\.|\/|$)/i.test(pathname) || !/^\/wikipedia\/(?:en|commons)\/(?:thumb\/)?[a-f0-9]\/[a-f0-9]{2}\/[^/]+\.(?:jpe?g|png|webp)(?:\/[0-9]+px-[^/]+\.(?:jpe?g|png|webp))?$/i.test(pathname)) return null;
      }
      if (url.hostname === 'en.wikipedia.org') {
        const pathname = decodeURIComponent(url.pathname);
        if (!source || value.includes('#') || !/^\/wiki\/[^/]+$/.test(pathname) || /[<>"\u0000-\u001f\u007f]/.test(pathname) || /^\/wiki\/(?:File|Category|Special|Wikipedia|Talk|Template|Help|Portal|User|Media|Draft):/i.test(pathname)) return null;
      }
      if (url.pathname === '/') return null;
      return url.href;
    } catch (_) { return null; }
  }

  function publicPosterSourceURL(value) {
    if (typeof value !== 'string' || /[\s\\<>"\u0000-\u001f\u007f]/u.test(value)) return null;
    const authority = /^https:\/\/([^/?#]+)(?:[/?#]|$)/i.exec(value)?.[1];
    if (!authority || /[:@%]/.test(authority)) return null;
    try {
      const url = new URL(value);
      const host = url.hostname;
      if (url.protocol !== 'https:' || url.username || url.password || url.port || !/^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z][a-z0-9-]*$/i.test(host) || /(?:^|\.)(?:localhost|local|localdomain|internal|intranet|lan|home|test|invalid|example|onion)$|\.home\.arpa$/i.test(host)) return null;
      if (/[\\<>"\u0000-\u001f\u007f]/u.test(decodeURIComponent(url.pathname + url.search + url.hash))) return null;
      if (['raw.githubusercontent.com', 'user-images.githubusercontent.com', 'github.com', 'upload.wikimedia.org', 'en.wikipedia.org'].includes(host)) return imageURL(value, true);
      return url.href;
    } catch (_) { return null; }
  }

  function mergeRecord(previous, item) {
    const fields = ['descriptionZh', 'gameNameZh', 'gameNameOriginal', 'posterUrl', 'posterSourceUrl', 'posterKind', 'posterStatus'];
    const artworkFields = ['posterUrl', 'posterSourceUrl', 'posterKind'];
    const authoritativeArtwork = item.status === 'ready' && item.detailsVersion === 1 && item.posterSearchVersion === 1;
    if (previous?.status === 'pending' && item.status === 'missing') return previous;
    const record = { ...item, error: string(item.error), detailsVersion: item.detailsVersion === 1 ? 1 : 0, posterSearchVersion: item.posterSearchVersion === 1 ? 1 : 0 };
    for (const field of fields) record[field] = string(item[field]);
    record.posterRetryAfter = Number.isFinite(item.posterRetryAfter) && item.posterRetryAfter > 0 ? item.posterRetryAfter : 0;
    if (previous && (item.status !== 'ready' || (record.posterSearchVersion === 1 && ['missing', 'unavailable'].includes(record.posterStatus)))) {
      for (const field of fields) {
        const artworkIsProvided = artworkFields.includes(field) && (authoritativeArtwork || Object.prototype.hasOwnProperty.call(item, field));
        if (!record[field] && !artworkIsProvided) record[field] = string(previous[field]);
      }
      record.detailsVersion = record.detailsVersion === 1 || previous.detailsVersion === 1 ? 1 : 0;
      if (item.posterSearchVersion === undefined) record.posterSearchVersion = previous.posterSearchVersion === 1 ? 1 : 0;
      if (item.checkedAt === undefined) record.checkedAt = previous.checkedAt;
      if (item.posterRetryAfter === undefined) record.posterRetryAfter = Number.isFinite(previous.posterRetryAfter) && previous.posterRetryAfter > 0 ? previous.posterRetryAfter : 0;
    } else if (previous?.detailsVersion === 1 && record.detailsVersion !== 1) {
      for (const field of fields.slice(1)) if (!artworkFields.includes(field) || !Object.prototype.hasOwnProperty.call(item, field)) record[field] = string(previous[field]);
      record.detailsVersion = previous.detailsVersion;
    }
    return record;
  }

  function needsDetails(game, record = {}) {
    return !(record.detailsVersion === 1 || game?.detailsVersion === 1) || describe({ ...game, descriptionZh: record.descriptionZh || game?.descriptionZh }).source === 'unknown' || needsPoster(game, record);
  }

  function posterEvidence(game, record = {}) {
    const value = { ...game, ...record };
    let url = imageURL(value.posterUrl);
    const cached = url && new URL(url).hostname === 'aigcnews.cn';
    let source = cached ? publicPosterSourceURL(value.posterSourceUrl) : imageURL(value.posterSourceUrl, true);
    if (cached && !source) url = null;
    else if (url && new URL(url).hostname === 'upload.wikimedia.org') {
      const normalize = text => text.normalize('NFKC').replace(/[‘’]/g, "'").replace(/[“”]/g, '"').replace(/_/g, ' ').replace(/\s+/g, ' ').trim().toLocaleLowerCase('en');
      const original = normalize(string(value.gameNameOriginal));
      const article = source && new URL(source).hostname === 'en.wikipedia.org' ? normalize(decodeURIComponent(new URL(source).pathname.slice('/wiki/'.length))) : '';
      if (!original || !article || ![original, original + ' (video game)'].includes(article)) { url = null; source = null; }
    } else if (!cached && source && new URL(source).hostname === 'en.wikipedia.org') source = null;
    return { url, source, kind: value.posterKind === 'screenshot' ? 'screenshot' : 'cover', status: ['ready', 'missing', 'unavailable'].includes(value.posterStatus) ? value.posterStatus : '' };
  }

  function canSearchPoster(game, record = {}) {
    const repo = string(record.repo) || string(game?.repo);
    return (record.detailsVersion === 1 || game?.detailsVersion === 1) && describe({ ...game, descriptionZh: record.descriptionZh || game?.descriptionZh }).source !== 'unknown' && /^[A-Za-z0-9][A-Za-z0-9-]{0,38}\/[A-Za-z0-9_.-]{1,100}$/.test(repo) && !/\/\.{1,2}$/.test(repo);
  }

  function needsPoster(game, record = {}) {
    return canSearchPoster(game, record) && !posterEvidence(game, record).url;
  }

  function posterRetrySeconds(record, now = Date.now()) {
    const checked = Date.parse(record?.checkedAt || '');
    const seconds = record?.posterRetryAfter;
    if (!Number.isFinite(checked) || !Number.isFinite(seconds) || seconds <= 0) return 0;
    const remaining = Math.ceil((checked + seconds * 1000 - now) / 1000);
    return Number.isFinite(remaining) ? Math.max(0, remaining) : 0;
  }

  globalThis.PortShelfDescriptions = Object.freeze({ describe, identity, imageURL, mergeRecord, needsDetails, posterEvidence, needsPoster, canSearchPoster, posterRetrySeconds });
})();
