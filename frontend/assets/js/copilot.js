/**
 * PathLab AI Copilot
 */
const Copilot = (() => {
  let isInit = false;
  let conversationHistory = []; // In-memory session cache (last 5 messages, resets on page refresh)

  const SVGS = {
    patient: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="copilot-svg-icon"><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>`,
    calendar: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="copilot-svg-icon"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>`,
    doctor: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="copilot-svg-icon"><path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z"></path><path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z"></path></svg>`,
    tests: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="copilot-svg-icon"><path d="M10 2v7.31"></path><path d="M14 9.3V1.99"></path><path d="M8.5 2h7"></path><path d="M14 9.3a6.5 6.5 0 1 1-4 0"></path><path d="M5.52 16h12.96"></path></svg>`,
    billing: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="copilot-svg-icon"><rect x="2" y="4" width="20" height="16" rx="2"></rect><line x1="2" y1="10" x2="22" y2="10"></line></svg>`,
    report: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="copilot-svg-icon"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line><polyline points="10 9 9 9 8 9"></polyline></svg>`,
    results: `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="copilot-svg-icon"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline></svg>`,
    alert: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="copilot-svg-icon-alert"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"></path><line x1="12" y1="9" x2="12" y2="13"></line><line x1="12" y1="17" x2="12.01" y2="17"></line></svg>`,
    download: `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" style="margin-right:4px;"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>`
  };

  function getSvgForLabel(label) {
    const l = (label || '').toLowerCase();
    if (l.includes('patient') || l.includes('demographics')) return SVGS.patient;
    if (l.includes('status') || l.includes('timeline') || l.includes('date') || l.includes('sample')) return SVGS.calendar;
    if (l.includes('doctor') || l.includes('staff')) return SVGS.doctor;
    if (l.includes('test') || l.includes('booked')) return SVGS.tests;
    if (l.includes('bill') || l.includes('payment') || l.includes('account')) return SVGS.billing;
    if (l.includes('report')) return SVGS.report;
    if (l.includes('result')) return SVGS.results;
    if (l.includes('abnormal') || l.includes('alert') || l.includes('warning')) return SVGS.alert;
    return '';
  }

  function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function decodeHtmlEntities(str) {
    if (!str) return '';
    return String(str)
      .replace(/&#(\d+);?/g, (m, dec) => String.fromCharCode(parseInt(dec, 10)))
      .replace(/&#x([0-9a-fA-F]+);?/g, (m, hex) => String.fromCharCode(parseInt(hex, 16)))
      .replace(/&quot;/g, '"')
      .replace(/&#39;/g, "'")
      .replace(/&lt;/g, '<')
      .replace(/&gt;/g, '>')
      .replace(/&amp;/g, '&');
  }

  function sanitizeUrl(rawUrl) {
    if (!rawUrl || typeof rawUrl !== 'string') return null;
    const decoded = decodeHtmlEntities(rawUrl);
    const cleaned = decoded.replace(/[\x00-\x1F\x7F-\x9F]/g, '').trim();
    if (!cleaned) return null;

    // Reject URLs with raw spaces, quotes, angle brackets, or backslashes
    if (/["'<>\s\\]/.test(cleaned)) {
      return null;
    }

    // Reject protocol-relative traversal schemes
    if (cleaned.startsWith('//')) {
      return null;
    }

    // Permit safe relative paths and fragment anchors genuinely needed by app
    if (cleaned.startsWith('/') || cleaned.startsWith('./') || cleaned.startsWith('../') || cleaned.startsWith('#')) {
      return cleaned;
    }

    // Validate scheme against strict allowlist: http, https, mailto, tel
    const schemeMatch = cleaned.match(/^([a-zA-Z][a-zA-Z0-9+.-]*):/);
    if (!schemeMatch) {
      const firstColon = cleaned.indexOf(':');
      const firstSlash = cleaned.indexOf('/');
      if (firstColon !== -1 && (firstSlash === -1 || firstColon < firstSlash)) {
        return null;
      }
      return cleaned;
    }

    const scheme = schemeMatch[1].toLowerCase();
    const allowedSchemes = ['http', 'https', 'mailto', 'tel'];
    if (!allowedSchemes.includes(scheme)) {
      return null;
    }

    try {
      const base = (typeof window !== 'undefined' && window.location && window.location.origin) ? window.location.origin : 'http://localhost';
      const parsed = new URL(cleaned, base);
      const proto = parsed.protocol.replace(':', '').toLowerCase();
      if (!allowedSchemes.includes(proto)) {
        return null;
      }
      return cleaned;
    } catch (e) {
      return null;
    }
  }

  function renderPatientCard(data) {
    if (!data || typeof data !== 'object') return '';

    const dueAmount = Number(data.due) || 0;
    const totalAmount = Number(data.total) || 0;
    const paidAmount = Number(data.paid) || 0;
    const isPaid = dueAmount <= 0 || String(data.pay_status || '').toLowerCase().includes('paid');
    const statusStr = String(data.status || '');
    const isReady = statusStr.toLowerCase().includes('ready');
    
    // Status Badge
    let statusClass = 'cpc-badge-default';
    if (isReady) statusClass = 'cpc-badge-success';
    else if (statusStr.toLowerCase().includes('collected')) statusClass = 'cpc-badge-info';
    else if (statusStr.toLowerCase().includes('pending')) statusClass = 'cpc-badge-warning';

    // Payment Badge
    const payClass = isPaid ? 'cpc-badge-success' : 'cpc-badge-warning';
    const payText = isPaid ? 'Paid' : `Due ₹${dueAmount}`;

    // Test chips
    let testChipsHtml = '';
    const testList = Array.isArray(data.tests) ? data.tests : String(data.tests || '').split(',');
    const validTests = testList.map(t => String(t).trim()).filter(Boolean);
    if (validTests.length > 0) {
      testChipsHtml = validTests.map(t => `<span class="cpc-chip">${escapeHtml(t)}</span>`).join('');
    } else {
      testChipsHtml = '<span class="cpc-text-muted">None specified</span>';
    }

    // Report button or status
    let reportHtml = '';
    const reportObj = data.report || (data.report_url ? { download_url: data.report_url, version_label: data.report_version } : null);
    if (reportObj && reportObj.download_url) {
      const safeDownloadUrl = sanitizeUrl(reportObj.download_url);
      const vText = reportObj.version_label ? ` (${escapeHtml(reportObj.version_label)})` : '';
      if (safeDownloadUrl) {
        const escapedUrl = escapeHtml(safeDownloadUrl);
        reportHtml = `<a href="${escapedUrl}" target="_blank" rel="noopener noreferrer" class="cpc-btn-report">
          ${SVGS.download} Download Report${vText}
        </a>`;
      } else {
        reportHtml = `<span class="cpc-report-pending">${SVGS.report} Invalid report link${vText}</span>`;
      }
    } else {
      reportHtml = `<span class="cpc-report-pending">${SVGS.report} No reports uploaded yet</span>`;
    }

    // Abnormal alert banner
    let abnormalHtml = '';
    if (data.abnormal) {
      abnormalHtml = `<div class="cpc-abnormal-banner">
        ${SVGS.alert} <span><strong>Attention:</strong> ${escapeHtml(data.abnormal)} (Doctor Review)</span>
      </div>`;
    }

    return `
    <div class="copilot-patient-card">
      <div class="cpc-header">
        <div class="cpc-patient-meta">
          <span class="cpc-patient-name">${escapeHtml(data.name || 'Patient')}</span>
          <span class="cpc-patient-code">${escapeHtml(data.code || '')}</span>
        </div>
        <div class="cpc-badges">
          <span class="cpc-badge ${escapeHtml(statusClass)}">${escapeHtml(data.status || 'Active')}</span>
          <span class="cpc-badge ${escapeHtml(payClass)}">${escapeHtml(payText)}</span>
        </div>
      </div>

      <div class="cpc-grid">
        <div class="cpc-cell"><span class="cpc-k">Age/Sex:</span> <span class="cpc-v">${escapeHtml(data.age || '-')}/${escapeHtml(data.gender || '-')}</span></div>
        <div class="cpc-cell"><span class="cpc-k">Mobile:</span> <span class="cpc-v">${escapeHtml(data.mobile || '-')}</span></div>
        <div class="cpc-cell"><span class="cpc-k">Doctor:</span> <span class="cpc-v">${escapeHtml(data.doctor || 'Self')}</span></div>
        <div class="cpc-cell"><span class="cpc-k">Sample Date:</span> <span class="cpc-v">${escapeHtml(data.sample_date || '-')}</span></div>
      </div>

      <div class="cpc-section">
        <span class="cpc-section-label">Booked Tests:</span>
        <div class="cpc-chips">${testChipsHtml}</div>
      </div>

      <div class="cpc-finance-bar">
        <div class="cpc-fin-item"><span class="cpc-fin-lbl">Total</span><span class="cpc-fin-val">₹${totalAmount}</span></div>
        <div class="cpc-fin-sep"></div>
        <div class="cpc-fin-item"><span class="cpc-fin-lbl">Paid</span><span class="cpc-fin-val text-success">₹${paidAmount}</span></div>
        <div class="cpc-fin-sep"></div>
        <div class="cpc-fin-item"><span class="cpc-fin-lbl">Due</span><span class="cpc-fin-val ${dueAmount > 0 ? 'text-danger' : 'text-success'}">₹${dueAmount}</span></div>
      </div>

      ${abnormalHtml}

      <div class="cpc-footer">
        ${reportHtml}
      </div>
    </div>`;
  }

  function parseAndRenderMarkdownCard(str) {
    const nameMatch = str.match(/\*\*Patient Record:\s*(.+?)\*\*\s*(?:\(`?([A-Z0-9]+)`?\))?/i);
    const demoMatch = str.match(/Demographics:\*\*\s*([^\/|]+)\s*\/\s*([^|]+)\s*\|\s*\*\*Mobile:\*\*\s*([^\n]+)/i);
    const statusMatch = str.match(/Status:\*\*\s*([^|]+)\s*\|\s*\*\*Sample Date:\*\*\s*([^\n]+)/i);
    const doctorMatch = str.match(/Doctor:\*\*\s*([^\n]+)/i);
    const testsMatch = str.match(/Booked Tests:\*\*\s*([^\n]+)/i);
    const billMatch = str.match(/Billing:\*\*\s*Total Rs\s*([\d.]+)\s*\|\s*Paid Rs\s*([\d.]+)\s*\|\s*Due Rs\s*([\d.]+)\s*(?:\(([^)]+)\))?/i);
    const reportMatch = str.match(/Diagnostic Report:\*\*\s*(?:\[([^\]]+)\]\(([^)]+)\)|([^\n]+))/i);
    const abnormalMatch = str.match(/Abnormal Findings:\*\*\s*([^\n]+)/i);

    const data = {
      name: nameMatch ? nameMatch[1].trim() : '',
      code: nameMatch ? (nameMatch[2] || '').trim() : '',
      age: demoMatch ? demoMatch[1].trim() : '',
      gender: demoMatch ? demoMatch[2].trim() : '',
      mobile: demoMatch ? demoMatch[3].trim() : '',
      status: statusMatch ? statusMatch[1].trim() : '',
      sample_date: statusMatch ? statusMatch[2].trim() : '',
      doctor: doctorMatch ? doctorMatch[1].trim() : '',
      tests: testsMatch ? testsMatch[1].split(',').map(s => s.trim()) : [],
      total: billMatch ? parseFloat(billMatch[1]) : 0,
      paid: billMatch ? parseFloat(billMatch[2]) : 0,
      due: billMatch ? parseFloat(billMatch[3]) : 0,
      pay_status: billMatch && billMatch[4] ? billMatch[4].trim() : '',
      report: reportMatch && reportMatch[2] ? { download_url: reportMatch[2], version_label: reportMatch[1] } : null,
      abnormal: abnormalMatch ? abnormalMatch[1].replace(/\(Requires Doctor Review\)/i, '').trim() : null
    };

    return renderPatientCard(data);
  }

  function formatMarkdown(str) {
    if (!str) return '';

    // Check if str is or contains a JSON patient card
    const trimmed = str.trim();
    if (trimmed.startsWith('{') && trimmed.includes('"__card": "patient"')) {
      try {
        const parsed = JSON.parse(trimmed);
        if (parsed && parsed.__card === 'patient') {
          return renderPatientCard(parsed);
        }
      } catch (e) {}
    }

    // Check if str is a Markdown patient record card
    if (str.includes('Patient Record:') && str.includes('Demographics:')) {
      return parseAndRenderMarkdownCard(str);
    }

    // 1. Remove all Unicode emojis completely
    let s = str.replace(/[\u{1F300}-\u{1F9FF}\u{2600}-\u{26FF}\u{2700}-\u{27BF}\u{1F600}-\u{1F64F}\u{1F680}-\u{1F6FF}\u{1FA00}-\u{1FAFF}]/gu, '');

    // 2. Remove orphan asterisks, dashes, or bullets on lines by themselves
    s = s.replace(/^[ \t]*[*•-][ \t]*$/gm, '');

    // 3. Escape HTML entities
    s = escapeHtml(s);

    // 4. Multi-line fenced code blocks ```code```
    s = s.replace(/```(?:[a-zA-Z0-9_-]+)?\n?([\s\S]*?)```/g, (m, code) => {
      return `<pre class="copilot-code-block"><code class="copilot-inline-code">${code.trim()}</code></pre>`;
    });

    // 5. Markdown tables
    s = s.replace(/((?:^[ \t]*\|.+?\|[ \t]*(?:\r?\n|$))+)/gm, (match) => {
      const lines = match.trim().split(/\r?\n/).map(l => l.trim()).filter(Boolean);
      if (lines.length < 2) return match;
      if (!/^\|(?:\s*:?-+:?\s*\|)+$/.test(lines[1])) return match;
      const parseRow = (line) => line.replace(/^\||\|$/g, '').split('|').map(c => c.trim());
      const headers = parseRow(lines[0]);
      const ths = headers.map(h => `<th>${h}</th>`).join('');
      let rowsHtml = '';
      for (let i = 2; i < lines.length; i++) {
        if (!lines[i].includes('|')) continue;
        const cells = parseRow(lines[i]);
        const tds = cells.map(c => `<td>${c}</td>`).join('');
        rowsHtml += `<tr>${tds}</tr>`;
      }
      return `<div class="table-wrapper" style="margin:8px 0; overflow-x:auto;"><table class="data-table" style="width:100%; font-size:12px;"><thead><tr>${ths}</tr></thead><tbody>${rowsHtml}</tbody></table></div>`;
    });

    // 6. Header Cards (e.g. **Patient Record: ...**)
    s = s.replace(/^\*\*Patient Record:\s*(.+?)\*\*$/gm, (m, title) => {
      return `<div class="copilot-card-header">${SVGS.patient} <span>${title}</span></div>`;
    });

    // 7. Convert markdown headers (### Header, ## Header, # Header) to styled headers with SVG
    s = s.replace(/^[ \t]*#{1,4}[ \t]+(.+)$/gm, (m, hdr) => {
      const icon = getSvgForLabel(hdr);
      return `<div class="copilot-section-header">${icon}<span>${hdr}</span></div>`;
    });

    // 8. Convert bullet items with key labels (• **Label:** Value) into clean SVG-badged items
    s = s.replace(/^[ \t]*[•*+-][ \t]+\*\*([^*:]+):\*\*[ \t]*(.*)$/gm, (m, label, val) => {
      const icon = getSvgForLabel(label);
      return `<div class="copilot-list-item">${icon}<strong>${label}:</strong> <span>${val}</span></div>`;
    });

    // 9. Any remaining bullets (* item, - item, • item)
    s = s.replace(/^[ \t]*[•*+-][ \t]+(.+)$/gm, `<div class="copilot-list-item"><span class="copilot-bullet">•</span> $1</div>`);

    // 10. Numbered lists (1. item)
    s = s.replace(/^[ \t]*(\d+)\.[ \t]+(.+)$/gm, '<div class="copilot-list-item"><span class="copilot-num">$1.</span> $2</div>');

    // 11. Bold **text**
    s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');

    // 12. Italic *text* (word level only)
    s = s.replace(/(^|[^\*])\*([^\*\n]+)\*([^\*]|$)/g, '$1<em>$2</em>$3');

    // 13. Inline code `code`
    s = s.replace(/`([^`]+)`/g, '<code class="copilot-inline-code">$1</code>');

    // 14. Links: validate protocol and sanitize URL destinations
    s = s.replace(/\[([^\]]+)\]\(((?:[^\s()]+|\([^\s()]*\))+)\)/g, (m, txt, rawUrl) => {
      const safeUrl = sanitizeUrl(rawUrl);
      if (!safeUrl) {
        return `<span class="copilot-link copilot-link-disabled">${txt}</span>`;
      }
      const escapedUrl = escapeHtml(safeUrl);
      const isReport = txt.toLowerCase().includes('report') || txt.toLowerCase().includes('download') || txt.toLowerCase().includes('view');
      if (isReport) {
        return `<a href="${escapedUrl}" target="_blank" rel="noopener noreferrer" class="copilot-report-btn">${SVGS.download} ${txt}</a>`;
      }
      return `<a href="${escapedUrl}" target="_blank" rel="noopener noreferrer" class="copilot-link">${txt}</a>`;
    });

    // 15. Highlight Doctor Review / Abnormal badges
    s = s.replace(/\((?:Requires Doctor Review|ABNORMAL)\)/gi, `<span class="copilot-badge-abnormal">${SVGS.alert} Doctor Review</span>`);

    // 16. Clean up any newlines around <div> tags to prevent empty blank lines
    s = s.replace(/<\/div>\n+/g, '</div>');
    s = s.replace(/\n+<div/g, '<div');
    s = s.replace(/\n\n+/g, '<br><br>');
    s = s.replace(/\n/g, '<br>');

    return s;
  }

  const COPILOT_ICON = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path><path d="M9 9h6"></path><path d="M9 13h6"></path></svg>`;
  const SEND_ICON = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>`;

  function initUI() {
    if (isInit) return;
    
    // Inject Copilot Toggle into Topbar
    const topbar = document.querySelector('.topbar');
    if (topbar) {
      let topbarRight = topbar.querySelector('.topbar-right');
      if (!topbarRight) {
        topbarRight = document.createElement('div');
        topbarRight.className = 'topbar-right';
        topbarRight.style.marginLeft = 'auto'; // Ensure it floats right
        topbar.appendChild(topbarRight);
      }
      const copilotBtn = document.createElement('button');
      copilotBtn.className = 'ask-ai-badge';
      copilotBtn.setAttribute('aria-label', 'Open AI Copilot');
      copilotBtn.innerHTML = `Ask AI ✨`;
      copilotBtn.addEventListener('click', toggleDrawer);
      topbarRight.appendChild(copilotBtn);
    }

    // Inject CSS
    if (!document.getElementById('copilot-css')) {
      const link = document.createElement('link');
      link.id = 'copilot-css';
      link.rel = 'stylesheet';
      link.href = '/assets/css/copilot.css?v=' + Date.now();
      document.head.appendChild(link);
    }

    // Inject Drawer HTML
    const drawerHtml = `
      <div class="copilot-overlay" id="copilot-overlay"></div>
      <div class="copilot-drawer" id="copilot-drawer">
        <div class="copilot-header">
          <div class="copilot-brand">
            ${COPILOT_ICON} PathLab AI
          </div>
          <div style="display:flex; align-items:center; gap:6px;">
            <button class="copilot-reset-btn" id="copilot-reset" title="New Session (Reset Memory)" aria-label="Reset Conversation" style="background:none; border:none; color:inherit; cursor:pointer; opacity:0.75; padding:4px 6px; display:inline-flex; align-items:center; border-radius:4px;">
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
            </button>
            <button class="copilot-close" id="copilot-close" aria-label="Close AI">&times;</button>
          </div>
        </div>
        <div class="copilot-body" id="copilot-messages">
          <div class="copilot-msg system">
            Hi ${escapeHtml(window._me?.name || 'there')}! I'm your PathLab AI assistant. How can I help you today?
          </div>
        </div>
        <div class="copilot-footer">
          <textarea id="copilot-input" placeholder="Ask PathLab AI..." rows="1" enterkeyhint="send" style="resize: none; overflow: hidden;"></textarea>
          <button id="copilot-send" aria-label="Send message">${SEND_ICON}</button>
        </div>
      </div>
    `;
    
    const wrapper = document.createElement('div');
    wrapper.innerHTML = drawerHtml;
    document.body.appendChild(wrapper);

    // Bind Drawer Events
    document.getElementById('copilot-close').addEventListener('click', closeDrawer);
    document.getElementById('copilot-overlay').addEventListener('click', closeDrawer);
    
    const resetBtn = document.getElementById('copilot-reset');
    if (resetBtn) {
      resetBtn.addEventListener('click', () => {
        conversationHistory = [];
        const container = document.getElementById('copilot-messages');
        if (container) {
          container.innerHTML = `
            <div class="copilot-msg system">
              Hi ${escapeHtml(window._me?.name || 'there')}! Memory reset. How can I help you today?
            </div>
          `;
        }
      });
    }
    
    const input = document.getElementById('copilot-input');
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });
    
    document.getElementById('copilot-send').addEventListener('click', sendMessage);

    isInit = true;
  }

  function toggleDrawer() {
    document.getElementById('copilot-drawer').classList.add('open');
    document.getElementById('copilot-overlay').classList.add('open');
  }

  function closeDrawer() {
    document.getElementById('copilot-drawer').classList.remove('open');
    document.getElementById('copilot-overlay').classList.remove('open');
  }

  function appendMessage(role, text) {
    const container = document.getElementById('copilot-messages');
    const msg = document.createElement('div');
    msg.className = `copilot-msg ${role}`;
    msg.textContent = text;
    container.appendChild(msg);
    container.scrollTop = container.scrollHeight;
    return msg;
  }

  async function sendMessage() {
    const input = document.getElementById('copilot-input');
    const sendBtn = document.getElementById('copilot-send');
    const text = input.value.trim();
    if (!text) return;
    
    input.disabled = true;
    sendBtn.disabled = true;

    appendMessage('user', text);
    input.value = '';
    input.style.height = 'auto';

    const msg = appendMessage('system', 'Thinking');
    let dotCount = 0;
    const loadingInterval = setInterval(() => {
      dotCount = (dotCount + 1) % 4;
      msg.textContent = 'Thinking' + '.'.repeat(dotCount);
    }, 400);

    let isFirstChunk = true;
    let rawText = '';
    try {
      const token = localStorage.getItem('akriti_token') || '';
      // Pass up to last 5 messages from session memory
      const historyPayload = conversationHistory.slice(-5);

      const response = await fetch('/api/v1/copilot/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({ 
          message: text,
          history: historyPayload
        })
      });
      
      if (!response.ok) {
        clearInterval(loadingInterval);
        msg.textContent = 'Error connecting to AI Copilot.';
        return;
      }
      
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        
        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split('\n');
        
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6).trim();
            if (data === '[DONE]') break;
            
            if (isFirstChunk) {
               clearInterval(loadingInterval);
               msg.innerHTML = '';
               isFirstChunk = false;
            }
            
            let textToAppend = data;
            try {
              textToAppend = JSON.parse(data);
            } catch(e) {
              // Fallback to raw text if parsing fails
            }
            
            rawText += textToAppend;
            msg.innerHTML = formatMarkdown(rawText);
            if (msg.querySelector('.copilot-patient-card')) {
              msg.classList.add('has-card');
            } else {
              msg.classList.remove('has-card');
            }
            const container = document.getElementById('copilot-messages');
            container.scrollTop = container.scrollHeight;
          }
        }
      }

      // Record this exchange in session memory (capped at last 5 messages)
      if (rawText) {
        conversationHistory.push({ role: 'user', content: text });
        conversationHistory.push({ role: 'assistant', content: rawText });
        if (conversationHistory.length > 5) {
          conversationHistory = conversationHistory.slice(-5);
        }
      }
    } catch (err) {
      clearInterval(loadingInterval);
      console.error(err);
      if (isFirstChunk) msg.textContent = 'Error connecting to AI Copilot.';
    } finally {
      input.disabled = false;
      sendBtn.disabled = false;
      input.focus();
    }
  }

  return {
    init: initUI,
    toggle: toggleDrawer,
    close: closeDrawer,
    formatMarkdown,
    renderPatientCard,
    parseAndRenderMarkdownCard,
    sanitizeUrl,
    escapeHtml
  };
})();

if (typeof window !== 'undefined') {
  window.Copilot = Copilot;
}
if (typeof module !== 'undefined' && module.exports) {
  module.exports = Copilot;
}

