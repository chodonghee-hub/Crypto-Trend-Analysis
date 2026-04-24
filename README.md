# Crypto Trend Analysis

글로벌 암호화폐 뉴스의 감성을 AI 모델로 수치화하고, 비트코인 가격 변동과의 시차별 상관관계를 분석하는 데이터 분석 프로젝트입니다.  
FinBERT와 Gemma를 앙상블하여 뉴스 감성을 정량화하고, 실시간 웹 대시보드로 시각화합니다.

---

## 핵심 가설

> **"해외 전문 미디어의 긍정적 뉴스는 발행 후 15분 이내에 BTC 가격 상승을 유도한다."**

뉴스 헤드라인 + 본문을 FinBERT + Gemma 앙상블로 감성 수치화하고,  
Binance 1분 캔들 데이터와 시계열 정렬하여 **T+5m / T+15m / T+30m / T+60m** 구간의 피어슨 상관계수와 방향 예측 적중률을 도출합니다.

---

## 기술 스택

| 구분 | 기술 |
|------|------|
| 언어 | Python 3.9+, JavaScript (ES2020) |
| 백엔드 | FastAPI + uvicorn |
| 프론트엔드 | Vite + Vanilla JS, Chart.js v4 |
| NLP 모델 | FinBERT (`ProsusAI/finbert`), Gemma 3 (`gemma3:1b` via Ollama) |
| 데이터 처리 | pandas, numpy, pyarrow |
| 통계 분석 | scipy (Pearson r), statsmodels, sklearn |
| 시각화 | matplotlib, seaborn |
| 가격 데이터 | Binance REST API |
| 뉴스 데이터 | CryptoCompare API, CoinGecko API, RSS (feedparser) |

---

## 프로젝트 구조

```
Crypto-Trend-Analysis/
├── notebooks/
│   ├── 01_data_collection.ipynb           # 뉴스 & 가격 수집
│   ├── 02_sentiment_scoring.ipynb         # FinBERT + Gemma 감성 분석
│   ├── 03_correlation_analysis.ipynb      # 시차별 상관관계 분석
│   ├── 04_visualization.ipynb             # matplotlib 대시보드 생성
│   ├── 05_cryptocompare_api.ipynb         # CryptoCompare API 통합
│   └── 06_ensemble_price_prediction.ipynb # 앙상블 가중치 비교 & 예측 적중률
├── src/
│   ├── collector.py                       # 뉴스 & 가격 데이터 수집
│   ├── sentiment.py                       # FinBERT + Gemma 앙상블 추론
│   ├── analyzer.py                        # 상관관계 및 수익률 계산
│   └── visualizer.py                      # matplotlib 6-zone 대시보드
├── web/
│   ├── index.html
│   ├── css/                               # 디자인 토큰, 레이아웃, 컴포넌트
│   ├── js/                                # api, charts, sentiment, correlation, poll
│   └── data/snapshot.json                 # 파이프라인 후 생성 (정적 배포용)
├── scripts/
│   └── export_snapshot.py                 # CSV → snapshot.json 변환
├── data/
│   ├── raw/                               # 월별 뉴스 CSV, BTC 가격 Parquet
│   └── processed/                         # 감성 점수, 병합 분석 결과
├── output/                                # matplotlib PNG (1D/7D/1M/3M)
├── server.py                              # FastAPI 서버
├── requirements.txt
└── .env.example
```

---

## 데이터 파이프라인

