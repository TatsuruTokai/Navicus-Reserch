let SNAPSHOT = {
  schemaVersion: 'navicus_proposal_research_db_v1',
  exportedAt: '',
  runs: [],
  proposals: [],
  similarProposals: [],
  proposalMaterials: [],
  resultFollowups: [],
  stats: {filtered: 0, total: 0, tabCounts: {}},
  page: 1,
  pageSize: 25,
  totalPages: 1,
  start: 0,
  end: 0,
};

const VIEW_KEY = 'navicusProposalDb:v1:viewLog';
const FAV_KEY = 'navicusProposalDb:v1:favorites';
const DEADLINE_TAB_KEY = 'navicusProposalDb:v2:deadlineTab';
const $ = id => document.getElementById(id);
const GRADE_COLOR = {S:'var(--S)', A:'var(--A)', B:'var(--B)', C:'var(--C)', D:'var(--D)', E:'var(--E)', F:'var(--F)'};
const DEADLINE_TABS = [
  {key:'all', label:'全件'},
  {key:'active', label:'募集期間内'},
  {key:'expired_unresearched', label:'期限切れ（追加調査未完了）'},
  {key:'expired_researched', label:'期限切れ（追加調査実施済）'},
];

const loadSet = key => new Set(JSON.parse(localStorage.getItem(key) || '[]'));
const saveSet = (key, set) => localStorage.setItem(key, JSON.stringify([...set].sort()));
let viewed = loadSet(VIEW_KEY);
let favorites = loadSet(FAV_KEY);
let currentPage = 1;
let quickMode = '';
let deadlineTab = localStorage.getItem(DEADLINE_TAB_KEY) || 'all';
let pageSize = Number(localStorage.getItem('navicusProposalDb:v1:pageSize') || '25');
let sortKey = localStorage.getItem('navicusProposalDb:v1:sortBy') || 'rank';
let requestSeq = 0;
let renderTimer = null;
let SIMILAR_BY_ID = new Map();
let FOLLOWUPS_BY_ID = new Map();
let MATERIALS_BY_ID = new Map();

