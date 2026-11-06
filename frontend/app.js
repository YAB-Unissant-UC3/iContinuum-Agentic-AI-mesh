'use strict';

const $ = (id) => document.getElementById(id);
const state = { documents: [], selected: -1, view: 'source', start: null, end: null, task: 'brief', busy: false, user: null, result: null };
const limits = { max_files: 12, max_file_bytes: 256 * 1024, max_total_bytes: 2 * 1024 * 1024 };
let initializing = true;

function notice(message, error = false) {
  $('notice').textContent = message;
  $('notice').classList.toggle('error', error);
  $('notice').hidden = !message;
}

async function request(path, options) {
  const response = await fetch(path, options);
  const payload = await response.json();
  if (!response.ok) {
    if (response.status === 401 && state.user) setUser(null);
    throw new Error(payload.error?.message || 'The request could not be completed.');
  }
  return payload;
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function busy(value) {
  state.busy = value;
  for (const id of ['browse-button', 'demo-button', 'file-input', 'refresh-runs-button']) $(id).disabled = value || !state.user;
  for (const id of ['login-button', 'username', 'password', 'logout-button', 'upload-access']) $(id).disabled = value || initializing;
  $('run-button').disabled = value || !state.user || !state.documents.some((doc) => doc.status === 'ok');
  $('load-run-button').disabled = value || !state.user || !$('analysis-history').value;
  $('approve-button').disabled = value || !canApprove(state.result);
  $('reject-button').disabled = value || !state.result;
  $('clear-button').disabled = value || !state.documents.length;
  $('dropzone').setAttribute('aria-busy', String(value));
  document.querySelectorAll('.remove-document').forEach((button) => { button.disabled = value; });
}

function addDocuments(incoming) {
  let duplicates = 0;
  let errors = 0;
  let added = 0;
  for (const document of incoming) {
    if (document.document_id && state.documents.some((item) => item.document_id === document.document_id)) {
      duplicates += 1;
      continue;
    }
    if (state.documents.length >= limits.max_files) continue;
    state.documents.push(document);
    added += 1;
    if (document.status === 'error') errors += 1;
  }
  if (state.selected < 0 && state.documents.length) state.selected = 0;
  const parts = [`${added} document${added === 1 ? '' : 's'} added.`];
  if (duplicates) parts.push(`${duplicates} identical cop${duplicates === 1 ? 'y skipped' : 'ies skipped'}.`);
  if (errors) parts.push(`${errors} could not be read. Select the file to see why.`);
  notice(parts.join(' '), errors > 0);
  render();
}

function citation() {
  const source = state.documents[state.selected];
  if (!source?.document_id || state.start === null) return null;
  return { document_id: source.document_id, line_start: Math.min(state.start, state.end), line_end: Math.max(state.start, state.end) };
}

function renderSelection() {
  const reference = citation();
  $('copy-button').disabled = !reference;
  $('citation-hint').textContent = reference
    ? `Line${reference.line_start === reference.line_end ? '' : 's'} ${reference.line_start}${reference.line_start === reference.line_end ? '' : `–${reference.line_end}`} selected · Shift-click another line for a range.`
    : 'Select a source line to create a citation.';
  for (const row of $('source-lines').children) {
    const number = Number(row.dataset.line);
    const selected = Boolean(reference && number >= reference.line_start && number <= reference.line_end);
    row.classList.toggle('selected', selected);
    row.setAttribute('aria-pressed', String(selected));
  }
}

function renderViewer() {
  const source = state.documents[state.selected];
  const hasLines = Boolean(source?.lines.length);
  $('viewer-name').textContent = source?.file_name || 'Source preview';
  $('source-meta').hidden = !source;
  $('source-meta').textContent = source?.document_id || 'No source ID available';
  $('json-preview').hidden = !source || state.view !== 'json';
  $('json-preview').textContent = source ? JSON.stringify(source, null, 2) : '';
  $('source-lines').hidden = state.view !== 'source' || !hasLines;
  $('viewer-empty').hidden = Boolean(source && (state.view === 'json' || hasLines));
  const title = $('viewer-empty').querySelector('h3');
  const description = $('viewer-empty').querySelector('h3 + p');
  title.textContent = source?.status === 'error' ? 'This document could not be read.' : source?.status === 'empty' ? 'This document is empty.' : 'No source selected.';
  description.textContent = source?.error?.message || (source?.status === 'empty' ? 'The file has a stable ID, but contains no source lines.' : 'Upload a text file or load the sample documents to view numbered lines.');
  $('source-tab').setAttribute('aria-pressed', String(state.view === 'source'));
  $('json-tab').setAttribute('aria-pressed', String(state.view === 'json'));
  const fragment = document.createDocumentFragment();
  if (source) for (const line of source.lines) {
    const row = element('button', 'source-line');
    row.dataset.line = String(line.line_number);
    row.setAttribute('aria-label', `Select source line ${line.line_number}: ${line.text}`);
    row.append(element('span', 'line-number', line.line_number), element('span', 'line-text', line.text));
    row.addEventListener('click', (event) => {
      if (!event.shiftKey || state.start === null) state.start = line.line_number;
      state.end = line.line_number;
      renderSelection();
    });
    fragment.append(row);
  }
  $('source-lines').replaceChildren(fragment);
  renderSelection();
}

function render() {
  const ready = state.documents.filter((item) => item.status === 'ok');
  $('document-count').textContent = String(state.documents.length).padStart(2, '0');
  $('line-count').textContent = String(state.documents.reduce((sum, item) => sum + item.line_count, 0)).padStart(2, '0');
  $('ready-count').textContent = String(ready.length).padStart(2, '0');
  $('library-count').textContent = state.documents.length;
  $('library-empty').hidden = state.documents.length > 0;
  $('export-button').disabled = !state.documents.length;
  $('clear-button').disabled = state.busy || !state.documents.length;
  $('request-button').disabled = !ready.length;
  const fragment = document.createDocumentFragment();
  state.documents.forEach((source, index) => {
    const row = element('div', `document-row${index === state.selected ? ' selected' : ''}`);
    const select = element('button', 'document-select');
    select.setAttribute('aria-pressed', String(index === state.selected));
    const info = element('span', 'document-info');
    const label = source.status === 'error' ? 'Could not read file' : source.status === 'empty' ? 'Empty file' : `${source.line_count} source lines`;
    info.append(element('span', 'document-name', source.file_name), element('span', `document-subtitle${source.status === 'error' ? ' has-error' : ''}`, `${label}${source.access === 'restricted' ? ' / Manager only' : ''}`));
    const documentNumber = element('span', 'document-index', String(index + 1).padStart(2, '0'));
    documentNumber.setAttribute('aria-hidden', 'true');
    select.append(documentNumber, info);
    select.addEventListener('click', () => { state.selected = index; state.start = null; state.end = null; render(); });
    const remove = element('button', 'remove-document', 'Remove');
    remove.disabled = state.busy;
    remove.setAttribute('aria-label', `Remove ${source.file_name}`);
    remove.addEventListener('click', () => {
      state.documents.splice(index, 1);
      state.selected = Math.min(index, state.documents.length - 1);
      state.start = null; state.end = null;
      render();
      notice('Document removed from this workspace.');
    });
    row.append(select, remove);
    fragment.append(row);
  });
  $('document-list').replaceChildren(fragment);
  renderViewer();
  busy(state.busy);
}

function base64(bytes) {
  let binary = '';
  for (let offset = 0; offset < bytes.length; offset += 8192) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
  }
  return btoa(binary);
}