```
┌─────────────────────────────────────────────────────────────────────┐
│  Step 1. 데이터 수집                                                 │
│                                                                      │
│  Binance REST API          CryptoCompare API          RSS 피드       │
│  (BTC/USDT 1min·1h 캔들)   (뉴스 + 본문 포함)    (CoinDesk 등)    │
│         │                          │                     │           │
│         ▼                          ▼                     ▼           │
│   data/raw/*.parquet         data/raw/*.csv        data/raw/*.csv   │
│   (월별 분할 저장)            (월별 분할 저장)     (월별 분할 저장) │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Step 2. 감성 분석 (sentiment.py)                                    │
│                                                                      │
│  title + body[:512]                                                  │
│        │                                                             │
│        ├──▶ FinBERT (ProsusAI/finbert)  ← CPU/GPU 자동 감지        │
│        │    → finbert_score = P(positive) - P(negative)             │
│        │                                                             │
│        └──▶ Gemma 3 1b (Ollama HTTP API)  ← 미실행 시 폴백        │
│             → gemma_score (positive/neutral/negative → 확률 매핑)   │
│                                                                      │
│        앙상블 결합 → ensemble_score, agreement_score, is_valid      │
│                                                                      │
│   data/processed/news_sentiment.csv                                  │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Step 3. 상관관계 분석 (analyzer.py)                                 │
│                                                                      │
│  news_sentiment.csv           btc_1m_*.parquet                      │
│        │                            │                                │
│        ▼                            ▼                                │
│  5분 윈도우 신뢰도 가중집계    T+5m/15m/30m/60m 수익률 계산         │
│        │                            │                                │
│        └──────────┬─────────────────┘                               │
│                   ▼                                                  │
│         Pearson 상관계수 + 방향 예측 적중률                          │
│                                                                      │
│   data/processed/merged_analysis.csv                                 │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Step 4. 시각화 & 배포                                               │
│                                                                      │
│  matplotlib 대시보드 PNG           웹 대시보드 (Vite + FastAPI)     │
│  output/dashboard_{1D/7D/1M/3M}   http://localhost:5173             │
│  .png                              60초 자동 갱신 폴링              │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 핵심 알고리즘 및 수식

### 1. FinBERT — 금융 특화 감성 분석

**모델**: `ProsusAI/finbert` (BERT 기반, 금융 뉴스 fine-tuned, ~110M 파라미터)  
**입력**: 뉴스 헤드라인 + 본문 앞 512 토큰  
**출력**: 세 클래스의 소프트맥스 확률 — P(positive), P(neutral), P(negative), 합계 = 1

**감성 점수** (범위: −1 ~ +1):

```
finbert_score = P(positive) - P(negative)
```

> 예시: P(pos)=0.86, P(neu)=0.12, P(neg)=0.02 → score = **+0.84**

---

### 2. Gemma 3 — 프롬프트 기반 감성 분류

**모델**: `gemma3:1b` (Google, Ollama로 로컬 실행)  
**방식**: 제로샷 프롬프트 → 단일 레이블 출력

```
Classify the sentiment of the following cryptocurrency news headline.
Respond with ONLY one word: positive, neutral, or negative.

