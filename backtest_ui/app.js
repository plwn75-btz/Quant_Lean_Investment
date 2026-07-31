/**
 * backtest_ui/app.js
 * ──────────────────
 * UI logic for the Quant-LEAN Engineering dashboard.
 * - Renders buy/sell condition toggles
 * - Collects all parameters from the form
 * - Calls the Flask API to run a backtest
 * - Polls for status and streams log output
 * - Renders equity curve / per-trade bar chart using Chart.js (CDN)
 * - Populates trade table and metric cards
 */

// ── Load Chart.js dynamically ─────────────────────────────────────────────
(function () {
  const s = document.createElement('script');
  s.src = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.2/dist/chart.umd.min.js';
  s.onload = () => { window._chartJsReady = true; };
  document.head.appendChild(s);
})();

// ── API base URL ──────────────────────────────────────────────────────────
const API = window.location.origin;   // same host as Flask server

// ── Condition definitions ─────────────────────────────────────────────────
const BUY_CONDITIONS = [
  { id: 'bcond1',  label: 'BCOND1',  tip: 'EMA50 > EMA200 (uptrend)',                  default: true  },
  { id: 'bcond2',  label: 'BCOND2',  tip: 'Buy Volume > vol-ratio x Sell Volume',       default: false },
  { id: 'bcond3',  label: 'BCOND3',  tip: 'RSI(14) < Oversold (do NOT combine w/ B10)', default: false },
  { id: 'bcond4',  label: 'BCOND4',  tip: 'Close crosses above Parabolic SAR',          default: false },
  { id: 'bcond5',  label: 'BCOND5',  tip: 'ADX(14) < threshold (non-trending)',         default: false },
  { id: 'bcond6',  label: 'BCOND6',  tip: 'PDI(14) > MDI(14)',                          default: false },
  { id: 'bcond7',  label: 'BCOND7',  tip: 'PDI(14) > pdi-threshold (strong uptrend)',   default: false },
  { id: 'bcond8',  label: 'BCOND8',  tip: 'Within 10% of 52-week high',                 default: false },
  { id: 'bcond9',  label: 'BCOND9',  tip: 'MACD(12,26) > 0 (bullish momentum)',         default: true  },
  { id: 'bcond10', label: 'BCOND10', tip: 'StochK > buy-thr (do NOT combine w/ B3)',    default: false },
  { id: 'bcond11', label: 'BCOND11', tip: 'Close > Parabolic SAR',                      default: false },
  { id: 'bcond12', label: 'BCOND12', tip: 'Close > Bollinger Band Mid',                 default: true  },
  { id: 'bcond13', label: 'BCOND13', tip: 'Big Gap Up (Low > 1+gap-pct x prev High)',   default: false },
];

const SELL_CONDITIONS = [
  { id: 'scond1',  label: 'SCOND1',  tip: 'EMA200 > EMA50 (trend reversal)',            default: true  },
  { id: 'scond2',  label: 'SCOND2',  tip: 'EMA13 crosses above EMA200',                 default: false },
  { id: 'scond3',  label: 'SCOND3',  tip: 'RSI(14) > Overbought threshold',             default: false },
  { id: 'scond5',  label: 'SCOND5',  tip: 'ADX(14) > threshold (strong trend)',         default: false },
  { id: 'scond6',  label: 'SCOND6',  tip: 'PDI(14) < MDI(14) (bears dominate)',         default: false },
  { id: 'scond7',  label: 'SCOND7',  tip: 'Price > l52w-margin above 52-week Low',      default: false },
  { id: 'scond9',  label: 'SCOND9',  tip: 'MACD(12,26) < 0 (bearish momentum)',         default: true  },
  { id: 'scond10', label: 'SCOND10', tip: 'StochK < sell threshold',                    default: false },
  { id: 'scond11', label: 'SCOND11', tip: 'EMA13 < EMA50 within ema-proximity',         default: false },
  { id: 'scond12', label: 'SCOND12', tip: 'Big Gap Down (High < 1-gap-pct x prev Low)', default: false },
];

// ── State ─────────────────────────────────────────────────────────────────
let _chart      = null;
let _chartMode  = 'pnl';   // 'pnl' | 'bar'
let _pollTimer  = null;
let _lastLog    = 0;        // index into log array for incremental display

// ── Init ──────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  buildToggles('buy-toggles',  BUY_CONDITIONS,  'buy');
  buildToggles('sell-toggles', SELL_CONDITIONS, 'sell');

  // Set default date range: End date = Today (or Friday if weekend), Start date = 7 years prior
  const now = new Date();
  const day = now.getDay();
  if (day === 6) now.setDate(now.getDate() - 1); // Sat -> Fri
  else if (day === 0) now.setDate(now.getDate() - 2); // Sun -> Fri

  const endStr = now.toISOString().split('T')[0];
  const startObj = new Date(now);
  startObj.setFullYear(now.getFullYear() - 6);  // default: latest 6 years of data
  const startStr = startObj.toISOString().split('T')[0];


  const startEl = document.getElementById('start-date');
  const endEl   = document.getElementById('end-date');
  if (startEl) startEl.value = startStr;
  if (endEl)   endEl.value   = endStr;
});