async function uploadFiles(fileList) {
  if (state.busy || !state.user || !fileList.length) return;
  const files = Array.from(fileList);
  if (files.length + state.documents.length > limits.max_files) return notice('Keep up to 12 documents in the workspace. Remove a document before adding more.', true);
  if (files.some((file) => !file.name.toLowerCase().endsWith('.txt'))) return notice('Choose .txt files saved as UTF-8.', true);
  if (files.some((file) => file.size > limits.max_file_bytes)) return notice('Each file must be 256 KiB or smaller.', true);
  if (files.reduce((sum, file) => sum + file.size, 0) > limits.max_total_bytes) return notice('Upload up to 2 MiB of text at a time.', true);
  busy(true);
  notice('Reading your documents…');
  try {
    const uploads = await Promise.all(files.map(async (file) => ({ file_name: file.name, content_base64: base64(new Uint8Array(await file.arrayBuffer())) })));
    const payload = await request('/api/documents', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ files: uploads, access: $('upload-access').value }) });
    addDocuments(payload.documents);
  } catch (error) { notice(`Could not read the documents. ${error.message}`, true); }
  finally { busy(false); $('file-input').value = ''; }
}

function download(name, payload) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }));
  const anchor = element('a');
  anchor.href = url; anchor.download = name;
  document.body.append(anchor); anchor.click(); anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

