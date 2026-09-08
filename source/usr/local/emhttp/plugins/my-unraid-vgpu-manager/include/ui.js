(function () {
  'use strict';
  const root = document.querySelector('.vgpu-manager');
  if (!root) return;
  const page = window.vgpuPage;
  const text = (key, params) => {
    let value = page.labels[key] || key;
    Object.keys(params || {}).forEach(k => { value = value.split('{' + k + '}').join(String(params[k])); });
    return value;
  };
  const message = (value, ok) => {
    const box = document.getElementById('vgpu-message');
    box.textContent = value;
    box.className = 'vgpu-banner ' + (ok ? 'msg' : 'err');
    box.hidden = false;
  };
  const remember = (key, value) => { try { sessionStorage.setItem(key, value); } catch (_) {} };
  const recall = key => { try { return sessionStorage.getItem(key); } catch (_) { return null; } };
  const tabs = Array.from(root.querySelectorAll('[data-tab]'));
  let currentTab = 'tab-drivers';
  function switchTab(id) {
    if (!tabs.some(button => button.dataset.tab === id)) id = 'tab-drivers';
    currentTab = id;
    tabs.forEach(button => {
      const selected = button.dataset.tab === id;
      button.classList.toggle('active', selected);
      button.setAttribute('aria-selected', String(selected));
      button.tabIndex = selected ? 0 : -1;
    });
    root.querySelectorAll('.vgpu-tab-content').forEach(tab => tab.classList.toggle('active', tab.id === id));
    remember('vgpu-tab', id);
    history.replaceState(null, '', location.pathname + location.search + '#' + id);
  }
  tabs.forEach((button, index) => {
    button.addEventListener('click', () => switchTab(button.dataset.tab));
    button.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 :
        (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
      switchTab(tabs[next].dataset.tab);
      tabs[next].focus();
    });
  });
  switchTab(location.hash.slice(1) || recall('vgpu-tab'));
  try {
    const flash = JSON.parse(recall('vgpu-message') || 'null');
    sessionStorage.removeItem('vgpu-message');
    if (flash) message(flash.message, flash.ok);
  } catch (_) {}

  function fillTypes() {
    const select = document.getElementById('add-pci');
    const box = document.getElementById('type-table');
    if (!select || !box) return;
    const types = page.gpuTypes[select.value] || [];
    box.textContent = '';
    if (!types.length) { box.textContent = text('No profiles are available on this GPU.'); return; }
    const table = document.createElement('table');
    table.className = 'vgpu-table vgpu-profiles';
    const head = table.createTHead().insertRow();
    ['', 'Profile', 'Type', 'Framebuffer', 'Displays', 'Max resolution', 'FRL', 'Free'].forEach(label => {
      const cell = document.createElement('th'); cell.textContent = text(label); head.appendChild(cell);
    });
    const body = table.createTBody();
    types.forEach(profile => {
      const row = body.insertRow();
      const radio = document.createElement('input');
      radio.type = 'radio'; radio.name = 'mtype'; radio.value = profile.type;
      radio.disabled = !(Number(profile.avail) > 0);
      radio.setAttribute('aria-label', profile.name || profile.type);
      row.insertCell().appendChild(radio);
      [profile.name, profile.type, profile.fb, profile.heads, profile.res, profile.frl, profile.avail].forEach(value => {
        row.insertCell().textContent = value == null ? '' : String(value);
      });
      row.classList.toggle('vgpu-soldout', radio.disabled);
      const choose = () => {
        if (radio.disabled) return;
        radio.checked = true;
        Array.from(body.rows).forEach(r => r.classList.toggle('vgpu-selected', r === row));
      };
      row.addEventListener('click', choose);
      radio.addEventListener('change', choose);
    });
    box.appendChild(table);
  }
  fillTypes();
  const gpuSelect = document.getElementById('add-pci');
  if (gpuSelect) gpuSelect.addEventListener('change', fillTypes);
  const generate = document.getElementById('generate-uuid');
  if (generate) generate.addEventListener('click', () => {
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
    const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
    document.getElementById('add-uuid').value = [hex.slice(0,8),hex.slice(8,12),hex.slice(12,16),hex.slice(16,20),hex.slice(20)].join('-');
  });

  let submitting = false;
  async function submit(form) {
    if (submitting) return;
    if (form.id === 'vgpu-add-form' && !form.querySelector('input[name="mtype"]:checked')) {
      message(text('Select a profile first.'), false); return;
    }
    if (form.dataset.detachVm && !confirm(text('Detach this vGPU from {vm}? Cold-start the VM to release it.', {vm: form.dataset.detachVm}))) return;
    const data = new FormData(form);
    submitting = true;
    const buttons = Array.from(form.querySelectorAll('button[type="submit"]')).filter(b => !b.disabled);
    buttons.forEach(button => { button.disabled = true; });
    try {
      const response = await fetch(form.action, {method: 'POST', body: data, credentials: 'same-origin'});
      const result = await response.json();
      if (typeof result.ok !== 'boolean' || typeof result.message !== 'string') throw new Error('Invalid response');
      // Mutations use a separate endpoint. Navigation is a fresh GET, so refresh
      // never resubmits an add/remove/attach or repeats a settings change.
      remember('vgpu-message', JSON.stringify(result));
      history.replaceState(null, '', location.pathname + location.search + '#' + currentTab);
      location.reload();
    } catch (_) {
      message(text('The request failed. Refresh the page and check the result before retrying.'), false);
    } finally {
      submitting = false;
      buttons.forEach(button => { button.disabled = false; });
    }
  }
  root.querySelectorAll('form.vgpu-form').forEach(form => form.addEventListener('submit', event => {
    event.preventDefault(); event.stopPropagation(); submit(form);
  }));
  root.querySelectorAll('[data-device-action]').forEach(button => button.addEventListener('click', () => {
    if (button.dataset.deviceAction === 'remove_device' && !confirm(text('Remove this vGPU? Detach it from VMs first.'))) return;
    const form = document.getElementById('vgpu-device-form');
    form.elements.vgpu_action.value = button.dataset.deviceAction;
    form.elements.uuid.value = button.dataset.uuid;
    submit(form);
  }));
  root.querySelectorAll('[data-show-xml]').forEach(button => button.addEventListener('click', () => {
    const row = document.getElementById(button.dataset.showXml); row.hidden = !row.hidden;
  }));
  root.querySelectorAll('[data-copy-xml]').forEach(button => button.addEventListener('click', async () => {
    const xml = document.getElementById(button.dataset.copyXml).textContent;
    try {
      if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(xml);
      else {
        const area = document.createElement('textarea');
        area.value = xml; area.style.position = 'fixed'; area.style.opacity = '0';
        document.body.appendChild(area); area.select();
        const copied = document.execCommand('copy'); area.remove();
        if (!copied) throw new Error('Copy failed');
      }
      message(text('Copied.'), true);
    } catch (_) { message(text('Copy failed. Select and copy the XML manually.'), false); }
  }));

  const operations = {
    install_nvidia: ['Installing NVIDIA driver'],
    update_driver: ['Updating NVIDIA driver'],
    uninstall_nvidia: ['Uninstalling NVIDIA driver', 'Uninstall NVIDIA? Stop GPU VMs and containers first.'],
    restart_services: ['Restarting NVIDIA services', 'Stop GPU workloads before restarting NVIDIA services. Continue?'],
    install_intel: ['Installing Intel driver'],
    update_intel: ['Updating Intel driver'],
    uninstall_intel: ['Uninstalling Intel driver', 'Uninstall Intel i915 SR-IOV? Stop VMs using its VFs first.'],
    prepare_kernel: ['Preparing drivers for the next kernel']
  };
  root.querySelectorAll('[data-command]').forEach(button => button.addEventListener('click', () => {
    const command = button.dataset.command;
    const operation = operations[command];
    if (!operation || (operation[1] && !confirm(text(operation[1])))) return;
    let url = '/plugins/my-unraid-vgpu-manager/include/exec.sh&arg1=' + command;
    if (command === 'install_nvidia') url += '&arg2=' + encodeURIComponent(document.getElementById('nvidia-series-pick').value);
    if (command === 'update_driver') url += '&arg2=' + encodeURIComponent(button.dataset.series) + '&arg3=latest';
    if (command === 'prepare_kernel') {
      const kernel = document.getElementById('target-kernel').value.trim();
      if (kernel && !/^[0-9]+(?:\.[0-9]+){1,2}(?:-[A-Za-z0-9._+]+)*-Unraid$/.test(kernel)) {
        message(text('Enter a full Unraid kernel release, for example 6.18.47-Unraid.'), false); return;
      }
      if (kernel) url += '&arg2=' + encodeURIComponent(kernel);
    }
    openBox(url, text(operation[0]), 600, 900, true);
  }));
}());
