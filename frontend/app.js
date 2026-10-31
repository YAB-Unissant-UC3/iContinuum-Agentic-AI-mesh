'use strict';

const $ = (id) => document.getElementById(id);
const state = { documents: [], selected: -1, view: 'source', start: null, end: null, task: 'brief', busy: false };
const limits = { max_files: 12, max_file_bytes: 256 * 1024, max_total_bytes: 2 * 1024 * 1024 };

function notice(message, error = false) {
  $('notice').textContent = message;
  $('notice').classList.toggle('error', error);
  $('notice').hidden = !message;
}

async function request(path, options) {
  const response = await fetch(path, options);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error?.message || 'The request could not be completed.');
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
  for (const id of ['browse-button', 'demo-button', 'file-input']) $(id).disabled = value;
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
  const description = $('viewer-empty').querySelector('p');
  title.textContent = source?.status === 'error' ? 'This document could not be read.' : source?.status === 'empty' ? 'This document is empty.' : 'A clear view of the original.';
  description.textContent = source?.error?.message || (source?.status === 'empty' ? 'The file has a stable ID, but contains no source lines.' : 'Add a document or load the examples to explore its text and numbered source lines.');
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
    const label = source.status === 'error' ? 'Could not read file' : source.status === 'empty' ? 'Empty file' : `${source.line_count} lines · Source preserved`;
    info.append(element('span', 'document-name', source.file_name), element('span', `document-subtitle${source.status === 'error' ? ' has-error' : ''}`, label));
    select.append(element('span', 'file-symbol', '▤'), info);
    select.addEventListener('click', () => { state.selected = index; state.start = null; state.end = null; render(); });
    const remove = element('button', 'remove-document', '×');
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
}

function base64(bytes) {
  let binary = '';
  for (let offset = 0; offset < bytes.length; offset += 8192) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
  }
  return btoa(binary);
}

async function uploadFiles(fileList) {
  if (state.busy || !fileList.length) return;
  const files = Array.from(fileList);
  if (files.length + state.documents.length > limits.max_files) return notice('Keep up to 12 documents in the workspace. Remove a document before adding more.', true);
  if (files.some((file) => !file.name.toLowerCase().endsWith('.txt'))) return notice('Choose .txt files saved as UTF-8.', true);
  if (files.some((file) => file.size > limits.max_file_bytes)) return notice('Each file must be 256 KiB or smaller.', true);
  if (files.reduce((sum, file) => sum + file.size, 0) > limits.max_total_bytes) return notice('Upload up to 2 MiB of text at a time.', true);
  busy(true);
  notice('Reading your documents…');
  try {
    const uploads = await Promise.all(files.map(async (file) => ({ file_name: file.name, content_base64: base64(new Uint8Array(await file.arrayBuffer())) })));
    const payload = await request('/api/documents', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ files: uploads }) });
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
  if (state.documents.length > limits.max_files - 3) return notice('Make room for three example documents first.', true);
  busy(true); notice('Loading the fictional examples…');
  try { addDocuments((await request('/api/demo')).documents); }
  catch (error) { notice(`Could not load examples. ${error.message}`, true); }
  finally { busy(false); }
});
$('clear-button').addEventListener('click', () => {
  state.documents = []; state.selected = -1; state.start = null; state.end = null;
  render(); notice('Workspace cleared. Original files are unchanged.');
});
for (const view of ['source', 'json']) $(`${view}-tab`).addEventListener('click', () => { state.view = view; renderViewer(); });
$('copy-button').addEventListener('click', async () => {
  const reference = citation();
  if (!reference) return;
  try { await navigator.clipboard.writeText(JSON.stringify(reference, null, 2)); notice('Citation copied. It identifies source lines; claim verification is still pending.'); }
  catch { notice(`Clipboard unavailable. Copy this reference: ${JSON.stringify(reference)}`); }
});
$('export-button').addEventListener('click', () => download('icontinuum-documents.json', { api_version: '1.0', documents: state.documents }));
$('request-button').addEventListener('click', () => download('icontinuum-analysis-request.json', {
  api_version: '1.0', task: state.task, documents: state.documents.filter((item) => item.status === 'ok'),
}));
for (const task of ['brief', 'requirements']) $(`${task}-task`).addEventListener('click', () => {
  state.task = task;
  $('brief-task').setAttribute('aria-pressed', String(task === 'brief'));
  $('requirements-task').setAttribute('aria-pressed', String(task === 'requirements'));
  $('task-description').textContent = task === 'brief' ? 'Prepare the source documents for a cited brief.' : 'Prepare the source documents for requirements review.';
});
async function checkConnection() {
  try {
    const health = await request('/api/health');
    Object.assign(limits, health.limits);
    $('connection-label').textContent = 'Reader connected';
    $('reader-status').textContent = 'Connected · Local';
  } catch {
    $('connection-label').textContent = 'API unavailable';
    $('connection-dot').classList.add('offline');
    $('reader-status').textContent = 'Connection unavailable';
    notice('Cannot reach the local API. Start python -m backend, then refresh this page.', true);
  }
}
render();
checkConnection();
