"""
텔레그램 봇 메시지 발송 모듈
- 2단계 장세 (추세/변동성) 반영
- 이전 주 대비 변화 표시
- parse_mode 없이 발송
"""

import requests
import os
import json

TELEGRAM_TOKEN   = os.environ.get('TELEGRAM_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')
PREV_RESULT_PATH = 'data/prev_result.json'

REGIME_EMOJI = {
    '폭등': '🚀', '상승': '📈', '횡보': '➡️', '하락': '📉', '급락': '💥',
}

REGIME_STATS = {
    '폭등': {'avg': '+22.8%', 'prob': '100%',  'loss': '0%'},
    '상승': {'avg': '+10.8%', 'prob': '98.7%', 'loss': '0%'},
    '횡보': {'avg': '+2.7%',  'prob': '73.7%', 'loss': '7.7%'},
    '하락': {'avg': '-8.1%',  'prob': '8.7%',  'loss': '70.7%'},
    '급락': {'avg': '-25.2%', 'prob': '0%',    'loss': '100%'},
}


def load_prev():
    if os.path.exists(PREV_RESULT_PATH):
        try:
            with open(PREV_RESULT_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return None


def save_prev(result):
    os.makedirs('data', exist_ok=True)
    with open(PREV_RESULT_PATH, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, default=str)


def fmt_stat(curr, prev, curr_fmt_fn, diff_fmt, unit=''):
    """현재값 (변화량 / 전주값) 형식"""
    curr_str = curr_fmt_fn(curr)
    if prev is None:
        return curr_str
    diff = curr - prev
    prev_str = curr_fmt_fn(prev)
    if diff == 0:
        return f'{curr_str} (변동 없음 / 전주 {prev_str})'
    sign = '+' if diff >= 0 else ''
    return f'{curr_str} ({sign}{diff:{diff_fmt}}{unit} / 전주 {prev_str})'


def rsi_comment(v):
    if v >= 70: return '과열 구간 — 꼭지 주의'
    if v >= 60: return '추세 유지 중'
    if v >= 50: return '중립'
    if v >= 40: return '약세 — 하락 압력'
    return '과매도 — 급락 진행 중'


def vix_comment(v):
    if v >= 30: return '극도의 공포 — 급락 위험'
    if v >= 25: return '공포 구간 — 하락 주의'
    if v >= 20: return '불안 심리 증가 — 변동성 장세'
    if v >= 15: return '안정적, 시장 공포 낮음'
    return '공포 없음 — 과열 주의'


def dgs10_comment(regime_val):
    if regime_val > 0.3:  return '금리 상승 국면 — 긴축 압력'
    if regime_val > 0:    return '이평선 소폭 위 — 중립 국면'
    if regime_val > -0.3: return '이평선 소폭 아래 — 중립 국면'
    return '금리 하락 국면 — 완화 기대'


def t10y2y_comment(v):
    if v < -0.5: return '심각한 역전 — 침체 경고'
    if v < 0:    return '역전 상태 — 침체 주의'
    if v < 0.5:  return '정상화 중'
    return '역전 아님 — 침체 신호 없음'


def build_message(result, prev=None):
    regime      = result['regime']
    emoji       = REGIME_EMOJI.get(regime, '')
    stats       = REGIME_STATS[regime]
    p           = prev or {}
    is_volatile = result.get('is_volatile', False)
    bull_str    = ('정배열' if result['perfect_bull']
                   else ('역배열' if result['perfect_bear'] else '중립'))

    regime_changed   = p.get('regime') and p.get('regime') != regime
    volatile_changed = p.get('is_volatile') is not None and p.get('is_volatile') != is_volatile

    sep = '─' * 32

    # 모델 예측 수익률
    pred     = result['pred_13w']
    pred_str = f'+{pred:.1f}%' if pred >= 0 else f'{pred:.1f}%'
    pred_line = fmt_stat(pred, p.get('pred_13w'),
                         lambda v: (f'+{v:.1f}%' if v >= 0 else f'{v:.1f}%'),
                         '.1f', '%')

    lines = [
        '📊 S&P500 주간 시장 분석',
        f'📅 {result["date"]}',
        sep,
    ]

    # 대분류 (추세/변동성)
    vol_label = '변동성 장세 ⚠️' if is_volatile else '추세 장세'
    vol_change = '  ← 장세 유형 전환!' if volatile_changed else ''
    lines.append(f'[시장 국면] {vol_label} (VIX {result["vix"]:.1f}){vol_change}')

    # 소분류 (장세)
    if regime_changed:
        lines.append(f'[현재 장세] {REGIME_EMOJI.get(p["regime"],"")} {p["regime"]} → {emoji} {regime}  ⚠️ 장세 전환')
    else:
        lines.append(f'[현재 장세] {emoji} {regime}')

    lines += [
        '',
        f'  모델 예측 수익률: {pred_line}',
        f'  {regime} 장세 역사적 평균: {stats["avg"]} / 상승 확률 {stats["prob"]}',
        f'  5% 이상 손실 확률: {stats["loss"]}',
        '',
        sep,
    ]

    # 전략
    lines += [
        f'[전략] 권장 포지션: {result["pos_desc"]}',
        '',
    ]
    for t in result.get('transition', []):
        lines.append(f'  • {t}')

    lines += ['', sep, '[시장 상태]', '']

    # S&P500
    sp_line = fmt_stat(result['close'], p.get('close'),
                       lambda v: f'{v:,.0f}pt', ',.0f', 'pt')
    lines += [
        f'  S&P500  : {sp_line}',
        f'            20주 이평 대비 {result["disp_ma20"]:+.1f}% / 60주 이평 대비 {result["disp_ma60"]:+.1f}%',
        f'            이평선 정렬: {bull_str}',
        '',
    ]

    # RSI
    rsi_line = fmt_stat(result['rsi'], p.get('rsi'),
                        lambda v: f'{v:.1f}', '.1f')
    lines += [f'  RSI     : {rsi_line}', f'            {rsi_comment(result["rsi"])}', '']

    # VIX
    vix_line = fmt_stat(result['vix'], p.get('vix'),
                        lambda v: f'{v:.1f}', '.1f')
    lines += [f'  VIX     : {vix_line}', f'            {vix_comment(result["vix"])}', '']

    # DGS10
    dgs_line = fmt_stat(result['dgs10'], p.get('dgs10'),
                        lambda v: f'{v:.2f}%', '.2f', '%')
    lines += [f'  DGS10   : {dgs_line}', f'            {dgs10_comment(result.get("dgs10_regime", 0))}', '']

    # T10Y2Y
    t2y_line = fmt_stat(result['t10y2y'], p.get('t10y2y'),
                        lambda v: f'{v:+.3f}%', '.3f', '%')
    lines += [f'  T10Y2Y  : {t2y_line}', f'            {t10y2y_comment(result["t10y2y"])}', '']

    # Fwd EPS
    eps_line = fmt_stat(result['eps'], p.get('eps'),
                        lambda v: f'{v:.2f}', '.2f')
    lines += [f'  Fwd EPS : {eps_line}', '', sep]

    # 선행 경보
    if result['signals']:
        lines.append('[선행 경보]')
        for tag, desc in result['signals']:
            lines.append(f'  {tag} {desc}')
    else:
        lines.append('[선행 경보] 없음 — 현재 특이 신호 없음')

    lines += [sep, '매주 토요일 자동 업데이트']

    return '\n'.join(lines)


def send_telegram(message, token=None, chat_id=None):
    token   = token   or TELEGRAM_TOKEN
    chat_id = chat_id or TELEGRAM_CHAT_ID

    if not token or not chat_id:
        raise ValueError('TELEGRAM_TOKEN 또는 TELEGRAM_CHAT_ID가 설정되지 않았습니다')

    url = f'https://api.telegram.org/bot{token}/sendMessage'
    r = requests.post(url, json={'chat_id': chat_id, 'text': message}, timeout=15)

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
