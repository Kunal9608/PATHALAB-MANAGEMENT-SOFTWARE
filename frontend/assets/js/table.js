/**
 * AKRITI — Reusable Table Renderer
 * Handles: pagination, skeleton loading, empty state, search, filter, sort.
 *
 * Usage:
 *   const table = new DataTable({
 *     containerId: 'patients-table-container',
 *     columns: [
 *       { key: 'patient_code', label: 'Patient ID', width: '120px' },
 *       { key: 'name', label: 'Name' },
 *       { key: 'status', label: 'Status', render: (val) => renderBadge(val) },
 *       { key: null, label: 'Actions', render: (_, row) => `<button ...>` },
 *     ],
 *     fetchFn: async (params) => {
 *       // params: { page, page_size, q, ...filters }
 *       return { items: [...], total: N };
 *     },
 *     pageSize: 20,
 *   });
 *   table.load();
 */

class DataTable {
  constructor({ containerId, columns, fetchFn, pageSize = 20, emptyMessage = 'No records found.' }) {
    this.container = document.getElementById(containerId);
    if (!this.container) {
      this.unmounted = true;
      return;
    }
    this.columns = columns;
    this.fetchFn = fetchFn;
    this.pageSize = pageSize;
    this.emptyMessage = emptyMessage;

    this.page = 1;
    this.total = 0;
    this.items = [];
    this.filters = {};
    this.loading = false;

    this._buildShell();
  }

  _buildShell() {
    this.container.innerHTML = `
      <div class="table-wrapper">
        <table class="data-table" id="${this.container.id}-table">
          <thead>
            <tr>${this.columns.map(c =>
              `<th${c.width ? ` style="width:${c.width}"` : ''}>${c.label}</th>`
            ).join('')}</tr>
          </thead>
          <tbody id="${this.container.id}-tbody">
            ${this._skeletonRows(6)}
          </tbody>
        </table>
        <div class="pagination" id="${this.container.id}-pagination" style="display:none">
          <span id="${this.container.id}-count" class="text-sm text-muted"></span>
          <div class="pagination-pages" id="${this.container.id}-pages"></div>
        </div>
      </div>
    `;
    this.tbody = document.getElementById(`${this.container.id}-tbody`);
    this.paginationEl = document.getElementById(`${this.container.id}-pagination`);
    this.countEl = document.getElementById(`${this.container.id}-count`);
    this.pagesEl = document.getElementById(`${this.container.id}-pages`);
  }

  _skeletonRows(n) {
    return Array.from({ length: n }).map(() => `
      <tr>
        ${this.columns.map(() => `<td><span class="skel skel-text skel-w-full"></span></td>`).join('')}
      </tr>
    `).join('');
  }

  async load(extraFilters = {}, options = {}) {
    if (this.unmounted || !this.container || !document.contains(this.container)) return;
    if (this.loading) return;
    this.loading = true;
    if (!options.silent && this.tbody) {
      this.tbody.innerHTML = this._skeletonRows(6);
    }

    const params = {
      page: this.page,
      page_size: this.pageSize,
      ...this.filters,
      ...extraFilters,
    };

    try {
      const result = await this.fetchFn(params, options);
      if (!this.container || !document.contains(this.container)) return;
      this.items = result.items || [];
      this.total = result.total || 0;
      this._renderRows(this.items);
      this._renderPagination();
    } catch (err) {
      if (!this.container || !document.contains(this.container)) return;
      if (this.tbody) {
        this.tbody.innerHTML = `
          <tr><td colspan="${this.columns.length}" class="table-empty">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
            Failed to load data.
          </td></tr>
        `;
      }
    } finally {
      this.loading = false;
    }
  }