// ── Condition Toggle Builder ───────────────────────────────────────────────
function buildToggles(containerId, conditions, type) {
  const container = document.getElementById(containerId);
  conditions.forEach(c => {
    const div = document.createElement('div');
    div.className = 'cond-toggle cond-tooltip' + (c.default ? (type === 'buy' ? ' active' : ' sell-active') : '');
    div.id = `toggle-${c.id}`;
    div.setAttribute('data-tip', c.tip);
    div.setAttribute('data-id', c.id);
    div.setAttribute('data-type', type);
    div.innerHTML = `
      <input type="checkbox" id="chk-${c.id}" ${c.default ? 'checked' : ''} />
      <div class="cond-label">${c.label}</div>
      <div class="cond-pill"></div>
    `;
    div.addEventListener('click', () => toggleCondition(div, type));
    container.appendChild(div);
  });
}

function toggleCondition(div, type) {
  const chk = div.querySelector('input[type="checkbox"]');
  chk.checked = !chk.checked;
  const activeClass = type === 'buy' ? 'active' : 'sell-active';
  div.classList.toggle(activeClass, chk.checked);
}

// ── Utility: sync range slider label ─────────────────────────────────────
function syncRange(el, labelId, fmt) {
  const label = document.getElementById(labelId);
  if (!label) return;
  label.textContent = fmt ? fmt(el.value) : el.value;
}

// ── Collect all parameters from the form ──────────────────────────────────
function collectParams() {
  const g = id => document.getElementById(id);
  const v = id => g(id)?.value ?? '';
  const n = id => parseFloat(v(id)) || 0;
  const i = id => parseInt(v(id)) || 0;

  // Date split
  const startDate = v('start-date').split('-');
  const endDate   = v('end-date').split('-');

  const params = {
    'data-source':  v('data-source') || 'auto',
    ticker:         v('ticker').toUpperCase().trim() || 'GOOG',
    'start-year':   startDate[0] || '2016',
    'start-month':  startDate[1]?.replace(/^0/,'') || '1',
    'start-day':    startDate[2]?.replace(/^0/,'') || '1',
    'end-year':     endDate[0] || new Date().getFullYear().toString(),
    'end-month':    endDate[1]?.replace(/^0/,'') || '12',
    'end-day':      endDate[2]?.replace(/^0/,'') || '31',

    'initial-cash':  v('initial-cash') || '100000',
    'position-size': v('position-size') || '1.0',
    // EMA
    'ema13-period':  v('ema13-period')  || '13',
    'ema50-period':  v('ema50-period')  || '50',
    'ema200-period': v('ema200-period') || '200',
    'ema-proximity': v('ema-proximity') || '0.1',
    // RSI
    'rsi-period':     v('rsi-period')     || '14',
    'rsi-oversold':   v('rsi-oversold')   || '40',
    'rsi-overbought': v('rsi-overbought') || '65',
    // MACD
    'macd-fast':   v('macd-fast')   || '12',
    'macd-slow':   v('macd-slow')   || '26',
    'macd-signal': v('macd-signal') || '9',
    // Stochastic
    'stoch-period':   v('stoch-period')   || '14',
    'stoch-k':        v('stoch-k')        || '3',
    'stoch-buy-thr':  v('stoch-buy-thr')  || '70',
    'stoch-sell-thr': v('stoch-sell-thr') || '70',
    // ADX
    'adx-period':    v('adx-period')    || '14',
    'adx-threshold': v('adx-threshold') || '25',
    'pdi-threshold': v('pdi-threshold') || '30',
    // SAR
    'sar-acc':     v('sar-acc')     || '0.02',
    'sar-max-acc': v('sar-max-acc') || '0.2',
    // BB
    'bb-period': v('bb-period') || '15',
    'bb-width':  v('bb-width')  || '2',
    // Volume
    'avvol-period': v('avvol-period') || '5',
    'vol-ratio':    v('vol-ratio')    || '2',
    // 52-week
    'hwks52-period': '260',
    'lwks52-period': '260',
    'h52w-margin':   v('h52w-margin')   || '0.1',
    'l52w-margin':   v('l52w-margin')   || '0.3',
    // Gaps
    'gap-up-pct':   v('gap-up-pct')   || '0.02',
    'gap-down-pct': v('gap-down-pct') || '0.02',
  };

  // Buy condition toggles
  BUY_CONDITIONS.forEach(c => {
    const chk = document.getElementById(`chk-${c.id}`);
    params[c.id] = chk?.checked ? '1' : '0';
  });

  // Sell condition toggles
  SELL_CONDITIONS.forEach(c => {
    const chk = document.getElementById(`chk-${c.id}`);
    params[c.id] = chk?.checked ? '1' : '0';
  });

  return params;
}