Headline: "{headline}"
Sentiment:
```

**레이블 → 확률 매핑**:

| 출력 레이블 | P(positive) | P(neutral) | P(negative) | gemma_score |
|------------|-------------|------------|-------------|-------------|
| positive   | 0.90        | 0.05       | 0.05        | **+0.85**   |
| neutral    | 0.05        | 0.90       | 0.05        | **0.00**    |
| negative   | 0.05        | 0.05       | 0.90        | **−0.85**   |

```
gemma_score = P(positive) - P(negative)
```

---

### 3. 앙상블 결합

두 모델을 가중 평균으로 결합하여 단일 모델의 편향을 보완합니다.

**앙상블 점수** (기본값 α = 0.5, `.env`의 `FINBERT_WEIGHT`로 조정):

```
ensemble_score = α × finbert_score + (1 - α) × gemma_score
```

**합의 점수** — 두 모델의 신뢰도 지표 (범위: 0 ~ 1):

```
agreement_score = 1 - |finbert_score - gemma_score| / 2
```

- `agreement_score >= 0.7` → **고신뢰(High Confidence)** 신호

**중립 필터** — 감성이 모호한 기사를 상관관계 분석에서 제외:

```
is_valid = NOT (P(neutral) >= 0.5  OR  |P(pos) - P(neg)| < 0.15)
```

---

### 4. 5분 윈도우 신뢰도 가중집계

같은 5분 구간 내 여러 기사를 집계할 때, 확신도가 높은 기사에 더 큰 가중치를 부여합니다.

**신뢰도** — 중립에 가까울수록 낮아져 영향이 줄어듦:

```
confidence_i = max(P_i(positive), P_i(negative))
```

**윈도우 감성 점수**:

$$W = \frac{\sum_{i} s_i \cdot c_i}{\sum_{i} c_i}$$

> `s_i` = 기사 i의 감성 점수, `c_i` = 기사 i의 신뢰도

> 예시:  
> 기사 A: score=+0.8, confidence=0.9 → 기여도 0.72  
> 기사 B: score=−0.3, confidence=0.4 → 기여도 −0.12  
> W = (0.72 − 0.12) / (0.9 + 0.4) ≈ **+0.46**

---

### 5. BTC 가격 수익률 계산

1분 캔들의 종가를 기준으로 기사 발행 시점 이후 N분 수익률을 계산합니다.

$$r_{+N} = \frac{close_{t+N} - close_{t}}{close_{t}} \times 100\ (\%)$$

분석 구간: T+5분, T+15분, T+30분, T+60분

---

### 6. 피어슨 상관계수 분석   `보류`

감성 점수($x$)와 가격 수익률($y$) 사이의 선형 상관도를 측정합니다.

$$r = \frac{\sum_{i}(x_i - \bar{x})(y_i - \bar{y})}{\sqrt{\sum_{i}(x_i - \bar{x})^2} \cdot \sqrt{\sum_{i}(y_i - \bar{y})^2}}$$

- 범위: −1 (완전 음의 상관) ~ +1 (완전 양의 상관)
- **p-value < 0.05** 인 경우 통계적으로 유의

| r 범위 | 해석 |
|--------|------|
| 0.5 이상 | 강한 양의 상관 |
| 0.3 ~ 0.5 | 중간 양의 상관 |
| 0.1 ~ 0.3 | 약한 양의 상관 |
| −0.1 ~ 0.1 | 상관 없음 |
| −0.3 이하 | 음의 상관 |

---

### 7. 방향 예측 적중률 (Direction Accuracy)  `보류`

감성 점수의 부호로 가격 방향(상승/하락)을 예측하고 실제 방향과 비교합니다.

```
예측 방향:  ŷ = 1 (상승) if ensemble_score > 0,  else 0 (하락)
실제 방향:  y = 1 (상승) if return_+Nm   > 0,  else 0 (하락)
```

**평가 지표**:

$$\text{Accuracy} = \frac{\sum \mathbf{1}[\hat{y}_i = y_i]}{N} \times 100\ (\%)$$

$$\text{Precision} = \frac{TP}{TP + FP}, \qquad \text{Recall} = \frac{TP}{TP + FN}$$

$$F_1 = \frac{2 \cdot \text{Precision} \cdot \text{Recall}}{\text{Precision} + \text{Recall}}$$

**기준선 (Baseline)**: 50% — 무작위 예측(동전 던지기) 수준  
기준선 대비 **+5%p 이상** 이면 유의미한 예측력으로 판단합니다.

---

### 8. 최적 앙상블 가중치 탐색

FinBERT:Gemma 비율 5가지를 전수 탐색하여 가장 높은 평균 적중률을 보이는 가중치를 선정합니다.

| 비율 레이블 | α (FinBERT) | 1−α (Gemma) |
|------------|-------------|-------------|
| F0:G100    | 0.00        | 1.00        |
| F25:G75    | 0.25        | 0.75        |
| F50:G50    | 0.50        | 0.50        |
| F75:G25    | 0.75        | 0.25        |
| F100:G0    | 1.00        | 0.00        |

각 비율별로 T+5m/15m/30m/60m 적중률을 계산하고, 4개 시간대 **평균 적중률이 최대인 비율**을 최적 가중치로 선정합니다.

$$\alpha^* = \underset{\alpha}{\arg\max}\ \frac{1}{4}\sum_{\tau \in \{5,\, 15,\, 30,\, 60\}} \text{Acc}_\tau(\alpha)$$

<div align=center>
    <img width="1473" height="456" alt="image" src="https://github.com/user-attachments/assets/76f6da51-1b7c-4c79-a7d3-01f9dc250262" />
</div>

---

## 감성 분석 파이프라인 상세

```
뉴스 CSV (title + body)
        │
        ▼
  prepare_texts()          # title + body[:512] 결합
        │
        ├──▶ score_headlines()       # FinBERT 배치 추론 (batch_size=64)
        │         → finbert_score ∈ [-1, +1]
        │
        └──▶ score_headlines_gemma() # Gemma 순차 추론 (Ollama API)
                  → gemma_score ∈ {+0.85, 0.00, -0.85}
                          │
                          ▼
              combine_ensemble()
                  ensemble_score   = α·FB + (1-α)·GM
                  agreement_score  = 1 - |FB - GM| / 2
                  is_valid         = 중립 필터 적용
                  sentiment_label  = positive / negative
                          │
                          ▼
          data/processed/news_sentiment.csv
```

---

## 웹 대시보드 구성

| 영역 | 내용 | 데이터 소스 |
|------|------|------------|
| Zone A | BTC 현재가, 24h 변동률, 타임프레임 전환 | Binance API (실시간) |
| Zone B | 가격 + 감성 오버레이 듀얼 축 차트 | Binance + snapshot.json |
| Zone C | ATH, 기간별 변동률, 24h 가격 범위 바 | Binance API (실시간) |
| Zone D | 시가총액, 거래량, 공급량, 공포탐욕지수 | CoinGecko API (실시간) |
| Zone E | 감성 점수 vs 수익률 산점도 (T+15m/60m) | snapshot.json |
| Zone F | 시간 지연별 상관계수 바 차트 | snapshot.json |
| Sidebar | 감성 게이지, 최근 뉴스 목록 | snapshot.json + CoinGecko |

60초마다 Binance/CoinGecko API를 자동 폴링합니다.

---

## 시작하기

### 전제 조건

- Python 3.9 이상
- Node.js 18 이상
- Ollama (Gemma 사용 시): [ollama.ai](https://ollama.ai)

### 설치

```bash
# Python 패키지
pip install -r requirements.txt