  _renderRows(items) {
    if (!this.tbody || !document.contains(this.tbody)) return;
    if (!items.length) {
      this.tbody.innerHTML = `
        <tr><td colspan="${this.columns.length}" class="table-empty">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
          ${this.emptyMessage}
        </td></tr>
      `;
      return;
    }

    this.tbody.innerHTML = items.map((row, index) => `
      <tr>
        ${this.columns.map(col => {
          const val = col.key ? (row[col.key] ?? '') : '';
          const globalIndex = (this.page - 1) * this.pageSize + index + 1;
          const cell = col.render ? col.render(val, row, globalIndex) : escapeHtml(String(val));
          return `<td>${cell}</td>`;
        }).join('')}
      </tr>
    `).join('');
  }

  _renderPagination() {
    if (!this.paginationEl || !document.contains(this.paginationEl)) return;
    const totalPages = Math.ceil(this.total / this.pageSize);
    if (totalPages <= 1) {
      this.paginationEl.style.display = 'none';
      return;
    }
    this.paginationEl.style.display = 'flex';

    const from = (this.page - 1) * this.pageSize + 1;
    const to   = Math.min(this.page * this.pageSize, this.total);
    if (this.countEl) this.countEl.textContent = `${from}–${to} of ${this.total}`;

    // Build page buttons (window of 5 around current)
    const pages = [];
    for (let p = Math.max(1, this.page - 2); p <= Math.min(totalPages, this.page + 2); p++) {
      pages.push(p);
    }

    if (this.pagesEl) {
      this.pagesEl.innerHTML = [
        `<button class="page-btn" data-p="${this.page - 1}" ${this.page === 1 ? 'disabled' : ''}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="15 18 9 12 15 6"/></svg>
        </button>`,
        ...pages.map(p => `<button class="page-btn ${p === this.page ? 'active' : ''}" data-p="${p}">${p}</button>`),
        `<button class="page-btn" data-p="${this.page + 1}" ${this.page === totalPages ? 'disabled' : ''}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="9 18 15 12 9 6"/></svg>
        </button>`,
      ].join('');

      this.pagesEl.querySelectorAll('[data-p]').forEach(btn => {
        btn.addEventListener('click', () => {
          const p = parseInt(btn.dataset.p);
          if (!isNaN(p) && p >= 1 && p <= totalPages) {
            this.page = p;
            this.load();
          }
        });
      });
    }
  }

  setFilter(key, value) {
    if (this.unmounted) return;
    if (value === '' || value == null) {
      delete this.filters[key];
    } else {
      this.filters[key] = value;
    }
    this.page = 1;
  }

  refresh() {
    if (this.unmounted) return;
    this.page = 1;
    this.load();
  }
}

// Helper
function escapeHtml(str) {
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// Badge renderer helpers (used across many pages)
function statusBadge(status) {
  const map = {
    'sample_collected': ['badge-info',    'Collected'],
    'under_process':    ['badge-warning', 'Processing'],
    'partial_release':  ['badge-warning', 'Partial Release'],
    'report_ready':     ['badge-success', 'Report Ready'],
    'paid':             ['badge-success', 'Paid'],
    'partial':          ['badge-warning', 'Partial'],
    'due':              ['badge-error',   'Due'],
    'active':           ['badge-success', 'Active'],
    'inactive':         ['badge-neutral', 'Inactive'],
    'face_pending':     ['badge-warning', 'Face Pending'],
    'success':          ['badge-success', 'Success'],
    'bad_password':     ['badge-error',   'Failed'],
    'locked_out':       ['badge-error',   'Locked'],
    'unknown_email':    ['badge-error',   'Unknown'],
  };
  const [cls, label] = map[status] || ['badge-neutral', status];
  return `<span class="badge ${cls}">${label}</span>`;
}

function formatDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
}

function formatDateTime(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('en-IN', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function formatCurrency(n) {
  if (n == null) return '—';
  return '₹' + Number(n).toLocaleString('en-IN', { minimumFractionDigits: 0 });
}

window.DataTable = DataTable;
window.statusBadge = statusBadge;
window.formatDate = formatDate;
window.formatDateTime = formatDateTime;
window.formatCurrency = formatCurrency;
window.escapeHtml = escapeHtml;
