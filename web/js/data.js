/**
 * 분석 데이터 로더.
 * localhost → FastAPI /api/data/analysis
 * 그 외     → ./data/snapshot.json (정적 스냅샷)
 */

const IS_LOCAL =
  location.hostname === 'localhost' || location.hostname === '127.0.0.1';

export async function loadAnalysisData({ retries = 3, baseDelay = 2000 } = {}) {
  const url = IS_LOCAL ? '/api/data/analysis' : './data/snapshot.json';
  let lastError;
  for (let attempt = 0; attempt < retries; attempt++) {
    if (attempt > 0) {
      await new Promise(r => setTimeout(r, baseDelay * attempt));
    }
    try {
      const res = await fetch(url);
      if (!res.ok) {
        lastError = new Error(`Analysis data fetch failed: ${res.status}`);
        continue;
      }
      return res.json();
    } catch (e) {
      lastError = e;
    }
  }
  throw lastError;
}