# Node.js 패키지
npm install

# 환경 변수 설정
cp .env.example .env
```

`.env` 설정:

```env
CRYPTOCOMPARE_API_KEY=your_key_here   # https://min-api.cryptocompare.com
FINBERT_WEIGHT=0.5
GEMMA_WEIGHT=0.5
GEMMA_MODEL_ID=gemma3:1b
OLLAMA_HOST=http://localhost:11434
```

> CoinGecko News API와 Binance API는 **API 키 불필요**.

### Gemma 실행 (선택)

```bash
# Ollama 설치 후
ollama pull gemma3:1b
# Ollama는 백그라운드에서 자동 실행됩니다
```

Ollama 미실행 시 **FinBERT 단독 모드**로 자동 전환됩니다.

---

## 실행 순서

```
Step 1  데이터 수집       →  notebooks/01_data_collection.ipynb
Step 2  감성 분석         →  notebooks/02_sentiment_scoring.ipynb
Step 3  상관관계 분석     →  notebooks/03_correlation_analysis.ipynb
Step 4  스냅샷 생성       →  python scripts/export_snapshot.py
Step 5  대시보드 실행     →  아래 참조
```

### Step 5 — 웹 대시보드 실행

**개발 모드** (HMR 지원):

```bash
# 터미널 1 — FastAPI 백엔드
python -m uvicorn server:app --reload --port 8080

# 터미널 2 — Vite 개발 서버
npm run dev
```

- 대시보드: `http://localhost:5173`
- API 문서: `http://localhost:8080/docs`

**배포 모드** (FastAPI 단독):

```bash
npm run build
python -m uvicorn server:app --port 8080
# 대시보드: http://localhost:8080
```

---

## 분석 결과물

| 파일 | 내용 |
|------|------|
| `data/processed/news_sentiment.csv` | 기사별 FinBERT / Gemma / 앙상블 점수 전체 |
| `data/processed/merged_analysis.csv` | 감성 점수 + T+5/15/30/60m 수익률 병합 데이터 |
| `web/data/snapshot.json` | 웹 대시보드용 정적 스냅샷 |
| `output/dashboard_*.png` | matplotlib 정적 대시보드 (1D/7D/1M/3M) |

---

## 문제 해결

| 증상 | 원인 | 해결 |
|------|------|------|
| `ModuleNotFoundError: pandas` | 다른 Python 환경 | `python -m uvicorn` 사용 |
| Zone E/F 빈 화면 | snapshot.json 미생성 | `python scripts/export_snapshot.py` 실행 후 `npm run build` |
| `Address already in use` | 포트 충돌 | `--port 8081` 등 다른 포트 사용 |
| CoinGecko 429 오류 | 분당 30회 초과 | 잠시 대기 (파이프라인에 자동 backoff 적용됨) |
| FinBERT 메모리 부족 | RAM < 8GB | 노트북의 `batch_size`를 16 이하로 조정 |
| Gemma 분석이 끝나지 않음 | GPU 없이 CPU 추론 | `GEMMA_SAMPLE_CAP` 조정 또는 Ollama GPU 가속 활성화 |

---

## 참조 문서

### 분석 노트북

| 노트북 | 설명 |
|--------|------|
| [notebooks/01_data_collection.ipynb](notebooks/01_data_collection.ipynb) | Binance 1분·1시간 캔들, CryptoCompare/CoinGecko/RSS 뉴스 수집 및 월별 저장 |
| [notebooks/02_sentiment_scoring.ipynb](notebooks/02_sentiment_scoring.ipynb) | FinBERT + Gemma 앙상블로 뉴스 감성 점수화, 중립 필터 적용 |
| [notebooks/03_correlation_analysis.ipynb](notebooks/03_correlation_analysis.ipynb) | 5분 윈도우 감성 집계 → T+5/15/30/60m 수익률과 피어슨 상관계수 도출 |
| [notebooks/04_visualization.ipynb](notebooks/04_visualization.ipynb) | matplotlib 6-zone 대시보드 PNG 생성 (가격·감성·상관계수·산점도) |
| [notebooks/05_cryptocompare_api.ipynb](notebooks/05_cryptocompare_api.ipynb) | CryptoCompare API 키 설정, 본문 포함 뉴스 수집 및 저장 파이프라인 검증 |
| [notebooks/06_ensemble_price_prediction.ipynb](notebooks/06_ensemble_price_prediction.ipynb) | FinBERT:Gemma 가중치 5종 비교, 시간대별 방향 예측 적중률 분석 및 최적 가중치 선정 |