$('browse-button').addEventListener('click', () => $('file-input').click());
$('file-input').addEventListener('change', (event) => {
  const files = Array.from(event.target.files);
  event.target.value = '';
  uploadFiles(files);
});
for (const eventName of ['dragenter', 'dragover']) $('dropzone').addEventListener(eventName, (event) => {
  event.preventDefault(); if (!state.busy) $('dropzone').classList.add('dragging');
});
for (const eventName of ['dragleave', 'drop']) $('dropzone').addEventListener(eventName, (event) => {
  event.preventDefault(); $('dropzone').classList.remove('dragging');
});
$('dropzone').addEventListener('drop', (event) => uploadFiles(event.dataTransfer.files));
// Avoid navigating away if a file is dropped outside the upload area.
window.addEventListener('dragover', (event) => event.preventDefault());
window.addEventListener('drop', (event) => event.preventDefault());
$('demo-button').addEventListener('click', async () => {
  if (!state.user || state.busy) return;
  if (state.documents.length > limits.max_files - 4) return notice('Make room for the example documents first.', true);
  busy(true); notice('Loading the fictional examples…');
  try { addDocuments((await request('/api/demo')).documents); }
  catch (error) { notice(`Could not load examples. ${error.message}`, true); }
  finally { busy(false); }
});
$('clear-button').addEventListener('click', () => {
  state.documents = []; state.selected = -1; state.start = null; state.end = null;
  state.result = null; renderResult();
  render(); notice('Workspace cleared. Original files are unchanged.');
});
for (const view of ['source', 'json']) $(`${view}-tab`).addEventListener('click', () => { state.view = view; renderViewer(); });
$('copy-button').addEventListener('click', async () => {
  const reference = citation();
  if (!reference) return;
  try { await navigator.clipboard.writeText(JSON.stringify(reference, null, 2)); notice('Citation copied. It identifies source lines; the analysis audit is shown with each result.'); }
  catch { notice(`Clipboard unavailable. Copy this reference: ${JSON.stringify(reference)}`); }
});
$('export-button').addEventListener('click', () => download('icontinuum-documents.json', { api_version: '1.0', documents: state.documents }));
$('request-button').addEventListener('click', () => download('icontinuum-analysis-request.json', {
  api_version: '1.0', task: state.task, documents: state.documents.filter((item) => item.status === 'ok'), requirements: requirements(),
}));
for (const task of ['brief', 'requirements']) $(`${task}-task`).addEventListener('click', () => {
  state.task = task;
  $('brief-task').setAttribute('aria-pressed', String(task === 'brief'));
  $('requirements-task').setAttribute('aria-pressed', String(task === 'requirements'));
  $('requirements-label').hidden = task !== 'requirements';
  $('task-description').textContent = task === 'brief' ? 'Prepare documents for a cited brief.' : 'Prepare documents for requirements review.';
});
async function checkConnection() {
  try {
    const health = await request('/api/health');
    Object.assign(limits, health.limits);
    $('connection-label').textContent = 'Reader connected';
    $('reader-status').textContent = 'Connected locally';
    const configured = ['gemini_with_fallback', 'groq_with_fallback'].includes(health.mode);
    const provider = health.brief_provider === 'groq' ? 'Groq' : 'Gemini';
    $('analysis-status').textContent = configured ? `${provider} briefs / fallback available` : 'Deterministic extracts';
    $('audit-agent-status').textContent = 'Source validation / review flags';
    $('mode-banner').textContent = configured
      ? `${provider} is selected for briefs (${health.brief_model}); availability is not verified and requests may fall back. Requirements Checker remains deterministic.`
      : 'Deterministic demo mode (no LLM). Live generation is disabled unless explicitly configured.';
  } catch {
    $('connection-label').textContent = 'API unavailable';
    $('connection-dot').classList.add('offline');
    $('reader-status').textContent = 'Connection unavailable';
    notice('Cannot reach the local API. Start python -m backend, then refresh this page.', true);
  }
}

function post(path, payload) {
  return request(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
}

function canApprove(result) {
  if (!result) return false;
  const audit = result.audit;
  return audit.status === 'passed' || (['gemini', 'groq'].includes(result.mode) && audit.status === 'needs_review'
    && audit.flags.length > 0 && audit.flags.every((flag) => flag.severity === 'warning'));
}

function requirements() {
  return state.task === 'requirements' ? $('requirements-input').value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean) : [];
}

