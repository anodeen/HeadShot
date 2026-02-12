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

let selectedPlan = 'basic';
let packageCatalog = {};
let pollingId = null;

function assessQuality(file) {
  if (file.size > 8 * 1024 * 1024) return 'Too large (>8MB)';
  if (!/image\/(png|jpeg|heic|heif)/i.test(file.type)) return 'Unsupported format';
  return 'Looks good';
}

function formatUsd(cents) {
  return `$${(cents / 100).toFixed(0)}`;
}

function calculateEstimate(cents, teamSize) {
  if (teamSize <= 1) return cents;
  return Math.floor(cents * teamSize * 0.9);
}

function teamSizeValue() {
  const teamSize = Number.parseInt(teamSizeInput.value, 10);
  if (Number.isNaN(teamSize)) return 1;
  return Math.max(1, Math.min(50, teamSize));
}

function setStatus(message, mode = 'idle') {
  statusBox.className = `status ${mode}`;
  statusBox.textContent = message;
}

function updateSelectedPlanSummary() {
  const pkg = packageCatalog[selectedPlan];
  if (!pkg) {
    selectedPlanSummary.textContent = 'Selected package: loading...';
    return;
  }

  const teamSize = teamSizeValue();
  const total = calculateEstimate(pkg.priceCents, teamSize);
  const teamLabel = teamSize > 1 ? ` · team of ${teamSize} (10% bundle discount)` : '';

  selectedPlanSummary.textContent = `Selected package: ${pkg.name} (${formatUsd(total)})${teamLabel} • ${pkg.headshotCount} headshots each • ${pkg.delivery}`;
}

function buildDeleteButton(onDelete) {
  const button = document.createElement('button');
  button.className = 'secondary mini';
  button.textContent = 'Delete';
  button.type = 'button';
  button.addEventListener('click', onDelete);
  return button;
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
  if (!orders.length) {
    const item = document.createElement('li');
    item.className = 'order-item';
    item.textContent = 'No orders yet.';
    orderList.appendChild(item);
    return;
  }

  orders.forEach((order) => {
    const item = document.createElement('li');
    item.className = 'order-item';

    const details = document.createElement('div');
    details.innerHTML = `<strong>#${order.id}</strong> · ${order.plan}<br /><small>${formatUsd(order.amountCents)} · team size ${order.teamSize} · ${order.paymentStatus}</small>`;

    const controls = document.createElement('div');
    controls.className = 'item-controls';
    controls.append(
      buildDeleteButton(async () => {
        const response = await fetch(`/api/orders/${order.id}`, { method: 'DELETE' });
        if (!response.ok) {
          setStatus(`Failed to delete order #${order.id}.`, 'idle');
          return;
        }
        setStatus(`Order #${order.id} and related jobs deleted.`, 'done');
        fetchRecentOrders();
        fetchRecentJobs();
      })
    );

    item.append(details, controls);
    orderList.appendChild(item);
  });
}

function renderRecentJobs(jobs) {
  jobList.innerHTML = '';

  if (!jobs.length) {
    const item = document.createElement('li');
    item.className = 'job-item';
    item.textContent = 'No jobs yet. Submit your first generation.';
    jobList.appendChild(item);
    return;
  }

  jobs.forEach((job) => {
    const item = document.createElement('li');
    item.className = 'job-item';

    const details = document.createElement('div');
    details.innerHTML = `<strong>#${job.id} · ${job.plan}</strong><br /><small>Order #${job.orderId ?? '-'} · ${job.style}/${job.background}/${job.outfit} · ${job.uploadCount} uploads</small>`;

    const controls = document.createElement('div');
    controls.className = 'item-controls';

    const chip = document.createElement('span');
    chip.className = `chip ${job.status}`;
    chip.textContent = job.status;

    const deleteButton = buildDeleteButton(async () => {
      const response = await fetch(`/api/jobs/${job.id}`, { method: 'DELETE' });
      if (!response.ok) {
        setStatus(`Failed to delete job #${job.id}.`, 'idle');
        return;
      }
      setStatus(`Job #${job.id} deleted.`, 'done');
      fetchRecentJobs();
    });

    controls.append(chip, deleteButton);
    item.append(details, controls);
    jobList.appendChild(item);
  });
}

