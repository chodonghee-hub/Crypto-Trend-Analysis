/**
 * 감성 게이지 및 뉴스 헤드라인 렌더링
 */

export function updateGauge(score, count) {
  const scoreEl = document.getElementById('gauge-score');
  const countEl = document.getElementById('gauge-count');
  const needle  = document.getElementById('gauge-needle');

  if (!scoreEl) return;

  const s = score ?? 0;
  scoreEl.textContent = (s >= 0 ? '+' : '') + s.toFixed(3);
  scoreEl.className = 'gauge-score ' + (s > 0.05 ? 'positive' : s < -0.05 ? 'negative' : 'neutral');

  if (countEl) countEl.textContent = count ?? 0;

  if (needle) {
    // score -1~+1 → 0~100%
    const pct = ((s + 1) / 2) * 100;
    needle.style.left = `${Math.max(2, Math.min(98, pct))}%`;
  }
}

export function renderNews(newsItems) {
  const container = document.getElementById('news-list');
  if (!container) return;

  if (!newsItems?.length) {
    container.innerHTML = `
      <div class="empty-state">
        <svg class="empty-state__icon" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
        </svg>
        <span>뉴스 데이터 없음</span>
      </div>`;
    return;
  }

  container.innerHTML = newsItems.map(item => {
    const bar  = item.sentiment_label || 'neutral';
    const score = typeof item.score === 'number'
      ? (item.score >= 0 ? '+' : '') + item.score.toFixed(2)
      : '—';
    const time = item.published_at
      ? new Date(item.published_at).toLocaleDateString('ko-KR', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
      : '';

    return `
      <a class="news-item" href="${item.url || '#'}" target="_blank" rel="noopener">
        <div class="news-item__bar news-item__bar--${bar}"></div>
        <div class="news-item__body">
          <div class="news-item__title">${escapeHtml(item.title || '')}</div>
          <div class="news-item__meta">
            <span>${escapeHtml(item.source || '')}</span>
            <span>${time}</span>
            <span class="badge badge--${bar === 'positive' ? 'up' : bar === 'negative' ? 'down' : ''}">${score}</span>
          </div>
        </div>
      </a>`;
  }).join('');
}

function escapeHtml(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