function setUser(user) {
  state.user = user;
  state.documents = []; state.result = null; state.selected = -1; state.start = null; state.end = null;
  state.view = 'source';
  $('session-panel').hidden = Boolean(user);
  $('logout-button').hidden = !user;
  $('signed-in-user').textContent = user ? `${user.username} / ${user.role}` : 'Signed out';
  $('upload-access-label').hidden = user?.role !== 'manager';
  $('upload-access').value = 'public';
  $('review-comment').value = '';
  $('requirements-input').value = 'audit records\nquantum encryption';
  $('password').value = '';
  $('analysis-history').replaceChildren(element('option', '', 'No accessible runs'));
  $('analysis-history').firstChild.value = '';
  render(); renderResult();
}

async function refreshRuns() {
  if (!state.user) return;
  const previous = state.result?.analysis_id || $('analysis-history').value;
  const payload = await request('/api/analyses');
  const placeholder = element('option', '', payload.analyses.length ? 'Select a saved run' : 'No accessible runs');
  placeholder.value = '';
  const options = payload.analyses.map((run) => {
    const option = element('option', '', `${run.task} / ${run.analysis_id.slice(0, 12)} / ${run.review}`);
    option.value = run.analysis_id;
    return option;
  });
  $('analysis-history').replaceChildren(placeholder, ...options);
  $('analysis-history').value = previous;
  if (!$('analysis-history').value && options.length) $('analysis-history').value = options[0].value;
  busy(state.busy);
}

async function showCitation(cite) {
  try {
    const source = (await request(`/api/documents/${encodeURIComponent(cite.document_id)}`)).document;
    let index = state.documents.findIndex((item) => item.document_id === cite.document_id);
    if (index < 0) {
      if (state.documents.length >= limits.max_files) state.documents.pop();
      index = state.documents.push(source) - 1;
    } else state.documents[index] = source;
    state.selected = index; state.start = cite.line_start; state.end = cite.line_end; state.view = 'source';
    render();
    $('sources').scrollIntoView({ block: 'start' });
    $('source-lines').querySelector(`[data-line="${cite.line_start}"]`)?.scrollIntoView({ block: 'nearest' });
  } catch (error) { notice(error.message, true); }
}

function citationButtons(citations) {
  const links = element('div', 'result-citations');
  for (const cite of citations || []) {
    const name = state.documents.find((doc) => doc.document_id === cite.document_id)?.file_name || cite.document_id;
    const range = cite.line_start === cite.line_end ? `line ${cite.line_start}` : `lines ${cite.line_start}–${cite.line_end}`;
    const button = element('button', 'text-button result-citation', `${name}, ${range}`);
    button.title = `${cite.document_id}: ${cite.quote}`;
    button.addEventListener('click', () => showCitation(cite));
    links.append(button);
  }
  return links;
}

function renderResult() {
  const result = state.result;
  $('analysis-result').hidden = !result;
  $('result-content').replaceChildren();
  $('audit-trail').hidden = true; $('audit-trail').textContent = '';
  $('result-meta').textContent = '';
  $('result-status').textContent = '';
  $('review-comment').value = '';
  $('manager-review').hidden = !result || state.user?.role !== 'manager';
  $('review-readonly').hidden = state.user?.role === 'manager';
  if (!result) return;
  const generated = ['gemini', 'groq'].includes(result.mode);
  $('result-heading').textContent = result.task === 'brief' ? (generated ? `Project brief: ${result.mode === 'groq' ? 'Groq' : 'Gemini'} draft` : 'Brief: cited source extracts') : 'Requirements: evidence and potential conflicts';
  $('result-meta').textContent = `${result.mode_label}${result.model ? ` / ${result.model}` : ''} / ${result.analysis_id}${result.fallback_reason ? ` / fallback: ${result.fallback_reason}` : ''}`;
  $('result-status').textContent = `Automated audit: ${result.audit.status}. Human review: ${result.review.status}.${result.review.comment ? ` Note: ${result.review.comment}` : ''}`;
  const content = $('result-content');
  if (!generated) content.append(element('h3', '', 'Source-supported extracts'));
  if (!result.claims.length) content.append(element('p', 'muted', 'No matching extracts. This does not establish that a requirement is unmet.'));
  let section = '';
  for (const claim of result.claims) {
    if (generated && claim.section !== section) {
      section = claim.section;
      content.append(element('h3', '', section));
    }
    const item = element('article', 'result-item');
    item.append(element('p', '', claim.text), citationButtons(claim.citations));
    content.append(item);
  }
  if (result.task === 'requirements' || result.contradictions.length) {
    content.append(element('h3', '', 'Potential conflicts'));
    if (!result.contradictions.length) content.append(element('p', 'muted', 'No explicit retention-duration conflicts found by the demo rules. Other conflicts may exist.'));
    for (const conflict of result.contradictions) {
      const item = element('article', 'result-item');
      item.append(element('p', '', conflict.description), citationButtons(conflict.citations));
      content.append(item);
    }
  }
  if (result.task === 'requirements') {
    content.append(element('h3', '', 'Requirement evidence'));
    for (const check of result.requirement_checks) {
      const item = element('article', 'result-item');
      item.append(element('strong', '', `${check.text}: ${check.status}`), element('p', 'muted', check.explanation), citationButtons(check.citations));
      content.append(item);
    }
  }
  content.append(element('h3', '', 'Audit findings'));
  if (!result.audit.flags.length) content.append(element('p', 'muted', 'No invalid references or unsupported extracts detected. This is not general semantic verification.'));
  for (const flag of result.audit.flags) content.append(element('p', 'audit-flag', `${flag.severity || 'error'} / ${flag.code} / ${flag.target}: ${flag.message}`));
  content.append(element('h3', '', 'Limits of this result'));
  const limitations = element('ul', 'result-limitations');
  for (const text of result.limitations) limitations.append(element('li', '', text));
  content.append(limitations);
  busy(state.busy);
}

