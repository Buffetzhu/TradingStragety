from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
import socket

import pandas as pd


def normalize_symbol(symbol: str) -> str:
    clean = symbol.strip().upper()
    if not clean:
        raise ValueError("股票代码不能为空")
    if "." in clean:
        return clean
    return f"US.{clean}"


def cache_file_name(symbol: str) -> str:
    return normalize_symbol(symbol).replace(".", "_") + ".csv"


@dataclass(frozen=True)
class FutuDataConfig:
    host: str = "127.0.0.1"
    port: int = 11111
    cache_dir: Path = Path("data/cache")


class FutuHistoricalDataProvider:
    def __init__(self, config: FutuDataConfig | None = None) -> None:
        self.config = config or FutuDataConfig()

    def get_positions(
        self,
        *,
        market: str = "US",
        trd_env: str = "SIMULATE",
        acc_id: int | None = None,
    ) -> pd.DataFrame:
        try:
            from futu import OpenSecTradeContext, RET_OK, TrdEnv, TrdMarket
        except ImportError as exc:
            raise RuntimeError("缺少 futu-api，请先安装 requirements.txt") from exc

        market_map = {
            "US": TrdMarket.US,
            "HK": TrdMarket.HK,
            "HKCC": TrdMarket.HKCC,
            "CN": TrdMarket.CN,
            "SG": TrdMarket.SG,
        }
        trd_env_map = {
            "SIMULATE": TrdEnv.SIMULATE,
            "REAL": TrdEnv.REAL,
        }
        market_key = market.upper().strip()
        trd_env_key = trd_env.upper().strip()
        if market_key not in market_map:
            raise ValueError(f"不支持的交易市场：{market}")
        if trd_env_key not in trd_env_map:
            raise ValueError(f"不支持的交易环境：{trd_env}")

        trd_ctx = OpenSecTradeContext(filter_trdmarket=market_map[market_key], host=self.config.host, port=self.config.port)
        try:
            query_args = {"trd_env": trd_env_map[trd_env_key], "refresh_cache": True}
            if acc_id is not None:
                query_args["acc_id"] = int(acc_id)
            ret, data = trd_ctx.position_list_query(**query_args)
            if ret != RET_OK:
                raise RuntimeError(f"富途持仓查询失败：{data}")
        finally:
            trd_ctx.close()

        if data.empty:
            return pd.DataFrame(columns=["标的", "持仓股数", "成本价"])

        code_column = "code" if "code" in data.columns else "stock_code"
        qty_column = "qty" if "qty" in data.columns else "position_qty"
        cost_column = next(
            (column for column in ["average_cost", "avg_cost", "cost_price"] if column in data.columns),
            None,
        )
        if code_column not in data.columns or qty_column not in data.columns:
            raise RuntimeError("富途持仓返回字段缺少 code/qty，无法解析。")

        rows = []
        for _, row in data.iterrows():
            shares = float(row[qty_column])
            if shares <= 0:
                continue
            code = str(row[code_column]).upper().strip()
            cost = float(row[cost_column]) if cost_column and pd.notna(row[cost_column]) else 0.0
            rows.append({"标的": code, "持仓股数": shares, "成本价": cost})
        return pd.DataFrame(rows, columns=["标的", "持仓股数", "成本价"])

    def get_market_data(
        self,
        symbols: list[str],
        *,
        sector_symbol: str,
        years: float,
        warmup_days: int = 120,
        use_cache: bool = True,
    ) -> dict[str, pd.DataFrame]:
        all_symbols = list(dict.fromkeys([*symbols, sector_symbol]))
        start = date.today() - timedelta(days=int(years * 365.25) + max(warmup_days, 0) + 10)
        end = date.today()
        return {
            symbol: self.get_history(symbol, start=start, end=end, use_cache=use_cache)
            for symbol in all_symbols
        }

    def get_market_data_with_errors(
        self,
        symbols: list[str],
        *,
        sector_symbol: str,
        years: float,
        warmup_days: int = 120,
        use_cache: bool = True,
    ) -> tuple[dict[str, pd.DataFrame], dict[str, str]]:
        all_symbols = list(dict.fromkeys([*symbols, sector_symbol]))
        start = date.today() - timedelta(days=int(years * 365.25) + max(warmup_days, 0) + 10)
        end = date.today()
        market_data: dict[str, pd.DataFrame] = {}
        errors: dict[str, str] = {}
        for symbol in all_symbols:
            try:
                market_data[symbol] = self.get_history(symbol, start=start, end=end, use_cache=use_cache)
            except Exception as exc:
                errors[symbol] = str(exc)
        return market_data, errors

    def test_connection(self, timeout: float = 2.0) -> tuple[bool, str]:
        try:
            with socket.create_connection((self.config.host, self.config.port), timeout=timeout):
                return True, f"OpenD 端口可连接：{self.config.host}:{self.config.port}"
        except OSError as exc:
            return False, f"OpenD 端口不可连接：{self.config.host}:{self.config.port} ({exc})"

    def get_cache_info(self, symbol: str) -> dict[str, object]:
        normalized = normalize_symbol(symbol)
        cache_path = self.config.cache_dir / cache_file_name(normalized)
        if not cache_path.exists():
            return {
                "symbol": symbol,
                "normalized": normalized,
                "status": "未缓存",
                "rows": 0,
                "start": "",
                "end": "",
                "cache_age_days": "",
                "freshness": "",
                "path": str(cache_path),
            }

        cached = pd.read_csv(cache_path, parse_dates=["date"])
        last_date = cached["date"].max().date() if not cached.empty else None
        cache_age_days = (date.today() - last_date).days if last_date else ""
        if cache_age_days == "":
            freshness = ""
        elif cache_age_days == 0:
            freshness = "今日最新"
        elif cache_age_days <= 3:
            freshness = f"{cache_age_days} 天前"
        else:
            freshness = f"可能过期：{cache_age_days} 天前"
        return {
            "symbol": symbol,
            "normalized": normalized,
            "status": "已缓存",
            "rows": int(len(cached)),
            "start": str(cached["date"].min().date()) if not cached.empty else "",
            "end": str(last_date) if last_date else "",
            "cache_age_days": cache_age_days,
            "freshness": freshness,
            "path": str(cache_path),
        }

    def get_history(self, symbol: str, *, start: date, end: date, use_cache: bool = True) -> pd.DataFrame:
        normalized = normalize_symbol(symbol)
        cache_path = self.config.cache_dir / cache_file_name(normalized)
        if use_cache and cache_path.exists():
            cached = pd.read_csv(cache_path, parse_dates=["date"])
            filtered = cached[(cached["date"].dt.date >= start) & (cached["date"].dt.date <= end)]
            if not filtered.empty:
                return filtered.reset_index(drop=True)

        frame = self._fetch_from_futu(normalized, start=start, end=end)
        self.config.cache_dir.mkdir(parents=True, exist_ok=True)
        frame.to_csv(cache_path, index=False)
        return frame

    def _fetch_from_futu(self, symbol: str, *, start: date, end: date) -> pd.DataFrame:
        try:
            from futu import AuType, KLType, OpenQuoteContext, RET_OK
        except ImportError as exc:
            raise RuntimeError("缺少 futu-api，请先安装 requirements.txt") from exc

        quote_ctx = OpenQuoteContext(host=self.config.host, port=self.config.port)
        frames: list[pd.DataFrame] = []
        page_req_key = None
        try:
            while True:
                ret, data, page_req_key = quote_ctx.request_history_kline(
                    symbol,
                    start=start.isoformat(),
                    end=end.isoformat(),
                    ktype=KLType.K_DAY,
                    autype=AuType.QFQ,
                    page_req_key=page_req_key,
                )
                if ret != RET_OK:
                    raise RuntimeError(f"富途历史 K 线拉取失败：{symbol} {data}")
                frames.append(data)
                if page_req_key is None:
                    break
        finally:
            quote_ctx.close()

        if not frames:
            raise RuntimeError(f"未获取到历史 K 线：{symbol}")

        raw = pd.concat(frames, ignore_index=True)
        if raw.empty:
            raise RuntimeError(f"历史 K 线为空：{symbol}")

        return pd.DataFrame(
            {
                "date": pd.to_datetime(raw["time_key"]).dt.normalize(),
                "symbol": symbol.split(".", 1)[1],
                "open": raw["open"].astype(float),
                "high": raw["high"].astype(float),
                "low": raw["low"].astype(float),
                "close": raw["close"].astype(float),
                "volume": raw["volume"].astype(float),
            }
        ).sort_values("date").reset_index(drop=True)