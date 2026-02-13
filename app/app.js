const el = (id) => document.getElementById(id);
const photoInput = el('photoInput');
const uploadList = el('uploadList');
const template = el('uploadItemTemplate');
const submitBtn = el('submitBtn');
const statusBox = el('status');
const plans = el('plans');
const preset = el('preset');
const background = el('background');
const outfit = el('outfit');
const teamSizeInput = el('teamSize');
const previewGrid = el('previewGrid');
const jobList = el('jobList');
const orderList = el('orderList');
const selectedPlanSummary = el('selectedPlanSummary');
const privacySummary = el('privacySummary');
const supportForm = el('supportForm');
const supportEmail = el('supportEmail');
const supportOrderId = el('supportOrderId');
const supportMessage = el('supportMessage');
const metricsBox = el('metrics');
const registerForm = el('registerForm');
const loginForm = el('loginForm');
const logoutBtn = el('logoutBtn');

let selectedPlan = 'basic';
let packageCatalog = {};
let token = localStorage.getItem('headshot_token') || '';
let pollingId = null;

const authHeaders = () => (token ? { Authorization: `Bearer ${token}` } : {});
async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}), ...authHeaders() };
  return fetch(path, { ...opts, headers });
}

function setStatus(message, mode = 'idle') { statusBox.className = `status ${mode}`; statusBox.textContent = message; }
function teamSizeValue() { const n = Number.parseInt(teamSizeInput.value, 10); return Number.isNaN(n) ? 1 : Math.max(1, Math.min(50, n)); }
const formatUsd = (cents) => `$${(cents / 100).toFixed(0)}`;
function assessQuality(file) { if (file.size > 8 * 1024 * 1024) return 'Too large (>8MB)'; if (!/image\/(png|jpeg|heic|heif)/i.test(file.type)) return 'Unsupported format'; return 'Looks good'; }

function updateSelectedPlanSummary() {
  const pkg = packageCatalog[selectedPlan]; if (!pkg) return;
  const team = teamSizeValue(); const total = team <= 1 ? pkg.priceCents : Math.floor(pkg.priceCents * team * 0.9);
  selectedPlanSummary.textContent = `Selected package: ${pkg.name} (${formatUsd(total)}) • team ${team}`;
}
function action(label, fn) { const b = document.createElement('button'); b.className = 'secondary mini'; b.type = 'button'; b.textContent = label; b.onclick = fn; return b; }

function renderMetrics(m) { metricsBox.innerHTML = `<h2>Dashboard metrics</h2><div class="metric-grid"><div><strong>${m.orders}</strong><small>Orders</small></div><div><strong>${m.jobs}</strong><small>Jobs</small></div><div><strong>${m.completedJobs}</strong><small>Completed</small></div><div><strong>${m.supportTickets}</strong><small>Support tickets</small></div></div>`; }
function renderBrandingPreviews(previews) { previewGrid.innerHTML = ''; previews.forEach((p) => { const c = document.createElement('div'); c.className = 'preview-card'; c.innerHTML = `<strong>${p.label}</strong><small>${p.width}×${p.height}</small><div class="preview-avatar"></div>`; previewGrid.appendChild(c); }); }

function renderRecentOrders(orders) {
  orderList.innerHTML = '';
  if (!orders.length) return (orderList.innerHTML = '<li class="order-item">No orders yet.</li>');
  orders.forEach((o) => {
    const li = document.createElement('li'); li.className = 'order-item';
    const d = document.createElement('div'); d.innerHTML = `<strong>#${o.id}</strong> · ${o.plan}<br /><small>${formatUsd(o.amountCents)} · team ${o.teamSize} · rerun credits ${o.rerunCredits}</small>`;
    const c = document.createElement('div'); c.className = 'item-controls';
    c.append(action('Delete', async () => { const r = await api(`/api/orders/${o.id}`, { method: 'DELETE' }); if (!r.ok) return setStatus('Delete order failed', 'idle'); setStatus(`Order #${o.id} deleted.`, 'done'); refreshAll(); }));
    li.append(d, c); orderList.appendChild(li);
  });
}

async function showAssets(jobId) {
  const r = await api(`/api/jobs/${jobId}/assets`); const b = await r.json().catch(() => ({}));
  if (!r.ok) return setStatus(b.error || 'Assets unavailable.', 'idle');
  setStatus(`Assets for #${jobId}: ${b.assets.map((a) => a.variant).join(', ')}`, 'done');
}

function renderRecentJobs(jobs) {
  jobList.innerHTML = '';
  if (!jobs.length) return (jobList.innerHTML = '<li class="job-item">No jobs yet.</li>');
  jobs.forEach((j) => {
    const li = document.createElement('li'); li.className = 'job-item';
    const d = document.createElement('div'); d.innerHTML = `<strong>#${j.id}</strong><br /><small>Order #${j.orderId} · ${j.status}</small>`;
    const c = document.createElement('div'); c.className = 'item-controls';
    const chip = document.createElement('span'); chip.className = `chip ${j.status}`; chip.textContent = j.status;
    c.append(chip,
      action('Assets', () => showAssets(j.id)),
      action('Rerun', async () => { const r = await api('/api/rerun', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ jobId: j.id }) }); const b = await r.json().catch(() => ({})); if (!r.ok) return setStatus(b.error || 'Rerun failed', 'idle'); setStatus(`Rerun started as #${b.id}`, 'processing'); refreshAll(); pollJob(b.id); }),
      action('Delete', async () => { const r = await api(`/api/jobs/${j.id}`, { method: 'DELETE' }); if (!r.ok) return setStatus('Delete job failed', 'idle'); setStatus(`Job #${j.id} deleted`, 'done'); refreshAll(); })
    );
    li.append(d, c); jobList.appendChild(li);
  });
}

