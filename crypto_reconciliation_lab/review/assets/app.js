/* Offline presentation only. Financial values remain strings or null. */
(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const own = (object, key) => Object.prototype.hasOwnProperty.call(object, key);
  const PAGE_SIZE = 20;
  const ISSUE_EXPLANATIONS = {
    MANIFEST_ABSENT: 'No applicable delivery manifest was selected; completeness is unknown.',
    MANIFEST_COUNT: 'The manifest count and the count of unique valid records differ.',
    MANIFEST_CONFLICT: 'Conflicting manifests are stored for the selected delivery scope.',
    OPENING_ABSENT: 'A required opening balance is absent at this knowledge cut.',
    OPENING_CONFLICT: 'Opening balance records conflict for this scope.',
    EVENT_ID_CONFLICT: 'Different economic contents share an event identity.',
    REPORT_ABSENT: 'No report for the required balance time was selected.',
    REPORT_STALE: 'An older balance-time report is recorded instead of a current report.',
    REPORT_VERSION_CONFLICT: 'A report version has conflicting contents.',
    NEGATIVE_ECONOMIC_BALANCE: 'The saved economic-order replay records a negative investor balance.',
    PROVISIONAL_NEGATIVE_BALANCE: 'A provisional negative balance was observed with incomplete data.',
    QUARANTINED_INPUT: 'The saved result includes a quarantined input. Its raw receipt remains available.'
  };
  const state = {source: null, run: null, finding: null, tab: 'overview', page: 0, detailPages: new Map(), opener: null, comparison: null};
  let bundle;
  let copyOpener = null;
  let announcementTimer;

  function node(tag, className, text) {
    const result = document.createElement(tag);
    if (className) result.className = className;
    if (text !== undefined) result.textContent = text;
    return result;
  }
  function clear(element) { element.replaceChildren(); }
  function plain(value) { return typeof value === 'string' ? value : value === null || value === undefined ? 'Not available' : typeof value === 'boolean' ? (value ? 'true' : 'false') : 'Unsupported display value'; }
  function amount(value) { return typeof value === 'string' ? value : value === null ? 'Unknown' : 'Not available'; }
  function truth(value) { return value === true ? 'true' : value === false ? 'false' : 'Not available'; }
  function shortId(value) { return typeof value === 'string' && value.length > 24 ? value.slice(0, 12) + '…' + value.slice(-8) : plain(value); }
  function runToken(run) { return 'run-' + bundle.runs.indexOf(run); }
  function sourceToken(source) { return 'source-' + bundle.sources.indexOf(source); }
  function runFromToken(value) { return bundle.runs.find((run) => runToken(run) === value) || null; }
  function runLabel(run) { return (run.run_label || run.knowledge_at) + ' · ' + shortId(run.run_id); }
  function statusClass(value) {
    const classes = {COMPLETE: 'complete', MATCHED: 'matched', MISMATCH: 'mismatch', INCOMPLETE: 'incomplete', STALE: 'stale', CONFLICT: 'conflict'};
    return own(classes, value) ? classes[value] : 'neutral';
  }
  function badge(value) { return node('span', 'badge ' + statusClass(value), plain(value)); }
  function button(text, handler, className) {
    const result = node('button', className || 'secondary', text);
    result.type = 'button';
    result.addEventListener('click', handler);
    return result;
  }
  function option(select, value, text) {
    const result = node('option', '', text); result.value = value; select.append(result); return result;
  }
  function announce(message) {
    clearTimeout(announcementTimer); $('announcement').textContent = message;
    announcementTimer = setTimeout(() => { $('announcement').textContent = ''; }, 6000);
  }
  async function copyText(text, opener) {
    try {
      if (!navigator.clipboard || !navigator.clipboard.writeText) throw new Error('Clipboard unavailable');
      await navigator.clipboard.writeText(text);
      announce('Saved text copied.');
    } catch (_) {
      copyOpener = opener || document.activeElement;
      $('copy-text').value = text;
      $('copy-dialog').showModal(); $('copy-text').focus(); $('copy-text').select();
    }
  }
  function closeCopy() {
    $('copy-dialog').close();
    if (copyOpener && copyOpener.isConnected) copyOpener.focus();
  }
  function downloadText(text, filename) {
    const blob = new Blob([text], {type: 'application/json;charset=utf-8'});
    const url = URL.createObjectURL(blob);
    const link = node('a'); link.href = url; link.download = filename;
    document.body.append(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
    announce('Original saved text downloaded.');
  }
  function rawDisclosure(container, text, title) {
    if (typeof text !== 'string') return;
    const details = node('details');
    details.append(node('summary', '', title || 'Original saved JSON text'));
    const pre = node('pre', 'raw-text', text); pre.tabIndex = 0;
    details.append(pre);
    const row = node('div', 'button-row');
    const copy = button('Copy raw text', () => copyText(text, copy)); row.append(copy);
    details.append(row); container.append(details);
  }
  function fields(container, rows) {
    const list = node('dl', 'raw-fields');
    for (const row of rows) { list.append(node('dt', '', row.name), node('dd', '', plain(row.value))); }
    container.append(list);
  }
  function amountPairs(container, rows, title) {
    if (!Array.isArray(rows)) return;
    if (title) container.append(node('h3', '', title));
    const list = node('dl', 'raw-fields');
    for (const row of rows) { list.append(node('dt', '', plain(row.scope)), node('dd', 'amount-value', amount(row.amount))); }
    container.append(list);
  }
  function pagination(container, total, page, change) {
    clear(container);
    if (total <= PAGE_SIZE) return;
    const pages = Math.ceil(total / PAGE_SIZE);
    const previous = button('Previous', () => change(page - 1)); previous.disabled = page === 0;
    const next = button('Next', () => change(page + 1)); next.disabled = page >= pages - 1;
    container.append(previous, node('span', '', 'Page ' + (page + 1) + ' of ' + pages + ' · ' + total + ' stored rows'), next);
  }
  function paged(container, rows, key, render) {
    const page = state.detailPages.get(key) || 0;
    container.append(node('p', 'help', rows.length + ' stored rows. Pagination changes presentation only.'));
    rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE).forEach((row, i) => render(row, page * PAGE_SIZE + i));
    const controls = node('div', 'pagination');
    pagination(controls, rows.length, page, (value) => { state.detailPages.set(key, value); renderDetailContent(); });
    container.append(controls);
    if (!rows.length) container.append(node('p', 'muted', 'No rows of this kind are stored for this finding.'));
  }
  function evidenceFor(run, id) { return run && run.evidence && own(run.evidence, id) ? run.evidence[id] : null; }
  function evidenceIds(finding) {
    const ids = new Set(finding.evidence_ids || []);
    for (const key of ['report_ids', 'event_ids', 'correction_ids']) for (const id of finding[key] || []) if (evidenceFor(state.run, id)) ids.add(id);
    const queue = Array.from(ids);
    for (let i = 0; i < queue.length; i += 1) {
      const evidence = evidenceFor(state.run, queue[i]);
      for (const id of evidence && evidence.receipt_ids || []) if (evidenceFor(state.run, id) && !ids.has(id)) { ids.add(id); queue.push(id); }
    }
    return Array.from(ids);
  }
  function reference(container, id, label) {
    const evidence = evidenceFor(state.run, id);
    if (!evidence) { container.append(node('code', '', plain(id) + ' · reference not available in this run')); return; }
    const control = button((label || 'Open evidence') + ' · ' + shortId(id), () => openEvidence(id), 'reference-button');
    control.dataset.evidenceKey = id;
    container.append(control);
  }
  function references(container, ids, title) {
    if (title) container.append(node('h3', '', title));
    const list = node('div', 'link-list');
    for (const id of ids || []) reference(list, id);
    if (!(ids || []).length) list.append(node('p', 'help', 'No references stored.'));
    container.append(list);
  }
  function renderEvidence(container, evidence, ordinal, title) {
    const card = node('article', 'detail-card'); card.id = 'evidence-card-' + ordinal;
    card.dataset.evidenceKey = evidence.id;
    card.append(node('h3', '', (title || plain(evidence.kind)) + ' · ' + shortId(evidence.id)));
    const idRow = node('div', 'button-row');
    const copy = button('Copy evidence ID', () => copyText(evidence.id, copy)); idRow.append(copy); card.append(idRow);
    fields(card, [{name: 'Evidence ID', value: evidence.id}, {name: 'Stored kind', value: evidence.kind}, {name: 'Receipt received at · UTC', value: evidence.received_at}]);
    if (evidence.received_at === null && typeof evidence.received_at_raw_text === 'string') {
      const rawTime = node('details'); rawTime.append(node('summary', '', 'Unknown or malformed delivery time · view saved text'), node('pre', 'raw-text', evidence.received_at_raw_text)); card.append(rawTime);
    }
    fields(card, evidence.fields || []);
    if ((evidence.receipt_ids || []).length) references(card, evidence.receipt_ids, 'Saved receipt references');
    rawDisclosure(card, evidence.raw_text);
    container.append(card);
  }
  function selectedLedger() { return state.run && state.finding && state.run.ledgers && state.run.ledgers[state.finding.asset] || null; }
  function storedReason(finding) {
    const messages = {
      INCOMPLETE: 'Required data is incomplete in this saved result. The stored observation is not a definitive reconciliation.',
      STALE: 'The saved result identifies stale data. A definitive comparison is not inferred from an older report.',
      CONFLICT: 'The saved result contains conflicting data. Review its issue codes and evidence; no cause is inferred.',
      COMPLETE: finding.reconciliation_state === 'MATCHED' ? 'The saved comparison is matched with complete required data.' : finding.reconciliation_state === 'MISMATCH' ? 'The saved comparison reports a mismatch with complete required data. A mismatch does not identify its cause.' : 'Required data is marked complete. The reconciliation state is shown exactly as stored.'
    };
    return own(messages, finding.data_state) ? messages[finding.data_state] : 'This stored data state is unrecognized by the viewer. No successful result is inferred.';
  }
  function renderOverview(container) {
    const finding = state.finding;
    container.append(node('p', '', storedReason(finding)));
    container.append(node('h3', '', 'Saved issues and reasons'));
    if (!(finding.issues || []).length) container.append(node('p', 'help', 'No issue entries are stored for this finding.'));
    for (const issue of finding.issues || []) {
      const card = node('article', 'detail-card'); card.append(node('h3', '', plain(issue.code)));
      fields(card, [{name: 'Stored issue state', value: issue.state}]);
      card.append(node('p', 'help', own(ISSUE_EXPLANATIONS, issue.code) ? ISSUE_EXPLANATIONS[issue.code] : 'Recorded issue code. Its saved details are shown below without an inferred cause.'));
      references(card, issue.evidence_ids || []);
      rawDisclosure(card, issue.raw_text, 'Saved issue details'); container.append(card);
    }
    references(container, finding.event_ids || [], 'Saved event references');
    if (own(finding, 'correction_ids')) references(container, finding.correction_ids, 'Saved correction references');
  }
  function renderReports(container) {
    const ids = state.finding.report_ids || [];
    container.append(node('p', '', 'Only reports selected by this saved finding are shown. No current report version is substituted.'));
    paged(container, ids, 'reports', (id, ordinal) => {
      const evidence = evidenceFor(state.run, id);
      if (evidence) renderEvidence(container, evidence, ordinal, 'Selected report');
      else container.append(node('p', 'missing-row', 'Missing stored report reference: ' + plain(id)));
    });
  }
  function renderTrace(container) {
    const ledger = selectedLedger();
    if (!ledger) { container.append(node('p', '', 'No ledger trace is stored for this finding.')); return; }
    container.append(node('p', '', 'Saved ' + state.finding.asset + ' ledger trace, in its stored economic order. Rows may include other investors in this asset. Delivery time does not reorder corrections.'));
    const opening = node('details'); opening.append(node('summary', '', 'Saved opening balances and ending balances'));
    amountPairs(opening, ledger.opening_amounts, 'Opening amounts'); amountPairs(opening, ledger.investor_balances, 'Saved ending investor balances'); amountPairs(opening, ledger.custody_rollforward, 'Saved customer custody roll-forward');
    fields(opening, [{name: 'Saved liability', value: ledger.liability}]); container.append(opening);
    paged(container, ledger.trace || [], 'trace', (row, ordinal) => {
      const card = node('article', 'detail-card'); card.append(node('h3', '', 'Trace row ' + (ordinal + 1) + ' · ' + shortId(row.event_id)));
      fields(card, [{name: 'Event / effect ID', value: row.event_id}, {name: 'Occurred at · UTC', value: row.occurred_at}, {name: 'Stored sequence', value: row.sequence}, {name: 'Customer custody location', value: row.custody_location}, {name: 'Customer custody delta', value: row.custody_delta}]);
      amountPairs(card, row.investor_deltas, 'Stored investor deltas'); amountPairs(card, row.balances_after, 'Stored balances after');
      const links = node('div', 'link-list'); if (evidenceFor(state.run, row.event_id)) reference(links, row.event_id, 'Open event evidence');
      if (own(row, 'correction_group_id')) {
        fields(card, [{name: 'Saved correction group', value: row.correction_group_id}]);
        const groupButton = button('Open correction groups', () => setTab('corrections'), 'reference-button'); links.append(groupButton);
      }
      card.append(links); rawDisclosure(card, row.raw_text, 'Saved trace row text'); container.append(card);
    });
  }
  function renderCorrections(container) {
    const ledger = selectedLedger();
    if (!ledger || !own(ledger, 'groups')) { container.append(node('p', '', 'Correction groups are not part of this historical payload format. No correction fields have been synthesized.')); return; }
    container.append(node('p', '', 'Groups and delivery metadata are stored under this asset ledger. Effects stay at the target economic time; they are not new delivery-time events.'));
    paged(container, ledger.groups || [], 'groups', (group, ordinal) => {
      const card = node('article', 'detail-card'); card.append(node('h3', '', 'Correction group ' + (ordinal + 1) + ' · ' + plain(group.mode)));
      fields(card, [{name: 'Group ID', value: group.id}, {name: 'Target event', value: group.target_record_id}, {name: 'Correction record', value: group.correction_record_id}, {name: 'Economic time · UTC', value: group.occurred_at}, {name: 'First known at · UTC', value: group.first_known_at}, {name: 'Original amount', value: group.original_amount}, {name: 'Effective amount', value: group.effective_amount}]);
      const links = node('div', 'link-list');
      for (const id of [group.id, group.target_record_id, group.correction_record_id, ...(group.manifest_ids || [])]) if (typeof id === 'string' && evidenceFor(state.run, id)) reference(links, id);
      card.append(links);
      for (const effect of group.effects || []) {
        const effectCard = node('div', 'detail-card'); effectCard.append(node('h3', '', 'Stored effect · ' + plain(effect.role)));
        amountPairs(effectCard, effect.investor_deltas, 'Investor deltas'); fields(effectCard, [{name: 'Customer custody location', value: effect.custody_location}, {name: 'Customer custody delta', value: effect.custody_delta}]); rawDisclosure(effectCard, effect.raw_text, 'Saved effect text'); card.append(effectCard);
      }
      rawDisclosure(card, group.raw_text, 'Saved group text'); container.append(card);
    });
    if (own(ledger, 'deliveries')) {
      const deliveries = node('details'); deliveries.append(node('summary', '', 'Saved correction delivery metadata (' + ledger.deliveries.length + ')'));
      const target = node('div'); deliveries.append(target);
      paged(target, ledger.deliveries, 'deliveries', (delivery, ordinal) => {
        const card = node('article', 'detail-card'); card.append(node('h3', '', 'Delivery ' + (ordinal + 1)));
        references(card, delivery.manifest_ids || [], 'Saved manifest references'); references(card, delivery.applied_correction_ids || [], 'Saved applied correction references'); rawDisclosure(card, delivery.raw_text, 'Saved delivery text'); target.append(card);
      }); container.append(deliveries);
    }
  }
  function renderReceipts(container) {
    const ids = evidenceIds(state.finding);
    container.append(node('p', '', 'Evidence comes only from this run. Invalid receipts remain visible as saved text; malformed fields are not repaired.'));
    paged(container, ids, 'receipts', (id, ordinal) => {
      const evidence = evidenceFor(state.run, id);
      if (evidence) renderEvidence(container, evidence, ordinal);
      else container.append(node('p', 'missing-row', 'Missing saved evidence: ' + plain(id)));
    });
  }
  const tabs = [['overview', 'Reasons & links'], ['reports', 'Reports'], ['trace', 'Ledger trace'], ['corrections', 'Corrections'], ['receipts', 'Receipts & raw evidence']];
  function renderDetailContent() {
    const container = $('detail-content'); clear(container);
    if (!state.run || !state.finding) return;
    $('detail-content').setAttribute('aria-labelledby', 'tab-' + state.tab);
    for (const control of $('detail-tabs').children) {
      const selected = control.id === 'tab-' + state.tab;
      control.setAttribute('aria-selected', selected ? 'true' : 'false'); control.tabIndex = selected ? 0 : -1;
    }
    ({overview: renderOverview, reports: renderReports, trace: renderTrace, corrections: renderCorrections, receipts: renderReceipts})[state.tab](container);
  }
  function setTab(key, focus) { state.tab = key; renderDetailContent(); if (focus) $('tab-' + key).focus(); }
  function openEvidence(id) {
    if (!state.finding || !evidenceFor(state.run, id)) return;
    const ids = evidenceIds(state.finding); const position = ids.indexOf(id);
    if (position < 0) { announce('This reference is not linked to the selected finding.'); return; }
    state.detailPages.set('receipts', Math.floor(position / PAGE_SIZE)); setTab('receipts', true);
    const card = $('evidence-card-' + position); if (card) { card.tabIndex = -1; card.focus(); card.scrollIntoView({block: 'nearest'}); }
  }
  function closeDetail(restoreFocus) {
    state.finding = null; state.detailPages.clear(); $('finding-panel').hidden = true; clear($('detail-content')); clear($('detail-summary'));
    if (restoreFocus && state.opener && state.opener.isConnected) state.opener.focus(); state.opener = null;
  }
  function openFinding(finding, opener) {
    state.finding = finding; state.opener = opener || null; state.tab = 'overview'; state.detailPages.clear();
    $('finding-panel').hidden = false; $('detail-heading').textContent = finding.comparison + ' · ' + finding.asset + ' · ' + finding.scope;
    const summary = $('detail-summary'); clear(summary);
    const states = node('div', 'detail-summary'); states.append(badge(finding.data_state), badge(finding.reconciliation_state), node('span', 'provisional', 'Provisional: ' + truth(finding.provisional))); summary.append(states);
    const amounts = node('dl', 'amount-grid');
    for (const [label, value] of [['Expected', finding.expected], ['Reported', finding.reported], ['Difference · expected_minus_reported', finding.difference]]) { const item = node('div'); item.append(node('dt', '', label), node('dd', '', amount(value))); amounts.append(item); }
    summary.append(amounts);
    const controls = $('detail-tabs'); clear(controls);
    tabs.forEach(([key, title], index) => {
      const control = button(title, () => setTab(key)); control.id = 'tab-' + key; control.setAttribute('role', 'tab'); control.setAttribute('aria-controls', 'detail-content');
      control.addEventListener('keydown', (event) => {
        let target = index;
        if (event.key === 'ArrowRight') target = (index + 1) % tabs.length;
        else if (event.key === 'ArrowLeft') target = (index + tabs.length - 1) % tabs.length;
        else if (event.key === 'Home') target = 0;
        else if (event.key === 'End') target = tabs.length - 1;
        else return;
        event.preventDefault(); setTab(tabs[target][0], true);
      }); controls.append(control);
    });
    renderDetailContent(); $('detail-heading').focus(); $('finding-panel').scrollIntoView({block: 'start'});
  }
  const filterDefinitions = [['comparison', 'filter-comparison'], ['asset', 'filter-asset'], ['scope', 'filter-scope'], ['data_state', 'filter-data'], ['reconciliation_state', 'filter-reconciliation']];
  function populateFilters() {
    for (const [field, id] of filterDefinitions) {
      const select = $(id); clear(select); option(select, '', 'All');
      Array.from(new Set(state.run.findings.map((finding) => finding[field]))).sort().forEach((value, index) => option(select, 'value-' + index, plain(value)));
      select._storedValues = Array.from(new Set(state.run.findings.map((finding) => finding[field]))).sort();
    }
  }
  function filterValue(select) { return select._storedValues.find((_, index) => 'value-' + index === select.value); }
  function renderFindings() {
    const tbody = $('finding-rows'); clear(tbody);
    if (!state.run) return;
    let active = 0;
    const rows = state.run.findings.filter((finding) => filterDefinitions.every(([field, id]) => {
      const control = $(id); return control.value === '' || finding[field] === filterValue(control);
    }));
    for (const [, id] of filterDefinitions) if ($(id).value !== '') active += 1;
    $('finding-count').textContent = rows.length + ' shown · ' + state.run.findings.length + ' stored findings';
    $('active-filters').textContent = active ? '· ' + active + ' active' : '';
    $('no-findings').hidden = rows.length !== 0; $('findings-table').hidden = rows.length === 0;
    if (state.run.findings.length === 0) {
      $('no-findings').querySelector('strong').textContent = 'This run has no stored findings.';
      $('no-findings').querySelector('p').textContent = 'An empty saved result is not an “all matched” result.';
    } else {
      $('no-findings').querySelector('strong').textContent = 'No findings match these filters.';
      $('no-findings').querySelector('p').textContent = 'This is an empty view, not an “all matched” result. Clear filters to see the stored findings.';
    }
    rows.slice(state.page * PAGE_SIZE, (state.page + 1) * PAGE_SIZE).forEach((finding) => {
      const tr = node('tr', 'finding-row'); tr.dataset.findingOrdinal = '' + finding.ordinal;
      function cell(label, className, content) { const td = node('td', className); td.dataset.label = label; if (content instanceof Node) td.append(content); else td.textContent = content; tr.append(td); return td; }
      const scope = node('div', 'scope-cell', finding.comparison); scope.append(node('span', 'scope-name', finding.scope));
      cell('Check / scope', '', scope); cell('Asset', 'asset-cell', finding.asset); cell('Data state', '', badge(finding.data_state)); cell('Reconciliation', '', badge(finding.reconciliation_state)); cell('Provisional', 'provisional ' + (finding.provisional === true ? 'true' : ''), truth(finding.provisional));
      cell('Expected', 'amount' + (finding.expected === null ? ' unknown' : ''), amount(finding.expected)); cell('Reported', 'amount' + (finding.reported === null ? ' unknown' : ''), amount(finding.reported)); cell('Difference', 'amount' + (finding.difference === null ? ' unknown' : ''), amount(finding.difference));
      const inspect = button('Inspect', () => openFinding(finding, inspect), 'inspect-button'); inspect.id = 'inspect-' + state.run.findings.indexOf(finding); inspect.setAttribute('aria-label', 'Inspect ' + finding.comparison + ' ' + finding.asset + ' ' + finding.scope); cell('Detail', '', inspect); tbody.append(tr);
    });
    pagination($('finding-pagination'), rows.length, state.page, (page) => { state.page = page; renderFindings(); });
  }
  function eligibility(left, right) {
    if (!left || !right) return ['Choose another stored run.'];
    const reasons = [];
    if (left.source_alias !== right.source_alias) reasons.push('Different source aliases cannot form one history.');
    if (typeof left.configuration_text !== 'string' || typeof right.configuration_text !== 'string' || left.configuration_text !== right.configuration_text || left.configuration_id !== right.configuration_id) reasons.push('The complete saved configurations differ.');
    if (!left.balance_sort_key || !right.balance_sort_key || left.balance_sort_key !== right.balance_sort_key) reasons.push('Economic balance times differ.');
    if (left.rule_version !== right.rule_version) reasons.push('Stored rule versions differ.');
    if (!left.knowledge_sort_key || !right.knowledge_sort_key) reasons.push('Chronological knowledge time is unavailable.');
    else if (left.knowledge_sort_key === right.knowledge_sort_key) reasons.push('Both runs have the same knowledge time; they remain separate records, not before/after snapshots.');
    return reasons;
  }
  function clearComparison() { state.comparison = null; clear($('comparison-output')); $('comparison-output').hidden = true; }
  function updateEligibility() {
    clearComparison();
    const candidate = runFromToken($('compare-select').value); const reasons = eligibility(state.run, candidate);
    $('compare-button').disabled = reasons.length !== 0;
    $('compare-eligibility').textContent = reasons.length ? reasons.join(' ') : 'Eligible: same source, complete saved configuration, economic time and rule; different knowledge cuts.';
  }
  function populateComparison() {
    const select = $('compare-select'); clear(select); option(select, '', 'Choose another stored run');
    for (const run of bundle.runs) if (run !== state.run) option(select, runToken(run), run.source_label + ' · ' + runLabel(run));
    const eligible = bundle.runs.find((run) => run !== state.run && eligibility(state.run, run).length === 0);
    if (eligible) select.value = runToken(eligible);
    updateEligibility();
  }
  function sameValue(left, right) {
    if (Array.isArray(left) || Array.isArray(right)) return Array.isArray(left) && Array.isArray(right) && left.length === right.length && left.every((value, index) => value === right[index]);
    return left === right;
  }
  function compareText(value) {
    if (Array.isArray(value)) return value.length ? value.join('\n') : '(none stored)';
    return value === null ? 'Unknown' : value === undefined ? 'Not stored in this payload' : plain(value);
  }
  function comparisonValue(finding, field) {
    if (!finding) return undefined;
    if (field === 'issues') return (finding.issues || []).map((issue) => issue.raw_text);
    return finding[field];
  }
  function renderComparison() {
    const other = runFromToken($('compare-select').value);
    if (eligibility(state.run, other).length) { updateEligibility(); return; }
    const earlier = state.run.knowledge_sort_key < other.knowledge_sort_key ? state.run : other;
    const later = earlier === state.run ? other : state.run;
    state.comparison = {earlier, later};
    const out = $('comparison-output'); clear(out); out.hidden = false;
    const times = node('div', 'history-times');
    for (const [title, run] of [['Earlier knowledge cut', earlier], ['Later knowledge cut', later]]) {
      const box = node('div'); box.append(node('strong', '', title), node('code', '', run.knowledge_at), node('p', '', 'Run ' + shortId(run.run_id))); times.append(box);
    }
    out.append(times, node('p', 'help', 'Saved values only. Highlighted fields changed; ledger event references and report references are shown separately. Missing findings stay missing.'));
    const leftMap = new Map(earlier.findings.map((finding) => [finding.match_key, finding]));
    const rightMap = new Map(later.findings.map((finding) => [finding.match_key, finding]));
    const keys = Array.from(new Set([...leftMap.keys(), ...rightMap.keys()]));
    const comparedFields = [['data_state', 'Data state'], ['reconciliation_state', 'Reconciliation'], ['provisional', 'Provisional'], ['expected', 'Expected'], ['reported', 'Reported'], ['difference', 'Difference: expected_minus_reported'], ['issues', 'Saved issues / reasons'], ['event_ids', 'Ledger event IDs'], ['report_ids', 'Report IDs'], ['evidence_ids', 'Evidence IDs'], ['correction_ids', 'Correction IDs']];
    for (const key of keys) {
      const left = leftMap.get(key); const right = rightMap.get(key); const referenceFinding = left || right;
      const card = node('article', 'history-card'); card.append(node('h3', '', referenceFinding.comparison + ' · ' + referenceFinding.asset + ' · ' + referenceFinding.scope));
      const controls = node('div', 'button-row'); controls.classList.add('history-inspect-controls');
      for (const [title, run, finding] of [['Inspect earlier finding', earlier, left], ['Inspect later finding', later, right]]) if (finding) controls.append(button(title, () => { selectRun(run); openFinding(run.findings.find((candidate) => candidate.match_key === key)); }));
      card.append(controls);
      const table = node('table', 'history-table'); const head = node('thead'); const row = node('tr');
      for (const label of ['Stored field', 'Earlier', 'Later']) { const th = node('th', '', label); th.scope = 'col'; row.append(th); } head.append(row); table.append(head);
      const body = node('tbody');
      if (!left || !right) { const missing = node('tr'); missing.append(node('th', '', 'Finding'), node('td', left ? '' : 'missing-row', left ? 'Stored' : 'Missing'), node('td', right ? '' : 'missing-row', right ? 'Stored' : 'Missing')); body.append(missing); }
      for (const [field, label] of comparedFields) {
        if (field === 'correction_ids' && (!left || !own(left, field)) && (!right || !own(right, field))) continue;
        const l = comparisonValue(left, field); const r = comparisonValue(right, field); const changed = !left || !right || !sameValue(l, r);
        const tr = node('tr', changed ? 'changed' : ''); const name = node('th', '', label); name.scope = 'row'; if (changed) name.append(node('span', 'changed-tag', 'Changed'));
        tr.append(name, node('td', left ? '' : 'missing-row', left ? compareText(l) : 'Missing finding'), node('td', right ? '' : 'missing-row', right ? compareText(r) : 'Missing finding')); body.append(tr);
      }
      table.append(body); card.append(table); out.append(card);
    }
    if (!keys.length) out.append(node('p', 'empty-state', 'Neither saved run contains findings. This is not an all-matched conclusion.'));
  }
  function selectionError(message) {
    state.run = null; closeDetail(false); clearComparison(); clear($('finding-rows')); $('finding-count').textContent = 'No run selected'; $('run-heading').textContent = 'Selection unavailable'; $('balance-at').textContent = 'Not available'; $('knowledge-at').textContent = 'Not available'; $('startup-error').hidden = false; $('startup-error').textContent = message; $('compare-button').disabled = true;
    for (const id of ['run-id', 'payload-sha', 'schema-version', 'rule-version']) $(id).textContent = 'Not available';
  }
  function selectRun(run) {
    if (!run) { selectionError('The selected run is not available in this export. Choose a stored run from the source selector.'); return; }
    const source = bundle.sources.find((candidate) => candidate.alias === run.source_alias);
    if (!source) { selectionError('The selected source is not available in this export.'); return; }
    $('startup-error').hidden = true;
    if (state.source !== source) { state.source = source; $('source-select').value = sourceToken(source); populateRuns(source); }
    state.run = run; state.page = 0; closeDetail(false); clearComparison(); $('run-select').value = runToken(run);
    $('run-heading').textContent = run.source_label || run.source_alias; $('rule-version').textContent = plain(run.rule_version); $('balance-at').textContent = plain(run.balance_at); $('knowledge-at').textContent = plain(run.knowledge_at); $('run-id').textContent = run.run_id; $('payload-sha').textContent = run.payload_sha256; $('schema-version').textContent = '' + run.schema_version;
    populateFilters(); renderFindings(); populateComparison();
  }
  function populateRuns(source) {
    const select = $('run-select'); clear(select);
    const rows = bundle.runs.filter((run) => run.source_alias === source.alias);
    for (const run of rows) option(select, runToken(run), runLabel(run));
    $('source-count').textContent = rows.length + ' saved run' + (rows.length === 1 ? '' : 's') + ' in this source · alias ' + source.alias;
  }
  function selectSource(source) {
    if (!source) { selectionError('The selected source is not available in this export. Choose one of the stored sources.'); return; }
    state.source = source; populateRuns(source); selectRun(bundle.runs.find((run) => run.source_alias === source.alias));
  }
  function start() {
    bundle = JSON.parse($('review-data').textContent);
    if (!bundle || bundle.format !== 'review-bundle-v1' || !Array.isArray(bundle.runs) || !Array.isArray(bundle.sources) || !bundle.runs.length || !bundle.sources.length) throw new Error('This page does not contain a supported nonempty review-bundle-v1 export.');
    for (const run of bundle.runs) if (run.identity_validated !== true || typeof run.raw_payload !== 'string' || !Array.isArray(run.findings)) throw new Error('Stored payload identity or display structure has not been validated.');
    for (const source of bundle.sources) option($('source-select'), sourceToken(source), source.label || source.alias);
    $('source-select').addEventListener('change', () => selectSource(bundle.sources.find((source) => sourceToken(source) === $('source-select').value)));
    $('run-select').addEventListener('change', () => selectRun(runFromToken($('run-select').value)));
    for (const [, id] of filterDefinitions) $(id).addEventListener('change', () => { state.page = 0; closeDetail(false); renderFindings(); });
    $('reset-filters').addEventListener('click', () => { for (const [, id] of filterDefinitions) $(id).value = ''; state.page = 0; closeDetail(false); renderFindings(); });
    $('copy-run').addEventListener('click', () => { if (state.run) copyText(state.run.run_id, $('copy-run')); });
    $('download-run').addEventListener('click', () => { if (state.run) downloadText(state.run.raw_payload, 'stored-' + runToken(state.run) + '.json'); });
    $('close-detail').addEventListener('click', () => closeDetail(true)); $('compare-select').addEventListener('change', updateEligibility); $('compare-button').addEventListener('click', renderComparison);
    $('select-copy').addEventListener('click', () => { $('copy-text').focus(); $('copy-text').select(); }); $('close-copy').addEventListener('click', closeCopy);
    $('copy-dialog').addEventListener('cancel', (event) => { event.preventDefault(); closeCopy(); });
    $('bundle-content').append(node('p', '', 'Contract: ' + bundle.format + ' · Exporter: ' + plain(bundle.exporter_version)), node('p', '', bundle.sources.length + ' selected sources · ' + bundle.runs.length + ' saved runs. Individual source snapshots are read consistently; no cross-database atomic snapshot is claimed.'));
    if (window.matchMedia('(max-width: 600px)').matches) $('filter-controls').open = false;
    $('workspace').hidden = false; selectSource(bundle.sources[0]); document.documentElement.dataset.reviewReady = 'true';
  }
  try { start(); } catch (error) {
    $('startup-error').textContent = 'Review page could not open: ' + error.message; $('startup-error').hidden = false; $('workspace').hidden = true; document.documentElement.dataset.reviewReady = 'error';
  }
})();
