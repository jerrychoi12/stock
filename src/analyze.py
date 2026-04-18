"""
분석 모듈
- 변수 계산 (YoY, 이격도, 이평선 조건)
- XGBoost 모델 예측
- 장세 판단 + 권장 비중
- 선행 신호 (꼭지/급락 경보)
"""

import pandas as pd
import numpy as np
from xgboost import XGBRegressor
from sklearn.preprocessing import StandardScaler


# ── 변수 계산 ──────────────────────────────────────────
def build_features(df):
    df = df.copy().sort_values('Date').reset_index(drop=True)

    # 매크로
    df['DGS10_ma52']   = df['DGS10'].rolling(52).mean()
    df['DGS10_regime'] = df['DGS10'] - df['DGS10_ma52']
    df['DGS10_slope']  = df['DGS10'] - df['DGS10'].shift(13)
    df['T10Y2Y_ma3']   = df['T10Y2Y'].rolling(13).mean()
    df['T10Y2Y_slope'] = df['T10Y2Y'] - df['T10Y2Y'].shift(26)

    # 수요
    df['VIX_yoy']  = df['VIX'].pct_change(52) * 100
    df['RSI_diff'] = df['RSI'].diff()

    # 기업가치
    df['EPS_yoy'] = df['EPS'].pct_change(52) * 100

    # 이평선 조건
    df['above_MA5']  = df['Close'] > df['MA5']
    df['above_MA10'] = df['Close'] > df['MA10']
    df['above_MA20'] = df['Close'] > df['MA20']
    df['above_MA60'] = df['Close'] > df['MA60']
    df['perfect_bull'] = (
        (df['MA5'] > df['MA10']) &
        (df['MA10'] > df['MA20']) &
        (df['MA20'] > df['MA60'])
    )
    df['perfect_bear'] = (
        (df['MA5'] < df['MA10']) &
        (df['MA10'] < df['MA20']) &
        (df['MA20'] < df['MA60'])
    )

    # 이격도
    df['disp_MA20'] = (df['Close'] - df['MA20']) / df['MA20'] * 100
    df['disp_MA60'] = (df['Close'] - df['MA60']) / df['MA60'] * 100

    # 선행 신호
    df['MA5_dead_MA10']   = (df['MA5'] < df['MA10']) & (df['MA5'].shift(1) >= df['MA10'].shift(1))
    df['MA5_golden_MA10'] = (df['MA5'] > df['MA10']) & (df['MA5'].shift(1) <= df['MA10'].shift(1))
    df['VIX_surge_20']    = df['VIX'] > df['VIX'].shift(1) * 1.20
    df['rsi_exit_65']     = (df['RSI'] < 65) & (df['RSI'].shift(1) >= 65)
    df['rsi_exit_70']     = (df['RSI'] < 70) & (df['RSI'].shift(1) >= 70)
    df['close_break_MA10']= (~df['above_MA10']) & (df['above_MA10'].shift(1))

    return df


# ── XGBoost 모델 학습 및 예측 ─────────────────────────
FEAT_COLS = [
    'DGS10_regime', 'DGS10_slope',
    'VIX_yoy', 'RSI_diff',
    'EPS_yoy',
    'T10Y2Y_ma3', 'T10Y2Y_slope'
]

def train_and_predict(df):
    df = df.copy()
    df['target_13w'] = df['Close'].pct_change(13).shift(-13) * 100

    train = df.dropna(subset=FEAT_COLS + ['target_13w'])
    X = train[FEAT_COLS]
    y = train['target_13w']

    sc = StandardScaler()
    X_s = sc.fit_transform(X)

    model = XGBRegressor(
        n_estimators=300, max_depth=3, learning_rate=0.03,
        subsample=0.8, colsample_bytree=0.8,
        random_state=42, verbosity=0
    )
    model.fit(X_s, y)

    # 전체 예측
    valid = df.dropna(subset=FEAT_COLS)
    X_all = valid[FEAT_COLS]
    X_all_s = sc.transform(X_all)
    df.loc[valid.index, 'pred_13w'] = model.predict(X_all_s)

    # 변수 중요도
    importances = dict(zip(FEAT_COLS, model.feature_importances_))

    return df, model, sc, importances