// ── Run Backtest ──────────────────────────────────────────────────────────
async function runBacktest() {
  const btn = document.getElementById('btn-run');
  if (btn.disabled) return;

  const params = collectParams();

  // Validate dates
  const start = new Date(document.getElementById('start-date').value);
  const end   = new Date(document.getElementById('end-date').value);
  if (start >= end) {
    showToast('⚠️ Start date must be before end date', 'error');
    return;
  }

  // Check at least one buy and one sell condition is enabled
  const anyBuy  = BUY_CONDITIONS.some(c => document.getElementById(`chk-${c.id}`)?.checked);
  const anySell = SELL_CONDITIONS.some(c => document.getElementById(`chk-${c.id}`)?.checked);
  if (!anyBuy)  { showToast('⚠️ Enable at least one Buy condition', 'error'); return; }
  if (!anySell) { showToast('⚠️ Enable at least one Sell condition', 'error'); return; }

  // Update UI
  setStatus('running');
  btn.disabled = true;
  btn.textContent = '⏳ Running…';
  _lastLog = 0;
  clearLog();
  clearResults();
  setProgress(2);

  try {
    const res = await fetch(`${API}/api/run-backtest`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    });

    if (!res.ok && res.status !== 202) {
      const err = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
      throw new Error(err.error || 'Request failed');
    }

    const data = await res.json();
    if (data.log) {
      appendLog(data.log);
    }
    
    // Start polling status asynchronously
    startPolling();

  } catch (err) {
    setStatus('error');
    btn.disabled = false;
    btn.innerHTML = '<div class="btn-shimmer"></div>▶ Run Backtest';
    showToast(`❌ ${err.message}`, 'error');
  }
}

// ── Polling ───────────────────────────────────────────────────────────────
function startPolling() {
  if (_pollTimer) clearInterval(_pollTimer);
  _pollTimer = setInterval(pollStatus, 1500);
}

async function pollStatus() {
  try {
    const res  = await fetch(`${API}/api/status`);
    const data = await res.json();

    // Append new log lines
    const lines = data.logLines || [];
    if (lines.length > _lastLog) {
      const newLines = lines.slice(_lastLog);
      _lastLog = lines.length;
      appendLog(newLines);
    }

    // Update progress
    if (data.progress !== undefined) setProgress(data.progress);

    if (data.status === 'done') {
      clearInterval(_pollTimer);
      _pollTimer = null;
      setStatus('done');
      setProgress(100);
      document.getElementById('btn-run').disabled = false;
      document.getElementById('btn-run').innerHTML = '<div class="btn-shimmer"></div>▶ Run Backtest';
      showToast('🎉 Backtest complete!', 'success');
      await loadResults();

    } else if (data.status === 'error') {
      clearInterval(_pollTimer);
      _pollTimer = null;
      setStatus('error');
      document.getElementById('btn-run').disabled = false;
      document.getElementById('btn-run').innerHTML = '<div class="btn-shimmer"></div>▶ Run Backtest';
      showToast(`❌ ${data.error || 'LEAN run failed'}`, 'error');
    }

  } catch (err) {
    // Server not reachable — show a warning but keep polling
    appendLog([`⚠️  Cannot reach server: ${err.message}`]);
  }
}

async function loadResults() {
  const res  = await fetch(`${API}/api/results`);
  if (!res.ok) return;
  const data = await res.json();
  renderResults(data);
}

// ── Results rendering ─────────────────────────────────────────────────────
function renderResults(data) {
  if (!data || !data.trades) return;
  const trades = data.trades;
  const summary = data.summary || data;

  // Metric cards
  const totalPnl = trades.reduce((s, t) => s + t.pnl_pct, 0);
  setText('m-return',    (totalPnl >= 0 ? '+' : '') + totalPnl.toFixed(2) + '%');
  setText('m-winrate',   (summary.win_rate ?? 0) + '%');
  setText('m-trades',    summary.total_trades ?? 0);
  const avgWin = summary.avg_win_pct ?? 0;
  const avgLoss = summary.avg_loss_pct ?? 0;

  setText('m-avgwin',    (avgWin > 0 ? '+' : '') + avgWin + '%');
  setText('m-avgloss',   (avgLoss > 0 ? '+' : '') + avgLoss + '%');
  setText('m-return-sub',   `${summary.wins ?? 0} wins, ${summary.losses ?? 0} losses`);
  setText('m-winrate-sub',  `${summary.wins ?? 0} of ${summary.total_trades ?? 0} trades`);
  setText('m-trades-sub',   `${summary.wins ?? 0}W / ${summary.losses ?? 0}L`);

  // Color total return card
  const retEl = document.getElementById('m-return');
  retEl.classList.toggle('positive', totalPnl >= 0);
  retEl.classList.toggle('negative', totalPnl < 0);

  const avgWinEl = document.getElementById('m-avgwin');
  if (avgWinEl) {
    avgWinEl.classList.toggle('positive', avgWin >= 0);
    avgWinEl.classList.toggle('negative', avgWin < 0);
  }

  const avgLossEl = document.getElementById('m-avgloss');
  if (avgLossEl) {
    avgLossEl.classList.toggle('positive', avgLoss >= 0);
    avgLossEl.classList.toggle('negative', avgLoss < 0);
  }

  // Render chart
  renderChart(trades);

  // Render trade table
  const tbody = document.getElementById('trade-tbody');
  tbody.innerHTML = '';
  if (trades.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" style="text-align:center;padding:30px;color:var(--text-muted)">No completed round-trip trades found.</td></tr>`;
  } else {
    trades.forEach((t, i) => {
      const pos = t.pnl_pct >= 0;
      const row = document.createElement('tr');
      row.innerHTML = `
        <td style="color:var(--text-muted)">${i + 1}</td>
        <td>${t.buy_date}</td>
        <td style="font-family:'JetBrains Mono',monospace">${fmt$(t.buy_price)}</td>
        <td>${t.sell_date}</td>
        <td style="font-family:'JetBrains Mono',monospace">${fmt$(t.sell_price)}</td>
        <td class="${pos ? 'pnl-pos' : 'pnl-neg'}">${pos ? '+' : ''}${t.pnl_pct}%</td>
        <td style="font-size:0.68rem;color:var(--text-muted)">${(t.buy_conds||[]).join(', ')}</td>
        <td style="font-size:0.68rem;color:var(--text-muted)">${(t.sell_conds||[]).join(', ')}</td>
      `;
      tbody.appendChild(row);
    });
  }
  document.getElementById('trade-count').textContent = `${trades.length} trade${trades.length !== 1 ? 's' : ''}`;

  // Render Detailed Statistics Table
  if (data.stats) {
    renderStatisticsTable(data.stats);
  }

  // Hide empty state
  document.getElementById('chart-empty').style.display = 'none';
}