function esc(x) { return String(x ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;'); }
function displayTitle(p) {
  const raw = String((p && p.title) || '');
  const clean = raw.replace(/https?:\/\/\S+/gi, ' ').replace(/(Title:|URL Source:).*$/i, '').replace(/\s+/g, ' ').trim().replace(/^[ /　-]+|[ /　-]+$/g, '');
  if (clean) return clean;
  const issuer = String((p && (p.issuer || p.issuer_organization || p.municipality || p.prefecture)) || '').trim();
  return `案件名未確認（${issuer || '公式URLあり'}）`;
}
function parseJson(value, fallback) { try { return typeof value === 'string' && value ? JSON.parse(value) : (value || fallback); } catch(e) { return fallback; } }
function arr(x) { return Array.isArray(x) ? x : (x ? [x] : []); }
function gradeRank(grade) { return ({S:0,A:1,B:2,C:3,D:4,E:5,F:6})[String(grade || 'F')] ?? 99; }
function cleanEvidenceText(value) {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  if (!text) return '';
  if (/URL Source:|Title:| \/ \//i.test(text)) {
    const beforeMeta = text.split(/Title:|URL Source:/i)[0].replace(/\s*\/\s*\/\s*/g, ' / ').trim();
    const parts = beforeMeta.split('/').map(x => x.trim()).filter(Boolean);
    const unique = parts.filter((part, index, all) => all.indexOf(part) === index);
    return unique.join(' / ') || '公式ページで案件掲載を確認';
  }
  return text;
}
function sourceOfSimilar(x) { return parseJson(x.source_json, {}); }
function bidderText(x) {
  const s = sourceOfSimilar(x);
  const names = arr(x.bidder_names || s.bidderNames || s.bidder_names || s.bidders || s.bidderName || s.winnerName || x.winner_name);
  return names.map(v => String(v || '').trim()).filter(Boolean).join('、') || '未公開';
}
function indexByCanonical(rows) {
  const map = new Map();
  rows.forEach(x => {
    const key = x.canonical_id;
    if (!map.has(key)) map.set(key, []);
    map.get(key).push(x);
  });
  return map;
}
function setSnapshot(next) {
  SNAPSHOT = next || SNAPSHOT;
  SIMILAR_BY_ID = indexByCanonical(SNAPSHOT.similarProposals || []);
  FOLLOWUPS_BY_ID = indexByCanonical(SNAPSHOT.resultFollowups || []);
  MATERIALS_BY_ID = indexByCanonical(SNAPSHOT.proposalMaterials || []);
}
function similarFor(id) { return SIMILAR_BY_ID.get(id) || []; }
function followupsFor(id) { return FOLLOWUPS_BY_ID.get(id) || []; }
function materialsFor(id) { return MATERIALS_BY_ID.get(id) || []; }
function selectedLabels(p, sims, follows, seen) {
  const s = p.summary || {};
  const sourceLabels = arr(s.labels).filter(Boolean);
  const origin = s.originStatus || ((p.is_new || p.newly_discovered || p.isNew) ? '今回追加' : (p.first_seen_run_date || p.first_seen_run_id ? `既存・初出${p.first_seen_run_date || p.first_seen_run_id}` : '既存'));
  if (origin && !sourceLabels.includes(origin)) sourceLabels.unshift(origin);
  if ((p.is_new || p.newly_discovered || p.isNew) && !sourceLabels.includes('新規')) sourceLabels.splice(Math.min(1, sourceLabels.length), 0, '新規');
  const labels = [p.latest_grade ? `ランク${p.latest_grade}` : '未ランク'];
  if (p.best_grade && gradeRank(p.best_grade) < gradeRank(p.latest_grade)) labels.push(`過去最高${p.best_grade}`);
  sourceLabels.slice(0, 5).forEach(label => { if (!labels.includes(label)) labels.push(label); });
  labels.push(seen ? '閲覧済み' : '未閲覧');
  labels.push(sims.length ? `類似${sims.length}件` : '類似なし');
  labels.push(materialsFor(p.canonical_id).length ? `資料${materialsFor(p.canonical_id).length}件` : '資料なし');
  if (follows.length) labels.push(`追跡:${follows[0].status || ''}`);
  return labels.filter(Boolean).filter((label, i, all) => all.indexOf(label) === i).slice(0, 10);
}
function chipClass(label) {
  if (label === '新規' || label === '今回追加') return 'hot';
  if (label.startsWith('既存・初出')) return 'warn';
  if (label.includes('過去最高')) return 'hot';
  if (label.includes('類似') && !label.includes('なし')) return 'warn';
  return '';
}
function setDeadlineTab(key) {
  deadlineTab = DEADLINE_TABS.some(tab => tab.key === key) ? key : 'all';
  localStorage.setItem(DEADLINE_TAB_KEY, deadlineTab);
  currentPage = 1;
  render();
}
function deadlineTabCounts() {
  return (SNAPSHOT.stats && SNAPSHOT.stats.tabCounts) || {all:0, active:0, expired_unresearched:0, expired_researched:0};
}
function renderStats() {
  const stats = SNAPSHOT.stats || {};
  const tabCounts = deadlineTabCounts();
  const newCount = stats.new || 0;
  const existingCount = stats.existing ?? Math.max(0, (stats.total || 0) - newCount);
  $('stats').innerHTML = [
    ['表示', stats.filtered || 0],
    ['全件', stats.total || 0],
    ['募集期間内', tabCounts.active || 0],
    ['期限切れ未調査', tabCounts.expired_unresearched || 0],
    ['期限切れ調査済', tabCounts.expired_researched || 0],
    ['今回追加', newCount],
    ['既存', existingCount],
    ['B以上(現)', stats.bplus || 0],
    ['B以上(過去最高)', stats.bestBplus || 0],
    ['過去S/A', stats.historicalAB || 0],
    ['類似あり', stats.similar || 0],
    ['資料/PDF', stats.materials || 0],
    ['気になる', stats.favorite || 0],
    ['Release', stats.releaseDecision || (SNAPSHOT.releaseGate && SNAPSHOT.releaseGate.decision) || ''],
    ['外部ポータル監査', stats.externalPortalRecall ? `${stats.externalPortalRecall.includedInRankedFinal || 0}/${stats.externalPortalRecall.caseCount || 0} ranked / 未収録${stats.externalPortalRecall.notFound || 0} / source止まり${stats.externalPortalRecall.sourceSeenNotRanked || 0}` : ''],
    ['exported', formatExportedAt(stats.exportedAt || SNAPSHOT.exportedAt || '')],
  ].map(([k,v]) => `<div class="row"><span>${esc(k)}</span><strong>${esc(v)}</strong></div>`).join('');
  $('resultCount').textContent = stats.filtered || 0;
}
function renderDeadlineTabs() {
  const counts = deadlineTabCounts();
  $('deadlineTabs').innerHTML = DEADLINE_TABS.map(tab => `<button class="deadline-tab ${deadlineTab === tab.key ? 'active' : ''}" onclick="setDeadlineTab('${tab.key}')"><span>${esc(tab.label)}</span><span class="deadline-tab-count">${esc(counts[tab.key] || 0)}</span></button>`).join('');
}
function markViewed(id) { viewed.add(id); saveSet(VIEW_KEY, viewed); }
function toggleFav(id) { favorites.has(id) ? favorites.delete(id) : favorites.add(id); saveSet(FAV_KEY, favorites); render(); }
function firstValue(...values) { return values.find(v => v !== '' && v !== null && v !== undefined) ?? ''; }
function proposalDeadlineValue(p) {
  const s = p.summary || {};
  const m = s.deadlineMilestones || {};
  return firstValue(
    p.proposalDeadline,
    p.proposal_deadline,
    p.submissionDeadline,
    p.submission_deadline,
    p.documentSubmissionDeadline,
    p.document_submission_deadline,
    s.proposalDeadline,
    s.proposal_deadline,
    m.proposalDeadline,
    s.submissionDeadline,
    s.submission_deadline,
    m.submissionDeadline,
    s.documentSubmissionDeadline,
    s.document_submission_deadline,
    m.documentSubmissionDeadline
  );
}
function proposalDaysRemainingValue(p, deadline) {
  const s = p.summary || {};
  const m = s.deadlineMilestones || {};
  const specific = firstValue(
    m.proposalDaysRemaining,
    m.submissionDaysRemaining,
    s.proposalDaysRemaining,
    s.submissionDaysRemaining,
    s.daysUntilProposalDeadline,
    s.daysUntilSubmissionDeadline
  );
  return deadline ? firstValue(specific, s.daysUntilDeadline, s.days_left) : specific;
}
function daysText(p) {
  const deadline = proposalDeadlineValue(p);
  const d = proposalDaysRemainingValue(p, deadline);
  if (!deadline && (d === '' || d === null || d === undefined)) return {text:'対象外', cls:'closed', note:'提出期限未確認のため除外'};
  if (d === '' || d === null || d === undefined) return {text:shortDate(deadline), cls:'', note:`提出期限: ${deadline}`};
  const n = Number(d);
  if (!Number.isFinite(n)) return {text:shortDate(deadline || d), cls:'', note:deadline ? `提出期限: ${deadline}` : '提出期限日付要確認'};
  if (n < 0) return {text:'終了', cls:'closed', note:`提出期限: ${deadline || '日付要確認'} / ${Math.abs(n)}日経過`};
  if (n <= 3) return {text:`${n}日`, cls:'urgent', note:`提出期限: ${deadline || '日付要確認'}`};
  if (n <= 10) return {text:`${n}日`, cls:'soon', note:`提出期限: ${deadline || '日付要確認'}`};
  return {text:`${n}日`, cls:'', note:`提出期限: ${deadline || '日付要確認'}`};
}
function shortDate(value) {
  const s = String(value || '');
  const m = s.match(/(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})/);
  if (!m) return s || '-';
  return `${Number(m[2])}/${Number(m[3])}`;
}
function deadlineRows(p, includeMissingProposal=false) {
  const s = p.summary || {};
  const m = s.deadlineMilestones || {};
  const rows = [];
  const proposal = proposalDeadlineValue(p);
  if (proposal) rows.push({label:'提出期限', value:proposal, primary:true});
  else if (includeMissingProposal) rows.push({label:'提出期限', value:'未確認・除外', primary:true, missing:true});
  [
    ['参加期限', firstValue(s.participationDeadline, s.participation_deadline, m.participationDeadline)],
    ['質問期限', firstValue(s.questionDeadline, s.question_deadline, m.questionDeadline)],
    ['説明会期限', firstValue(s.briefingDeadline, s.briefing_deadline, m.briefingDeadline)],
    ['回答期限', firstValue(s.answerDeadline, s.answer_deadline, m.answerDeadline)]
  ].forEach(([label, value]) => {
    if (value !== '' && value !== null && value !== undefined) rows.push({label, value, primary:false});
  });
  const seen = new Set();
  return rows.filter(row => {
    const key = `${row.label}:${row.value}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
function renderDeadlineRows(p) {
  const rows = deadlineRows(p, true);
  return `<div class="deadline-list">${rows.map(row => `<div class="deadline-row ${row.primary ? 'primary' : ''} ${row.missing ? 'missing' : ''}"><span>${esc(row.label)}</span><strong>${esc(row.value)}</strong></div>`).join('')}</div>`;
}
function formatYen(value) {
  if (value === '' || value === null || value === undefined) return '';
  if (typeof value === 'number' && Number.isFinite(value) && value > 0) return `${value.toLocaleString('ja-JP')}円`;
  const text = String(value || '').trim();
  if (!text || ['0','0円','未確認','不明','unknown','not_found','none','null'].includes(text.toLowerCase())) return '';
  if (/円|千円|万円|億円|上限|限度|予定価格|税込|税抜/.test(text)) return text;
  const digits = text.replace(/[^0-9]/g, '');
  if (digits && digits !== '0' && digits.length === text.replace(/,/g, '').length) return `${Number(digits).toLocaleString('ja-JP')}円`;
  return text;
}

function budgetSummary(p) {
  const s = p.summary || {};
  const values = [
    s.budgetText,
    s.upperLimitAmount,
    s.upper_limit_amount,
    s.amounts && (s.amounts.upper_limit_amount || s.amounts.upperLimitAmount),
    s.budgetYen,
    s.budget,
    s.upperLimitAmountYen,
    s.upper_limit_amount_yen,
    s.estimatedPrice,
    s.scheduledPrice,
    s.contractAmountYen,
    s.awardAmountYen,
    p.budget
  ];
  const amount = values.map(formatYen).find(Boolean) || '';
  const status = String(s.budgetStatus || '').toLowerCase();
  const unresolved = /記載なし|非公表|要確認|未確認|不明|unknown|not_found/.test(amount);
  const found = status === 'found' || (!!amount && !unresolved && /円|千円|万円|億円/.test(amount));
  const grade = (s.criteria && s.criteria.budget) || s.budgetGrade || '';
  const meta = found
    ? (grade ? `予算評価: ${grade}` : '公式資料から抽出')
    : (amount ? '金額情報の公開状況' : '公式資料で要確認');
  return {amount: amount || '未確認', cls: found ? '' : 'unknown', meta};
}

function cleanQualificationText(value) {
  const text = cleanEvidenceText(value).replace(/https?:\/\/\S+/g, '').replace(/\{[^{}]*(deadline|participation|proposal|submission)[^{}]*\}/gi, ' ').replace(/\s+/g, ' ').trim();
  return text.replace(/^[:：/・\s]+|[:：/・\s]+$/g, '');
}
function shortenText(text, limit=220) {
  const normalized = String(text || '').replace(/\s+/g, ' ').trim();
  return normalized.length <= limit ? normalized : `${normalized.slice(0, limit).trim()}...`;
}
function qualificationSummary(p) {
  const s = p.summary || {};
  const explicit = cleanQualificationText(s.bidderQualificationSummary || s.eligibilitySummary || s.qualificationSummary);
  if (explicit) return shortenText(explicit);
  let raw = cleanQualificationText(firstValue(s.eligibility, s.participation_eligibility, s.bidEligibility, p.eligibility));
  const term = /入札参加資格|参加資格|応募資格|資格要件|競争入札参加資格|資格者名簿|名簿|業種区分|営業種目|登録|地域要件|県内|市内|町内|本店|本社|支店|営業所|実績|許可|認定|共同企業体|JV|共同提案|単独又は共同|所在地を問わない|法人又は団体|全国|随時申請/;
  const summaryText = cleanQualificationText(s.summary);
  if (!raw && term.test(summaryText)) raw = summaryText;
  if (raw) {
    const chunks = raw.split(/[。\n\r]+/).map(x => x.trim().replace(/^[:：/・\s]+|[:：/・\s]+$/g, '')).filter(Boolean);
    const focused = chunks.filter(chunk => term.test(chunk));
    const unique = [...new Set(focused.length ? focused : (chunks.length ? chunks : [raw]))];
    return shortenText(unique.slice(0, 3).join('。'));
  }
  const statusLabel = {ELIGIBLE:'参加可能性あり', INELIGIBLE:'参加困難', NEEDS_CONFIRMATION:'要確認', UNKNOWN:'未確認'}[s.eligibilityStatus] || '未確認';
  const reason = cleanQualificationText(s.eligibilityReason);
  const action = cleanQualificationText(s.eligibilityNextAction);
  const detail = [reason, action ? `確認事項: ${action}` : ''].filter(Boolean).join('。');
  return detail ? shortenText(`${statusLabel}: ${detail}`) : '未確認: 公式資料の入札者資格欄で、地域要件・名簿登録・業種区分・JV可否・参加申請期限を確認する。';
}
function renderEligibilityDetails(p) {
  const s = p.summary || {};
  const rows = [
    ['要約', qualificationSummary(p)],
    ['判定', s.eligibilityStatus || 'UNKNOWN'],
    ['理由', s.eligibilityReason || ''],
    ['次アクション', s.eligibilityNextAction || ''],
  ];
  return rows.filter(([,v]) => v !== '' && v !== null && v !== undefined).map(([k,v]) => `<li>${esc(k)}: ${esc(v)}</li>`).join('');
}
function renderCriteria(p) {
  const c = (p.summary && p.summary.criteria) || {};
  const items = [
    ['fit','適合',c.fit || p.latest_grade || '-'],
    ['best','過去最高',p.best_grade || p.latest_grade || '-'],
    ['deadline','期限',c.deadline || p.latest_status || '-'],
    ['eligibility','資格',c.eligibility || '-'],
    ['budget','予算',c.budget || '-'],
  ];
  return items.map(([key,name,val]) => `<div class="criterion"><div><div class="criterion-name">${esc(name)}</div><div class="criterion-note">${esc(key)}</div></div><div class="mini-grade" style="--g:${GRADE_COLOR[val] || 'var(--brand)'}">${esc(val)}</div></div>`).join('');
}
function renderSimilar(sims) {
  if (!sims.length) return '<li>同一自治体・昨年以前の入札情報なし</li>';
  return sims.map(x => {
    const url = x.url || x.result_url || '';
    const titleText = displayTitle(x);
    const title = url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(titleText)}</a>` : esc(titleText);
    const result = x.result_url ? ` / <a href="${esc(x.result_url)}" target="_blank" rel="noopener noreferrer">結果</a>` : '';
    return `<li>${title}${result}<br><span class="small">${esc(x.fiscal_year || x.fiscalYear || '年度不明')} / 入札者・採択者: ${esc(bidderText(x))} / ${esc(x.similarity_reason || '')}</span></li>`;
  }).join('');
}
function renderFollowups(follows) {
  if (!follows.length) return '<li>落札/採択追跡なし</li>';
  return follows.map(x => `<li>${esc(x.status || '')} / ${esc(x.result_publication_date || '')}<br><span class="small">入札者・採択者: ${esc(x.winner_name || '未公開')}</span></li>`).join('');
}
function renderMaterials(materials) {
  if (!materials.length) return '<li>資料/PDF未抽出</li>';
  return materials.slice(0, 14).map(x => {
    const label = x.title || x.source_type || 'official_material';
    const evidence = cleanEvidenceText(x.evidence);
    const quote = evidence ? `<br><span class="small">${esc(evidence).slice(0, 240)}</span>` : '';
    return `<li><a href="${esc(x.url)}" target="_blank" rel="noopener noreferrer">${esc(label)}</a><br><span class="small">${esc(x.source_type || '')}</span>${quote}</li>`;
  }).join('');
}
function renderDetailsList(p) {
  const s = p.summary || {};
  const rows = [
    ...deadlineRows(p, true).map(row => [row.label, row.value]),
    ['予算', s.budgetText || s.budget || ''],
    ['提出方法', s.submissionMethod || s.submission_method || ''],
  ];
  return rows.filter(([,v]) => v !== '' && v !== null && v !== undefined).map(([k,v]) => `<li>${esc(k)}: ${esc(v)}</li>`).join('') || '<li>期限・提出条件は詳細資料で要確認</li>';
}
function renderWhy(p) {
  const s = p.summary || {};
  const why = arr(s.why).concat(arr(s.stopDisplayReason || s.stopReason)).filter(Boolean);
  const main = s.summary ? [`内容: ${s.summary}`] : [];
  return main.concat(why).slice(0, 8).map(x => `<li>${esc(x)}</li>`).join('') || '<li>案件詳細なし</li>';
}
function renderCard(p) {
  const s = p.summary || {};
  const sims = similarFor(p.canonical_id);
  const follows = followupsFor(p.canonical_id);
  const materials = materialsFor(p.canonical_id);
  const url = s.proposalPageUrl || s.titleUrl || s.sourceUrl || p.source_url || '';
  const titleText = displayTitle(p);
  const title = url ? `<a href="${esc(url)}" target="_blank" rel="noopener noreferrer" onclick="markViewed('${esc(p.canonical_id)}')">${esc(titleText)}</a>` : esc(titleText);
  const fav = favorites.has(p.canonical_id);
  const seen = viewed.has(p.canonical_id);
  const grade = p.latest_grade || 'F';
  const bestLine = p.best_grade && gradeRank(p.best_grade) < gradeRank(grade) ? ` / 過去最高${p.best_grade} ${p.best_grade_run_date || p.best_grade_run_id || ''}` : '';
  const days = daysText(p);
  const stopped = p.latest_status === 'DROP' || s.stopped === true;
  const labels = selectedLabels(p, sims, follows, seen);
  const originLine = s.originDetail || `初出: ${p.first_seen_run_date || p.first_seen_run_id || '-'} / 最新: ${p.updated_run_id || '-'}`;
  const eligibilityText = qualificationSummary(p);
  const budget = budgetSummary(p);
  return `<article class="proposal-card ${stopped ? 'stopped' : ''}" style="--grade-color:${GRADE_COLOR[grade] || 'var(--F)'}">
    <div class="card-head">
      <div class="rank"><strong>#${esc(p.latest_rank || '')}</strong><span>${esc(p.updated_run_id || '')}</span><span class="origin">${esc(originLine)}</span></div>
      <button class="decision ${fav ? 'primary' : ''}" onclick="toggleFav('${esc(p.canonical_id)}')"><span class="decision-dot"></span>${fav ? '気になる解除' : '気になる'}</button>
    </div>
    <div class="bento">
      <section class="tile tile-title"><div class="tile-kicker">TITLE</div><h2>${title}</h2></section>
      <section class="tile tile-grade"><div class="grade-badge">${esc(grade)}</div><div class="score-line">${esc(p.latest_status || '-')} / ${esc(s.decision || s.priority || '')}${esc(bestLine)}</div></section>
      <section class="tile tile-content"><div class="tile-kicker">CONTENT</div><p>${esc(s.summary || s.historicalSimilaritySummary || '内容要約なし')}</p></section>
      <section class="tile tile-deadline"><div class="tile-kicker">DEADLINE</div><div class="days ${days.cls}">${esc(days.text)}</div><div class="score-line">${esc(days.note)}</div>${renderDeadlineRows(p)}</section>
      <section class="tile tile-eligibility"><div class="tile-kicker">入札者資格</div><p>${esc(eligibilityText)}</p></section>
      <section class="tile tile-budget"><div class="tile-kicker">BUDGET</div><div class="budget-amount ${budget.cls}">${esc(budget.amount)}</div><div class="budget-meta">${esc(budget.meta)}</div></section>
      <section class="tile tile-issuer"><div class="tile-kicker">ISSUER</div><div class="issuer-name">${esc(p.issuer)}</div><div class="issuer-meta">${esc(p.historical_similarity_status || '')}</div></section>
      <section class="tile tile-labels"><div class="tile-kicker">LABELS</div><div class="chips">${labels.map(label => `<span class="chip ${chipClass(label)}">${esc(label)}</span>`).join('')}</div></section>
    </div>
    <details class="accordion"><summary>案件詳細・資料/PDF・期限・類似入札情報</summary>
      <div class="detail-body">
        <section class="detail-panel"><h4>案件詳細</h4><ul>${renderWhy(p)}</ul></section>
        <section class="detail-panel"><h4>入札者資格</h4><ul>${renderEligibilityDetails(p)}</ul></section>
        <section class="detail-panel"><h4>資料/PDF・公式情報</h4><ul>${renderMaterials(materials)}</ul></section>
        <section class="detail-panel"><h4>期限・提出条件</h4><ul>${renderDetailsList(p)}${arr(s.confirmPoints).slice(0,8).map(x => `<li>${esc(x)}</li>`).join('')}</ul></section>
        <section class="detail-panel"><h4>同一自治体・昨年以前の入札情報</h4><ul>${renderSimilar(sims)}</ul></section>
        <section class="detail-panel"><h4>落札/採択追跡</h4><ul>${renderFollowups(follows)}</ul></section>
        <section class="detail-panel"><h4>判定</h4><div class="criteria">${renderCriteria(p)}</div></section>
      </div>
    </details>
  </article>`;
}
function renderRuns() {
  $('runs').innerHTML = (SNAPSHOT.runs || []).slice(0,12).map(r => `<div class="small"><strong>${esc(r.run_date)}</strong> ${esc(r.run_label || r.run_id)} / ${esc(r.status)}</div>`).join('');
}
function renderPager(total, totalPages, start, end) {
  const html = `<div class="pager-group"><button class="btn" onclick="gotoPage(1)" ${currentPage<=1?'disabled':''}>最初</button><button class="btn" onclick="gotoPage(${currentPage-1})" ${currentPage<=1?'disabled':''}>前へ</button></div><div class="small">${total ? start + 1 : 0}-${end}件 / ${total}件（${currentPage}/${totalPages}ページ）</div><div class="pager-group"><button class="btn" onclick="gotoPage(${currentPage+1})" ${currentPage>=totalPages?'disabled':''}>次へ</button><button class="btn" onclick="gotoPage(${totalPages})" ${currentPage>=totalPages?'disabled':''}>最後</button></div>`;
  $('pagerTop').innerHTML = html;
  $('pagerBottom').innerHTML = html;
}
function gotoPage(page) {
  currentPage = Math.max(1, Number(page) || 1);
  render();
  window.scrollTo({top:0, behavior:'smooth'});
}

let FULL_DATA = null;
let FULL_SIMILAR_BY_ID = new Map();
let FULL_FOLLOWUPS_BY_ID = new Map();
let FULL_MATERIALS_BY_ID = new Map();

async function loadStaticData() {
  if (FULL_DATA) return FULL_DATA;
  const index = await fetchJson('data/index.json');
  const snapshotPath = index.latest && index.latest.snapshot;
  if (!snapshotPath) throw new Error('latest snapshot is not configured');
  FULL_DATA = await fetchJson(`data/${snapshotPath}`);
  FULL_DATA.index = index;
  FULL_SIMILAR_BY_ID = indexByCanonical(FULL_DATA.similarProposals || []);
  FULL_FOLLOWUPS_BY_ID = indexByCanonical(FULL_DATA.resultFollowups || []);
  FULL_MATERIALS_BY_ID = indexByCanonical(FULL_DATA.proposalMaterials || []);
  return FULL_DATA;
}

async function fetchJson(path) {
  const response = await fetch(path, {cache: 'no-store'});
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  if (!path.endsWith('.gz')) return response.json();
  if (!response.body || !('DecompressionStream' in window)) {
    throw new Error('This browser cannot read compressed snapshot data. Use a current Chrome, Edge, Safari, or Firefox.');
  }
  const stream = response.body.pipeThrough(new DecompressionStream('gzip'));
  const text = await new Response(stream).text();
  return JSON.parse(text);
}

function rankNumber(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n : 999999;
}

function parseDeadlineDate(value) {
  const m = String(value || '').match(/(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})/);
  if (!m) return 9999999999999;
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])).getTime();
}

