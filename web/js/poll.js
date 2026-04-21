/**
 * 커뮤니티 투표 — localStorage 유지
 */

const STORAGE_KEY = 'btc_poll_v1';

function loadState() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY)) || { bull: 0, bear: 0, voted: null };
  } catch {
    return { bull: 0, bear: 0, voted: null };
  }
}

function saveState(state) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

function render(state) {
  const total = state.bull + state.bear;
  const bullPct = total ? Math.round((state.bull / total) * 100) : 50;
  const bearPct = 100 - bullPct;

  const bullBtn = document.getElementById('poll-bull');
  const bearBtn = document.getElementById('poll-bear');
  if (bullBtn && bearBtn) {
    bullBtn.classList.toggle('voted-bullish', state.voted === 'bull');
    bearBtn.classList.toggle('voted-bearish', state.voted === 'bear');
    bullBtn.classList.toggle('disabled', state.voted !== null);
    bearBtn.classList.toggle('disabled', state.voted !== null);
  }

  const bullBar  = document.getElementById('poll-bull-bar');
  const bearBar  = document.getElementById('poll-bear-bar');
  const bullPctEl = document.getElementById('poll-bull-pct');
  const bearPctEl = document.getElementById('poll-bear-pct');
  const totalEl  = document.getElementById('poll-total');

  if (bullBar)   bullBar.style.width  = `${bullPct}%`;
  if (bearBar)   bearBar.style.width  = `${bearPct}%`;
  if (bullPctEl) bullPctEl.textContent = `${bullPct}%`;
  if (bearPctEl) bearPctEl.textContent = `${bearPct}%`;
  if (totalEl)   totalEl.textContent  = `${total.toLocaleString()} votes`;
}

export function initPoll() {
  const state = loadState();
  render(state);

  document.getElementById('poll-bull')?.addEventListener('click', () => {
    const s = loadState();
    if (s.voted) return;
    s.bull += 1;
    s.voted = 'bull';
    saveState(s);
    render(s);
  });

  document.getElementById('poll-bear')?.addEventListener('click', () => {
    const s = loadState();
    if (s.voted) return;
    s.bear += 1;
    s.voted = 'bear';
    saveState(s);
    render(s);
  });
}