// ── AmiBroker Statistics Table renderer ───────────────────────────────────
function renderStatisticsTable(stats) {
  const tbody = document.getElementById('stats-tbody');
  if (!tbody || !stats) return;

  const a = stats.all   || {};
  const l = stats.long  || {};
  const s = stats.short || {};

  const fmtVal = (val, type = 'num') => {
    if (val === null || val === undefined || val === 'N/A') return '<span class="val-neutral">N/A</span>';
    if (typeof val === 'string') {
      if (val.includes('-')) return `<span class="val-neg">${val}</span>`;
      if (val.includes('%') && !val.startsWith('0.00')) return `<span class="val-pos">${val}</span>`;
      return val;
    }
    const num = parseFloat(val);
    if (isNaN(num)) return val;
    
    let cls = 'val-neutral';
    if (num > 0) cls = 'val-pos';
    else if (num < 0) cls = 'val-neg';

    if (type === 'curr') return `<span class="${cls}">${num < 0 ? '-' : ''}$${Math.abs(num).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}</span>`;
    if (type === 'pct')  return `<span class="${cls}">${num > 0 ? '+' : ''}${num.toFixed(2)}%</span>`;
    if (type === 'num')  return `<span class="${cls}">${num.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2})}</span>`;
    if (type === 'int')  return `<span class="${cls}">${num}</span>`;
    return `<span class="${cls}">${num}</span>`;
  };

  const rows = [
    // Header section 1
    { hdr: 'Capital & Profit' },
    { label: 'Initial capital',            a: fmtVal(a.initial_capital, 'curr'), l: fmtVal(l.initial_capital, 'curr'), s: fmtVal(s.initial_capital, 'curr') },
    { label: 'Ending capital',             a: fmtVal(a.ending_capital, 'curr'),  l: fmtVal(l.ending_capital, 'curr'),  s: fmtVal(s.ending_capital, 'curr') },
    { label: 'Net Profit',                 a: fmtVal(a.net_profit, 'curr'),      l: fmtVal(l.net_profit, 'curr'),      s: fmtVal(s.net_profit, 'curr') },
    { label: 'Net Profit %',               a: fmtVal(a.net_profit_pct, 'pct'),  l: fmtVal(l.net_profit_pct, 'pct'),  s: fmtVal(s.net_profit_pct, 'pct') },
    { label: 'Exposure %',                 a: fmtVal(a.exposure_pct, 'pct'),    l: fmtVal(l.exposure_pct, 'pct'),    s: fmtVal(s.exposure_pct, 'pct') },
    { label: 'Net Risk Adjusted Return %', a: fmtVal(a.net_rar_pct, 'pct'),     l: fmtVal(l.net_rar_pct, 'pct'),     s: fmtVal(s.net_rar_pct, 'pct') },
    { label: 'Annual Return %',            a: fmtVal(a.annual_return_pct, 'pct'), l: fmtVal(l.annual_return_pct, 'pct'), s: fmtVal(s.annual_return_pct, 'pct') },
    { label: 'Risk Adjusted Return %',     a: fmtVal(a.rar_pct, 'pct'),         l: fmtVal(l.rar_pct, 'pct'),         s: fmtVal(s.rar_pct, 'pct') },
    { label: 'Total transaction costs',    a: fmtVal(a.total_tx_costs, 'curr'), l: fmtVal(l.total_tx_costs, 'curr'), s: fmtVal(s.total_tx_costs, 'curr') },

    // Header section 2
    { hdr: 'All trades' },
    { label: 'All trades',                 a: fmtVal(a.total_trades, 'int'),    l: fmtVal(l.total_trades, 'int'),    s: fmtVal(s.total_trades, 'int') },
    { label: 'Avg. Profit/Loss',           a: fmtVal(a.avg_pnl, 'curr'),        l: fmtVal(l.avg_pnl, 'curr'),        s: fmtVal(s.avg_pnl, 'curr') },
    { label: 'Avg. Profit/Loss %',         a: fmtVal(a.avg_pnl_pct, 'pct'),    l: fmtVal(l.avg_pnl_pct, 'pct'),    s: fmtVal(s.avg_pnl_pct, 'pct') },
    { label: 'Avg. Bars Held',             a: fmtVal(a.avg_bars, 'num'),        l: fmtVal(l.avg_bars, 'num'),        s: fmtVal(s.avg_bars, 'num') },

    // Header section 3
    { hdr: 'Winners' },
    { label: 'Winners',                    a: fmtVal(a.win_rate_pct, 'str'),    l: fmtVal(l.win_rate_pct, 'str'),    s: fmtVal(s.win_rate_pct, 'str') },
    { label: 'Total Profit',               a: fmtVal(a.total_profit, 'curr'),   l: fmtVal(l.total_profit, 'curr'),   s: fmtVal(s.total_profit, 'curr') },
    { label: 'Avg. Profit',                a: fmtVal(a.avg_win, 'curr'),        l: fmtVal(l.avg_win, 'curr'),        s: fmtVal(s.avg_win, 'curr') },
    { label: 'Avg. Profit %',              a: fmtVal(a.avg_win_pct, 'pct'),     l: fmtVal(l.avg_win_pct, 'pct'),     s: fmtVal(s.avg_win_pct, 'pct') },
    { label: 'Avg. Bars Held',             a: fmtVal(a.win_avg_bars, 'num'),    l: fmtVal(l.win_avg_bars, 'num'),    s: fmtVal(s.win_avg_bars, 'num') },
    { label: 'Max. Consecutive',           a: fmtVal(a.max_consec_wins, 'int'), l: fmtVal(l.max_consec_wins, 'int'), s: fmtVal(s.max_consec_wins, 'int') },
    { label: 'Largest win',                a: fmtVal(a.largest_win, 'curr'),    l: fmtVal(l.largest_win, 'curr'),    s: fmtVal(s.largest_win, 'curr') },
    { label: '# bars in largest win',      a: fmtVal(a.largest_win_bars, 'int'), l: fmtVal(l.largest_win_bars, 'int'), s: fmtVal(s.largest_win_bars, 'int') },

    // Header section 4
    { hdr: 'Losers' },
    { label: 'Losers',                     a: fmtVal(a.loss_rate_pct, 'str'),   l: fmtVal(l.loss_rate_pct, 'str'),   s: fmtVal(s.loss_rate_pct, 'str') },
    { label: 'Total Loss',                 a: fmtVal(a.total_loss, 'curr'),     l: fmtVal(l.total_loss, 'curr'),     s: fmtVal(s.total_loss, 'curr') },
    { label: 'Avg. Loss',                  a: fmtVal(a.avg_loss, 'curr'),       l: fmtVal(l.avg_loss, 'curr'),       s: fmtVal(s.avg_loss, 'curr') },
    { label: 'Avg. Loss %',                a: fmtVal(a.avg_loss_pct, 'pct'),    l: fmtVal(l.avg_loss_pct, 'pct'),    s: fmtVal(s.avg_loss_pct, 'pct') },
    { label: 'Avg. Bars Held',             a: fmtVal(a.loss_avg_bars, 'num'),   l: fmtVal(l.loss_avg_bars, 'num'),   s: fmtVal(s.loss_avg_bars, 'num') },
    { label: 'Max. Consecutive',           a: fmtVal(a.max_consec_losses, 'int'), l: fmtVal(l.max_consec_losses, 'int'), s: fmtVal(s.max_consec_losses, 'int') },
    { label: 'Largest loss',               a: fmtVal(a.largest_loss, 'curr'),   l: fmtVal(l.largest_loss, 'curr'),   s: fmtVal(s.largest_loss, 'curr') },
    { label: '# bars in largest loss',     a: fmtVal(a.largest_loss_bars, 'int'), l: fmtVal(l.largest_loss_bars, 'int'), s: fmtVal(s.largest_loss_bars, 'int') },

    // Header section 5
    { hdr: 'Drawdown & Performance Ratios' },
    { label: 'Max. trade drawdown',        a: fmtVal(a.max_trade_dd, 'curr'),   l: fmtVal(l.max_trade_dd, 'curr'),   s: fmtVal(s.max_trade_dd, 'curr') },
    { label: 'Max. trade % drawdown',      a: fmtVal(a.max_trade_dd_pct, 'pct'), l: fmtVal(l.max_trade_dd_pct, 'pct'), s: fmtVal(s.max_trade_dd_pct, 'pct') },
    { label: 'Max. system drawdown',       a: fmtVal(a.max_sys_dd, 'curr'),     l: fmtVal(l.max_sys_dd, 'curr'),     s: fmtVal(s.max_sys_dd, 'curr') },
    { label: 'Max. system % drawdown',     a: fmtVal(a.max_sys_dd_pct, 'pct'),  l: fmtVal(l.max_sys_dd_pct, 'pct'),  s: fmtVal(s.max_sys_dd_pct, 'pct') },
    { label: 'Recovery Factor',            a: fmtVal(a.recovery_factor, 'num'), l: fmtVal(l.recovery_factor, 'num'), s: fmtVal(s.recovery_factor, 'num') },
    { label: 'CAR/MaxDD',                  a: fmtVal(a.car_max_dd, 'num'),      l: fmtVal(l.car_max_dd, 'num'),      s: fmtVal(s.car_max_dd, 'num') },
    { label: 'RAR/MaxDD',                  a: fmtVal(a.rar_max_dd, 'num'),      l: fmtVal(l.rar_max_dd, 'num'),      s: fmtVal(s.rar_max_dd, 'num') },
    { label: 'Profit Factor',              a: fmtVal(a.profit_factor, 'num'),   l: fmtVal(l.profit_factor, 'num'),   s: fmtVal(s.profit_factor, 'num') },
    { label: 'Payoff Ratio',               a: fmtVal(a.payoff_ratio, 'num'),    l: fmtVal(l.payoff_ratio, 'num'),    s: fmtVal(s.payoff_ratio, 'num') },
    { label: 'Standard Error',             a: fmtVal(a.std_error, 'num'),       l: fmtVal(l.std_error, 'num'),       s: fmtVal(s.std_error, 'num') },
    { label: 'Risk-Reward Ratio',          a: fmtVal(a.risk_reward_ratio, 'num'), l: fmtVal(l.risk_reward_ratio, 'num'), s: fmtVal(s.risk_reward_ratio, 'num') },
    { label: 'Ulcer Index',                a: fmtVal(a.ulcer_index, 'num'),     l: fmtVal(l.ulcer_index, 'num'),     s: fmtVal(s.ulcer_index, 'num') },
    { label: 'Ulcer Performance Index',    a: fmtVal(a.ulcer_perf_index, 'num'), l: fmtVal(l.ulcer_perf_index, 'num'), s: fmtVal(s.ulcer_perf_index, 'num') },
    { label: 'Sharpe Ratio of trades',     a: fmtVal(a.sharpe_ratio, 'num'),    l: fmtVal(l.sharpe_ratio, 'num'),    s: fmtVal(s.sharpe_ratio, 'num') },
    { label: 'K-Ratio',                    a: fmtVal(a.k_ratio, 'num'),         l: fmtVal(l.k_ratio, 'num'),         s: fmtVal(s.k_ratio, 'num') },
  ];

  let html = '';
  rows.forEach(r => {
    if (r.hdr) {
      html += `<tr class="stats-section-hdr"><td colspan="4">${r.hdr}</td></tr>`;
    } else {
      html += `<tr>
        <td class="stats-label-col">${r.label}</td>
        <td class="stats-val-col">${r.a}</td>
        <td class="stats-val-col">${r.l}</td>
        <td class="stats-val-col">${r.s}</td>
      </tr>`;
    }
  });

  tbody.innerHTML = html;
}


