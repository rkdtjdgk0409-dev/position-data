from __future__ import annotations

import os
import sys
from dataclasses import dataclass

import numpy as np
import pandas as pd

from market_data import adjusted_close, beta_ols, ewma_covariance, naver_current_price, yahoo_ticker
from notion_common import NotionClient, get_prop, make_number, number_value, plain_text

SCRIPT_VERSION = "2026-08-01-current-positions-v7"
BENCHMARK = os.getenv("BENCHMARK_TICKER", "^KS11")
EWMA_DECAY = float(os.getenv("EWMA_DECAY", "0.94"))
CASH_KRW = float(os.getenv("PORTFOLIO_CASH_KRW", "0"))
DEBT_KRW = float(os.getenv("PORTFOLIO_DEBT_KRW", "0"))

# 사용자가 만든 현재 포지션 DB의 정확한 속성명
P_TITLE = os.getenv("PROP_TITLE", "이름")
P_NAME = os.getenv("PROP_NAME", "종목명")
P_CODE = os.getenv("PROP_CODE", "종목코드")
P_QTY = os.getenv("PROP_QTY", "보유수량")
P_AVG = os.getenv("PROP_AVG_PRICE", "평균단가")
P_PRICE = os.getenv("PROP_CURRENT_PRICE", "현재가")
P_BETA60 = os.getenv("PROP_BETA_60", "60일 시장 베타")
P_EWMA = os.getenv("PROP_EWMA_VOL", "EWMA 변동성")
P_NAV_WEIGHT = os.getenv("PROP_NAV_WEIGHT", "NAV 비중")
P_RISK_SHARE = os.getenv("PROP_RISK_SHARE", "위험기여율")


@dataclass
class Position:
    page_id: str
    name: str
    code: str
    quantity: float
    average_price: float


def validate_schema(notion: NotionClient) -> None:
    required = [P_TITLE, P_CODE, P_QTY, P_AVG, P_PRICE, P_BETA60, P_EWMA, P_NAV_WEIGHT, P_RISK_SHARE]
    missing = [name for name in required if name not in notion.schema]
    if missing:
        raise KeyError(f"현재 포지션 DB에 필요한 속성이 없습니다: {missing}")
    for name in [P_PRICE, P_BETA60, P_EWMA, P_NAV_WEIGHT, P_RISK_SHARE]:
        if notion.schema[name].get("type") != "number":
            raise TypeError(f"'{name}' 속성은 숫자 타입이어야 합니다.")


def load_positions(notion: NotionClient) -> list[Position]:
    positions: list[Position] = []
    for page in notion.query_all():
        title_name = plain_text(get_prop(page, P_TITLE))
        text_name = plain_text(get_prop(page, P_NAME)) if P_NAME in notion.schema else ""
        name = text_name or title_name
        code = plain_text(get_prop(page, P_CODE)).zfill(6)
        quantity = number_value(get_prop(page, P_QTY))
        average_price = number_value(get_prop(page, P_AVG))
        if not name or not code.strip("0") or quantity <= 0:
            print(f"[Skip] name={name!r}, code={code!r}, quantity={quantity}")
            continue
        positions.append(Position(page["id"], name, code, quantity, average_price))
    if not positions:
        raise RuntimeError("현재 포지션 DB에 계산 가능한 종목이 없습니다. 종목명·종목코드·보유수량·평균단가를 입력하세요.")
    return positions


def main() -> None:
    print(f"[Script] {SCRIPT_VERSION}")
    token = os.getenv("NOTION_TOKEN") or os.getenv("NOTION_API_KEY")
    database_id = os.getenv("NOTION_POSITIONS_DATABASE_ID")
    if not token or not database_id:
        raise RuntimeError("GitHub Secrets에 NOTION_TOKEN과 NOTION_POSITIONS_DATABASE_ID를 등록하세요.")

    notion = NotionClient(token, database_id)
    notion.initialize()
    validate_schema(notion)
    positions = load_positions(notion)

    market_returns = adjusted_close(BENCHMARK).pct_change(fill_method=None).dropna()

    returns_by_code: dict[str, pd.Series] = {}
    prices: dict[str, float] = {}
    betas: dict[str, float] = {}

    for position in positions:
        current_price, as_of = naver_current_price(position.code)
        ticker = yahoo_ticker(position.code)
        stock_returns = adjusted_close(ticker).pct_change(fill_method=None).dropna()
        prices[position.code] = current_price
        returns_by_code[position.code] = stock_returns
        betas[position.code] = beta_ols(stock_returns, market_returns, 60)
        print(
            f"[Market] {position.name}({position.code}) ticker={ticker} current={current_price:,.0f} "
            f"beta60={betas[position.code]:.4f} as_of={as_of}"
        )

    codes = [p.code for p in positions]
    aligned = pd.concat([returns_by_code[c].rename(c) for c in codes], axis=1, join="inner").dropna().tail(252)
    covariance = ewma_covariance(aligned, EWMA_DECAY)
    ewma_vols = np.sqrt(np.maximum(np.diag(covariance), 0.0))

    market_values = np.array([p.quantity * prices[p.code] for p in positions], dtype=float)
    total_positions = float(market_values.sum())
    nav = CASH_KRW + total_positions - DEBT_KRW
    if nav <= 0:
        raise RuntimeError(
            f"NAV가 0 이하입니다. cash={CASH_KRW:,.0f}, positions={total_positions:,.0f}, debt={DEBT_KRW:,.0f}"
        )

    weights = market_values / nav
    portfolio_variance = float(weights @ covariance @ weights)
    if portfolio_variance <= 0:
        risk_shares = np.zeros(len(positions), dtype=float)
    else:
        marginal_variance = covariance @ weights
        risk_shares = weights * marginal_variance / portfolio_variance

    for index, position in enumerate(positions):
        updates = {
            P_PRICE: make_number(prices[position.code]),
            P_BETA60: make_number(betas[position.code]),
            P_EWMA: make_number(float(ewma_vols[index])),
            P_NAV_WEIGHT: make_number(float(weights[index])),
            P_RISK_SHARE: make_number(float(risk_shares[index])),
        }
        notion.update_page(position.page_id, updates)
        print(
            f"[Updated] {position.name}: NAV weight={weights[index]:.2%}, "
            f"risk share={risk_shares[index]:.2%}, EWMA vol={ewma_vols[index]:.2%}"
        )

    portfolio_vol = float(np.sqrt(max(portfolio_variance, 0.0)))
    print("\n=== Portfolio summary ===")
    print(f"현금: {CASH_KRW:,.0f}원")
    print(f"주식 평가금액: {total_positions:,.0f}원")
    print(f"차입금: {DEBT_KRW:,.0f}원")
    print(f"NAV: {nav:,.0f}원")
    print(f"총 롱 익스포저: {weights.sum():.2%}")
    print(f"EWMA 포트폴리오 일일 변동성: {portfolio_vol:.2%}")
    print(f"공통 관측치: {len(aligned)} 거래일")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