function formatExportedAt(value) {
  const text = String(value || '');
  const m = text.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/);
  return m ? `${m[1]} ${m[2]}Z` : text;
}

function fullSimilarFor(id) { return FULL_SIMILAR_BY_ID.get(id) || []; }
function fullFollowupsFor(id) { return FULL_FOLLOWUPS_BY_ID.get(id) || []; }
function fullMaterialsFor(id) { return FULL_MATERIALS_BY_ID.get(id) || []; }

function filteredStaticRows(data) {
  const q = $('query').value.trim().toLowerCase();
  const grade = $('grade').value;
  const gradeBasis = $('gradeBasis').value || 'latest';
  const state = $('state').value;
  const favs = favorites;
  const seen = viewed;
  return (data.proposals || []).filter(p => {
    const cid = p.canonical_id;
    const filterGrade = gradeBasis === 'best' ? (p.best_grade || p.latest_grade) : p.latest_grade;
    if (deadlineTab !== 'all' && p.deadlineBucket !== deadlineTab) return false;
    if (quickMode === 'bplus' && !['S','A','B'].includes(filterGrade)) return false;
    if (quickMode === 'historical_ab' && !p.isHistoricalAB) return false;
    if (q && !String(p.searchText || '').toLowerCase().includes(q)) return false;
    if (grade && filterGrade !== grade) return false;
    if (state === 'favorite' && !favs.has(cid)) return false;
    if (state === 'new' && !(p.is_new || p.newly_discovered || p.isNew)) return false;
    if (state === 'viewed' && !seen.has(cid)) return false;
    if (state === 'unviewed' && seen.has(cid)) return false;
    if (state === 'similar' && !fullSimilarFor(cid).length) return false;
    if (state === 'followup' && !fullFollowupsFor(cid).length) return false;
    if (state === 'historical_ab' && !p.isHistoricalAB) return false;
    return true;
  });
}

