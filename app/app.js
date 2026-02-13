const photoInput = document.getElementById('photoInput');
const uploadList = document.getElementById('uploadList');
const template = document.getElementById('uploadItemTemplate');
const submitBtn = document.getElementById('submitBtn');
const statusBox = document.getElementById('status');
const plans = document.getElementById('plans');
const preset = document.getElementById('preset');
const background = document.getElementById('background');
const outfit = document.getElementById('outfit');
const teamSizeInput = document.getElementById('teamSize');
const previewGrid = document.getElementById('previewGrid');
const jobList = document.getElementById('jobList');
const orderList = document.getElementById('orderList');
const selectedPlanSummary = document.getElementById('selectedPlanSummary');
const privacySummary = document.getElementById('privacySummary');
const supportForm = document.getElementById('supportForm');
const supportEmail = document.getElementById('supportEmail');
const supportOrderId = document.getElementById('supportOrderId');
const supportMessage = document.getElementById('supportMessage');
const metricsBox = document.getElementById('metrics');

let selectedPlan = 'basic';
let packageCatalog = {};
let pollingId = null;

function assessQuality(file) {
  if (file.size > 8 * 1024 * 1024) return 'Too large (>8MB)';
  if (!/image\/(png|jpeg|heic|heif)/i.test(file.type)) return 'Unsupported format';
  return 'Looks good';
}
const formatUsd = (cents) => `$${(cents / 100).toFixed(0)}`;
const calculateEstimate = (cents, teamSize) => (teamSize <= 1 ? cents : Math.floor(cents * teamSize * 0.9));

function teamSizeValue() {
  const teamSize = Number.parseInt(teamSizeInput.value, 10);
  return Number.isNaN(teamSize) ? 1 : Math.max(1, Math.min(50, teamSize));
}

function setStatus(message, mode = 'idle') {
  statusBox.className = `status ${mode}`;
  statusBox.textContent = message;
}

function updateSelectedPlanSummary() {
  const pkg = packageCatalog[selectedPlan];
  if (!pkg) return;
  const teamSize = teamSizeValue();
  const total = calculateEstimate(pkg.priceCents, teamSize);
  selectedPlanSummary.textContent = `Selected package: ${pkg.name} (${formatUsd(total)}) • team ${teamSize} • ${pkg.headshotCount} headshots each`;
}

function buildActionButton(label, onClick) {
  const button = document.createElement('button');
  button.className = 'secondary mini';
  button.textContent = label;
  button.type = 'button';
  button.addEventListener('click', onClick);
  return button;
}

function renderMetrics(metrics) {
  metricsBox.innerHTML = `<h2>Dashboard metrics</h2>
  <div class="metric-grid">
    <div><strong>${metrics.orders}</strong><small>Orders</small></div>
    <div><strong>${metrics.jobs}</strong><small>Jobs</small></div>
    <div><strong>${metrics.completedJobs}</strong><small>Completed</small></div>
    <div><strong>${metrics.supportTickets}</strong><small>Support tickets</small></div>
  </div>`;
}

function renderBrandingPreviews(previews) {
  previewGrid.innerHTML = '';
  previews.forEach((preview) => {
    const card = document.createElement('div');
    card.className = 'preview-card';
    card.innerHTML = `<strong>${preview.label}</strong><small>${preview.width}×${preview.height}</small><div class="preview-avatar"></div>`;
    previewGrid.appendChild(card);
  });
}

function renderRecentOrders(orders) {
  orderList.innerHTML = '';
  if (!orders.length) return (orderList.innerHTML = '<li class="order-item">No orders yet.</li>');
  orders.forEach((order) => {
    const item = document.createElement('li');
    item.className = 'order-item';
    const details = document.createElement('div');
    details.innerHTML = `<strong>#${order.id}</strong> · ${order.plan}<br /><small>${formatUsd(order.amountCents)} · team ${order.teamSize} · rerun credits ${order.rerunCredits}</small>`;
    const controls = document.createElement('div');
    controls.className = 'item-controls';
    controls.append(buildActionButton('Delete', async () => {
      const response = await fetch(`/api/orders/${order.id}`, { method: 'DELETE' });
      if (!response.ok) return setStatus(`Failed to delete order #${order.id}.`, 'idle');
      setStatus(`Order #${order.id} deleted.`, 'done');
      refreshAll();
    }));
    item.append(details, controls);
    orderList.appendChild(item);
  });
}

async function showAssets(jobId) {
  const response = await fetch(`/api/jobs/${jobId}/assets`);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) return setStatus(body.error || 'Assets unavailable yet.', 'idle');
  const links = body.assets.map((a) => `<a href="${a.downloadUrl}" target="_blank">${a.variant}</a>`).join(' · ');
  setStatus(`Job #${jobId} assets: ${links}`, 'done');
}

