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

FinBERT는 수만 건의 금융 뉴스로 훈련된 AI로, 문장을 읽고 **긍정(positive) / 중립(neutral) / 부정(negative)** 세 가지 감성에 대한 확률을 출력합니다. 세 확률의 합은 항상 1(100%)입니다.

```
출력 예시: P(positive)=0.86  P(neutral)=0.12  P(negative)=0.02
```

**감성 점수** — "얼마나 긍정적인가"를 −1 ~ +1 사이 숫자 하나로 표현:

```
finbert_score = P(positive) - P(negative)
```

> ### *Key Points* <br>
> * 긍정 확률에서 부정 확률을 빼는 것입니다.  
> * 긍정이 압도적이면 +1에 가깝고, 부정이 압도적이면 −1에 가깝고, 둘이 비슷하면 0에 가깝습니다.  
> * 위 예시: 0.86 − 0.02 = **+0.84** (매우 긍정적인 뉴스)

---

### 2. Gemma 3 — 프롬프트 기반 감성 분류

**모델**: `gemma3:1b` (Google, 내 컴퓨터에서 Ollama로 로컬 실행)  

Gemma는 Google이 만든 소형 언어 모델입니다. FinBERT와 달리 **질문을 던지면 답을 말하는 방식**으로 작동합니다. 아래처럼 뉴스 헤드라인을 주고, 한 단어로만 감성을 답하도록 지시합니다.

```
Classify the sentiment of the following cryptocurrency news headline.
Respond with ONLY one word: positive, neutral, or negative.

Headline: "{headline}"
Sentiment:
```

Gemma가 "positive"라고 답하면, 이를 확률 숫자로 변환합니다.

**레이블 → 확률 매핑** — Gemma의 답변을 FinBERT와 같은 형식의 숫자로 통일:

| Gemma 답변 | 긍정 확률 | 중립 확률 | 부정 확률 | gemma_score |
|-----------|----------|----------|----------|-------------|
| positive  | 0.90     | 0.05     | 0.05     | **+0.85**   |
| neutral   | 0.05     | 0.90     | 0.05     | **0.00**    |
| negative  | 0.05     | 0.05     | 0.90     | **−0.85**   |

```
gemma_score = P(positive) - P(negative)
```

> ### *Key Points* <br>
> * Gemma는 "긍정이에요/중립이에요/부정이에요" 중 하나만 답합니다.  
> * FinBERT처럼 세밀한 확률 대신 확정적 답변이라서, 점수가 항상 +0.85 / 0 / −0.85 세 값 중 하나입니다.  
> * FinBERT가 금융 전문 용어에 강하고, Gemma는 문맥과 뉘앙스 파악에 강해서 두 모델을 함께 씁니다.

---

### 3. 앙상블 결합

두 모델을 합쳐서 **더 믿을 수 있는 하나의 점수**를 만듭니다.

**앙상블 점수** (기본값 50:50, `.env`의 `FINBERT_WEIGHT`로 비율 조정 가능):

```
ensemble_score = α × finbert_score + (1 - α) × gemma_score
```

> ### *Key Points* <br>
> * 두 모델 점수의 가중 평균입니다. α=0.5이면 정확히 반반 평균입니다.  
> * FinBERT가 +0.8, Gemma가 +0.6이면 → 앙상블 = 0.5×0.8 + 0.5×0.6 = **+0.70**  
> * 한 모델이 실수해도 다른 모델이 보완해주는 효과가 있습니다.

**합의 점수** — 두 모델이 얼마나 같은 의견인지를 0 ~ 1로 나타냄:

```
agreement_score = 1 - |finbert_score - gemma_score| / 2
```

> ### *Key Points* <br>
> * 두 점수의 차이가 클수록 0에 가깝고, 두 모델이 완전히 동의하면 1입니다.  
> * FinBERT=+0.8, Gemma=+0.7 → 차이=0.1 → agreement = 1 − 0.05 = **0.95** (매우 일치)  
> * FinBERT=+0.8, Gemma=−0.6 → 차이=1.4 → agreement = 1 − 0.7 = **0.30** (불일치, 신뢰도 낮음)  
> * `agreement_score >= 0.7` 인 경우만 **고신뢰(High Confidence)** 신호로 분류합니다.

**중립 필터** — 애매한 기사는 분석에서 제외:

```
is_valid = NOT (P(neutral) >= 0.5  OR  |P(pos) - P(neg)| < 0.15)
```