function sortedStaticRows(rows) {
  const key = sortKey || 'rank';
  const copy = rows.slice();
  const keyFn = key === 'best-grade'
    ? p => [gradeRank(p.best_grade || p.latest_grade), rankNumber(p.best_rank || p.latest_rank), rankNumber(p.latest_rank)]
    : key === 'grade'
      ? p => [gradeRank(p.latest_grade), rankNumber(p.latest_rank)]
      : key === 'run-rank'
        ? p => [rankNumber(p.latest_rank), gradeRank(p.latest_grade)]
        : key === 'deadline'
          ? p => [parseDeadlineDate(proposalDeadlineValue(p)), gradeRank(p.latest_grade), rankNumber(p.latest_rank)]
          : key === 'new'
            ? p => [(p.is_new || p.newly_discovered || p.isNew) ? 0 : 1, rankNumber(p.latest_rank)]
            : key === 'issuer'
              ? p => [String(p.issuer || ''), rankNumber(p.latest_rank)]
              : key === 'title'
                ? p => [String(p.title || ''), rankNumber(p.latest_rank)]
                : p => [gradeRank(p.latest_grade), rankNumber(p.latest_rank)];
  copy.sort((a, b) => {
    const ka = keyFn(a);
    const kb = keyFn(b);
    for (let i = 0; i < Math.max(ka.length, kb.length); i += 1) {
      if (ka[i] < kb[i]) return -1;
      if (ka[i] > kb[i]) return 1;
    }
    return 0;
  });
  return copy;
}