async function fetchPackages() {
  const response = await fetch('/api/packages');
  if (!response.ok) return;
  const data = await response.json();
  packageCatalog = data.packages || {};
  updateSelectedPlanSummary();
}

async function fetchBrandingPreviews() {
  const response = await fetch('/api/branding-previews');
  if (!response.ok) return;
  const data = await response.json();
  renderBrandingPreviews(data.previews || []);
}

async function fetchPrivacy() {
  const response = await fetch('/api/privacy');
  if (!response.ok) return;
  const data = await response.json();
  privacySummary.textContent = `Input retention: ${data.inputRetentionDays} days · Generated outputs: ${data.outputRetentionDays} days`;
}

async function fetchRecentOrders() {
  const response = await fetch('/api/orders');
  if (!response.ok) return;
  const data = await response.json();
  renderRecentOrders(data.orders || []);
}

async function fetchRecentJobs() {
  const response = await fetch('/api/jobs');
  if (!response.ok) return;
  const data = await response.json();
  renderRecentJobs(data.jobs || []);
}

async function pollJob(jobId) {
  if (pollingId) {
    window.clearInterval(pollingId);
  }

  pollingId = window.setInterval(async () => {
    const response = await fetch(`/api/jobs/${jobId}`);
    if (!response.ok) {
      setStatus('Unable to fetch job status.', 'idle');
      window.clearInterval(pollingId);
      return;
    }

    const job = await response.json();
    if (job.status === 'queued' || job.status === 'processing') {
      setStatus(`Job #${job.id} is ${job.status}. ~${job.secondsRemaining}s remaining.`, 'processing');
      return;
    }

    setStatus(`Job #${job.id} completed. Your headshots are ready to preview and download.`, 'done');
    window.clearInterval(pollingId);
    fetchRecentJobs();
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
  const button = event.target.closest('.plan');
  if (!button) return;

  [...plans.querySelectorAll('.plan')].forEach((item) => item.classList.remove('selected'));
  button.classList.add('selected');

  selectedPlan = button.dataset.plan;
  updateSelectedPlanSummary();
});

submitBtn.addEventListener('click', async () => {
  const files = [...photoInput.files];
  if (files.length < 8) {
    setStatus('Please upload at least 8 selfies to start generation.', 'idle');
    return;
  }

  const invalidFile = files.find((file) => assessQuality(file) !== 'Looks good');
  if (invalidFile) {
    setStatus('One or more files are invalid. Fix upload issues before submitting.', 'idle');
    return;
  }

  const pkg = packageCatalog[selectedPlan];
  if (!pkg) {
    setStatus('Package data is unavailable. Refresh and try again.', 'idle');
    return;
  }

  const teamSize = teamSizeValue();
  const estimatedTotal = calculateEstimate(pkg.priceCents, teamSize);

  setStatus(`Processing payment for ${pkg.name} (${formatUsd(estimatedTotal)})...`, 'processing');

  const orderResponse = await fetch('/api/orders', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ plan: selectedPlan, teamSize })
  });

  if (!orderResponse.ok) {
    const error = await orderResponse.json().catch(() => ({ error: 'Unknown error' }));
    setStatus(`Payment failed: ${error.error}`, 'idle');
    return;
  }

  const order = await orderResponse.json();

  setStatus(`Payment captured (Order #${order.id}, team size ${order.teamSize}). Starting generation...`, 'processing');

  const jobResponse = await fetch('/api/jobs', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      orderId: order.id,
      plan: selectedPlan,
      style: preset.value,
      background: background.value,
      outfit: outfit.value,
      uploadCount: files.length
    })
  });

  if (!jobResponse.ok) {
    const error = await jobResponse.json().catch(() => ({ error: 'Unknown error' }));
    setStatus(`Job creation failed: ${error.error}`, 'idle');
    fetchRecentOrders();
    return;
  }

  const job = await jobResponse.json();
  setStatus(`Job #${job.id} queued under Order #${order.id}. Estimated start in ${job.secondsRemaining}s.`, 'processing');
  fetchRecentOrders();
  fetchRecentJobs();
  pollJob(job.id);
});

fetchPrivacy();
fetchPackages();
fetchBrandingPreviews();
fetchRecentOrders();
fetchRecentJobs();
