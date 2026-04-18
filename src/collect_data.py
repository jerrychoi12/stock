"""
데이터 수집 모듈
- S&P500 주가/이평선/RSI: yfinance
- VIX, DGS10, T10Y2Y: FRED API
- Forward EPS: S&P Global xlsx
"""

import yfinance as yf
import pandas as pd
import numpy as np
import requests
import io
import os
from datetime import datetime, timedelta


FRED_API_KEY = os.environ.get('FRED_API_KEY', '')


def fetch_sp500(period='5y', interval='1wk'):
    """S&P500 주봉 데이터 + 이평선 + RSI"""
    ticker = yf.download('^GSPC', period=period, interval=interval, progress=False)
    if ticker.empty:
        raise ValueError('S&P500 데이터 수집 실패')

    df = ticker[['Close']].copy()
    df.columns = ['Close']
    df.index = pd.to_datetime(df.index)

    # 이평선
    df['MA5']  = df['Close'].rolling(5).mean()
    df['MA10'] = df['Close'].rolling(10).mean()
    df['MA20'] = df['Close'].rolling(20).mean()
    df['MA60'] = df['Close'].rolling(60).mean()

    # RSI (14주)
    delta = df['Close'].diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=13, min_periods=14).mean()
    avg_loss = loss.ewm(com=13, min_periods=14).mean()
    rs = avg_gain / avg_loss
    df['RSI'] = 100 - (100 / (1 + rs))

    return df.dropna()


def fetch_fred(series_id, api_key, start='1990-01-01'):
    """FRED에서 시계열 데이터 수집"""
    url = (
        f'https://api.stlouisfed.org/fred/series/observations'
        f'?series_id={series_id}'
        f'&api_key={api_key}'
        f'&file_type=json'
        f'&observation_start={start}'
        f'&sort_order=asc'
    )
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    data = r.json()

    df = pd.DataFrame(data['observations'])[['date', 'value']]
    df['date'] = pd.to_datetime(df['date'])
    df['value'] = pd.to_numeric(df['value'], errors='coerce')
    df = df.dropna().set_index('date')
    df.columns = [series_id]
    return df


def fetch_forward_eps():
    """S&P Global 공식 xlsx에서 Forward EPS 추출"""
    url = 'https://www.spglobal.com/spdji/en/documents/additional-material/sp-500-eps-est.xlsx'
    headers = {'User-Agent': 'Mozilla/5.0'}

    try:
        r = requests.get(url, headers=headers, timeout=20)
        r.raise_for_status()
        wb = pd.ExcelFile(io.BytesIO(r.content))

        # 시트 탐색
        for sheet in wb.sheet_names:
            df = wb.parse(sheet, header=None)
            # Forward EPS 키워드 탐색
            for i, row in df.iterrows():
                for j, val in enumerate(row):
                    if isinstance(val, str) and 'forward' in val.lower() and 'eps' in val.lower():
                        # 해당 행 다음 행에서 숫자 찾기
                        for k in range(i+1, min(i+5, len(df))):
                            num = pd.to_numeric(df.iloc[k, j], errors='coerce')
                            if pd.notna(num) and 100 < num < 600:
                                return float(num)

        # 못 찾으면 숫자 범위로 탐색 (100~600 사이 EPS 추정)
        for sheet in wb.sheet_names:
            df = wb.parse(sheet, header=None)
            nums = df.apply(pd.to_numeric, errors='coerce')
            candidates = nums[(nums > 100) & (nums < 600)].stack()
            if len(candidates) > 0:
                return float(candidates.iloc[0])

    except Exception as e:
        print(f'S&P Global EPS 수집 실패: {e}')

    # 폴백: 직전 저장값 사용
    return None


def collect_all(fred_api_key=None):
    """전체 데이터 수집 및 통합"""
    api_key = fred_api_key or FRED_API_KEY
    if not api_key:
        raise ValueError('FRED_API_KEY가 설정되지 않았습니다')

    print('📥 S&P500 주봉 수집 중...')
    sp = fetch_sp500()

    print('📥 VIX 수집 중...')
    vix = fetch_fred('VIXCLS', api_key)

    print('📥 DGS10 수집 중...')
    dgs = fetch_fred('DGS10', api_key)

    print('📥 T10Y2Y 수집 중...')
    t2y = fetch_fred('T10Y2Y', api_key)

    print('📥 Forward EPS 수집 중...')
    forward_eps = fetch_forward_eps()
    if forward_eps:
        print(f'  Forward EPS: {forward_eps:.2f}')
    else:
        print('  Forward EPS 수집 실패 — 직전값 사용')

    # 주봉 기준으로 일별 → 주봉 평균 변환
    def to_weekly(df_daily, col):
        df_daily = df_daily.copy()
        df_daily.index = pd.to_datetime(df_daily.index)
        return df_daily.resample('W-MON').mean()

    vix_w  = to_weekly(vix,  'VIXCLS')
    dgs_w  = to_weekly(dgs,  'DGS10')
    t2y_w  = to_weekly(t2y,  'T10Y2Y')

    # S&P500 인덱스를 월요일 기준으로 통일
    sp.index = sp.index.normalize()

    # 병합
    df = sp.copy()
    df = pd.merge_asof(
        df.reset_index().rename(columns={'index':'Date','Datetime':'Date','Price Date':'Date'}),
        vix_w.reset_index().rename(columns={'date':'Date'}),
        on='Date', direction='nearest', tolerance=pd.Timedelta('7d')
    )
    df = pd.merge_asof(
        df,
        dgs_w.reset_index().rename(columns={'date':'Date'}),
        on='Date', direction='nearest', tolerance=pd.Timedelta('7d')
    )
    df = pd.merge_asof(
        df,
        t2y_w.reset_index().rename(columns={'date':'Date'}),
        on='Date', direction='nearest', tolerance=pd.Timedelta('7d')
    )

    # EPS: 직전 저장된 값 로드 후 최신값 업데이트
    eps_path = 'data/eps_history.csv'
    if os.path.exists(eps_path):
        eps_hist = pd.read_csv(eps_path, parse_dates=['Date'])
        df = pd.merge_asof(
            df, eps_hist.rename(columns={'EPS':'EPS_hist'}),
            on='Date', direction='backward'
        )
        df['EPS'] = df['EPS_hist']
        df.drop(columns=['EPS_hist'], inplace=True)
    else:
        df['EPS'] = forward_eps or 274.0  # 기본값

    # 최신 행 EPS 업데이트
    if forward_eps:
        df.loc[df.index[-1], 'EPS'] = forward_eps
        # EPS 히스토리 저장
        new_row = pd.DataFrame({'Date': [df['Date'].iloc[-1]], 'EPS': [forward_eps]})
        if os.path.exists(eps_path):
            eps_hist = pd.read_csv(eps_path, parse_dates=['Date'])
            eps_hist = pd.concat([eps_hist, new_row]).drop_duplicates('Date').sort_values('Date')
        else:
            eps_hist = new_row
        eps_hist.to_csv(eps_path, index=False)

    df = df.dropna(subset=['Close','VIXCLS','DGS10','T10Y2Y']).reset_index(drop=True)
    df.rename(columns={'VIXCLS':'VIX'}, inplace=True)

    print(f'✅ 데이터 수집 완료: {len(df)}주 ({df["Date"].iloc[0].strftime("%Y-%m-%d")} ~ {df["Date"].iloc[-1].strftime("%Y-%m-%d")})')
    return df
