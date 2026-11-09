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

  globalThis.PortShelfDescriptions = Object.freeze({ describe });
})();
