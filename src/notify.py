"""
텔레그램 봇 메시지 발송 모듈
- parse_mode 없이 일반 텍스트로 발송 (특수문자 오류 방지)
"""

import requests
import os


TELEGRAM_TOKEN   = os.environ.get('TELEGRAM_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')


REGIME_EMOJI = {
    '폭등': '🚀',
    '상승': '📈',
    '횡보': '➡️',
    '하락': '📉',
    '급락': '💥',
}

REGIME_DESC = {
    '폭등': '정배열 + RSI>70 + MA60이격>10%  |  13주 평균 +22.8%  |  양수확률 100%',
    '상승': '정배열 또는 MA20위+RSI>55  |  13주 평균 +10.8%  |  양수확률 98.7%',
    '횡보': '방향성 불명확  |  13주 평균 +2.7%  |  양수확률 73.7%',
    '하락': 'MA20 이탈  |  13주 평균 -8.1%  |  양수확률 8.7%',
    '급락': '역배열 + RSI<45  |  13주 평균 -25.2%  |  양수확률 0%',
}

STRATEGY_DESC = {
    '폭등': '풀포지션 100% 유지',
    '상승': '풀포지션 100% 유지',
    '횡보': '50~70% 유지 (정배열 70% / 역배열 30%)',
    '하락': '20% 축소 (MA5 데드크로스 시 0%)',
    '급락': '현금 100% 대피',
}

TRANSITION_DESC = {
    '폭등': ['상승 전환시 유지', '횡보 전환시 모니터링 시작'],
    '상승': ['횡보 전환시 모니터링 시작', '하락 전환시 비중 축소'],
    '횡보': ['상승 전환(pred 7% 이상 + 정배열) → 추가매수', '하락 전환(pred -3% 이하 또는 MA20 이탈) → 비중 축소'],
    '하락': ['급락 전환(pred -10% 이하 + 역배열) → 즉시 현금화', '횡보 전환(pred -3% 이상 + VIX 안정) → 재진입 준비'],
    '급락': ['하락 전환(pred -10% 이상) → 소량 재진입 준비'],
}


def build_message(result):
    regime = result['regime']
    emoji  = REGIME_EMOJI.get(regime, '')
    weight = int(result['weight'] * 100)
    pred   = result['pred_13w']
    pred_str = f'+{pred:.1f}%' if pred >= 0 else f'{pred:.1f}%'
    bull_str = ('정배열' if result['perfect_bull']
                else ('역배열' if result['perfect_bear'] else '중립'))

    sep = '─' * 30
    lines = [
        '📊 S&P500 주간 시장 분석',
        f'📅 {result["date"]}',
        sep,
        f'[현재 장세] {emoji} {regime}',
        f'  {REGIME_DESC[regime]}',
        '',
        f'[모델 예측] 13주 후 수익률: {pred_str}',
        f'  매크로 {result["importances"]["macro"]}%  수요 {result["importances"]["demand"]}%  기업가치 {result["importances"]["fund"]}%',
        '',
        f'[전략] 권장 투자비중: {weight}%',
        f'  {STRATEGY_DESC[regime]}',
        sep,
        '[현재 지표]',
        f'  S&P500 : {result["close"]:,.0f} pt',
        f'  RSI    : {result["rsi"]:.1f}',
        f'  VIX    : {result["vix"]:.1f}',
        f'  DGS10  : {result["dgs10"]:.2f}%',
        f'  T10Y2Y : {result["t10y2y"]:.3f}%',
        f'  Fwd EPS: {result["eps"]:.2f}',
        f'  MA20 이격: {result["disp_ma20"]:+.1f}%',
        f'  MA60 이격: {result["disp_ma60"]:+.1f}%',
        f'  이평선 : {bull_str}',
        sep,
    ]

    # 선행 신호
    if result['signals']:
        lines.append('[선행 신호]')
        for tag, desc in result['signals']:
            lines.append(f'  {tag} {desc}')
    else:
        lines.append('[선행 신호] 없음')

    lines.append(sep)

    # 전환 기준
    lines.append('[다음 전환 기준]')
    for t in TRANSITION_DESC.get(regime, []):
        lines.append(f'  • {t}')

    lines.append(sep)
    lines.append('매주 월요일 자동 업데이트')

    return '\n'.join(lines)


def send_telegram(message, token=None, chat_id=None):
    token   = token   or TELEGRAM_TOKEN
    chat_id = chat_id or TELEGRAM_CHAT_ID

    if not token or not chat_id:
        raise ValueError('TELEGRAM_TOKEN 또는 TELEGRAM_CHAT_ID가 설정되지 않았습니다')

    url = f'https://api.telegram.org/bot{token}/sendMessage'
    payload = {
        'chat_id': chat_id,
        'text':    message,
        # parse_mode 제거 — 특수문자 파싱 오류 방지
    }
    r = requests.post(url, json=payload, timeout=15)

    # 에러 내용 출력 후 raise
    if not r.ok:
        print(f'텔레그램 오류: {r.status_code} {r.text}')
    r.raise_for_status()
    return r.json()


def notify(result, token=None, chat_id=None):
    message = build_message(result)
    resp = send_telegram(message, token, chat_id)
    print(f'텔레그램 발송 완료 (message_id: {resp["result"]["message_id"]})')
    return resp