function fmt$(n) { return '$' + parseFloat(n || 0).toFixed(2); }

// ── Chart rendering ────────────────────────────────────────────────────────
function renderChart(trades) {
  if (!window._chartJsReady) { setTimeout(() => renderChart(trades), 200); return; }

  const canvas = document.getElementById('chart-main');
  if (_chart) { _chart.destroy(); _chart = null; }
  canvas.style.display = 'block';

  const ctx = canvas.getContext('2d');
  const gradient = ctx.createLinearGradient(0, 0, 0, canvas.height || 420);
  gradient.addColorStop(0, 'rgba(59, 130, 246, 0.35)');
  gradient.addColorStop(1, 'rgba(59, 130, 246, 0.00)');

  if (_chartMode === 'pnl') {
    // Cumulative PnL line
    let cum = 0;
    const labels = ['Start'];
    const values = [0];
    trades.forEach(t => {
      cum += t.pnl_pct;
      labels.push(t.sell_date);
      values.push(parseFloat(cum.toFixed(2)));
    });

    _chart = new Chart(canvas, {
      type: 'line',
      data: {
        labels,
        datasets: [{
          label: 'Cumulative PnL %',
          data: values,
          borderColor: '#3b82f6',
          backgroundColor: gradient,
          pointBackgroundColor: values.map(v => v >= 0 ? '#10b981' : '#f43f5e'),
          pointBorderColor: '#ffffff',
          pointBorderWidth: 1.5,
          pointRadius: 5,
          pointHoverRadius: 8,
          fill: true,
          tension: 0.25,
          borderWidth: 2.5,
        }],
      },
      options: chartOptions('Cumulative Return (%)', true),
    });

  } else if (_chartMode === 'bar') {
    // Per-trade bar

    const labels = trades.map((t, i) => `#${i+1} ${t.sell_date}`);
    const values = trades.map(t => t.pnl_pct);
    const colors = values.map(v => v >= 0 ? 'rgba(16,185,129,0.85)' : 'rgba(244,63,94,0.85)');

    _chart = new Chart(canvas, {
      type: 'bar',
      data: {
        labels,
        datasets: [{
          label: 'PnL % per trade',
          data: values,
          backgroundColor: colors,
          borderColor: colors.map(c => c.replace('0.85','1')),
          borderWidth: 1.5,
          borderRadius: 4,
          maxBarThickness: 45,
        }],
      },
      options: chartOptions('Per-Trade PnL (%)', false),
    });

  } else if (_chartMode === 'price') {
    // ── Buy / Sell Price scatter with hold-period connectors ────────────────
    // Build two interleaved timelines: one per trade with buy_date+buy_price
    // and sell_date+sell_price, and a third dataset drawing connector lines.
    const labels   = [];
    const buyData  = [];
    const sellData = [];
    const holdData = [];

    trades.forEach(t => {
      // BUY point
      labels.push(t.buy_date);
      buyData.push(parseFloat(t.buy_price));
      sellData.push(null);
      holdData.push(parseFloat(t.buy_price));

      // SELL point
      labels.push(t.sell_date);
      buyData.push(null);
      sellData.push(parseFloat(t.sell_price));
      holdData.push(parseFloat(t.sell_price));
    });

    _chart = new Chart(canvas, {
      type: 'line',
      data: {
        labels,
        datasets: [
          {
            // Hold-period connector: thin dashed line buy→sell for each trade
            label: 'Hold Period',
            data: holdData,
            borderColor: 'rgba(139,148,184,0.35)',
            borderWidth: 1.5,
            borderDash: [5, 5],
            pointRadius: 0,
            pointHoverRadius: 0,
            fill: false,
            tension: 0,
            spanGaps: false,
            order: 3,
          },
          {
            label: 'Buy Price',
            data: buyData,
            borderColor: '#10b981',
            backgroundColor: '#10b981',
            pointBackgroundColor: buyData.map((v, i) => {
              // colour by outcome: green if trade was profitable, amber if not
              const tradeIdx = Math.floor(i / 2);
              return (trades[tradeIdx]?.pnl_pct ?? 0) >= 0 ? '#10b981' : '#f59e0b';
            }),
            pointBorderColor: '#ffffff',
            pointBorderWidth: 2,
            pointRadius: buyData.map(v => v === null ? 0 : 9),
            pointHoverRadius: 13,
            pointStyle: 'triangle',
            showLine: false,
            spanGaps: false,
            order: 1,
          },
          {
            label: 'Sell Price',
            data: sellData,
            borderColor: '#f43f5e',
            backgroundColor: '#f43f5e',
            pointBackgroundColor: sellData.map((v, i) => {
              const tradeIdx = Math.floor(i / 2);
              return (trades[tradeIdx]?.pnl_pct ?? 0) >= 0 ? '#10b981' : '#f43f5e';
            }),
            pointBorderColor: '#ffffff',
            pointBorderWidth: 2,
            pointRadius: sellData.map(v => v === null ? 0 : 9),
            pointHoverRadius: 13,
            pointStyle: 'rectRot',
            showLine: false,
            spanGaps: false,
            order: 2,
          },
        ],
      },
      options: chartOptionsPriceAxis(trades),
    });
  }
}