function renderRecentJobs(jobs) {
  jobList.innerHTML = '';
  if (!jobs.length) return (jobList.innerHTML = '<li class="job-item">No jobs yet. Submit your first generation.</li>');
  jobs.forEach((job) => {
    const item = document.createElement('li');
    item.className = 'job-item';
    const details = document.createElement('div');
    const rerunNote = job.sourceJobId ? ` · rerun of #${job.sourceJobId}` : '';
    details.innerHTML = `<strong>#${job.id} · ${job.plan}</strong><br /><small>Order #${job.orderId}${rerunNote} · ${job.style}/${job.background}/${job.outfit}</small>`;
    const controls = document.createElement('div');
    controls.className = 'item-controls';
    const chip = document.createElement('span'); chip.className = `chip ${job.status}`; chip.textContent = job.status;
    controls.append(
      chip,
      buildActionButton('Assets', () => showAssets(job.id)),
      buildActionButton('Rerun', async () => {
        const response = await fetch('/api/rerun', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ jobId: job.id }) });
        const body = await response.json().catch(() => ({}));
        if (!response.ok) return setStatus(`Rerun failed: ${body.error || 'Unknown error'}`, 'idle');
        setStatus(`Rerun started as job #${body.id}.`, 'processing');
        refreshAll(); pollJob(body.id);
      }),
      buildActionButton('Delete', async () => {
        const response = await fetch(`/api/jobs/${job.id}`, { method: 'DELETE' });
        if (!response.ok) return setStatus(`Failed to delete job #${job.id}.`, 'idle');
        setStatus(`Job #${job.id} deleted.`, 'done'); refreshAll();
      })
    );
    item.append(details, controls); jobList.appendChild(item);
  });
}

async function fetchPackages() { const r = await fetch('/api/packages'); if (!r.ok) return; packageCatalog = (await r.json()).packages || {}; updateSelectedPlanSummary(); }
async function fetchBrandingPreviews() { const r = await fetch('/api/branding-previews'); if (!r.ok) return; renderBrandingPreviews((await r.json()).previews || []); }
async function fetchMetrics() { const r = await fetch('/api/metrics'); if (!r.ok) return; renderMetrics(await r.json()); }
async function fetchPrivacy() { const r = await fetch('/api/privacy'); if (!r.ok) return; const d = await r.json(); privacySummary.textContent = `Input retention: ${d.inputRetentionDays} days · Generated outputs: ${d.outputRetentionDays} days`; }
async function fetchRecentOrders() { const r = await fetch('/api/orders'); if (!r.ok) return; renderRecentOrders((await r.json()).orders || []); }
async function fetchRecentJobs() { const r = await fetch('/api/jobs'); if (!r.ok) return; renderRecentJobs((await r.json()).jobs || []); }
async function refreshAll() { await Promise.all([fetchRecentOrders(), fetchRecentJobs(), fetchMetrics()]); }

async function pollJob(jobId) {
  if (pollingId) window.clearInterval(pollingId);
  pollingId = window.setInterval(async () => {
    const response = await fetch(`/api/jobs/${jobId}`);
    if (!response.ok) { setStatus('Unable to fetch job status.', 'idle'); return window.clearInterval(pollingId); }
    const job = await response.json();
    if (job.status !== 'completed') return setStatus(`Job #${job.id} is ${job.status}. ~${job.secondsRemaining}s remaining.`, 'processing');
    setStatus(`Job #${job.id} completed. Assets are now available.`, 'done');
    window.clearInterval(pollingId); refreshAll();
  }, 1800);
}

photoInput.addEventListener('change', () => {
  uploadList.innerHTML = '';
  [...photoInput.files].forEach((file) => {
    const node = template.content.firstElementChild.cloneNode(true);
    node.querySelector('.filename').textContent = file.name;
    node.querySelector('.quality').textContent = assessQuality(file);
    uploadList.appendChild(node);
  });
});
teamSizeInput.addEventListener('input', updateSelectedPlanSummary);
plans.addEventListener('click', (event) => {
  const button = event.target.closest('.plan'); if (!button) return;
  [...plans.querySelectorAll('.plan')].forEach((item) => item.classList.remove('selected'));
  button.classList.add('selected'); selectedPlan = button.dataset.plan; updateSelectedPlanSummary();
});

submitBtn.addEventListener('click', async () => {
  const files = [...photoInput.files];
  if (files.length < 8) return setStatus('Please upload at least 8 selfies to start generation.', 'idle');
  if (files.find((file) => assessQuality(file) !== 'Looks good')) return setStatus('One or more files are invalid.', 'idle');
  const pkg = packageCatalog[selectedPlan];
  if (!pkg) return setStatus('Package data unavailable.', 'idle');

  const teamSize = teamSizeValue();
  const orderResponse = await fetch('/api/orders', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ plan: selectedPlan, teamSize }) });
  const order = await orderResponse.json().catch(() => ({}));
  if (!orderResponse.ok) return setStatus(`Payment failed: ${order.error || 'Unknown error'}`, 'idle');

  const jobResponse = await fetch('/api/jobs', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ orderId: order.id, plan: selectedPlan, style: preset.value, background: background.value, outfit: outfit.value, uploadCount: files.length })
  });
  const job = await jobResponse.json().catch(() => ({}));
  if (!jobResponse.ok) return setStatus(`Job creation failed: ${job.error || 'Unknown error'}`, 'idle');

  setStatus(`Job #${job.id} queued under Order #${order.id}.`, 'processing');
  refreshAll(); pollJob(job.id);
});

supportForm.addEventListener('submit', async (event) => {
  event.preventDefault();
  const payload = { email: supportEmail.value, orderId: supportOrderId.value || null, message: supportMessage.value };
  const response = await fetch('/api/support', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) return setStatus(`Support request failed: ${body.error || 'Unknown error'}`, 'idle');
  setStatus(`Support ticket #${body.id} created.`, 'done'); supportForm.reset(); refreshAll();
});

fetchPrivacy();
fetchPackages();
fetchBrandingPreviews();
refreshAll();
