"""
텔레그램 봇 메시지 발송 모듈
- 이전 주 대비 변화 표시
- 자연어 해석 포함
- parse_mode 없이 발송 (특수문자 오류 방지)
"""

import requests
import os
import json


TELEGRAM_TOKEN   = os.environ.get('TELEGRAM_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')

PREV_RESULT_PATH = 'data/prev_result.json'

REGIME_EMOJI = {
    '폭등': '🚀',
    '상승': '📈',
    '횡보': '➡️',
    '하락': '📉',
    '급락': '💥',
}

# 장세별 역사적 통계
REGIME_STATS = {
    '폭등': {'avg': '+22.8%', 'prob': '100%', 'loss': '0%'},
    '상승': {'avg': '+10.8%', 'prob': '98.7%', 'loss': '0%'},
    '횡보': {'avg': '+2.7%',  'prob': '73.7%', 'loss': '7.7%'},
    '하락': {'avg': '-8.1%',  'prob': '8.7%',  'loss': '70.7%'},
    '급락': {'avg': '-25.2%', 'prob': '0%',    'loss': '100%'},
}

# 장세별 전략 행동
STRATEGY_ACTION = {
    '폭등': '풀포지션 100% 유지',
    '상승': '풀포지션 100% 유지',
    '횡보': '50~70% 유지',
    '하락': '20%로 축소',
    '급락': '현금 100% 대피',
}

# 장세별 다음 전환 기준 (자연어)
TRANSITION_DESC = {
    '폭등': [
        '상승 전환 시 → 비중 유지',
        '횡보 전환 시 → 70%로 축소 후 모니터링',
    ],
    '상승': [
        '횡보 전환 시 → 70%로 축소 후 모니터링',
        '하락 전환 시 → 20%로 비중 축소',
    ],
    '횡보': [
        '정배열 완성 시, 상승 추세 전환 예상 → 70%로 늘리세요',
        '모델 예측 수익률 -3% 이하 또는 MA20 이탈 시, 하락 추세 전환 예상 → 비중 축소하세요',
    ],
    '하락': [
        'MA5 데드크로스 발생 시, 급락 위험 → 즉시 현금화하세요',
        'VIX 안정 + 모델 예측 수익률 -3% 이상 시, 횡보 전환 예상 → 재진입 준비하세요',
    ],
    '급락': [
        '모델 예측 수익률 -10% 이상 + VIX 하락 시, 하락 전환 예상 → 소량 재진입 준비하세요',
    ],
}


