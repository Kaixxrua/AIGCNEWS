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
    if (typeof value !== 'string' || /[\s\\\u0000-\u001f\u007f]/u.test(value) || !/^https:\/\/(?:raw\.githubusercontent\.com|user-images\.githubusercontent\.com|github\.com)\//i.test(value)) return null;
    try {
      const url = new URL(value);
      if (url.username || url.password || url.port || url.search || (!source && url.hash) || /(?:^|\/)\.{1,2}(?:\/|$)|%(?:2f|5c|0[0-9a-f]|7f)/i.test(value.slice(value.indexOf('/', 8)))) return null;
      if (url.hostname === 'github.com' && !source && !/^\/user-attachments\/assets\/[a-zA-Z0-9-]+$/.test(url.pathname)) return null;
      if (url.pathname === '/') return null;
      return url.href;
    } catch (_) { return null; }
  }

  function mergeRecord(previous, item) {
    const fields = ['descriptionZh', 'gameNameZh', 'gameNameOriginal', 'posterUrl', 'posterSourceUrl', 'posterKind'];
    if (previous?.status === 'pending' && item.status === 'missing') return previous;
    const record = { ...item, error: string(item.error), detailsVersion: item.detailsVersion === 1 ? 1 : 0 };
    for (const field of fields) record[field] = string(item[field]);
    if (previous && item.status !== 'ready') {
      for (const field of fields) if (!record[field]) record[field] = string(previous[field]);
      record.detailsVersion = record.detailsVersion === 1 || previous.detailsVersion === 1 ? 1 : 0;
    } else if (previous?.detailsVersion === 1 && record.detailsVersion !== 1) {
      for (const field of fields.slice(1)) record[field] = string(previous[field]);
      record.detailsVersion = previous.detailsVersion;
    }
    return record;
  }

  function needsDetails(game, record = {}) {
    return !(record.detailsVersion === 1 || game?.detailsVersion === 1) || describe({ ...game, descriptionZh: record.descriptionZh || game?.descriptionZh }).source === 'unknown';
  }

  globalThis.PortShelfDescriptions = Object.freeze({ describe, identity, imageURL, mergeRecord, needsDetails });
})();