function staticStats(data, filtered) {
  const proposals = data.proposals || [];
  const allIds = new Set(proposals.map(p => p.canonical_id));
  const base = data.stats || {};
  return {
    ...base,
    filtered,
    total: proposals.length,
    tabCounts: base.tabCounts || {},
    favorite: [...favorites].filter(id => allIds.has(id)).length,
    viewed: [...viewed].filter(id => allIds.has(id)).length,
    exportedAt: data.exportedAt,
    latestRunId: (data.latestRun && data.latestRun.run_id) || base.latestRunId || '',
  };
}

function requestPayload() {
  return {
    q: $('query').value.trim(),
    grade: $('grade').value,
    gradeBasis: $('gradeBasis').value,
    state: $('state').value,
    quickMode,
    deadlineTab,
    sortKey,
    page: currentPage,
    pageSize,
    viewed: [...viewed],
    favorites: [...favorites],
  };
}

async function render() {
  const seq = ++requestSeq;
  const firstLoad = !FULL_DATA;
  if (firstLoad) {
    $('cards').innerHTML = '<div class="empty">静的データを読み込み中...</div>';
  }
  try {
    const data = await loadStaticData();
    if (seq !== requestSeq) return;
    const rows = sortedStaticRows(filteredStaticRows(data));
    const total = rows.length;
    const totalPages = Math.max(1, Math.ceil(total / pageSize));
    currentPage = Math.max(1, Math.min(currentPage, totalPages));
    const start = (currentPage - 1) * pageSize;
    const end = Math.min(total, start + pageSize);
    const pageRows = rows.slice(start, end);
    const pageIds = pageRows.map(row => row.canonical_id);
    const similar = pageIds.flatMap(id => fullSimilarFor(id));
    const materials = pageIds.flatMap(id => fullMaterialsFor(id));
    const followups = pageIds.flatMap(id => fullFollowupsFor(id));
    setSnapshot({
      ...data,
      proposals: pageRows,
      similarProposals: similar,
      proposalMaterials: materials,
      resultFollowups: followups,
      stats: staticStats(data, total),
      page: currentPage,
      pageSize,
      totalPages,
      start,
      end,
    });
    renderDeadlineTabs();
    renderStats();
    $('resultLabel').textContent = `${total ? start + 1 : 0}-${end}件 / 全${(SNAPSHOT.stats && SNAPSHOT.stats.total) || 0}件`;
    $('cards').innerHTML = pageRows.map(renderCard).join('') || '<div class="empty">該当案件がありません。</div>';
    renderPager(total, totalPages, start, end);
    renderRuns();
  } catch (error) {
    if (seq !== requestSeq) return;
    $('cards').innerHTML = `<div class="empty">静的データを読み込めません。<br><span class="small">${esc(error.message || error)}</span></div>`;
    $('resultCount').textContent = 0;
    $('resultLabel').textContent = 'データ未読込';
  }
}