async function fetchPackages() { const r = await fetch('/api/packages'); if (!r.ok) return; packageCatalog = (await r.json()).packages || {}; updateSelectedPlanSummary(); }
async function fetchBranding() { const r = await fetch('/api/branding-previews'); if (!r.ok) return; renderBrandingPreviews((await r.json()).previews || []); }
async function fetchPrivacy() { const r = await fetch('/api/privacy'); if (!r.ok) return; const d = await r.json(); privacySummary.textContent = `Input retention: ${d.inputRetentionDays} days · Generated outputs: ${d.outputRetentionDays} days`; }
async function fetchMetrics() { const r = await api('/api/metrics'); if (!r.ok) return; renderMetrics(await r.json()); }
async function fetchOrders() { const r = await api('/api/orders'); if (!r.ok) return; renderRecentOrders((await r.json()).orders || []); }
async function fetchJobs() { const r = await api('/api/jobs'); if (!r.ok) return; renderRecentJobs((await r.json()).jobs || []); }
async function refreshAll() { if (!token) return; await Promise.all([fetchMetrics(), fetchOrders(), fetchJobs()]); }

async function pollJob(jobId) {
  if (pollingId) window.clearInterval(pollingId);
  pollingId = window.setInterval(async () => {
    const r = await api(`/api/jobs/${jobId}`); if (!r.ok) return;
    const j = await r.json(); if (j.status !== 'completed') return setStatus(`Job #${j.id} ${j.status} (~${j.secondsRemaining}s)`, 'processing');
    setStatus(`Job #${j.id} completed.`, 'done'); window.clearInterval(pollingId); refreshAll();
  }, 1800);
}

registerForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const r = await fetch('/api/auth/register', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: el('registerEmail').value, password: el('registerPassword').value }) });
  const b = await r.json().catch(() => ({}));
  setStatus(r.ok ? 'Registration successful. Now log in.' : `Register failed: ${b.error || 'Unknown error'}`, r.ok ? 'done' : 'idle');
});

loginForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const r = await fetch('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: el('loginEmail').value, password: el('loginPassword').value }) });
  const b = await r.json().catch(() => ({}));
  if (!r.ok) return setStatus(`Login failed: ${b.error || 'Unknown error'}`, 'idle');
  token = b.token; localStorage.setItem('headshot_token', token); setStatus(`Logged in as ${b.user.email}`, 'done'); refreshAll();
});

logoutBtn.addEventListener('click', async () => {
  if (token) await api('/api/auth/logout', { method: 'POST' });
  token = ''; localStorage.removeItem('headshot_token');
  setStatus('Logged out.', 'idle'); orderList.innerHTML = ''; jobList.innerHTML = ''; metricsBox.innerHTML = '';
});

photoInput.addEventListener('change', () => {
  uploadList.innerHTML = '';
  [...photoInput.files].forEach((f) => { const n = template.content.firstElementChild.cloneNode(true); n.querySelector('.filename').textContent = f.name; n.querySelector('.quality').textContent = assessQuality(f); uploadList.appendChild(n); });
});
teamSizeInput.addEventListener('input', updateSelectedPlanSummary);
plans.addEventListener('click', (e) => { const b = e.target.closest('.plan'); if (!b) return; [...plans.querySelectorAll('.plan')].forEach((x) => x.classList.remove('selected')); b.classList.add('selected'); selectedPlan = b.dataset.plan; updateSelectedPlanSummary(); });

submitBtn.addEventListener('click', async () => {
  if (!token) return setStatus('Please log in first.', 'idle');
  const files = [...photoInput.files];
  if (files.length < 8) return setStatus('Please upload at least 8 selfies.', 'idle');
  if (files.find((f) => assessQuality(f) !== 'Looks good')) return setStatus('One or more files are invalid.', 'idle');

  const orderResp = await api('/api/orders', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ plan: selectedPlan, teamSize: teamSizeValue() }) });
  const order = await orderResp.json().catch(() => ({}));
  if (!orderResp.ok) return setStatus(`Payment failed: ${order.error || 'Unknown error'}`, 'idle');

  const jobResp = await api('/api/jobs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ orderId: order.id, plan: selectedPlan, style: preset.value, background: background.value, outfit: outfit.value, uploadCount: files.length }) });
  const job = await jobResp.json().catch(() => ({}));
  if (!jobResp.ok) return setStatus(`Job creation failed: ${job.error || 'Unknown error'}`, 'idle');
  setStatus(`Job #${job.id} queued.`, 'processing'); refreshAll(); pollJob(job.id);
});

supportForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  if (!token) return setStatus('Please log in first.', 'idle');
  const r = await api('/api/support', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ email: supportEmail.value, orderId: supportOrderId.value || null, message: supportMessage.value }) });
  const b = await r.json().catch(() => ({}));
  if (!r.ok) return setStatus(`Support failed: ${b.error || 'Unknown error'}`, 'idle');
  setStatus(`Support ticket #${b.id} created.`, 'done'); supportForm.reset(); refreshAll();
});

fetchPrivacy();
fetchPackages();
fetchBranding();
if (token) refreshAll();