function chartOptions(yLabel, hasArea) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 600, easing: 'easeInOutQuart' },
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: '#131c2e',
        borderColor: 'rgba(59,130,246,0.3)',
        borderWidth: 1,
        titleColor: '#8a9ab8',
        bodyColor: '#e8edf5',
        padding: 10,
        callbacks: {
          label: ctx => ` ${ctx.raw >= 0 ? '+' : ''}${ctx.raw}%`,
        },
      },
    },
    scales: {
      x: {
        grid: { color: 'rgba(255,255,255,0.04)', drawBorder: false },
        ticks: { 
          color: '#8a9ab8', 
          font: { size: 11, family: 'JetBrains Mono' }, 
          maxRotation: 35,
          autoSkip: true,
          maxTicksLimit: 14
        },
      },
      y: {
        beginAtZero: false,
        grace: '10%',
        grid: { color: 'rgba(255,255,255,0.06)', drawBorder: false },
        ticks: { 
          color: '#8a9ab8', 
          font: { size: 11, family: 'JetBrains Mono', weight: '500' },
          padding: 8,
          callback: v => (v >= 0 ? '+' : '') + Number(v).toFixed(1) + '%' 
        },
        title: { display: true, text: yLabel, color: '#8a9ab8', font: { size: 12, weight: '600' } },
      },
    },
  };
}

