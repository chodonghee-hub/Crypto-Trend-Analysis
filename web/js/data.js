/**
 * 분석 데이터 로더.
 * localhost → FastAPI /api/data/analysis
 * 그 외     → ./data/snapshot.json (정적 스냅샷)
 */

const IS_LOCAL =
  location.hostname === 'localhost' || location.hostname === '127.0.0.1';

export async function loadAnalysisData() {
  const url = IS_LOCAL ? '/api/data/analysis' : './data/snapshot.json';
  const res = await fetch(url);
  if (!res.ok) throw new Error(`Analysis data fetch failed: ${res.status}`);
  return res.json();
}
