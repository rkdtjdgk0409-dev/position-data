from __future__ import annotations

import io
import re
from typing import Any

import numpy as np
import pandas as pd
import requests
import yfinance as yf

HEADERS = {"User-Agent": "Mozilla/5.0"}


def naver_current_price(code: str) -> tuple[float, str]:
    url = f"https://finance.naver.com/item/main.naver?code={code}"
    response = requests.get(url, headers=HEADERS, timeout=20)
    response.raise_for_status()
    html = response.text
    match = re.search(r'<p class="no_today">.*?<span class="blind">([0-9,]+)</span>', html, re.S)
    if not match:
        raise RuntimeError(f"네이버 현재가 파싱 실패: {code}")
    price = float(match.group(1).replace(",", ""))
    return price, pd.Timestamp.now(tz="Asia/Seoul").strftime("%Y-%m-%d %H:%M")


def yahoo_ticker(code: str) -> str:
    # KOSPI를 우선 시도하고, 실패 시 KOSDAQ을 시도합니다.
    for suffix in (".KS", ".KQ"):
        ticker = f"{code}{suffix}"
        data = yf.download(ticker, period="2y", auto_adjust=True, progress=False)
        if not data.empty:
            return ticker
    raise RuntimeError(f"Yahoo Finance에서 종목을 찾지 못했습니다: {code}")


def adjusted_close(ticker: str, period: str = "2y") -> pd.Series:
    data = yf.download(ticker, period=period, auto_adjust=True, progress=False)
    if data.empty:
        raise RuntimeError(f"가격 데이터가 없습니다: {ticker}")
    if isinstance(data.columns, pd.MultiIndex):
        series = data["Close"].iloc[:, 0]
    else:
        series = data["Close"]
    return series.dropna().astype(float)


def beta_ols(asset_returns: pd.Series, market_returns: pd.Series, window: int) -> float:
    aligned = pd.concat(
        [asset_returns.rename("asset"), market_returns.rename("market")], axis=1
    ).dropna().tail(window)
    if len(aligned) < max(30, int(window * 0.7)):
        raise RuntimeError(f"베타 관측치 부족: {len(aligned)}/{window}")
    market_var = float(aligned["market"].var(ddof=1))
    if market_var <= 0:
        raise RuntimeError("시장분산이 0이라 베타를 계산할 수 없습니다.")
    return float(aligned["asset"].cov(aligned["market"]) / market_var)


def ewma_covariance(returns: pd.DataFrame, decay: float = 0.94) -> np.ndarray:
    values = returns.to_numpy(dtype=float)
    if len(values) < 30:
        raise RuntimeError(f"EWMA 공분산 관측치 부족: {len(values)}")
    demeaned = values - np.nanmean(values, axis=0, keepdims=True)
    covariance = np.zeros((values.shape[1], values.shape[1]), dtype=float)
    weight_sum = 0.0
    for age, row in enumerate(demeaned[::-1]):
        weight = (1.0 - decay) * (decay**age)
        covariance += weight * np.outer(row, row)
        weight_sum += weight
    if weight_sum <= 0:
        raise RuntimeError("EWMA 가중치 합이 0입니다.")
    return covariance / weight_sum