def load_prev():
    """이전 주 결과 로드"""
    if os.path.exists(PREV_RESULT_PATH):
        try:
            with open(PREV_RESULT_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return None


def save_prev(result):
    """현재 결과를 이전 결과로 저장"""
    os.makedirs('data', exist_ok=True)
    with open(PREV_RESULT_PATH, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, default=str)


def diff_str(curr, prev, fmt='.1f', unit=''):
    """이전 대비 변화량 문자열"""
    if prev is None:
        return ''
    diff = curr - prev
    sign = '+' if diff >= 0 else ''
    return f' ({sign}{diff:{fmt}}{unit} 전주比)'


def rsi_comment(rsi):
    if rsi >= 70: return '과열 구간 — 꼭지 주의'
    if rsi >= 60: return '추세 유지 중'
    if rsi >= 50: return '중립'
    if rsi >= 40: return '약세 — 하락 압력'
    return '과매도 — 급락 진행 중'


def vix_comment(vix):
    if vix >= 30: return '극도의 공포 — 급락 위험'
    if vix >= 25: return '공포 구간 — 하락 주의'
    if vix >= 20: return '불안 심리 증가'
    if vix >= 15: return '안정적'
    return '공포 없음 — 과열 주의'


def dgs10_comment(regime_val):
    """DGS10 국면값 해석 (현재-52주이평)"""
    if regime_val > 0.3:  return '금리 상승 국면 — 긴축 압력'
    if regime_val > 0:    return '이평선 소폭 위 — 중립'
    if regime_val > -0.3: return '이평선 소폭 아래 — 중립'
    return '금리 하락 국면 — 완화 기대'


def t10y2y_comment(val):
    if val < -0.5: return '심각한 역전 — 침체 경고'
    if val < 0:    return '역전 상태 — 침체 주의'
    if val < 0.5:  return '정상화 중'
    return '역전 아님 — 침체 신호 없음'


def build_message(result, prev=None):
    regime   = result['regime']
    emoji    = REGIME_EMOJI.get(regime, '')
    weight   = int(result['weight'] * 100)
    stats    = REGIME_STATS[regime]
    bull_str = ('정배열' if result['perfect_bull']
                else ('역배열' if result['perfect_bear'] else '중립'))

    # 이전 주 값
    p = prev or {}
    prev_regime  = p.get('regime')
    regime_changed = prev_regime and prev_regime != regime

    sep = '─' * 32

    lines = [
        '📊 S&P500 주간 시장 분석',
        f'📅 {result["date"]}',
        sep,
    ]

    # 장세 (전환 여부 표시)
    if regime_changed:
        lines.append(f'[현재 장세] {REGIME_EMOJI.get(prev_regime,"")} {prev_regime} → {emoji} {regime}  ⚠️ 장세 전환')
    else:
        lines.append(f'[현재 장세] {emoji} {regime}')

    pred   = result['pred_13w']
    pred_str = f'+{pred:.1f}%' if pred >= 0 else f'{pred:.1f}%'
    pred_d = diff_str(pred, p.get('pred_13w') if p else None, fmt='.1f', unit='%')

    lines += [
        f'  모델 예측 13주 수익률: {pred_str}{pred_d}',
        f'  {regime} 장세 역사적 평균: {stats["avg"]}  /  상승 확률 {stats["prob"]}',
        f'  5% 이상 손실 확률: {stats["loss"]}',
        '',
    ]

    # 전략
    lines += [
        f'[전략] 권장 투자비중: {weight}%',
        f'  {STRATEGY_ACTION[regime]}',
    ]
    for t in TRANSITION_DESC.get(regime, []):
        lines.append(f'  • {t}')
    lines.append('')
    lines.append(sep)

    # 시장 상태 (이전 주 대비)
    lines.append('[시장 상태]')

    # S&P500
    close_d = diff_str(result['close'], p.get('close'), fmt=',.0f', unit='pt')
    lines.append(f'  S&P500  : {result["close"]:,.0f}pt{close_d}')
    lines.append(f'            20주 이평선 대비 {result["disp_ma20"]:+.1f}%  /  60주 이평선 대비 {result["disp_ma60"]:+.1f}%')
    lines.append(f'            이평선 정렬: {bull_str}')
    lines.append('')

    # RSI
    rsi_d = diff_str(result['rsi'], p.get('rsi'), fmt='.1f')
    lines.append(f'  RSI     : {result["rsi"]:.1f}{rsi_d}')
    lines.append(f'            {rsi_comment(result["rsi"])}')
    lines.append('')

    # VIX
    vix_d = diff_str(result['vix'], p.get('vix'), fmt='.1f')
    lines.append(f'  VIX     : {result["vix"]:.1f}{vix_d}')
    lines.append(f'            {vix_comment(result["vix"])}')
    lines.append('')

    # 금리
    dgs_d = diff_str(result['dgs10'], p.get('dgs10'), fmt='.2f', unit='%')
    lines.append(f'  DGS10   : {result["dgs10"]:.2f}%{dgs_d}')
    lines.append(f'            {dgs10_comment(result.get("dgs10_regime", 0))}')
    lines.append('')

    # 장단기금리차
    t2y_d = diff_str(result['t10y2y'], p.get('t10y2y'), fmt='.3f', unit='%')
    lines.append(f'  T10Y2Y  : {result["t10y2y"]:+.3f}%{t2y_d}')
    lines.append(f'            {t10y2y_comment(result["t10y2y"])}')
    lines.append('')

    # EPS
    eps_d = diff_str(result['eps'], p.get('eps'), fmt='.2f')
    lines.append(f'  Fwd EPS : {result["eps"]:.2f}{eps_d}')

    lines.append(sep)

    # 선행 경보
    if result['signals']:
        lines.append('[선행 경보]')
        for tag, desc in result['signals']:
            lines.append(f'  {tag} {desc}')
    else:
        lines.append('[선행 경보] 없음 — 현재 특이 신호 없음')

    lines += [sep, '매주 월요일 자동 업데이트']

    return '\n'.join(lines)


def send_telegram(message, token=None, chat_id=None):
    token   = token   or TELEGRAM_TOKEN
    chat_id = chat_id or TELEGRAM_CHAT_ID

    if not token or not chat_id:
        raise ValueError('TELEGRAM_TOKEN 또는 TELEGRAM_CHAT_ID가 설정되지 않았습니다')

    url = f'https://api.telegram.org/bot{token}/sendMessage'
    payload = {'chat_id': chat_id, 'text': message}
    r = requests.post(url, json=payload, timeout=15)

    if not r.ok:
        print(f'텔레그램 오류: {r.status_code} {r.text}')
    r.raise_for_status()
    return r.json()


def notify(result, token=None, chat_id=None):
    prev = load_prev()
    message = build_message(result, prev)
    resp = send_telegram(message, token, chat_id)
    save_prev(result)
    print(f'텔레그램 발송 완료 (message_id: {resp["result"]["message_id"]})')
    return resp
