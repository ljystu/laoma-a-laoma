const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;'}[c]));
const TYPE = {ban: '封禁/禁言', hiatus: '停更', takedown: '下架'};
const CONF = {inferred: '推断', confirmed: '确认', pending: '待定'};
const ST = {live: 'B站在线', mirrored: '有补档', transcript_only: '仅文稿', lost: '找不到', unknown: '未知'};
const SRC = {bilibili: 'B站', youtube: 'YouTube', transcript: '文稿', wayback: 'Wayback', podcast: '播客', other: '其他'};
const DAY = 864e5;
const today = () => new Date().toISOString().slice(0, 10);
const span = e => Math.round((Date.parse(e.end || today()) - Date.parse(e.start)) / DAY);

const theme = $('theme');
theme.onclick = () => {
  const dark = matchMedia('(prefers-color-scheme: dark)').matches;
  const cur = document.documentElement.dataset.theme || (dark ? 'dark' : 'light');
  document.documentElement.dataset.theme = cur === 'dark' ? 'light' : 'dark';
};

Promise.all(['status', 'episodes', 'events'].map(n => fetch(`../data/${n}.json`, {cache: 'no-store'}).then(r => {
  if (!r.ok) throw new Error(`${n}.json ${r.status}`);
  return r.json();
}))).then(([status, eps, evs]) => {
  stats(status, eps, evs); timeline(evs); heat(eps, evs); wall(eps, evs);
  $('foot').innerHTML = `数据来源：B站投稿列表、YouTube「睡前消息」频道、<a href="https://github.com/bedtimenews/bedtimenews-archive-contents">社区文稿库</a>、Wayback Machine。最后检查 ${esc(status.last_check)}`;
}).catch(e => { $('stats').innerHTML = `<p class="err">数据加载失败：${esc(e.message)}。请在项目根目录运行 <code>python3 -m http.server</code> 后打开 /site/。</p>`; });

function stats(s, eps, evs) {
  const bans = evs.filter(e => e.type !== 'takedown');
  const acc = s.account || {};
  const state = acc.silence == null ? '未知（接口被风控）' : acc.silence ? '禁言中' : '正常';
  const open = s.open_event_id && evs.find(e => e.id === s.open_event_id);
  const items = [
    [bans.filter(e => e.type === 'ban').length + ' / ' + bans.filter(e => e.type === 'hiatus').length, '封禁 / 停更次数'],
    [bans.reduce((a, e) => a + span(e), 0), '累计停更天数'],
    [evs.filter(e => e.type === 'takedown').length, '下架视频数'],
    [eps.filter(e => !['live', 'unknown'].includes(e.status) && e.kind === 'main').length + ` <small style="font-size:12px;font-weight:normal">(另 ${eps.filter(e => e.status === 'unknown').length} 期未知)</small>`, '确认不在B站的期数'],
    [open ? '⏳ ' + esc(open.title) : esc(state), '当前账号状态'],
    [esc((s.last_check || '').replace('T', ' ').slice(0, 16)), '最后检查时间'],
  ];
  $('stats').innerHTML = items.map(([v, k]) => `<div class="stat"><b>${v}</b><span>${k}</span></div>`).join('');
}

function card(e) {
  const link = (u, t) => `<a href="${esc(/^data\//.test(u) ? '../' + u : u)}" target="_blank" rel="noopener">${t}</a>`;
  const ev = (e.evidence || []).map(x => `<li>${esc(x.label)}${x.date ? ' · ' + esc(x.date) : ''}：` +
    (x.before ? `${link(x.before, '之前')} → ${link(x.url, '之后')}` : link(x.url, '链接')) + '</li>').join('');
  const days = e.type === 'takedown' ? '' : ` · ${span(e)} 天`;
  return `<div class="ev ${esc(e.type)}"><h3>${esc(e.title)}<span class="tag ${esc(e.confidence)}">${CONF[e.confidence] || esc(e.confidence)}</span></h3>
  <div class="meta">${esc(e.start)} → ${e.end ? esc(e.end) : (e.type === 'takedown' ? '' : '至今')}${days} · ${TYPE[e.type] || esc(e.type)}</div>
  <p>${esc(e.summary)}</p>${ev ? `<ul>${ev}</ul>` : ''}</div>`;
}

