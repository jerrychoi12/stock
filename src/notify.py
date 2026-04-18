"""
텔레그램 봇 메시지 발송 모듈
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
    '폭등': '정배열 + RSI>70 + MA60이격>10% | 13주 평균 +22.8% | 양수확률 100%',
    '상승': '정배열 또는 MA20위+RSI>55 | 13주 평균 +10.8% | 양수확률 98.7%',
    '횡보': '방향성 불명확 | 13주 평균 +2.7% | 양수확률 73.7%',
    '하락': 'MA20 이탈 또는 RSI<50+MA10이탈 | 13주 평균 -8.1% | 양수확률 8.7%',
    '급락': '역배열 + RSI<45 | 13주 평균 -25.2% | 양수확률 0%',
}

STRATEGY_DESC = {
    '폭등': '✅ 풀포지션 100% 유지',
    '상승': '✅ 풀포지션 100% 유지',
    '횡보': '⚖️ 50~70% 유지 (정배열 70% / 역배열 30%)',
    '하락': '⚠️ 20% 축소 (MA5 데드크로스 시 0%)',
    '급락': '🚨 현금 100% 대피',
}


def build_message(result):
    regime = result['regime']
    emoji  = REGIME_EMOJI.get(regime, '')
    weight = int(result['weight'] * 100)

    lines = []
    lines.append(f'📊 *S&P500 주간 시장 분석*')
    lines.append(f'📅 {result["date"]}')
    lines.append('')

    # 현재 장세
    lines.append(f'*[현재 장세]* {emoji} *{regime}*')
    lines.append(f'└ {REGIME_DESC[regime]}')
    lines.append('')

    # 모델 예측
    pred = result['pred_13w']
    pred_str = f'+{pred:.1f}%' if pred >= 0 else f'{pred:.1f}%'
    lines.append(f'*[모델 예측]* 13주 후 수익률: *{pred_str}*')
    lines.append(f'└ 매크로 {result["importances"]["macro"]}% | 수요 {result["importances"]["demand"]}% | 기업가치 {result["importances"]["fund"]}%')
    lines.append('')

    # 전략
    lines.append(f'*[전략]* 권장 투자비중: *{weight}%*')
    lines.append(f'└ {STRATEGY_DESC[regime]}')
    lines.append('')

    # 현재 지표
    bull_str = '✅ 정배열' if result['perfect_bull'] else ('⛔ 역배열' if result['perfect_bear'] else '➡️ 중립')
    lines.append(f'*[현재 지표]*')
    lines.append(f'• S\\&P500: {result["close"]:,.0f}pt')
    lines.append(f'• RSI: {result["rsi"]:.1f} | VIX: {result["vix"]:.1f}')
    lines.append(f'• 금리(DGS10): {result["dgs10"]:.2f}% | 장단기금리차: {result["t10y2y"]:.3f}%')
    lines.append(f'• Forward EPS: {result["eps"]:.2f}')
    lines.append(f'• MA20 이격: {result["disp_ma20"]:+.1f}% | MA60 이격: {result["disp_ma60"]:+.1f}%')
    lines.append(f'• 이평선: {bull_str}')
    lines.append('')

    # 선행 신호
    if result['signals']:
        lines.append(f'*[선행 신호]*')
        for tag, desc in result['signals']:
            lines.append(f'{tag} {desc}')
        lines.append('')
    else:
        lines.append(f'*[선행 신호]* 없음 — 현재 특이 신호 없음')
        lines.append('')

    # 장세 전환 안내
    lines.append(f'*[다음 전환 기준]*')
    if regime in ['폭등', '상승']:
        lines.append(f'• 상승→횡보: pred < 7% 또는 MA5 데드크로스')
        lines.append(f'• 상승→하락: pred < -3% 또는 MA20 이탈')
    elif regime == '횡보':
        lines.append(f'• 횡보→상승: pred ≥ 7% + 정배열')
        lines.append(f'• 횡보→하락: pred < -3% 또는 MA20 이탈')
    elif regime == '하락':
        lines.append(f'• 하락→급락: pred < -10% + 역배열')
        lines.append(f'• 하락→횡보: pred > -3% + VIX 안정')
    elif regime == '급락':
        lines.append(f'• 급락→하락: pred > -10% 또는 VIX 하락')

    lines.append('')
    lines.append('_매주 월요일 자동 업데이트_')

    return '\n'.join(lines)


def send_telegram(message, token=None, chat_id=None):
    token   = token   or TELEGRAM_TOKEN
    chat_id = chat_id or TELEGRAM_CHAT_ID

    if not token or not chat_id:
        raise ValueError('TELEGRAM_TOKEN 또는 TELEGRAM_CHAT_ID가 설정되지 않았습니다')

    url = f'https://api.telegram.org/bot{token}/sendMessage'
    payload = {
        'chat_id':    chat_id,
        'text':       message,
        'parse_mode': 'Markdown',
    }
    r = requests.post(url, json=payload, timeout=15)
    r.raise_for_status()
    return r.json()


def notify(result, token=None, chat_id=None):
    message = build_message(result)
    resp = send_telegram(message, token, chat_id)
    print(f'✅ 텔레그램 발송 완료 (message_id: {resp["result"]["message_id"]})')
    return resp