function queueRender(resetPage=true) {
  if (resetPage) currentPage = 1;
  clearTimeout(renderTimer);
  renderTimer = setTimeout(render, 160);
}
function exportState() { $('stateText').value = JSON.stringify({viewed:[...viewed], favorites:[...favorites]}, null, 2); }
function importState() {
  try {
    const obj = JSON.parse($('stateText').value || '{}');
    viewed = new Set(obj.viewed || []);
    favorites = new Set(obj.favorites || []);
    saveSet(VIEW_KEY, viewed); saveSet(FAV_KEY, favorites); render();
  } catch(e) { alert('JSONを読み込めません'); }
}
function clearFilters() {
  $('query').value='';
  $('grade').value='';
  $('gradeBasis').value='latest';
  $('state').value='';
  quickMode='';
  deadlineTab='all';
  localStorage.setItem(DEADLINE_TAB_KEY, deadlineTab);
  currentPage=1;
  render();
}

['query','grade','gradeBasis','state'].forEach(id => $(id).addEventListener('input', () => { quickMode=''; queueRender(true); }));
$('sortBy').value = sortKey;
$('sortBy').addEventListener('input', () => { sortKey = $('sortBy').value || 'rank'; localStorage.setItem('navicusProposalDb:v1:sortBy', sortKey); queueRender(true); });
$('pageSize').value = String(pageSize);
$('pageSize').addEventListener('input', () => { pageSize = Number($('pageSize').value) || 25; localStorage.setItem('navicusProposalDb:v1:pageSize', String(pageSize)); queueRender(true); });
$('exportState').addEventListener('click', exportState);
$('importState').addEventListener('click', importState);
$('resetFilters').addEventListener('click', clearFilters);
$('showAll').addEventListener('click', clearFilters);
$('showSimilar').addEventListener('click', () => { $('state').value='similar'; quickMode=''; currentPage=1; render(); });
$('showBplus').addEventListener('click', () => { $('grade').value=''; $('query').value=''; $('state').value=''; quickMode='bplus'; currentPage=1; render(); });
$('showHistoricalAB').addEventListener('click', () => {
  $('grade').value='';
  $('query').value='';
  $('state').value='historical_ab';
  $('gradeBasis').value='best';
  quickMode='historical_ab';
  sortKey='best-grade';
  $('sortBy').value=sortKey;
  localStorage.setItem('navicusProposalDb:v1:sortBy', sortKey);
  currentPage=1;
  render();
});
render();