# ── 장세 판단 ──────────────────────────────────────────
def pred_to_regime(pred):
    if pred >= 15:  return '폭등'
    if pred >= 7:   return '상승'
    if pred >= -3:  return '횡보'
    if pred >= -10: return '하락'
    return '급락'


def get_weight(regime, perfect_bull, perfect_bear, ma5_dead):
    if regime in ['폭등', '상승']:
        return 1.0
    elif regime == '횡보':
        if perfect_bull: return 0.7
        if perfect_bear: return 0.3
        return 0.5
    elif regime == '하락':
        if ma5_dead: return 0.0
        return 0.2
    return 0.0  # 급락


# ── 선행 신호 점검 ─────────────────────────────────────
def check_signals(latest):
    signals = []

    # 급락 선행 신호
    if latest.get('VIX_surge_20', False):
        signals.append(('🔴 급락경보', 'VIX 전주比 +20% 급등 — 공포 폭발 신호'))
    if latest.get('MA5_dead_MA10', False):
        signals.append(('🔴 급락경보', 'MA5 데드크로스(MA10) — 단기 추세 꺾임 시작'))
    if latest.get('close_break_MA10', False):
        signals.append(('🟠 주의', 'Close MA10 하향 이탈 — 중기 지지선 붕괴'))

    # 꼭지 선행 신호 (과열)
    if latest.get('RSI', 0) > 70 and latest.get('disp_MA60', 0) > 10:
        signals.append(('🟡 과열경보', f'RSI {latest["RSI"]:.1f} + MA60 이격 {latest["disp_MA60"]:.1f}% — 과열 구간'))
    if latest.get('rsi_exit_70', False):
        signals.append(('🟡 꼭지주의', 'RSI 70 하향이탈 — 꼭지 확정 신호 (2단계)'))
    if latest.get('MA5_dead_MA10', False) and latest.get('RSI', 100) > 60:
        signals.append(('🟡 꼭지주의', 'RSI 고점에서 MA5 데드크로스 — 꼭지 확정 패턴'))

    # 급등 신호
    if latest.get('MA5_golden_MA10', False) and latest.get('perfect_bull', False):
        signals.append(('🟢 매수신호', 'MA5 골든크로스(MA10) + 정배열 — 상승 초입'))

    return signals


# ── 전체 분석 실행 ─────────────────────────────────────
def run_analysis(df):
    print('🔧 변수 계산 중...')
    df = build_features(df)

    print('🤖 모델 학습 중...')
    df, model, sc, importances = train_and_predict(df)

    latest = df.iloc[-1]
    pred = latest.get('pred_13w', 0)
    regime = pred_to_regime(pred)
    weight = get_weight(
        regime,
        bool(latest.get('perfect_bull', False)),
        bool(latest.get('perfect_bear', False)),
        bool(latest.get('MA5_dead_MA10', False))
    )
    signals = check_signals(latest)

    # 매크로/수요/기업가치 가중치
    macro_w = sum(v for k, v in importances.items() if 'DGS10' in k or 'T10Y2Y' in k)
    demand_w = sum(v for k, v in importances.items() if 'VIX' in k or 'RSI' in k)
    fund_w = sum(v for k, v in importances.items() if 'EPS' in k)

    result = {
        'date':         latest['Date'].strftime('%Y-%m-%d'),
        'close':        float(latest['Close']),
        'rsi':          float(latest['RSI']),
        'vix':          float(latest['VIX']),
        'dgs10':        float(latest['DGS10']),
        't10y2y':       float(latest['T10Y2Y']),
        'eps':          float(latest['EPS']),
        'disp_ma20':    float(latest['disp_MA20']),
        'disp_ma60':    float(latest['disp_MA60']),
        'perfect_bull': bool(latest['perfect_bull']),
        'perfect_bear': bool(latest['perfect_bear']),
        'pred_13w':     float(pred),
        'regime':       regime,
        'weight':       weight,
        'signals':      signals,
        'importances':  {
            'macro':   round(macro_w * 100, 1),
            'demand':  round(demand_w * 100, 1),
            'fund':    round(fund_w * 100, 1),
        }
    }

    return result