$('login-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const credentials = { username: $('username').value.trim(), password: $('password').value };
  busy(true);
  try {
    const payload = await post('/api/login', credentials);
    setUser(payload.user);
    await refreshRuns();
    notice(`Signed in as ${payload.user.role}. Load examples or upload synthetic documents.`);
  } catch (error) { notice(error.message, true); }
  finally { $('password').value = ''; busy(false); }
});
$('logout-button').addEventListener('click', async () => {
  busy(true);
  try { await post('/api/logout', {}); setUser(null); notice('Signed out. Source text and results have been cleared from this page.'); }
  catch (error) { notice(error.message, true); }
  finally { busy(false); }
});
$('run-button').addEventListener('click', async () => {
  if (state.busy || !state.user) return;
  busy(true); notice('Running analysis and source audit...');
  try {
    const result = await post('/api/analysis', { task: state.task,
      document_ids: state.documents.filter((doc) => doc.status === 'ok').map((doc) => doc.document_id),
      requirements: requirements() });
    state.result = result; renderResult(); await refreshRuns();
    notice(`Analysis complete. Automated audit: ${result.audit.status}. Human review is ${result.review.status}.`);
    $('analysis-result').scrollIntoView({ block: 'start' });
  } catch (error) { notice(error.message, true); }
  finally { busy(false); }
});
$('refresh-runs-button').addEventListener('click', async () => {
  busy(true);
  try { await refreshRuns(); notice('Accessible run list refreshed.'); }
  catch (error) { notice(error.message, true); }
  finally { busy(false); }
});
$('analysis-history').addEventListener('change', () => busy(state.busy));
$('load-run-button').addEventListener('click', async () => {
  busy(true);
  try {
    const result = await request(`/api/analysis/${$('analysis-history').value}`);
    const sources = await Promise.all(result.document_ids.map((id) => request(`/api/documents/${id}`)));
    state.documents = sources.map((item) => item.document); state.selected = 0; state.start = null; state.end = null;
    state.result = result; render(); renderResult(); notice('Saved result and its authorized source documents loaded.');
    $('analysis-result').scrollIntoView({ block: 'start' });
  } catch (error) { notice(error.message, true); }
  finally { busy(false); }
});
for (const decision of ['approve', 'reject']) $(`${decision}-button`).addEventListener('click', async () => {
  if (!state.result || state.busy) return;
  const comment = $('review-comment').value.trim();
  if (!comment) return notice('Enter a review note before approving or rejecting.', true);
  busy(true);
  try {
    state.result = await post(`/api/analysis/${state.result.analysis_id}/review`, { decision, comment });
    renderResult(); await refreshRuns(); notice(`Human review recorded: ${state.result.review.status}.`);
  } catch (error) { notice(error.message, true); }
  finally { busy(false); }
});
$('trail-button').addEventListener('click', async () => {
  if (!state.result) return;
  try {
    const payload = await request(`/api/analysis/${state.result.analysis_id}/audit`);
    $('audit-trail').textContent = JSON.stringify(payload.events, null, 2); $('audit-trail').hidden = false;
  } catch (error) { notice(error.message, true); }
});
$('result-download').addEventListener('click', () => { if (state.result) download(`${state.result.analysis_id}.json`, state.result); });
async function restoreSession() {
  try { setUser((await request('/api/session')).user); if (state.user) await refreshRuns(); }
  catch (error) { notice(error.message, true); }
}
render();
async function initialize() {
  await checkConnection();
  await restoreSession();
  initializing = false;
  busy(false);
}
initialize();