> *Key Points*: 두 조건 중 하나라도 해당하면 그 기사는 분석에서 뺍니다.  
> 1. 중립 확률이 50% 이상 → 감성이 뚜렷하지 않은 뉴스 (예: 단순 시황 보도)  
> 2. 긍정과 부정 확률의 차이가 15% 미만 → 긍정인지 부정인지 모호한 뉴스  
> 노이즈를 걸러내어 상관관계 분석의 신뢰성을 높이기 위한 장치입니다.

---

### 4. 5분 윈도우 신뢰도 가중집계

같은 5분 안에 뉴스가 여러 건 발행될 수 있습니다. 이를 하나의 감성 신호로 합칠 때, **확신이 강한 기사일수록 더 큰 영향**을 주도록 계산합니다.

**신뢰도** — 모델이 얼마나 확신하는지를 나타내는 값:

```
confidence = max(P(positive), P(negative))
```

> ### *Key Points* <br>
> * 긍정 확률과 부정 확률 중 큰 값을 신뢰도로 씁니다.  
> * "긍정 90%, 부정 5%" → 신뢰도 0.90 (매우 확신)  
> * "긍정 40%, 부정 35%" → 신뢰도 0.40 (애매함)  
> * 중립에 가까운 기사는 신뢰도가 낮아 자동으로 영향력이 줄어듭니다.

**윈도우 감성 점수** — 신뢰도를 가중치로 쓴 평균:

$$W = \frac{\sum_{i} s_i \cdot c_i}{\sum_{i} c_i}$$

> `s_i` = i번째 기사의 감성 점수, `c_i` = i번째 기사의 신뢰도

> ### *Key Points* <br>
> * 단순 평균과 달리, 확신이 강한 기사가 결과에 더 많이 반영됩니다.  
> * 마치 시험에서 "자신 있는 문제"에 더 많은 가중치를 두는 것과 같습니다.
>
> 구체적 예시 (5분 구간에 기사 2건):
> - 기사 A: score=**+0.8**, confidence=**0.9** → 기여도 = 0.8 × 0.9 = 0.72
> - 기사 B: score=**−0.3**, confidence=**0.4** → 기여도 = −0.3 × 0.4 = −0.12
> - 윈도우 점수 W = (0.72 − 0.12) / (0.9 + 0.4) = 0.60 / 1.30 ≈ **+0.46**
>
> 단순 평균이었다면 (0.8 − 0.3) / 2 = **+0.25** 였겠지만,  
> 기사 A가 훨씬 확신이 강하므로 가중집계 결과는 더 긍정 쪽으로 기웁니다.

---

### 5. BTC 가격 수익률 계산

뉴스가 발행된 시점을 기준으로, 이후 몇 분 뒤에 가격이 얼마나 변했는지 계산합니다.

$$r_{+N} = \frac{close_{t+N} - close_{t}}{close_{t}} \times 100\ (\%)$$

> ### *Key Points* <br>
> (N분 후 가격 − 현재 가격) ÷ 현재 가격 × 100 입니다.  
> * 현재 가격이 100만원, 15분 후 가격이 101만원이면 → **+1.0%**  
> * 현재 가격이 100만원, 15분 후 가격이 99만원이면 → **−1.0%**
>
> * 이 계산을 T+5분, T+15분, T+30분, T+60분 4개 구간에 대해 각각 수행합니다.  
> * "뉴스가 나온 뒤 몇 분 만에 가격 반응이 가장 잘 나타나는가"를 알아내기 위해서입니다.

---

### 6. 피어슨 상관계수 분석

감성 점수와 가격 수익률이 **함께 움직이는 경향**이 있는지를 −1 ~ +1 사이 숫자로 측정합니다.

$$r = \frac{\sum_{i}(x_i - \bar{x})(y_i - \bar{y})}{\sqrt{\sum_{i}(x_i - \bar{x})^2} \cdot \sqrt{\sum_{i}(y_i - \bar{y})^2}}$$

> `x` = 감성 점수, `y` = 가격 수익률, `x̄` = x의 평균, `ȳ` = y의 평균

> ### *Key Points* <br>
> "감성 점수가 높은 날일수록 가격도 오르는가?"를 통계적으로 수치화한 것입니다.  
> - **r = +1**: 감성이 좋으면 가격이 항상 오름 (완벽한 양의 상관)  
> - **r = 0**: 감성과 가격은 아무 관계 없음  
> - **r = −1**: 감성이 좋으면 오히려 가격이 내림 (완벽한 음의 상관)  
>
> 또한 **p-value**라는 지표로 "이 결과가 우연이 아닐 확률"을 검증합니다.  
> p-value < 0.05 이면 "95% 이상 확률로 우연이 아닌 진짜 경향"으로 판단합니다.

