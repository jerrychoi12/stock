"""
데이터 수집 모듈
- S&P500 주가/이평선/RSI: FRED API (SP500) — yfinance 대신 안정적
- VIX, DGS10, T10Y2Y: FRED API
- Forward EPS: S&P Global xlsx (실패 시 저장값 사용)
"""

import pandas as pd
import numpy as np
import requests
import io
import os


FRED_API_KEY = os.environ.get('FRED_API_KEY', '')


def fetch_fred(series_id, api_key, start='1990-01-01'):
    url = (
        f'https://api.stlouisfed.org/fred/series/observations'
        f'?series_id={series_id}'
        f'&api_key={api_key}'
        f'&file_type=json'
        f'&observation_start={start}'
        f'&sort_order=asc'
    )
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    data = r.json()

    if 'observations' not in data or len(data['observations']) == 0:
        raise ValueError(f'FRED {series_id} 데이터 없음')

    df = pd.DataFrame(data['observations'])[['date', 'value']]
    df['date'] = pd.to_datetime(df['date'])
    df['value'] = pd.to_numeric(df['value'], errors='coerce')
    df = df.dropna().set_index('date')
    df.columns = [series_id]
    return df


def calc_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def fetch_sp500(api_key, start='1990-01-01'):
    sp_daily = fetch_fred('SP500', api_key, start=start)
    sp_daily.index = pd.to_datetime(sp_daily.index)
    sp_daily = sp_daily.sort_index()

    sp_weekly = sp_daily.resample('W').last()
    sp_weekly.columns = ['Close']
    sp_weekly = sp_weekly.dropna()

    if sp_weekly.empty:
        raise ValueError('S&P500 주봉 데이터 수집 실패')

    sp_weekly['MA5']  = sp_weekly['Close'].rolling(5).mean()
    sp_weekly['MA10'] = sp_weekly['Close'].rolling(10).mean()
    sp_weekly['MA20'] = sp_weekly['Close'].rolling(20).mean()
    sp_weekly['MA60'] = sp_weekly['Close'].rolling(60).mean()
    sp_weekly['RSI']  = calc_rsi(sp_weekly['Close'], period=14)

    print(f'  S&P500: {len(sp_weekly)}주 ({sp_weekly.index[0].strftime("%Y-%m-%d")} ~ {sp_weekly.index[-1].strftime("%Y-%m-%d")})')
    return sp_weekly


def fetch_forward_eps():
    url = 'https://www.spglobal.com/spdji/en/documents/additional-material/sp-500-eps-est.xlsx'
    try:
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=30)
        r.raise_for_status()
        wb = pd.ExcelFile(io.BytesIO(r.content))

        for sheet in wb.sheet_names:
            df = wb.parse(sheet, header=None)
            for i, row in df.iterrows():
                for j, val in enumerate(row):
                    if isinstance(val, str) and 'forward' in val.lower() and 'eps' in val.lower():
                        for k in range(i + 1, min(i + 5, len(df))):
                            num = pd.to_numeric(df.iloc[k, j], errors='coerce')
                            if pd.notna(num) and 100 < num < 600:
                                return float(num)

        for sheet in wb.sheet_names:
            df = wb.parse(sheet, header=None)
            nums = df.apply(pd.to_numeric, errors='coerce')
            candidates = nums[(nums > 100) & (nums < 600)].stack()
            if len(candidates) > 0:
                return float(candidates.iloc[0])

    except Exception as e:
        print(f'  S&P Global EPS 수집 실패: {e}')

    return None


def collect_all(fred_api_key=None):
    api_key = fred_api_key or FRED_API_KEY
    if not api_key:
        raise ValueError('FRED_API_KEY 환경변수가 설정되지 않았습니다')

    print('📥 S&P500 주봉 수집 중...')
    sp = fetch_sp500(api_key)

    print('📥 VIX 수집 중...')
    vix = fetch_fred('VIXCLS', api_key)

    print('📥 DGS10 수집 중...')
    dgs = fetch_fred('DGS10', api_key)

    print('📥 T10Y2Y 수집 중...')
    t2y = fetch_fred('T10Y2Y', api_key)

    print('📥 Forward EPS 수집 중...')
    forward_eps = fetch_forward_eps()
    print(f'  Forward EPS: {forward_eps:.2f}' if forward_eps else '  Forward EPS 실패 — 저장값 사용')

    # 주봉 변환
    vix_w = vix.resample('W').mean()
    dgs_w = dgs.resample('W').mean()
    t2y_w = t2y.resample('W').mean()

    # Date 컬럼으로 변환
    df = sp.reset_index()
    df.columns = ['Date'] + list(df.columns[1:])

    def to_df(d):
        d = d.reset_index()
        d.columns = ['Date'] + list(d.columns[1:])
        return d.sort_values('Date')

    vix_df = to_df(vix_w)
    dgs_df = to_df(dgs_w)
    t2y_df = to_df(t2y_w)

    df = df.sort_values('Date')
    tol = pd.Timedelta('10d')
    df = pd.merge_asof(df, vix_df, on='Date', direction='nearest', tolerance=tol)
    df = pd.merge_asof(df, dgs_df, on='Date', direction='nearest', tolerance=tol)
    df = pd.merge_asof(df, t2y_df, on='Date', direction='nearest', tolerance=tol)
    df = df.rename(columns={'VIXCLS': 'VIX'})

    # EPS 처리
    os.makedirs('data', exist_ok=True)
    eps_path = 'data/eps_history.csv'

    if os.path.exists(eps_path):
        eps_hist = pd.read_csv(eps_path, parse_dates=['Date']).sort_values('Date')
        df = pd.merge_asof(df, eps_hist.rename(columns={'EPS': 'EPS_hist'}),
                           on='Date', direction='backward')
        df['EPS'] = df['EPS_hist'].fillna(forward_eps or 274.0)
        df.drop(columns=['EPS_hist'], inplace=True, errors='ignore')
    else:
        df['EPS'] = forward_eps or 274.0

    if forward_eps:
        df.loc[df.index[-1], 'EPS'] = forward_eps
        new_row = pd.DataFrame({'Date': [df['Date'].iloc[-1]], 'EPS': [forward_eps]})
        if os.path.exists(eps_path):
            eps_hist = pd.read_csv(eps_path, parse_dates=['Date'])
            eps_hist = pd.concat([eps_hist, new_row]).drop_duplicates('Date').sort_values('Date')
        else:
            eps_hist = new_row
        eps_hist.to_csv(eps_path, index=False)

    df = df.dropna(subset=['Close', 'VIX', 'DGS10', 'T10Y2Y']).reset_index(drop=True)

    if df.empty:
        raise ValueError('병합 후 데이터가 비어있습니다')

    print(f'✅ 수집 완료: {len(df)}주 ({df["Date"].iloc[0].strftime("%Y-%m-%d")} ~ {df["Date"].iloc[-1].strftime("%Y-%m-%d")})')
    return df
