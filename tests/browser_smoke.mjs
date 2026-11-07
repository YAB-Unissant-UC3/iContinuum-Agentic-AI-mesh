// Optional Windows UI check: Node 22+ and installed Chrome, no npm packages.
// Start python -m backend first. Screenshots/downloads use a temporary folder.
import { spawn } from 'node:child_process';
import { access, mkdtemp, mkdir, readFile, readdir, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';

const origin = process.argv[2] || 'http://127.0.0.1:8000';
const mockedGemini = process.argv.includes('--mock-gemini');
const mockedGroq = process.argv.includes('--mock-groq');
const mockedFallback = process.argv.includes('--mock-fallback');
const mockedAI = (mockedGemini || mockedGroq) && !mockedFallback;
if (!/^http:\/\/(127\.0\.0\.1|localhost):\d+$/.test(origin)) throw new Error('Use a local demo URL.');
const scratch = await mkdtemp(path.join(tmpdir(), 'icontinuum-full-browser-'));
const profile = path.join(scratch, 'profile'), downloads = path.join(scratch, 'downloads');
await mkdir(profile); await mkdir(downloads);
const executable = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
await access(executable);
const chrome = spawn(executable, ['--headless=new', '--disable-gpu', '--no-first-run', '--disable-extensions',
  '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank'], { windowsHide: true, stdio: 'ignore' });
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
let ws, counter = 0;
const pending = new Map(), errors = [];
function send(method, params = {}) {
  const id = ++counter;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`Timeout: ${method}`)); }, 15000);
    pending.set(id, { resolve, reject, timer }); ws.send(JSON.stringify({ id, method, params }));
  });
}
async function evaluate(expression) {
  const response = await send('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true, userGesture: true });
  if (response.exceptionDetails) throw new Error(JSON.stringify(response.exceptionDetails));
  return response.result.value;
}
async function waitFor(expression) {
  for (let attempt = 0; attempt < 100; attempt++) { if (await evaluate(expression)) return; await pause(100); }
  console.log('UI diagnostics:', await evaluate(`({notice:document.getElementById('notice')?.textContent, user:state.user, busy:state.busy, signedIn:document.getElementById('signed-in-user')?.textContent})`));
  console.log('Browser exceptions:', JSON.stringify(errors));
  await screenshot('failure.png');
  throw new Error(`Condition failed: ${expression}`);
}
async function click(id) {
  assert.ok(await evaluate(`document.getElementById(${JSON.stringify(id)}).checkVisibility()`), `Control is hidden: ${id}`);
  await evaluate(`document.getElementById(${JSON.stringify(id)}).click()`);
}
async function openDetails(id) {
  await evaluate(`(() => {
    const details = document.getElementById(${JSON.stringify(id)});
    if (!details.open) details.querySelector('summary').click();
  })()`);
}
async function assertIdentity(name) {
  const identity = await evaluate(`({
    role: state.user?.role, label: document.getElementById('signed-in-user').textContent,
    username: document.getElementById('session-username').textContent,
    visible: !document.getElementById('session-identity').hidden,
    analyst: getComputedStyle(document.getElementById('analyst-icon')).display !== 'none',
    manager: getComputedStyle(document.getElementById('manager-icon')).display !== 'none',
    signout: !document.getElementById('logout-button').hidden,
    signoutName: document.getElementById('logout-button').getAttribute('aria-label')
  })`);
  assert.equal(identity.role, name);
  assert.equal(identity.label, name === 'manager' ? 'Manager' : 'Analyst');
  assert.equal(identity.username, name);
  assert.equal(identity.visible, true);
  assert.equal(identity.analyst, name === 'analyst');
  assert.equal(identity.manager, name === 'manager');
  assert.equal(identity.signout, true);
  assert.match(identity.signoutName, /sign out/i);
}
async function assertMobileIdentity(name) {
  for (const width of [390, 320, 768]) {
    await send('Emulation.setDeviceMetricsOverride', { width, height: 844, deviceScaleFactor: 1, mobile: true });
    await evaluate('window.scrollTo(0, document.body.scrollHeight)');
    await assertIdentity(name);
    assert.ok(await evaluate('document.documentElement.scrollWidth <= window.innerWidth'), `Page overflow at ${width}px`);
    assert.ok(await evaluate(`(() => {
      const box = document.getElementById('session-identity').getBoundingClientRect();
      return box.left >= 0 && box.right <= innerWidth && box.top >= 0 && box.bottom <= innerHeight;
    })()`), `Session identity not visible at ${width}px`);
  }
}
async function login(name, password) {
  await evaluate(`document.getElementById('username').value=${JSON.stringify(name)}; document.getElementById('password').value=${JSON.stringify(password)}; document.getElementById('login-form').requestSubmit()`);
  await waitFor(`state.user?.role === '${name}' && !state.busy`);
  await assertIdentity(name);
  assert.equal(await evaluate(`document.getElementById('workspace').hidden`), false);
  assert.equal(await evaluate(`document.getElementById('session-panel').hidden`), true);
  assert.equal(await evaluate(`document.getElementById('run-button').disabled`), true);
  assert.match(await evaluate(`document.getElementById('analysis-hint').textContent`), /Add documents/);
  assert.equal(await evaluate(`document.getElementById('manager-nav').hidden`), true);
}
async function run(task) {
  await click(`${task}-task`);
  const previous = await evaluate('state.result?.analysis_id');
  await click('run-button');
  await waitFor(`Boolean(state.result && state.result.analysis_id !== ${JSON.stringify(previous || null)} && !state.busy)`);
  assert.equal(await evaluate('state.result.audit.status'), mockedAI && task === 'brief' ? 'needs_review' : 'passed');
  if (mockedAI && task === 'brief') {
    assert.equal(await evaluate('state.result.mode'), mockedGroq ? 'groq' : 'gemini');
    assert.equal(await evaluate('state.result.provider'), mockedGroq ? 'groq' : 'gemini');
  }
  assert.equal(await evaluate(`document.getElementById('result-kind').dataset.generation`), mockedAI && task === 'brief' ? 'ai' : 'deterministic');
  assert.match(await evaluate(`document.getElementById('result-kind').textContent`), mockedAI && task === 'brief' ? /AI-generated draft/ : /Demo mode/);
  if (!mockedAI || task !== 'brief') assert.match(await evaluate(`document.getElementById('result-mode-explanation').textContent`), /document extracts/);
  if (mockedFallback && task === 'brief') {
    assert.equal(await evaluate('state.result.fallback_reason'), 'provider_unavailable');
    assert.match(await evaluate(`document.getElementById('result-kind').textContent`), /AI not used/);
  }
  await assertIdentity(await evaluate('state.user.role'));
  return evaluate('state.result.analysis_id');
}
async function upload(files) {
  const { root } = await send('DOM.getDocument');
  const { nodeId } = await send('DOM.querySelector', { nodeId: root.nodeId, selector: '#file-input' });
  await send('DOM.setFileInputFiles', { nodeId, files });
  await waitFor('!state.busy');
}
async function screenshot(name, fullPage = true) {
  const { data } = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: fullPage });
  const filename = path.join(scratch, name); await writeFile(filename, Buffer.from(data, 'base64')); console.log(filename);
}
async function downloaded(prefix) {
  for (let attempt = 0; attempt < 60; attempt++) {
    for (const filename of await readdir(downloads)) if (filename.startsWith(prefix) && filename.endsWith('.json')) {
      return JSON.parse(await readFile(path.join(downloads, filename), 'utf8'));
    }
    await pause(100);
  }
  throw new Error(`Missing download: ${prefix}`);
}
try {
  let port;
  for (let attempt = 0; attempt < 100; attempt++) {
    try { port = (await readFile(path.join(profile, 'DevToolsActivePort'), 'utf8')).split('\n')[0]; break; }
    catch { await pause(100); }
  }
  if (!port) throw new Error('Chrome did not start.');
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  ws = new WebSocket(targets.find((target) => target.type === 'page').webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { ws.addEventListener('open', resolve, { once: true }); ws.addEventListener('error', reject, { once: true }); });
  ws.addEventListener('message', ({ data }) => {
    const message = JSON.parse(data), handler = pending.get(message.id);
    if (handler) { pending.delete(message.id); clearTimeout(handler.timer); message.error ? handler.reject(new Error(JSON.stringify(message.error))) : handler.resolve(message.result); }
    if (message.method === 'Runtime.exceptionThrown') errors.push(message.params);
  });
  await send('Page.enable'); await send('Runtime.enable');
  await send('Emulation.setFocusEmulationEnabled', { enabled: true });
  await send('Browser.grantPermissions', { permissions: ['clipboardReadWrite', 'clipboardSanitizedWrite'], origin });
  await send('Browser.setDownloadBehavior', { behavior: 'allow', downloadPath: downloads });
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });
  await send('Page.navigate', { url: origin });
  await waitFor(`document.getElementById('connection-label')?.textContent === 'System ready' && !document.getElementById('login-button').disabled`);
  assert.ok(await evaluate(`document.fonts.ready.then(() => ['DM Serif Display', 'Manrope'].every(
    family => Array.from(document.fonts).some(font => font.family.replace(/["']/g, '') === family && font.status === 'loaded')))`), 'Local editorial fonts did not load');
  assert.ok(await evaluate(`performance.getEntriesByType('resource').every(resource => new URL(resource.name).origin === location.origin)`), 'Workspace must not require external font services');
  assert.equal(await evaluate(`document.getElementById('browse-button').disabled`), true);
  assert.equal(await evaluate(`document.getElementById('workspace').hidden`), true);
  assert.equal(await evaluate(`document.getElementById('workspace-sidebar').hidden`), true);
  assert.equal(await evaluate(`document.getElementById('login-heading').textContent`), 'Sign in');
  await screenshot('sign-in.png', false);
  await login('analyst', 'AnalystDemo!2026');
  // The authenticated session, rather than a local role selector, survives reload.
  await send('Page.reload');
  await waitFor(`typeof state !== 'undefined' && state.user?.role === 'analyst' && !state.busy && !document.getElementById('login-button').disabled`);
  await assertIdentity('analyst');
  await click('demo-button');
  await waitFor(`document.getElementById('document-count').textContent === '03' && !state.busy`);
  assert.equal(await evaluate(`document.getElementById('line-count').textContent`), '30');
  assert.equal(await evaluate(`document.getElementById('sources').open`), false);
  assert.ok(await evaluate(`['add-heading', 'handoff-heading', 'history-heading'].every(id =>
    document.getElementById(id).getBoundingClientRect().bottom <= innerHeight)`), 'Three steps should fit on the desktop starting view');
  await evaluate('window.scrollTo(0, 0)');
  await screenshot('workspace-desktop.png', false);
  const briefRun = await run('brief');
  assert.ok(await evaluate('state.result.claims.length > 0'));
  await evaluate(`document.querySelector('.result-citation').click()`);
  await waitFor(`document.querySelectorAll('.source-line.selected').length === 1`);
  assert.equal(await evaluate(`document.getElementById('sources').open`), true);
  assert.ok(await evaluate(`document.querySelector('.source-line.selected').checkVisibility()`), 'A citation must open its source preview');
  await click('copy-button');
  await waitFor(`document.getElementById('notice').textContent.includes('Citation copied')`);
  assert.match(JSON.parse(await evaluate('navigator.clipboard.readText()')).document_id, /^doc_[a-f0-9]{64}$/);
  const requirementsRun = await run('requirements');
  assert.deepEqual(await evaluate('state.result.contradictions[0].citations.map(c => c.line_start)'), [9, 8]);
  assert.equal(await evaluate('state.result.requirement_checks[1].status'), 'unclear');
  await click('export-button'); assert.equal((await downloaded('icontinuum-documents')).documents.length, 3);
  await openDetails('sources');
  await click('json-tab');
  assert.ok(await evaluate(`document.getElementById('json-preview').checkVisibility()`));
  await click('source-tab');
  await openDetails('analysis-options');
  await click('request-button'); assert.equal((await downloaded('icontinuum-analysis-request')).task, 'requirements');
  await click('result-download'); assert.equal((await downloaded(requirementsRun)).audit.status, 'passed');
  await screenshot('analyst-result.png');
  await writeFile(path.join(scratch, 'empty.txt'), '');
  await writeFile(path.join(scratch, 'invalid.txt'), Buffer.from([255]));
  await writeFile(path.join(scratch, 'literal.txt'), '<script>globalThis.injected=true</script>\n');
  await upload([path.join(scratch, 'empty.txt'), path.join(scratch, 'invalid.txt'), path.join(scratch, 'literal.txt')]);
  await waitFor(`document.getElementById('document-count').textContent === '06'`);
  await evaluate(`Array.from(document.querySelectorAll('.document-select')).find(b => b.textContent.includes('literal.txt')).click()`);
  assert.equal(await evaluate(`document.querySelectorAll('#source-lines script').length`), 0);
  assert.ok(await evaluate(`globalThis.injected === undefined`));
  await click('logout-button'); await waitFor('!state.user && !state.busy');
  assert.equal(await evaluate('state.documents.length'), 0);
  assert.equal(await evaluate(`document.getElementById('result-content').textContent`), '');
  assert.equal(await evaluate(`document.getElementById('session-identity').hidden`), true);
  assert.equal(await evaluate(`document.getElementById('session-username').textContent`), '');
  assert.equal(await evaluate(`document.getElementById('workspace').hidden`), true);
  assert.equal(await evaluate(`document.getElementById('workspace-sidebar').hidden`), true);
  await login('manager', 'ManagerDemo!2026');
  const reviewRun = mockedAI ? briefRun : requirementsRun;
  await openDetails('saved-results');
  await evaluate(`document.getElementById('analysis-history').value=${JSON.stringify(reviewRun)}; document.getElementById('analysis-history').dispatchEvent(new Event('change'))`);
  await click('load-run-button'); await waitFor(`state.result?.analysis_id === '${reviewRun}' && !state.busy`);
  assert.equal(await evaluate(`document.getElementById('manager-review').hidden`), false);
  assert.equal(await evaluate(`document.getElementById('manager-nav').hidden`), false);
  await click('manager-nav');
  await evaluate(`document.getElementById('review-comment').value='Reviewed the retention conflict; escalation recorded.'`);
  await click('approve-button'); await waitFor(`state.result.review.status === 'approved' && !state.busy`);
  assert.equal(await evaluate('state.result.audit.status'), mockedAI ? 'needs_review' : 'passed');
  await click('trail-button'); await waitFor(`!document.getElementById('audit-trail').hidden`);
  assert.equal(await evaluate(`document.getElementById('trail-button').textContent`), 'Hide audit trail');
  assert.equal(await evaluate(`document.getElementById('trail-button').getAttribute('aria-expanded')`), 'true');
  assert.equal(JSON.parse(await evaluate(`document.getElementById('audit-trail').textContent`)).at(-1).role, 'manager');
  await click('trail-button');
  assert.equal(await evaluate(`document.getElementById('audit-trail').hidden`), true);
  assert.equal(await evaluate(`document.getElementById('trail-button').textContent`), 'Show audit trail');
  assert.equal(await evaluate(`document.getElementById('trail-button').getAttribute('aria-expanded')`), 'false');
  await click('trail-button'); await waitFor(`!document.getElementById('audit-trail').hidden`);
  await evaluate(`document.getElementById('review-comment').value='Rejected pending reconciliation of retention periods.'`);
  await click('reject-button'); await waitFor(`state.result.review.status === 'rejected' && !state.busy`);
  assert.equal(await evaluate(`document.getElementById('audit-trail').hidden`), true);
  assert.equal(await evaluate(`document.getElementById('trail-button').textContent`), 'Show audit trail');
  await screenshot('manager-review.png');
  await assertMobileIdentity('manager');
  await send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 1, mobile: true });
  await evaluate('window.scrollTo(0, document.body.scrollHeight)');
  await screenshot('manager-mobile.png', false);
  await send('Emulation.setDeviceMetricsOverride', { width: 1440, height: 1100, deviceScaleFactor: 1, mobile: false });
  await openDetails('sources');
  await click('clear-button'); await click('demo-button'); await waitFor('state.documents.length === 4 && !state.busy');
  const restrictedId = await evaluate(`state.documents.find(d => d.access === 'restricted').document_id`);
  await openDetails('sources');
  await evaluate(`for (let i=0;i<3;i++) document.querySelector('.remove-document').click()`);
  const restrictedRun = await run('brief');
  assert.ok(await evaluate(`JSON.stringify(state.result).includes('CEDAR-DEMO-742')`));
  await click('logout-button'); await waitFor('!state.user && !state.busy');
  assert.equal(await evaluate(`document.body.textContent.includes('CEDAR-DEMO-742')`), false);
  await login('analyst', 'AnalystDemo!2026');
  for (const route of [`/api/documents/${restrictedId}`, `/api/analysis/${restrictedRun}`, `/api/analysis/${restrictedRun}/audit`]) {
    const denied = await evaluate(`fetch(${JSON.stringify(route)}).then(async r => ({status:r.status,body:await r.text()}))`);
    assert.equal(denied.status, 403); assert.ok(!denied.body.includes('CEDAR-DEMO-742'));
  }
  await assertMobileIdentity('analyst');
  await screenshot('narrow-layout.png');
  await upload([path.join(scratch, 'empty.txt')]);
  assert.equal(await evaluate(`document.getElementById('run-button').disabled`), true);
  assert.match(await evaluate(`document.getElementById('analysis-hint').textContent`), /No readable text/);
  assert.deepEqual(errors, []);
  console.log('PASS: login, examples, uploads, extracts, conflicts, source links, clipboard, downloads, audit trail, Manager approve/reject, logout clearing, direct restricted API denial, and responsive layouts.');
} finally {
  if (ws?.readyState === WebSocket.OPEN) { await send('Browser.close').catch(() => {}); ws.close(); }
  for (const handler of pending.values()) clearTimeout(handler.timer);
  chrome.kill();
}