| r 값 | 의미 |
|------|------|
| +0.5 이상 | 감성↑ 이면 가격도 꽤 오르는 경향 |
| +0.3 ~ +0.5 | 약간의 양의 관계 |
| −0.1 ~ +0.1 | 거의 무관 |
| −0.3 이하 | 오히려 역방향 경향 |

---

### 7. 방향 예측 적중률 (Direction Accuracy)

감성 점수의 부호(양수/음수)로 가격 방향(상승/하락)을 예측하고, 실제 결과와 비교해 **맞힌 비율**을 계산합니다.

```
예측: ensemble_score > 0  →  상승 예측
      ensemble_score ≤ 0  →  하락 예측

실제: return_+Nm > 0  →  실제 상승
      return_+Nm ≤ 0  →  실제 하락
```

> ### *Key Points* <br>
> * 감성 점수가 양수(긍정)면 "가격이 오를 것"으로 예측하고,  
> * 실제로 가격이 올랐는지를 대조해서 맞힌 비율을 구합니다.

**평가 지표 4가지**:

| 지표 | 공식 | 설명 |
|------|------|------|
| **정확도 (Accuracy)** | 전체 예측 중 맞힌 비율 | 10번 예측해서 6번 맞으면 60% |
| **정밀도 (Precision)** | TP ÷ (TP + FP) | "상승 예측" 중 실제로 오른 비율 |
| **재현율 (Recall)** | TP ÷ (TP + FN) | 실제 상승한 것 중 예측이 맞은 비율 |
| **F1 점수** | 정밀도와 재현율의 조화평균 | 정밀도와 재현율을 균형 있게 합친 점수 |

> TP(True Positive) = 상승이라 예측했고 실제로 오른 경우  
> FP(False Positive) = 상승이라 예측했지만 실제로 내린 경우  
> FN(False Negative) = 하락이라 예측했지만 실제로 오른 경우

**기준선 (Baseline)**: **50%** — 아무 정보 없이 동전 던지기로 예측하는 수준  
이 프로젝트에서는 기준선 대비 **+5%p 이상**이면 감성 분석이 유의미한 예측력을 가진다고 판단합니다.

<div align=center>
    <img width="1370" height="698" alt="image" src="https://github.com/user-attachments/assets/b13c334a-82f0-4a6a-921c-599a621e1d11" />
</div>

---

### 8. 최적 앙상블 가중치 탐색

FinBERT와 Gemma를 몇 대 몇으로 섞는 것이 가장 좋은지, 5가지 비율을 모두 시험해보고 **적중률이 가장 높은 비율을 자동으로 선정**합니다.

| 비율 레이블 | FinBERT 비중 | Gemma 비중 | 의미 |
|------------|-------------|------------|------|
| F0:G100    | 0%          | 100%       | Gemma만 사용 |
| F25:G75    | 25%         | 75%        | Gemma 위주 |
| F50:G50    | 50%         | 50%        | 균등 혼합 (기본값) |
| F75:G25    | 75%         | 25%        | FinBERT 위주 |
| F100:G0    | 100%        | 0%         | FinBERT만 사용 |

5가지 비율 각각에 대해 T+5m/15m/30m/60m 4개 시간대의 적중률을 계산하고, **4개 시간대 평균이 가장 높은 비율**을 최적 가중치로 선정합니다.

$$\alpha^* = \underset{\alpha}{\arg\max}\ \frac{1}{4}\sum_{\tau \in \{5,\, 15,\, 30,\, 60\}} \text{Acc}_\tau(\alpha)$$

> ### *Key Points* <br>
> "어떤 혼합 비율이 가장 예측을 잘 맞히나요?"를 실험으로 알아내는 과정입니다.  
> 최적 가중치가 F50:G50로 나오면 → `.env`에서 `FINBERT_WEIGHT=0.50`로 설정해 반영합니다.

<div align=center>
    <img width="1473" height="456" alt="image" src="https://github.com/user-attachments/assets/76f6da51-1b7c-4c79-a7d3-01f9dc250262" />
</div>

---

## 감성 분석 파이프라인 상세 및 자동화

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

<div align=center>
    <img width="1632" height="866" alt="image" src="https://github.com/user-attachments/assets/7be578d6-2ed0-491f-9e83-2194b27843e3" />
</div>

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