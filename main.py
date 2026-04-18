"""
메인 실행 파일
GitHub Actions에서 매주 실행됨
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

    # 1. 데이터 수집
    fred_api_key = os.environ.get('FRED_API_KEY')
    if not fred_api_key:
        print('❌ FRED_API_KEY 환경변수가 없습니다')
        sys.exit(1)

    df = collect_all(fred_api_key)

    # 2. 분석
    result = run_analysis(df)

    # 결과 출력
    print(f'\n{"="*50}')
    print(f'📊 분석 결과')
    print(f'{"="*50}')
    print(f'날짜:        {result["date"]}')
    print(f'S&P500:      {result["close"]:,.0f}')
    print(f'예측 13w:    {result["pred_13w"]:+.2f}%')
    print(f'장세:        {result["regime"]}')
    print(f'권장 비중:   {int(result["weight"]*100)}%')
    print(f'선행 신호:   {len(result["signals"])}개')
    for tag, desc in result["signals"]:
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
        print('\n⚠️ TELEGRAM_TOKEN 또는 TELEGRAM_CHAT_ID 없음 — 발송 스킵')
        print('\n메시지 미리보기:')
        print('-' * 40)
        print(build_message(result))

    print(f'\n{"="*50}')
    print(f'완료: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print(f'{"="*50}\n')


if __name__ == '__main__':
    main()
