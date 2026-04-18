"""
분석 모듈
- 변수 계산
- XGBoost 모델 예측
- 2단계 장세 판단 (추세/변동성 x 폭등/상승/횡보/하락/급락)
- 권장 포지션 (레버리지 배수 + 비중)
- 선행 경보
"""

import pandas as pd
import numpy as np
from xgboost import XGBRegressor
from sklearn.preprocessing import StandardScaler


FEAT_COLS = [
    'DGS10_regime', 'DGS10_slope',
    'VIX_yoy', 'RSI_diff',
    'EPS_yoy',
    'T10Y2Y_ma3', 'T10Y2Y_slope'
]


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

    # 변동성 대분류
    df['is_volatile'] = df['VIX'] > 20

    # 선행 신호
    df['MA5_dead_MA10']   = (df['MA5'] < df['MA10']) & (df['MA5'].shift(1) >= df['MA10'].shift(1))
    df['MA5_golden_MA10'] = (df['MA5'] > df['MA10']) & (df['MA5'].shift(1) <= df['MA10'].shift(1))
    df['VIX_surge_20']    = df['VIX'] > df['VIX'].shift(1) * 1.20
    df['rsi_exit_65']     = (df['RSI'] < 65) & (df['RSI'].shift(1) >= 65)
    df['rsi_exit_70']     = (df['RSI'] < 70) & (df['RSI'].shift(1) >= 70)
    df['close_break_MA10']= (~df['above_MA10']) & (df['above_MA10'].shift(1))

    return df


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

    valid = df.dropna(subset=FEAT_COLS)
    df.loc[valid.index, 'pred_13w'] = model.predict(sc.transform(valid[FEAT_COLS]))

    importances = dict(zip(FEAT_COLS, model.feature_importances_))
    return df, model, sc, importances


def pred_to_regime(pred):
    if pred >= 15:  return '폭등'
    if pred >= 7:   return '상승'
    if pred >= -3:  return '횡보'
    if pred >= -10: return '하락'
    return '급락'


def get_position(regime, is_volatile, perfect_bull, perfect_bear, ma5_dead):
    """
    (레버리지 배수, 비중, 설명) 반환
    양수 = 롱, 음수 = 인버스
    """
    if not is_volatile:
        # 추세 장세 (VIX <= 20)
        if regime in ['폭등', '상승']:
            return (2, 1.0, '2x 롱 100%')
        elif regime == '횡보':
            if perfect_bull: return (2, 0.7, '2x 롱 70% (정배열)')
            if perfect_bear: return (2, 0.3, '2x 롱 30% (역배열)')
            return (2, 0.5, '2x 롱 50% (중립)')
        elif regime == '하락':
            if ma5_dead: return (-2, 0.5, '인버스 2x 50% (데드크로스 확인)')
            return (-1, 0.5, '인버스 1x 50% (추세 하락)')
        else:  # 급락
            return (-2, 1.0, '인버스 2x 100%')
    else:
        # 변동성 장세 (VIX > 20)
        if regime in ['폭등', '상승']:
            return (1, 0.7, '1x 롱 70% (변동성 — 레버리지 축소)')
        elif regime == '횡보':
            return (0, 0.0, '현금 대기 (변동성 — 방향 불명확)')
        elif regime == '하락':
            return (1, 0.2, '1x 롱 20% (변동성 — 인버스 자제)')
        else:  # 급락
            return (-1, 0.5, '인버스 1x 50% (변동성 — 인버스 보수적)')


def check_signals(latest):
    signals = []

    # 급락 선행 경보
    if latest.get('VIX_surge_20', False):
        signals.append(('🔴 급락경보', 'VIX 전주比 +20% 급등 — 공포 폭발'))
    if latest.get('MA5_dead_MA10', False):
        signals.append(('🔴 급락경보', 'MA5 데드크로스(MA10) — 단기 추세 꺾임'))
    if latest.get('close_break_MA10', False):
        signals.append(('🟠 주의', 'Close MA10 하향 이탈 — 중기 지지선 붕괴'))

    # 꼭지 선행 경보
    if latest.get('RSI', 0) > 70 and latest.get('disp_MA60', 0) > 10:
        signals.append(('🟡 과열경보', f'RSI {latest["RSI"]:.1f} + MA60 이격 {latest["disp_MA60"]:.1f}% — 과열'))
    if latest.get('rsi_exit_70', False):
        signals.append(('🟡 꼭지주의', 'RSI 70 하향이탈 — 꼭지 확정 신호'))

    # 매수 신호
    if latest.get('MA5_golden_MA10', False) and latest.get('perfect_bull', False):
        signals.append(('🟢 매수신호', 'MA5 골든크로스 + 정배열 — 상승 초입'))

    return signals


