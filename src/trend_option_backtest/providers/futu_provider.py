from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
import socket
import time

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


FUTU_WATCHLIST_WINDOW_SECONDS = 31.0
FUTU_WATCHLIST_MAX_REQUESTS_PER_WINDOW = 9


class FutuHistoricalDataProvider:
    def __init__(self, config: FutuDataConfig | None = None) -> None:
        self.config = config or FutuDataConfig()

    @staticmethod
    def _is_rate_limited_error(message: str) -> bool:
        text = str(message)
        text_lower = text.lower()
        return (
            "频率太高" in text
            or "请求过于频繁" in text
            or "too frequent" in text_lower
            or ("rate" in text_lower and "limit" in text_lower)
        )

    @classmethod
    def _call_quote_api_with_retry(
        cls,
        *,
        action_label: str,
        call,
        ret_ok: int,
        max_attempts: int = 3,
        retry_delay_seconds: float = FUTU_WATCHLIST_WINDOW_SECONDS,
    ):
        last_message = "未知错误"
        for attempt in range(1, max_attempts + 1):
            ret, payload = call()
            if ret == ret_ok:
                return payload
            last_message = str(payload)
            if attempt < max_attempts and cls._is_rate_limited_error(last_message):
                time.sleep(retry_delay_seconds)
                continue
            break
        if cls._is_rate_limited_error(last_message):
            raise RuntimeError(f"{action_label}失败：请求过于频繁，请等待约 30 秒后重试。原始信息：{last_message}")
        raise RuntimeError(f"{action_label}失败：{last_message}")

    def get_watchlist_groups(self) -> list[str]:
        try:
            from futu import OpenQuoteContext, RET_OK
        except ImportError as exc:
            raise RuntimeError("缺少 futu-api，请先安装 requirements.txt") from exc

        quote_ctx = OpenQuoteContext(host=self.config.host, port=self.config.port)
        try:
            data = self._call_quote_api_with_retry(
                action_label="富途自选股分组读取",
                call=quote_ctx.get_user_security_group,
                ret_ok=RET_OK,
            )
        finally:
            quote_ctx.close()

        if data is None or getattr(data, "empty", False):
            return []
        group_column = next((column for column in ["group_name", "name", "group"] if column in data.columns), "")
        if not group_column:
            raise RuntimeError("富途自选股分组返回字段缺少 group_name/name，无法解析。")
        return list(dict.fromkeys(str(value).strip() for value in data[group_column].dropna().tolist() if str(value).strip()))

    def get_watchlist_symbols(self, group_names: list[str] | None = None) -> dict[str, list[str]]:
        try:
            from futu import OpenQuoteContext, RET_OK
        except ImportError as exc:
            raise RuntimeError("缺少 futu-api，请先安装 requirements.txt") from exc

        request_count = 0
        if group_names is None:
            selected_groups = self.get_watchlist_groups()
            request_count = 1
        else:
            selected_groups = group_names
        if not selected_groups:
            return {}

        quote_ctx = OpenQuoteContext(host=self.config.host, port=self.config.port)
        try:
            groups: dict[str, list[str]] = {}
            for group_name in selected_groups:
                if request_count >= FUTU_WATCHLIST_MAX_REQUESTS_PER_WINDOW:
                    time.sleep(FUTU_WATCHLIST_WINDOW_SECONDS)
                    request_count = 0
                data = self._call_quote_api_with_retry(
                    action_label=f"富途自选股读取（{group_name}）",
                    call=lambda group=group_name: quote_ctx.get_user_security(str(group)),
                    ret_ok=RET_OK,
                )
                request_count += 1
                if data is None or getattr(data, "empty", False):
                    groups[str(group_name)] = []
                    continue
                code_column = next((column for column in ["code", "stock_code", "symbol"] if column in data.columns), "")
                if not code_column:
                    raise RuntimeError("富途自选股返回字段缺少 code/stock_code，无法解析。")
                groups[str(group_name)] = list(
                    dict.fromkeys(
                        normalize_symbol(str(value))
                        for value in data[code_column].dropna().tolist()
                        if str(value).strip()
                    )
                )
        finally:
            quote_ctx.close()
        return groups

    def get_account_info(
        self,
        *,
        market: str = "US",
        trd_env: str = "SIMULATE",
        acc_id: int | None = None,
    ) -> dict[str, object]:
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
            ret, data = trd_ctx.accinfo_query(**query_args)
            if ret != RET_OK:
                raise RuntimeError(f"富途资金查询失败：{data}")
        finally:
            trd_ctx.close()

        if data.empty:
            raise RuntimeError("富途资金查询结果为空。")

        row = data.iloc[0]

        def first_number(columns: list[str]) -> float | None:
            for column in columns:
                if column in data.columns and pd.notna(row[column]):
                    return float(row[column])
            return None

        total_assets = first_number(["total_assets", "total_asset", "assets", "net_assets", "market_val"])
        cash = first_number(["cash", "cash_balance", "available_cash", "withdraw_cash"])
        buying_power = first_number(["power", "buying_power", "cash_power", "net_cash_power", "max_power_long"])
        currency = str(row["currency"]) if "currency" in data.columns and pd.notna(row["currency"]) else ""
        plan_capital = next((value for value in [buying_power, cash, total_assets] if value is not None and value > 0), 0.0)

        return {
            "market": market_key,
            "trd_env": trd_env_key,
            "acc_id": int(acc_id) if acc_id is not None else "",
            "currency": currency,
            "total_assets": total_assets,
            "cash": cash,
            "buying_power": buying_power,
            "plan_capital": plan_capital,
        }

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
        qty_column = next((column for column in ["qty", "position_qty", "quantity", "position"] if column in data.columns), "")
        cost_column = next(
            (column for column in ["average_cost", "avg_cost", "cost_price", "diluted_cost"] if column in data.columns),
            None,
        )
        if code_column not in data.columns or qty_column not in data.columns:
            raise RuntimeError("富途持仓返回字段缺少 code/qty，无法解析。")

        rows = []
        for _, row in data.iterrows():
            shares = float(row[qty_column])
            if shares == 0:
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