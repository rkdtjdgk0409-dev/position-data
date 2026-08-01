# Notion 현재 포지션 자동화 v7

## 필요한 Notion 속성
- 이름: 제목
- 종목명: 텍스트(선택, 비어 있으면 이름 사용)
- 종목코드: 텍스트
- 보유수량: 숫자
- 평균단가: 숫자(원화)
- 현재가: 숫자(원화)
- 평가금액: 수식
- 미실현손익: 수식
- 수익률: 수식
- NAV 비중: 숫자(퍼센트)
- 60일 시장 베타: 숫자
- EWMA 변동성: 숫자(퍼센트)
- 위험기여율: 숫자(퍼센트)

## GitHub Secrets
필수:
- NOTION_TOKEN
- NOTION_POSITIONS_DATABASE_ID

권장:
- NOTION_POSITIONS_DATA_SOURCE_ID
- PORTFOLIO_CASH_KRW
- PORTFOLIO_DEBT_KRW

현재 확인된 ID:
- Database ID: 3af5a03a123e80b1b624f628184180ff
- Data Source ID: 3af5a03a123e8034b375000b07b72c6c

## 업로드 경로
- update_positions.py
- notion_common.py
- market_data.py
- requirements.txt
- .github/workflows/update-positions.yml

## 실행
GitHub → Actions → Update Notion current positions → Run workflow