// ── Buy/Sell Price chart helpers ──────────────────────────────────────────
function chartOptionsPriceAxis(trades) {
  // Compute nice min/max for the price Y-axis
  const allPrices = trades.flatMap(t => [parseFloat(t.buy_price), parseFloat(t.sell_price)]);
  const minP = Math.min(...allPrices);
  const maxP = Math.max(...allPrices);
  const pad  = (maxP - minP) * 0.15 || maxP * 0.05;

  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 500, easing: 'easeInOutQuart' },
    plugins: {
      legend: {
        display: true,
        position: 'top',
        labels: {
          color: '#8a9ab8',
          usePointStyle: true,
          pointStyleWidth: 14,
          font: { size: 11, family: 'JetBrains Mono' },
          filter: item => item.text !== 'Hold Period',  // hide connector from legend
        },
      },
      tooltip: {
        backgroundColor: '#131c2e',
        borderColor: 'rgba(59,130,246,0.3)',
        borderWidth: 1,
        titleColor: '#8a9ab8',
        bodyColor: '#e8edf5',
        padding: 12,
        callbacks: {
          title: items => items[0]?.label ?? '',
          label: ctx => {
            if (ctx.raw === null || ctx.raw === undefined) return null;
            if (ctx.dataset.label === 'Hold Period') return null;
            const isBuy  = ctx.dataset.label === 'Buy Price';
            const icon   = isBuy ? '▲ Buy ' : '◆ Sell';
            const pnl    = (() => {
              // Find which trade this point belongs to
              const idx = Math.floor(ctx.dataIndex / 1);
              const t   = trades[Math.floor(ctx.dataIndex / 2)];
              if (!t) return '';
              const pct = t.pnl_pct;
              return `  PnL: ${pct >= 0 ? '+' : ''}${pct}%`;
            })();
            return ` ${icon}: ${parseFloat(ctx.raw).toFixed(2)}${pnl}`;
          },
        },
      },
    },
    scales: {
      x: {
        grid: { color: 'rgba(255,255,255,0.04)', drawBorder: false },
        ticks: {
          color: '#8a9ab8',
          font: { size: 11, family: 'JetBrains Mono' },
          maxRotation: 35,
          autoSkip: true,
          maxTicksLimit: 14,
        },
      },
      y: {
        min: minP - pad,
        max: maxP + pad,
        grid: { color: 'rgba(255,255,255,0.06)', drawBorder: false },
        ticks: {
          color: '#8a9ab8',
          font: { size: 11, family: 'JetBrains Mono', weight: '500' },
          padding: 8,
          callback: v => parseFloat(v).toFixed(2),
        },
        title: {
          display: true,
          text: 'Price',
          color: '#8a9ab8',
          font: { size: 12, weight: '600' },
        },
      },
    },
  };
}