def run_analysis(df):
    print('🔧 변수 계산 중...')
    df = build_features(df)

    print('🤖 모델 학습 중...')
    df, model, sc, importances = train_and_predict(df)

    latest = df.iloc[-1]
    pred   = float(latest.get('pred_13w', 0))
    regime = pred_to_regime(pred)

    is_volatile  = bool(latest.get('is_volatile', False))
    perfect_bull = bool(latest.get('perfect_bull', False))
    perfect_bear = bool(latest.get('perfect_bear', False))
    ma5_dead     = bool(latest.get('MA5_dead_MA10', False))

    lev, weight, pos_desc = get_position(
        regime, is_volatile, perfect_bull, perfect_bear, ma5_dead
    )

    signals = check_signals(latest)

    # 가중치
    macro_w  = sum(v for k, v in importances.items() if 'DGS10' in k or 'T10Y2Y' in k)
    demand_w = sum(v for k, v in importances.items() if 'VIX' in k or 'RSI' in k)
    fund_w   = sum(v for k, v in importances.items() if 'EPS' in k)

    # 전환 기준 (장세 + 대분류 조합)
    if not is_volatile:
        transition = {
            '폭등': ['상승 전환 시 → 비중 유지', '횡보 전환 시 → 2x 롱 70%로 축소'],
            '상승': ['횡보 전환 시 → 2x 롱 70%로 축소', '하락 전환 시 → 인버스 1x 50%'],
            '횡보': [
                '정배열 완성 시, 상승 추세 전환 예상 → 2x 롱 70%로 늘리세요',
                '모델 예측 수익률 -3% 이하 또는 MA20 이탈 시, 하락 추세 전환 예상 → 인버스 1x 50%로 전환하세요',
            ],
            '하락': [
                'MA5 데드크로스 확인 시 → 인버스 2x 50%로 전환하세요',
                'VIX 안정 + 모델 예측 수익률 -3% 이상 시 → 인버스 해제, 1x 롱 재진입하세요',
            ],
            '급락': ['모델 예측 수익률 -10% 이상 + VIX 하락 시 → 인버스 1x로 축소하세요'],
        }
    else:
        transition = {
            '폭등': ['VIX 20 이하 복귀 시 → 2x 롱 100%로 전환하세요', '횡보 전환 시 → 현금 대기'],
            '상승': ['VIX 20 이하 복귀 시 → 2x 롱 100%로 전환하세요', '횡보 전환 시 → 현금 대기'],
            '횡보': ['VIX 20 이하 복귀 + 상승 전환 시 → 2x 롱 진입하세요', '하락 전환 시 → 1x 롱 20% 유지'],
            '하락': ['급락 전환 시 → 인버스 1x 50% 진입하세요', '횡보 전환 시 → 현금 대기'],
            '급락': ['VIX 안정화 시 → 인버스 해제 후 현금 대기하세요'],
        }

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
        'dgs10_regime': float(latest.get('DGS10_regime', 0)),
        'perfect_bull': perfect_bull,
        'perfect_bear': perfect_bear,
        'is_volatile':  is_volatile,
        'pred_13w':     pred,
        'regime':       regime,
        'leverage':     lev,
        'weight':       weight,
        'pos_desc':     pos_desc,
        'transition':   transition.get(regime, []),
        'signals':      signals,
        'importances':  {
            'macro':  round(macro_w * 100, 1),
            'demand': round(demand_w * 100, 1),
            'fund':   round(fund_w * 100, 1),
        }
    }

    return result
