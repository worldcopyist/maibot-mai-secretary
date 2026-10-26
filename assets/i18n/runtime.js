(() => {
  const catalogs = __SECRETARY_CATALOGS__;
  const fragments = __SECRETARY_FRAGMENTS__;
  const originals = new WeakMap();
  const attributes = new WeakMap();
  let language = 'zh';

  function translate(value) {
    if (language === 'zh') return value;
    const catalog = catalogs[language];
    const trimmed = value.trim();
    if (catalog[trimmed]) return value.replace(trimmed, catalog[trimmed]);
    const weekdays = {
      en: ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'],
      ja: ['月曜日', '火曜日', '水曜日', '木曜日', '金曜日', '土曜日', '日曜日'],
      ko: ['월요일', '화요일', '수요일', '목요일', '금요일', '토요일', '일요일'],
    }[language];
    const longDate = trimmed.match(/^(\d{4}) 年 (\d{1,2}) 月 (\d{1,2}) 日$/);
    if (longDate) {
      const date = new Date(Date.UTC(+longDate[1], +longDate[2] - 1, +longDate[3]));
      return new Intl.DateTimeFormat(language, { year: 'numeric', month: 'long', day: 'numeric', timeZone: 'UTC' }).format(date);
    }
    const dateLabel = trimmed.match(/^(\d{4})年(\d{1,2})月(\d{1,2})日，(\d+)项任务$/);
    if (dateLabel) {
      const date = new Date(Date.UTC(+dateLabel[1], +dateLabel[2] - 1, +dateLabel[3]));
      const label = new Intl.DateTimeFormat(language, { year: 'numeric', month: 'long', day: 'numeric', timeZone: 'UTC' }).format(date);
      return `${label}, ${dateLabel[4]} ${catalog['项任务']}`;
    }
    let translated = value;
    translated = translated.replace(/^周 ([1-7]) (\d{2}:\d{2})$/, (_, day, time) => `${weekdays[+day - 1]} ${time}`);
    translated = translated.replace(/^周([1-7]) 第(\d+)–(\d+)节/, (_, day, first, last) => {
      if (language === 'en') return `${weekdays[+day - 1]}, periods ${first}–${last}`;
      if (language === 'ja') return `${weekdays[+day - 1]}・${first}～${last}限`;
      return `${weekdays[+day - 1]} ${first}~${last}교시`;
    });
    translated = translated.replace(/第([\d、]+)周/g, (_, weeks) => {
      if (language === 'en') return `weeks ${weeks.replaceAll('、', ', ')}`;
      if (language === 'ja') return `第${weeks}週`;
      return `제${weeks.replaceAll('、', ', ')}주`;
    });
    translated = translated.replace(/第 (\d+) 周/g, (_, week) => {
      if (language === 'en') return `week ${week}`;
      if (language === 'ja') return `第${week}週`;
      return `제${week}주`;
    });
    translated = translated.replace(/第 (\d+)–(\d+) 节(?!开始时间)/g, (_, first, last) => {
      if (language === 'en') return `periods ${first}–${last}`;
      if (language === 'ja') return `第${first}～${last}限`;
      return `제${first}~${last}교시`;
    });
    const status = {
      en: { active: 'Active', sent: 'Sent', send_failed: 'Send failed', unknown: 'Unknown', familiar: 'Familiar', stranger: 'Stranger' },
      ja: { active: '有効', sent: '送信済み', send_failed: '送信失敗', unknown: '不明', familiar: '知人', stranger: '初対面' },
      ko: { active: '활성', sent: '전송됨', send_failed: '전송 실패', unknown: '알 수 없음', familiar: '지인', stranger: '낯선 사람' },
    }[language];
    translated = translated.replace(/^(active|sent|send_failed|unknown)(?= · )/, match => status[match]);
    translated = translated.replace(/(?<= · )(familiar|stranger)$/, match => status[match]);
    for (const source of fragments) {
      if (translated.includes(source)) translated = translated.replaceAll(source, catalog[source]);
    }
    return translated;
  }

  function updateText(node) {
    if (node.parentElement?.closest('script,style')) return;
    const current = node.nodeValue || '';
    let item = originals.get(node);
    if (!item || current !== item.rendered) item = { source: current, rendered: current };
    const rendered = translate(item.source);
    item.rendered = rendered;
    originals.set(node, item);
    if (current !== rendered) node.nodeValue = rendered;
  }

  function updateAttributes(element) {
    let saved = attributes.get(element);
    if (!saved) saved = {};
    for (const name of ['placeholder', 'aria-label', 'title']) {
      if (!element.hasAttribute(name)) continue;
      const current = element.getAttribute(name) || '';
      let item = saved[name];
      if (!item || current !== item.rendered) item = { source: current, rendered: current };
      const rendered = translate(item.source);
      item.rendered = rendered;
      saved[name] = item;
      if (current !== rendered) element.setAttribute(name, rendered);
    }
    attributes.set(element, saved);
  }

  function scan(root) {
    if (root.nodeType === Node.TEXT_NODE) return updateText(root);
    if (root.nodeType !== Node.ELEMENT_NODE || root.matches('script,style')) return;
    updateAttributes(root);
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      if (walker.currentNode.nodeType === Node.TEXT_NODE) updateText(walker.currentNode);
      else if (!walker.currentNode.matches('script,style')) updateAttributes(walker.currentNode);
    }
  }

  function setLanguage(value) {
    const next = String(value || 'zh').toLowerCase().split('-')[0];
    language = Object.hasOwn(catalogs, next) ? next : 'zh';
    scan(document.body);
  }

  window.secretaryTranslate = translate;

  const observer = new MutationObserver(records => {
    for (const record of records) {
      if (record.type === 'characterData') updateText(record.target);
      else if (record.type === 'attributes') updateAttributes(record.target);
      else for (const node of record.addedNodes) scan(node);
    }
  });
  observer.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ['placeholder', 'aria-label', 'title'] });
  scan(document.body);
  maibot.ready.then(() => setLanguage(maibot.context.language));
  window.addEventListener('maibot:context', event => setLanguage(event.detail.language));
})();