// ── Tab switching ─────────────────────────────────────────────────────────
// ── Tab switching ─────────────────────────────────────────────────────────
function switchTab(mode) {
  _chartMode = mode;
  ['pnl', 'bar', 'price'].forEach(m => {
    document.getElementById(`tab-${m}`)?.classList.toggle('active', m === mode);
  });
  // Re-render with last data
  fetch(`${API}/api/results`)
    .then(r => r.ok ? r.json() : null)
    .then(d => { if (d?.trades) renderChart(d.trades); });
}


// ── Log helpers ───────────────────────────────────────────────────────────
function appendLog(lines) {
  const el = document.getElementById('log-console');
  lines.forEach(line => {
    const div = document.createElement('div');
    div.className = 'log-line' +
      (line.includes('BUY')   ? ' buy'  :
       line.includes('SELL')  ? ' sell' :
       line.includes('Error') || line.includes('❌') ? ' err' : '');
    div.textContent = line;
    el.appendChild(div);
  });
  el.scrollTop = el.scrollHeight;
}

function clearLog() {
  const el = document.getElementById('log-console');
  el.innerHTML = '';
  _lastLog = 0;
}

// ── Status helpers ────────────────────────────────────────────────────────
function setStatus(s) {
  const dot  = document.getElementById('status-dot');
  const text = document.getElementById('status-text');
  dot.className = 'status-dot ' + s;
  const MAP = {
    idle:    'Idle — configure and run a backtest',
    running: 'Running backtest…',
    done:    'Backtest complete ✅',
    error:   'Backtest failed ❌',
  };
  text.textContent = MAP[s] || s;
}

function setProgress(pct) {
  document.getElementById('progress-fill').style.width = Math.min(100, pct) + '%';
}

function clearResults() {
  ['m-return','m-winrate','m-trades','m-avgwin','m-avgloss'].forEach(id => {
    const el = document.getElementById(id);
    if (el) { el.textContent = '—'; el.className = 'metric-value'; }
  });
  document.getElementById('trade-tbody').innerHTML = `
    <tr><td colspan="8" style="text-align:center;padding:30px;color:var(--text-muted)">Running…</td></tr>`;
  document.getElementById('trade-count').textContent = '';
  document.getElementById('chart-empty').style.display = 'flex';
  const canvas = document.getElementById('chart-main');
  canvas.style.display = 'none';
  if (_chart) { _chart.destroy(); _chart = null; }
}

// ── Section collapse ──────────────────────────────────────────────────────
function toggleSection(header) {
  const body     = header.nextElementSibling;
  const chevron  = header.querySelector('.section-chevron');
  const collapsed = body.classList.toggle('hidden');
  chevron.classList.toggle('collapsed', collapsed);
}

// ── Toast ─────────────────────────────────────────────────────────────────
let _toastTimer = null;
function showToast(msg, type = 'success') {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = `show ${type}`;
  if (_toastTimer) clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => { el.className = ''; }, 4000);
}

// ── Helpers ───────────────────────────────────────────────────────────────
function setText(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}
