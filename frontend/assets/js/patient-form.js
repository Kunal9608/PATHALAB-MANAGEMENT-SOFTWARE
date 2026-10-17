/**
 * AKRITI — Patient Form Logic
 * Handles: multi-test selection, live total, returning-patient lookup,
 * QR generation, payment mode toggle, form submission.
 *
 * Requires: qrcode.min.js loaded on the page, API, Toast.
 *
 * FIXES:
 *  - Test search: race condition fixed — render() only called after tests loaded
 *  - Test selection: click-away-safe event delegation on container (not per-item)
 *  - QR code: generated client-side immediately from UPI string, no server call
 *  - QR code: amount change triggers fresh QR, old one cleared first
 *  - QR code: debounced so fast typing doesn't spam QR generation
 *  - QR code: re-generated whenever QR mode is active AND amount > 0
 */

const PatientForm = (() => {
  let allTests = [];
  let selectedTests = new Map(); // test_id → { name, price }
  let lookupDebounce = null;
  let qrDebounce = null;
  let labSettingsCache = null;
  let activeRender = null;

  // ── Load tests from API with Stale-While-Revalidate caching ────────────────
  async function loadTests() {
    const cached = localStorage.getItem('akriti_tests_cache');
    if (cached) {
      try {
        allTests = JSON.parse(cached);
      } catch (_) {}
    }
    
    // If no cached tests are available, block and wait for network fetch
    if (!allTests || allTests.length === 0) {
      await revalidateTests().catch(() => {});
    } else {
      revalidateTests().catch(() => {});
    }
    
    return allTests;
  }

  async function revalidateTests() {
    try {
      const res = await API.get('/api/v1/tests?page_size=1000');
      const latestTests = (res.items || res || []).filter(t => t.is_active !== false);
      const latestStr = JSON.stringify(latestTests);
      
      if (JSON.stringify(allTests) !== latestStr) {
        allTests = latestTests;
        localStorage.setItem('akriti_tests_cache', latestStr);
        
        // Refresh picker if currently visible on page
        if (document.getElementById('test-picker-container')) {
          renderTestPicker('test-picker-container', 'test-search-input');
        }
        if (document.getElementById('popular-test-chips')) {
          renderPopularChips('popular-test-chips');
        }
      }
    } catch (err) {
      if (!allTests.length) {
        Toast.show('Failed to load test catalog', 'error');
      }
    }
  }

  // ── Render test picker ────────────────────────────────────────────────────
  // Uses EVENT DELEGATION on the container — no per-item listener re-binding.
  function renderTestPicker(containerId, searchInputId) {
    const container  = document.getElementById(containerId);
    const searchInput = document.getElementById(searchInputId);
    if (!container) return;

    // Event delegation — one listener on container handles all clicks
    // Remove old listener by cloning (safe even if called multiple times)
    const fresh = container.cloneNode(false);
    container.parentNode.replaceChild(fresh, container);
    const cont = document.getElementById(containerId);

    function render(filter = '') {
      const q = (filter || '').toLowerCase().trim();
      const filtered = allTests.filter(t =>
        !q ||
        t.name.toLowerCase().includes(q) ||
        (t.category && t.category.toLowerCase().includes(q))
      );

      if (!filtered.length) {
        cont.innerHTML = `<p class="text-faint text-sm" style="padding:12px 16px">
          ${q ? `No tests match "<strong>${escapeHtml(q)}</strong>"` : 'No tests available'}
        </p>`;
        return;
      }

      // Group by category for better UX
      const groups = {};
      filtered.forEach(t => {
        const cat = t.category || 'General';
        if (!groups[cat]) groups[cat] = [];
        groups[cat].push(t);
      });

      cont.innerHTML = Object.entries(groups).map(([cat, tests]) => `
        <div class="test-group-label" style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;color:var(--color-ink-faint);padding:10px 14px 4px;border-top:1px solid var(--color-border);user-select:none">${escapeHtml(cat)}</div>
        ${tests.map(t => `
          <div class="test-option ${selectedTests.has(String(t.id)) ? 'selected' : ''}" data-id="${t.id}" style="cursor:pointer;user-select:none">
            <span class="test-name">${escapeHtml(t.name)}</span>
            <span class="test-price">${formatCurrency(t.price)}</span>
          </div>
        `).join('')}
      `).join('');
    }

    cont.addEventListener('click', (e) => {
      const label = e.target.closest('.test-option');
      if (!label) return;
      const id = String(label.dataset.id);
      const test = allTests.find(t => String(t.id) === id);
      if (!test) return;

      if (selectedTests.has(id)) {
        selectedTests.delete(id);
        label.classList.remove('selected');
      } else {
        selectedTests.set(id, { name: test.name, price: Number(test.price) });
        label.classList.add('selected');
      }
      updateTotal();
      renderSelectedChips();
      triggerQRRefresh();
    });

    // Wire search input without cloning to prevent focus loss during background revalidation
    if (searchInput) {
      if (!searchInput.dataset.listenerBound) {
        searchInput.addEventListener('input', e => {
          if (activeRender) {
            activeRender(e.target.value);
          }
        });
        searchInput.dataset.listenerBound = 'true';
      }
      activeRender = render;
      render(searchInput.value);
    } else {
      render();
    }
    return { render };
  }

  // ── Selected test chips ───────────────────────────────────────────────────
  function renderSelectedChips(chipContainerId = 'selected-tests-chips') {
    const el = document.getElementById(chipContainerId);
    if (!el) return;
    if (!selectedTests.size) {
      el.innerHTML = `<span class="text-faint text-xs">No tests selected</span>`;
      return;
    }
    el.innerHTML = [...selectedTests.entries()].map(([id, t]) => `
      <span class="chip">
        ${escapeHtml(t.name)}
        <span style="font-size:10px;color:var(--color-ink-muted);margin-left:2px">${formatCurrency(t.price)}</span>
        <button type="button" class="chip-remove" data-id="${id}" aria-label="Remove ${escapeHtml(t.name)}">×</button>
      </span>
    `).join('');

    el.querySelectorAll('.chip-remove').forEach(btn => {
      btn.addEventListener('click', () => {
        const id = btn.dataset.id;
        selectedTests.delete(id);
        updateTotal();
        renderSelectedChips(chipContainerId);
        triggerQRRefresh();
        // Deselect in picker
        const picker = document.querySelector(`#test-picker-container .test-option[data-id="${id}"]`);
        if (picker) {
          picker.classList.remove('selected');
        }
      });
    });
  }

  // ── Live total ────────────────────────────────────────────────────────────
  function updateTotal(totalElId = 'total-amount-display') {
    const el = document.getElementById(totalElId);
    const total = [...selectedTests.values()].reduce((s, t) => s + Number(t.price), 0);
    if (el) el.textContent = formatCurrency(total);
    const hidden = document.getElementById('total-amount-hidden');
    if (hidden) hidden.value = total;

    // Read discount to calculate net payable
    const discountInput = document.getElementById('discount-amount');
    let discount = 0;
    if (discountInput) {
      discount = parseFloat(discountInput.value) || 0;
      if (discount > total) {
        discount = total;
        discountInput.value = discount;
      }
    }
    const net = Math.max(0, total - discount);

    // Auto-adjust Amount Paid if it exceeds the net payable
    const amountInput = document.getElementById('amount-paid');
    if (amountInput) {
      let amount = parseFloat(amountInput.value) || 0;
      if (amount > net) {
        amountInput.value = net;
        // Trigger update to update visibility/QR code
        const modeSection = document.getElementById('payment-mode-section');
        const modeSelect  = document.getElementById('payment-mode');
        const qrSection   = document.getElementById('qr-code-section');
        if (modeSection) modeSection.style.display = net > 0 ? '' : 'none';
        if (qrSection) {
          const isQR = modeSelect && modeSelect.value === 'qr';
          qrSection.style.display = (net > 0 && isQR) ? '' : 'none';
        }
      }
    }
    return total;
  }

  // ── Payment mode toggle ───────────────────────────────────────────────────
  function initPaymentMode() {
    const amountInput = document.getElementById('amount-paid');
    const discountInput = document.getElementById('discount-amount');
    const modeSection = document.getElementById('payment-mode-section');
    const modeSelect  = document.getElementById('payment-mode');
    const qrSection   = document.getElementById('qr-code-section');
    if (!amountInput) return;

    function update() {
      const total = [...selectedTests.values()].reduce((s, t) => s + Number(t.price), 0);
      
      let discount = 0;
      if (discountInput) {
        discount = parseFloat(discountInput.value) || 0;
        if (discount > total) {
          discount = total;
          discountInput.value = discount;
        }
      }
      const net = Math.max(0, total - discount);

      let amount = parseFloat(amountInput.value) || 0;
      if (amount > net) {
        amount = net;
        amountInput.value = net;
      }
      if (modeSection) modeSection.style.display = amount > 0 ? '' : 'none';
      if (qrSection) {
        const isQR = modeSelect && modeSelect.value === 'qr';
        qrSection.style.display = (amount > 0 && isQR) ? '' : 'none';
      }
      triggerQRRefresh();
    }

    amountInput.addEventListener('input', update);
    if (discountInput) discountInput.addEventListener('input', update);
    if (modeSelect) modeSelect.addEventListener('change', update);
    update();
  }

  // ── QR Code — client-side generation ─────────────────────────────────────
  // Generates UPI QR directly without a server call.
  // Debounced so rapid amount typing doesn't spam renders.
  function triggerQRRefresh() {
    if (qrDebounce) clearTimeout(qrDebounce);
    qrDebounce = setTimeout(_generateQR, 400);
  }

  async function _generateQR() {
    const modeSelect  = document.getElementById('payment-mode');
    const amountInput = document.getElementById('amount-paid');
    const qrEl        = document.getElementById('qr-code-canvas');
    const qrSection   = document.getElementById('qr-code-section');
    if (!qrEl) return;

    const mode   = modeSelect ? modeSelect.value : '';
    const amount = parseFloat(amountInput ? amountInput.value : 0) || 0;

    if (mode !== 'qr' || amount <= 0) {
      qrEl.innerHTML = '';
      if (qrSection) qrSection.style.display = 'none';
      return;
    }

    if (qrSection) qrSection.style.display = '';

    // Fetch lab settings once and cache
    if (!labSettingsCache || !labSettingsCache.lab_upi_vpa) {
      try {
        const fetched = await API.get('/api/v1/settings/lab', { silent: true });
        if (fetched && fetched.lab_upi_vpa) {
          labSettingsCache = fetched;
        } else {
          labSettingsCache = fetched || {};
        }
      } catch {
        labSettingsCache = null;
      }
    }

    const vpa     = (labSettingsCache && labSettingsCache.lab_upi_vpa) || '';
    const labName = (labSettingsCache && labSettingsCache.lab_name)    || 'Akriti Diagnostics';

    // Clear previous QR
    qrEl.innerHTML = '';

    if (!vpa) {
      qrEl.innerHTML = `
        <div style="text-align:center;padding:20px">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#9A0002" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          <p style="font-size:13px;color:var(--color-ink-muted);margin-top:8px">UPI VPA not configured.<br>Contact Admin to configure Lab UPI VPA in Settings.</p>
        </div>`;
      return;
    }

    // Build UPI deep link
    const note = 'Lab Payment';
    const upiString = `upi://pay?pa=${encodeURIComponent(vpa)}&pn=${encodeURIComponent(labName)}&am=${amount.toFixed(2)}&cu=INR&tn=${encodeURIComponent(note)}`;

    // Amount display above QR
    qrEl.innerHTML = `
      <div style="margin-bottom:12px">
        <div style="font-size:12px;color:var(--color-ink-faint);margin-bottom:2px">Pay to: <strong>${escapeHtml(labName)}</strong></div>
        <div style="font-family:var(--font-display);font-size:28px;font-weight:700;color:var(--color-primary)">${formatCurrency(amount)}</div>
        <div style="font-size:11px;color:var(--color-ink-faint)">${escapeHtml(vpa)}</div>
      </div>
      <div id="qr-canvas-inner" style="display:inline-block;padding:12px;background:#fff;border-radius:8px;border:2px solid var(--color-border)"></div>
      <p style="font-size:11px;color:var(--color-ink-faint);margin-top:8px">Scan with any UPI app (PhonePe, GPay, Paytm…)</p>
    `;

    try {
      if (typeof QRCode !== 'undefined') {
        new QRCode(document.getElementById('qr-canvas-inner'), {
          text: upiString,
          width: 200,
          height: 200,
          colorDark: '#1a1a1a',
          colorLight: '#ffffff',
          correctLevel: QRCode.CorrectLevel.M,
        });
      } else {
        // Fallback: use a public QR API
        const encoded = encodeURIComponent(upiString);
        document.getElementById('qr-canvas-inner').innerHTML =
          `<img src="https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=${encoded}" width="200" height="200" alt="UPI QR Code">`;
      }
    } catch (err) {
      document.getElementById('qr-canvas-inner').innerHTML =
        `<p style="font-size:12px;color:var(--color-ink-muted)">QR generation failed.<br>Ask patient to pay manually.</p>`;
    }
  }

  // ── Returning patient lookup ───────────────────────────────────────────────
  function initReturningPatientLookup() {
    const mobileInput  = document.getElementById('patient-mobile');
    const suggestionEl = document.getElementById('returning-patient-suggestion');
    if (!mobileInput) return;

    mobileInput.addEventListener('input', e => {
      const val = e.target.value.replace(/\D/g, '');
      if (lookupDebounce) clearTimeout(lookupDebounce);
      if (val.length < 10) {
        if (suggestionEl) suggestionEl.style.display = 'none';
        return;
      }
      lookupDebounce = setTimeout(async () => {
        try {
          if (typeof OfflineQueue !== 'undefined') {
            const online = await OfflineQueue.isOnline();
            if (!online) {
              if (suggestionEl) suggestionEl.style.display = 'none';
              return;
            }
          }
          const res = await API.get(`/api/v1/patients/search?mobile=${val}`, { silent: true });
          if (res && res.length > 0 && suggestionEl) {
            const p = res[0];
            suggestionEl.style.display = '';
            suggestionEl.innerHTML = `
              <div class="suggestion-card">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M20 21v-2a4 4 0 00-4-4H8a4 4 0 00-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
                Returning patient: <strong>${escapeHtml(p.name)}</strong> · Age ${p.age} · Dr. ${escapeHtml(p.doctor_name || 'Self')}
                <button type="button" id="autofill-btn" class="btn btn-sm btn-secondary" style="margin-left:8px">Autofill</button>
              </div>
            `;
            document.getElementById('autofill-btn')?.addEventListener('click', () => {
              const nameEl = document.getElementById('patient-name');
              const ageEl  = document.getElementById('patient-age');
              const genderEl = document.getElementById('patient-gender');
              const doctorEl = document.getElementById('patient-doctor');
              if (nameEl)   nameEl.value   = p.name;
              if (ageEl)    ageEl.value    = p.age;
              if (genderEl) genderEl.value = p.gender || '';
              if (doctorEl) doctorEl.value = p.doctor_id || '';
              suggestionEl.style.display = 'none';
              Toast.show('Patient details prefilled', 'info', 2000);
            });
          } else if (suggestionEl) {
            suggestionEl.style.display = 'none';
          }
        } catch {
          if (suggestionEl) suggestionEl.style.display = 'none';
        }
      }, 500);
    });
  }

  // ── Load doctors from API ──────────────────────────────────────────────────
  let allDoctors = [];
  async function loadDoctors() {
    try {
      const res = await API.get('/api/v1/doctors?page_size=1000', { silent: true });
      allDoctors = res.items || res || [];
      return allDoctors;
    } catch {
      return [];
    }
  }

  function renderDoctorDropdown(selectId) {
    const listEl = document.getElementById('doctor-dropdown-list');
    const selectEl = document.getElementById(selectId);
    
    if (listEl) {
      function renderItems(filter = '') {
        const q = filter.toLowerCase().trim();
        const filtered = allDoctors.filter(d => !q || d.name.toLowerCase().includes(q) || (d.clinic_name && d.clinic_name.toLowerCase().includes(q)));
        const currentVal = document.getElementById('patient-doctor')?.value || '';
        
        let html = `<div class="custom-dropdown-item ${!currentVal ? 'selected' : ''}" data-value="" data-name="SELF / Direct Walk-in">SELF / Direct Walk-in</div>`;
        html += filtered.map(d => {
          const isSel = String(currentVal) === String(d.id);
          return `<div class="custom-dropdown-item ${isSel ? 'selected' : ''}" data-value="${d.id}" data-name="${escapeHtml(d.name)}">${escapeHtml(d.name)}${d.clinic_name ? ` <span style="font-size:11px;opacity:0.7">(${escapeHtml(d.clinic_name)})</span>` : ''}</div>`;
        }).join('');
        listEl.innerHTML = html;

        listEl.querySelectorAll('.custom-dropdown-item').forEach(item => {
          item.addEventListener('click', (e) => {
            e.stopPropagation();
            const val = item.dataset.value;
            const name = item.dataset.name || item.textContent;
            setDoctor(val, name);
            
            const menu = document.getElementById('doctor-dropdown-menu');
            if (menu) menu.style.display = 'none';
            const trigger = document.getElementById('doctor-dropdown-trigger');
            if (trigger) trigger.classList.remove('open');
          });
        });
      }
      
      renderItems('');
      const searchInput = document.getElementById('doctor-search-input');
      if (searchInput && !searchInput.dataset.bound) {
        searchInput.dataset.bound = 'true';
        searchInput.addEventListener('input', e => renderItems(e.target.value));
      }
      
      const trigger = document.getElementById('doctor-dropdown-trigger');
      const menu = document.getElementById('doctor-dropdown-menu');
      if (trigger && menu && !trigger.dataset.bound) {
        trigger.dataset.bound = 'true';
        trigger.addEventListener('click', (e) => {
          e.stopPropagation();
          const isOpen = menu.style.display === 'block';
          menu.style.display = isOpen ? 'none' : 'block';
          trigger.classList.toggle('open', !isOpen);
          if (!isOpen && searchInput) {
            searchInput.value = '';
            renderItems('');
            setTimeout(() => searchInput.focus(), 50);
          }
        });
        document.addEventListener('click', (e) => {
          if (!trigger.contains(e.target) && !menu.contains(e.target)) {
            menu.style.display = 'none';
            trigger.classList.remove('open');
          }
        });
      }
    }

    if (selectEl && selectEl.tagName === 'SELECT') {
      selectEl.innerHTML = `
        <option value="">SELF</option>
        ${allDoctors.map(d => `<option value="${d.id}">${escapeHtml(d.name)}</option>`).join('')}
      `;
    }
  }

  function setDoctor(val, nameStr = null) {
    const hidden = document.getElementById('patient-doctor');
    const text = document.getElementById('doctor-selected-text');
    if (hidden) hidden.value = val || '';
    if (text) {
      if (nameStr) {
        text.textContent = nameStr;
      } else {
        const doc = allDoctors.find(d => String(d.id) === String(val));
        text.textContent = doc ? doc.name : 'SELF / Direct Walk-in';
      }
    }
    const listEl = document.getElementById('doctor-dropdown-list');
    if (listEl) {
      listEl.querySelectorAll('.custom-dropdown-item').forEach(i => {
        i.classList.toggle('selected', String(i.dataset.value) === String(val || ''));
      });
    }
  }

  // ── Custom Gender Selector ─────────────────────────────────────────────
  function initGenderSelector() {
    const container = document.getElementById('gender-segmented-control');
    const hidden = document.getElementById('patient-gender');
    if (!container || !hidden) return;

    container.querySelectorAll('.gender-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        setGender(btn.dataset.value);
      });
    });

    const currentVal = hidden.value || 'male';
    setGender(currentVal);
  }

  function setGender(val) {
    const container = document.getElementById('gender-segmented-control');
    const hidden = document.getElementById('patient-gender');
    if (hidden) hidden.value = val;
    if (container) {
      container.querySelectorAll('.gender-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.value === val);
      });
    }
  }

  // ── Collect form data ─────────────────────────────────────────────────────
  function getFormData() {
    const v = id => { const el = document.getElementById(id); return el ? el.value : ''; };
    const docId = v('patient-doctor');
    return {
      name:          v('patient-name').trim(),
      mobile:        v('patient-mobile').trim(),
      age:           parseInt(v('patient-age')),
      gender:        v('patient-gender'),
      doctor_id:     docId ? docId : null,
      sample_date:   v('patient-sample-date'),
      amount_paid:   parseFloat(v('amount-paid')) || 0,
      payment_mode:  v('payment-mode') || 'cash',
      test_ids:      [...selectedTests.keys()],
      total_amount:  [...selectedTests.values()].reduce((s, t) => s + Number(t.price), 0),
      discount_amount: parseFloat(v('discount-amount')) || 0,
    };
  }

  function getSelectedTestIds() { return [...selectedTests.keys()]; }

  function setSelectedTests(tests) {
    selectedTests.clear();
    tests.forEach(t => selectedTests.set(String(t.test_id || t.id), { name: t.name, price: Number(t.price ?? t.price_at_booking ?? 0) }));
  }

  // ── Popular Test Chips ──────────────────────────────────────────────────
  function renderPopularChips(containerId) {
    const container = document.getElementById(containerId);
    if (!container || !allTests.length) return;
    
    // Pick first 8 active tests or popular ones
    const popular = allTests.slice(0, 8);
    container.innerHTML = popular.map(t => {
      const isSelected = selectedTests.has(String(t.id));
      return `<div class="popular-chip ${isSelected ? 'selected' : ''}" data-id="${t.id}">${isSelected ? '✓ ' : '+ '}${escapeHtml(t.name)} (₹${t.price})</div>`;
    }).join('');

    container.querySelectorAll('.popular-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        const id = String(chip.dataset.id);
        const test = allTests.find(t => String(t.id) === id);
        if (!test) return;

        if (selectedTests.has(id)) {
          selectedTests.delete(id);
        } else {
          selectedTests.set(id, { name: test.name, price: Number(test.price) });
        }
        updateTotal();
        renderSelectedChips();
        renderTestPicker('test-picker-container', 'test-search-input');
        renderPopularChips(containerId);
      });
    });
  }

  function clearForm() { selectedTests.clear(); }

  return {
    loadTests,
    revalidateTests,
    loadDoctors,
    renderDoctorDropdown,
    setDoctor,
    renderTestPicker,
    renderPopularChips,
    renderSelectedChips,
    initGenderSelector,
    setGender,
    updateTotal,
    initPaymentMode,
    initReturningPatientLookup,
    triggerQRRefresh,
    getFormData,
    getSelectedTestIds,
    setSelectedTests,
    clearForm,
  };
})();

window.PatientForm = PatientForm;