function timeline(evs) {
  const main = evs.filter(e => e.type !== 'takedown').reverse();
  const tk = evs.filter(e => e.type === 'takedown').reverse();
  $('tl').innerHTML = main.map(card).join('') +
    `<details class="tk"><summary>另有 ${tk.length} 条下架记录（点击展开）</summary><div style="margin-top:10px">${tk.map(card).join('')}</div></details>`;
}

function heat(eps, evs) {
  const dated = eps.filter(e => e.date);
  if (!dated.length) return;
  const wk = d => Math.floor((Date.parse(d) / DAY + 3) / 7);  // 以周一为界
  const w0 = wk(dated.reduce((a, e) => e.date < a ? e.date : a, '9999')), w1 = wk(today());
  const cnt = {};
  dated.forEach(e => { cnt[wk(e.date)] = (cnt[wk(e.date)] || 0) + 1; });
  const max = Math.max(...Object.values(cnt));
  // 一行一年，列 = 当年第几周
  const S = 11, G = 2, L = 34, cols = 53;
  const monday = w => new Date((w * 7 - 3) * DAY);
  const y0 = monday(w0).getUTCFullYear(), rows = monday(w1).getUTCFullYear() - y0 + 1;
  let out = '';
  for (let r = 0; r < rows; r++) out += `<text x="0" y="${r * (S + G) + S - 2}" font-size="9" fill="currentColor" opacity=".6">${y0 + r}</text>`;
  const bad = evs.filter(e => e.type !== 'takedown').map(e => [wk(e.start), wk(e.end || today()), e]);
  for (let w = w0; w <= w1; w++) {
    const m = monday(w), yr = m.getUTCFullYear();
    const col = Math.floor((m - Date.UTC(yr, 0, 1)) / DAY / 7);
    const x = L + col * (S + G), y = (yr - y0) * (S + G);
    const n = cnt[w] || 0, b = bad.find(([a, z]) => w >= a && w <= z);
    const d = new Date((w * 7 - 3) * DAY).toISOString().slice(0, 10);
    const fill = n ? `rgba(var(--heat),${(0.3 + 0.7 * n / max).toFixed(2)})` : 'var(--heat0)';
    out += `<rect x="${x}" y="${y}" width="${S}" height="${S}" rx="2" style="fill:${fill}"${b ? ' stroke="var(--ban)" stroke-width="1.5"' : ''}><title>${d} 当周 ${n} 期${b ? ' · ' + esc(b[2].title) : ''}</title></rect>`;
    if (b && !n) out += `<rect x="${x}" y="${y}" width="${S}" height="${S}" rx="2" style="fill:var(--ban);opacity:.35"/>`;
  }
  const W = L + cols * (S + G), H = rows * (S + G);
  $('heat').innerHTML = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="每周更新热力图">${out}</svg>`;
}

function wall(eps, evs) {
  const byId = Object.fromEntries(evs.map(e => [e.id, e]));
  $('wall').innerHTML = eps.map((e, i) =>
    `<button class="s-${esc(e.status)}${e.event_id ? ' ev-mark' : ''}" data-i="${i}" title="第${e.no}期 · ${ST[e.status]}" aria-label="第${e.no}期 ${ST[e.status]}">${e.no}</button>`).join('');
  $('wall').onclick = ev => {
    const b = ev.target.closest('button'); if (!b) return;
    const e = eps[b.dataset.i], x = e.event_id && byId[e.event_id];
    const src = e.sources.map(s => `<li>${SRC[s.kind] || esc(s.kind)}${s.official ? '（官方）' : ''}：<a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.url)}</a>${s.alive === false ? ' ❌已失效' : ''}</li>`).join('');
    $('pop').innerHTML = `<button class="x" aria-label="关闭">×</button><b>第${e.no}期</b> ${esc(e.title || '（标题未知）')}<div class="sub">${esc(e.date || '日期未知')} · ${ST[e.status]}${x ? ' · 关联事件：' + esc(x.title) : ''}</div>
      ${src ? `<ul style="font-size:13px;padding-left:18px;margin:6px 0 0;word-break:break-all">${src}</ul>` : '<p class="sub">没有找到任何来源。</p>'}`;
    $('pop').classList.add('on');
  };
  $('pop').onclick = ev => { if (ev.target.classList.contains('x')) $('pop').classList.remove('on'); };
}
