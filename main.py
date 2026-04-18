"""
메인 실행 파일
"""

import sys
import os
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.collect_data import collect_all
from src.analyze import run_analysis
from src.notify import notify, build_message


def main():
    print(f'\n{"="*50}')
    print(f'S&P500 시장 분석 시작: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print(f'{"="*50}\n')

    fred_api_key = os.environ.get('FRED_API_KEY')
    if not fred_api_key:
        print('❌ FRED_API_KEY 환경변수가 없습니다')
        sys.exit(1)

    # 1. 데이터 수집
    df = collect_all(fred_api_key)

    # 2. 분석
    result = run_analysis(df)

    # 결과 출력
    vol_label = '변동성 장세' if result['is_volatile'] else '추세 장세'
    print(f'\n{"="*50}')
    print(f'📊 분석 결과')
    print(f'{"="*50}')
    print(f'날짜:             {result["date"]}')
    print(f'S&P500:           {result["close"]:,.0f}')
    print(f'시장 국면:        {vol_label} (VIX {result["vix"]:.1f})')
    print(f'현재 장세:        {result["regime"]}')
    print(f'모델 예측 수익률: {result["pred_13w"]:+.2f}%')
    print(f'권장 포지션:      {result["pos_desc"]}')
    print(f'선행 경보:        {len(result["signals"])}개')
    for tag, desc in result['signals']:
        print(f'  {tag} {desc}')

    # 결과 저장
    os.makedirs('data', exist_ok=True)
    with open('data/latest_result.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    print('\n✅ 결과 저장 완료: data/latest_result.json')

    # 3. 텔레그램 발송
    telegram_token   = os.environ.get('TELEGRAM_TOKEN')
    telegram_chat_id = os.environ.get('TELEGRAM_CHAT_ID')

    if telegram_token and telegram_chat_id:
        print('\n📤 텔레그램 발송 중...')
        notify(result, telegram_token, telegram_chat_id)
    else:
        print('\n⚠️ 텔레그램 설정 없음 — 메시지 미리보기:')
        print('-' * 50)
        from src.notify import load_prev
        print(build_message(result, load_prev()))

    print(f'\n{"="*50}')
    print(f'완료: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print(f'{"="*50}\n')


if __name__ == '__main__':
    main()
