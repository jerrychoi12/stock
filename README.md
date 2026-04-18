# S&P500 주간 시장 신호 시스템

매주 월요일 자동으로 S&P500 시장을 분석하고 텔레그램으로 알림을 보냅니다.

## 구조

```
매주 월요일 09:00 (한국시간)
    ↓
1. 데이터 수집
   - S&P500 주가/RSI/이평선 (yfinance)
   - VIX, DGS10, T10Y2Y (FRED API)
   - Forward EPS (S&P Global)
    ↓
2. XGBoost 모델 분석
   - 매크로 52.6% + 수요 24% + 기업가치 23.4%
   - 13주 후 수익률 예측
    ↓
3. 장세 판단 + 권장 비중
   - 폭등/상승/횡보/하락/급락
    ↓
4. 텔레그램 봇 발송
```

## 세팅 방법

### 1. 이 레포지토리 Fork

GitHub에서 Fork 버튼 클릭

### 2. FRED API 키 발급 (무료)

1. https://fred.stlouisfed.org/docs/api/api_key.html 접속
2. 계정 생성 후 API 키 발급 (무료)

### 3. 텔레그램 봇 생성

1. 텔레그램에서 `@BotFather` 검색
2. `/newbot` 명령어로 봇 생성
3. 봇 토큰 복사
4. `@userinfobot` 으로 내 Chat ID 확인

### 4. GitHub Secrets 설정

레포지토리 → Settings → Secrets and variables → Actions → New repository secret

| Secret 이름 | 값 |
|---|---|
| `FRED_API_KEY` | FRED API 키 |
| `TELEGRAM_TOKEN` | 텔레그램 봇 토큰 |
| `TELEGRAM_CHAT_ID` | 텔레그램 Chat ID |

### 5. Actions 활성화

레포지토리 → Actions 탭 → Enable workflows

### 6. 수동 테스트

Actions → Weekly Signal → Run workflow

## 장세별 전략

| 장세 | 조건 | 권장 비중 | 13주 실제 수익 |
|---|---|---|---|
| 🚀 폭등 | 정배열+RSI>70+MA60이격>10% | 100% | +22.8% |
| 📈 상승 | 정배열 또는 MA20위+RSI>55 | 100% | +10.8% |
| ➡️ 횡보 | 위아래 조건 불충족 | 50~70% | +2.7% |
| 📉 하락 | MA20이탈 또는 RSI<50+MA10이탈 | 0~20% | -8.1% |
| 💥 급락 | 역배열+RSI<45 | 0% | -25.2% |

## 선행 신호

- 🔴 급락경보: VIX +20% 급등 / MA5 데드크로스(MA10)
- 🟠 주의: Close MA10 하향이탈
- 🟡 과열경보: RSI>70 + MA60이격>10%
- 🟡 꼭지주의: RSI 70 하향이탈
- 🟢 매수신호: MA5 골든크로스 + 정배열

## 모델 가중치

- 매크로(DGS10, T10Y2Y): 52.6%
- 수요(VIX, RSI): 24.0%
- 기업가치(EPS): 23.4%
