"""
JARVIS V5 - Finance Intelligence Service
Banking via Plaid, market data via yfinance/Yahoo, crypto via CoinGecko.
"""

import json
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Optional imports
try:
    import plaid
    from plaid.api import plaid_api
    from plaid.model.transactions_get_request import TransactionsGetRequest
    from plaid.model.transactions_get_request_options import TransactionsGetRequestOptions
    from plaid.model.accounts_get_request import AccountsGetRequest
    from plaid.configuration import Configuration
    from plaid.api_client import ApiClient
    import plaid.model.country_code as CountryCode
    import plaid.model.products as Products
    PLAID_AVAILABLE = True
except ImportError:
    PLAID_AVAILABLE = False

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False

try:
    import requests as _requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    _requests = None

# Keyword maps for spending categorization
CATEGORY_KEYWORDS = {
    "food": ["restaurant", "cafe", "uber eats", "doordash", "grubhub", "mcdonald", "starbucks", "pizza",
             "chipotle", "subway", "chick-fil-a", "taco bell", "wendy", "burger king", "panera", "dunkin",
             "sushi", "thai", "chinese", "diner", "bistro", "grill", "kitchen", "eatery", "bakery"],
    "transport": ["uber", "lyft", "gas", "parking", "transit", "metro", "bart", "mta", "shell",
                  "chevron", "bp ", "exxon", "citgo", "sunoco", "speedway", "wawa", "circle k",
                  "toll", "ezpass", "train", "amtrak", "greyhound"],
    "shopping": ["amazon", "walmart", "target", "ebay", "etsy", "costco", "sam's club", "best buy",
                 "home depot", "lowe's", "ikea", "zara", "h&m", "gap", "old navy", "macy's",
                 "nordstrom", "tj maxx", "marshalls", "ross"],
    "entertainment": ["netflix", "spotify", "hulu", "steam", "movie", "cinema", "theater", "concert",
                      "ticketmaster", "eventbrite", "disney+", "apple tv", "hbo", "peacock",
                      "paramount", "amazon prime", "twitch", "youtube premium", "apple music"],
    "utilities": ["electric", "water", "internet", "phone", "at&t", "verizon", "t-mobile", "comcast",
                  "xfinity", "spectrum", "pge", "con edison", "gas bill", "sewage", "trash",
                  "waste management", "insurance", "rent", "mortgage"],
}


class FinanceIntelligence:
    """Manages financial data, transactions, market prices, and spending analysis."""

    def _get_plaid_client(self):
        """Build and return a Plaid API client, or None if not configured."""
        if not PLAID_AVAILABLE:
            return None
        client_id = os.environ.get("PLAID_CLIENT_ID")
        secret = os.environ.get("PLAID_SECRET")
        plaid_env = os.environ.get("PLAID_ENV", "sandbox")
        if not client_id or not secret:
            return None
        host_map = {
            "sandbox": plaid.Environment.Sandbox,
            "development": plaid.Environment.Development,
            "production": plaid.Environment.Production,
        }
        host = host_map.get(plaid_env, plaid.Environment.Sandbox)
        config = Configuration(host=host)
        config.api_key["clientId"] = client_id
        config.api_key["secret"] = secret
        api_client = ApiClient(config)
        return plaid_api.PlaidApi(api_client)

    def _get_access_token(self) -> Optional[str]:
        """Read stored Plaid access token from memory."""
        token_file = Path("/Users/kisha/Downloads/JARVIS_V5/memory/plaid_token.json")
        if not token_file.exists():
            return None
        try:
            with open(token_file) as f:
                data = json.load(f)
            return data.get("access_token")
        except Exception:
            return None

    def account_summary(self) -> dict:
        """Return bank account summary via Plaid, or not_configured if unavailable."""
        client = self._get_plaid_client()
        access_token = self._get_access_token()

        if not client or not access_token:
            return {
                "status": "not_configured",
                "message": (
                    "Configure PLAID_CLIENT_ID, PLAID_SECRET, and PLAID_ENV environment variables "
                    "to enable banking integration."
                ),
                "accounts": [],
            }

        try:
            request = AccountsGetRequest(access_token=access_token)
            response = client.accounts_get(request)
            accounts = []
            for acct in response["accounts"]:
                accounts.append({
                    "name": acct["name"],
                    "type": str(acct["type"]),
                    "subtype": str(acct.get("subtype", "")),
                    "balance_current": acct["balances"]["current"],
                    "balance_available": acct["balances"].get("available"),
                    "currency": acct["balances"].get("iso_currency_code", "USD"),
                    "account_id": acct["account_id"],
                })
            total_assets = sum(
                a["balance_current"] for a in accounts
                if a["balance_current"] is not None and a["type"] in ("depository", "investment")
            )
            return {
                "status": "ok",
                "accounts": accounts,
                "total_accounts": len(accounts),
                "total_assets": round(total_assets, 2),
                "as_of": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"Plaid account_summary error: {e}")
            return {"status": "error", "message": str(e), "accounts": []}

    def recent_transactions(self, days: int = 7) -> dict:
        """Return recent transactions via Plaid."""
        client = self._get_plaid_client()
        access_token = self._get_access_token()

        if not client or not access_token:
            return {"status": "not_configured", "transactions": []}

        try:
            end_date = datetime.now().date()
            start_date = (datetime.now() - timedelta(days=days)).date()
            request = TransactionsGetRequest(
                access_token=access_token,
                start_date=start_date,
                end_date=end_date,
            )
            response = client.transactions_get(request)
            txns = []
            for t in response["transactions"]:
                txns.append({
                    "date": str(t["date"]),
                    "name": t["name"],
                    "amount": t["amount"],
                    "category": t.get("category", []),
                    "merchant_name": t.get("merchant_name"),
                    "account_id": t["account_id"],
                    "transaction_id": t["transaction_id"],
                })
            return {
                "status": "ok",
                "transactions": txns,
                "count": len(txns),
                "period_days": days,
                "start_date": str(start_date),
                "end_date": str(end_date),
            }
        except Exception as e:
            logger.error(f"Plaid recent_transactions error: {e}")
            return {"status": "error", "message": str(e), "transactions": []}

    def _get_transactions_for_analysis(self, month: Optional[str] = None) -> list:
        """
        Helper: fetch transactions for spending analysis.
        Returns list of transaction dicts.
        """
        result = self.recent_transactions(days=31)
        txns = result.get("transactions", [])
        if month and txns:
            txns = [t for t in txns if t.get("date", "").startswith(month)]
        return txns

    def spending_analysis(self, month: Optional[str] = None) -> dict:
        """
        Categorize transactions by keyword matching.
        Returns category totals dict.
        """
        if month is None:
            month = datetime.now().strftime("%Y-%m")

        txns = self._get_transactions_for_analysis(month)

        totals = {cat: 0.0 for cat in CATEGORY_KEYWORDS}
        totals["other"] = 0.0
        counts = {cat: 0 for cat in CATEGORY_KEYWORDS}
        counts["other"] = 0

        for t in txns:
            name_lower = t.get("name", "").lower()
            merchant_lower = (t.get("merchant_name") or "").lower()
            combined = f"{name_lower} {merchant_lower}"
            amount = abs(float(t.get("amount", 0)))

            matched = False
            for cat, keywords in CATEGORY_KEYWORDS.items():
                if any(kw in combined for kw in keywords):
                    totals[cat] += amount
                    counts[cat] += 1
                    matched = True
                    break
            if not matched:
                totals["other"] += amount
                counts["other"] += 1

        return {
            "month": month,
            "category_totals": {cat: round(v, 2) for cat, v in totals.items()},
            "category_counts": counts,
            "total_spending": round(sum(totals.values()), 2),
            "transaction_count": len(txns),
            "status": "ok" if txns else "no_data",
        }

    def unusual_charges(self, threshold_multiplier: float = 2.0) -> list:
        """
        Find transactions exceeding threshold_multiplier × typical spend for their category.
        Returns list of flagged transactions.
        """
        txns = self._get_transactions_for_analysis()
        if not txns:
            return []

        # Build category → list of amounts
        cat_amounts: dict = {cat: [] for cat in CATEGORY_KEYWORDS}
        cat_amounts["other"] = []
        txn_cats = []

        for t in txns:
            name_lower = t.get("name", "").lower()
            merchant_lower = (t.get("merchant_name") or "").lower()
            combined = f"{name_lower} {merchant_lower}"
            amount = abs(float(t.get("amount", 0)))
            matched_cat = "other"
            for cat, keywords in CATEGORY_KEYWORDS.items():
                if any(kw in combined for kw in keywords):
                    matched_cat = cat
                    break
            cat_amounts[matched_cat].append(amount)
            txn_cats.append((t, matched_cat, amount))

        # Compute typical (average) per category
        cat_avg = {}
        for cat, amounts in cat_amounts.items():
            cat_avg[cat] = (sum(amounts) / len(amounts)) if amounts else 0.0

        flagged = []
        for t, cat, amount in txn_cats:
            avg = cat_avg.get(cat, 0)
            if avg > 0 and amount > threshold_multiplier * avg:
                flagged.append({
                    "date": t.get("date"),
                    "name": t.get("name"),
                    "amount": amount,
                    "category": cat,
                    "category_avg": round(avg, 2),
                    "multiplier": round(amount / avg, 2),
                    "threshold_multiplier": threshold_multiplier,
                })

        return sorted(flagged, key=lambda x: x["multiplier"], reverse=True)

    def subscription_tracker(self) -> list:
        """
        Find recurring charges: same merchant, same amount ±$1, appearing monthly.
        Returns list of detected subscriptions.
        """
        # Fetch 60 days to catch monthly recurrences
        result = self.recent_transactions(days=60)
        txns = result.get("transactions", [])
        if not txns:
            return []

        # Group by merchant name
        from collections import defaultdict
        merchant_groups: dict = defaultdict(list)
        for t in txns:
            key = (t.get("merchant_name") or t.get("name", "")).strip().lower()
            if key:
                merchant_groups[key].append(t)

        subscriptions = []
        for merchant, charges in merchant_groups.items():
            if len(charges) < 2:
                continue
            amounts = [abs(float(c.get("amount", 0))) for c in charges]
            avg_amount = sum(amounts) / len(amounts)
            # Check if all amounts are within $1 of average
            if all(abs(a - avg_amount) <= 1.0 for a in amounts):
                dates = sorted([c.get("date", "") for c in charges])
                subscriptions.append({
                    "name": (charges[0].get("merchant_name") or charges[0].get("name", merchant)).title(),
                    "amount": round(avg_amount, 2),
                    "frequency": "monthly" if len(charges) >= 2 else "recurring",
                    "occurrences": len(charges),
                    "first_seen": dates[0],
                    "last_seen": dates[-1],
                    "annual_cost": round(avg_amount * 12, 2),
                })

        return sorted(subscriptions, key=lambda x: x["amount"], reverse=True)

    def get_stock_price(self, symbol: str) -> dict:
        """
        Get current stock price via yfinance, falling back to Yahoo Finance HTML scrape.
        """
        symbol = symbol.upper().strip()

        if YFINANCE_AVAILABLE:
            try:
                ticker = yf.Ticker(symbol)
                info = ticker.fast_info
                price = getattr(info, "last_price", None)
                prev_close = getattr(info, "previous_close", None)
                if price is not None:
                    change = (price - prev_close) if prev_close else 0.0
                    change_pct = (change / prev_close * 100) if prev_close else 0.0
                    return {
                        "symbol": symbol,
                        "price": round(float(price), 2),
                        "change": round(float(change), 2),
                        "change_pct": round(float(change_pct), 2),
                        "previous_close": round(float(prev_close), 2) if prev_close else None,
                        "source": "yfinance",
                    }
            except Exception as e:
                logger.warning(f"yfinance failed for {symbol}: {e}")

        # Fallback: Yahoo Finance query API (JSON endpoint)
        if REQUESTS_AVAILABLE:
            try:
                url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=2d"
                resp = _requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()
                data = resp.json()
                meta = data["chart"]["result"][0]["meta"]
                price = meta.get("regularMarketPrice", 0.0)
                prev_close = meta.get("previousClose", price)
                change = price - prev_close
                change_pct = (change / prev_close * 100) if prev_close else 0.0
                return {
                    "symbol": symbol,
                    "price": round(float(price), 2),
                    "change": round(float(change), 2),
                    "change_pct": round(float(change_pct), 2),
                    "previous_close": round(float(prev_close), 2),
                    "source": "yahoo_finance_api",
                }
            except Exception as e:
                logger.error(f"Yahoo Finance scrape failed for {symbol}: {e}")
                return {"symbol": symbol, "price": None, "change": None, "change_pct": None,
                        "error": str(e)}

        return {"symbol": symbol, "price": None, "change": None, "change_pct": None,
                "error": "No market data source available (install yfinance or requests)."}

    def crypto_prices(self, coins: list) -> dict:
        """
        Fetch crypto prices from CoinGecko free API.
        coins: list of CoinGecko IDs e.g. ["bitcoin", "ethereum", "solana"]
        """
        if not REQUESTS_AVAILABLE:
            return {"error": "requests library not installed", "coins": {}}

        ids_str = ",".join(coins)
        url = (
            f"https://api.coingecko.com/api/v3/simple/price"
            f"?ids={ids_str}&vs_currencies=usd,btc&include_24hr_change=true"
        )
        try:
            resp = _requests.get(url, timeout=10, headers={"Accept": "application/json"})
            resp.raise_for_status()
            raw = resp.json()
            result = {}
            for coin_id, data in raw.items():
                result[coin_id] = {
                    "usd": data.get("usd"),
                    "btc": data.get("btc"),
                    "usd_24h_change": round(data.get("usd_24h_change", 0.0), 2),
                    "btc_24h_change": round(data.get("btc_24h_change", 0.0), 2),
                }
            return {"status": "ok", "coins": result, "as_of": datetime.now().isoformat()}
        except Exception as e:
            logger.error(f"CoinGecko API error: {e}")
            return {"status": "error", "message": str(e), "coins": {}}

    def finance_brief(self) -> str:
        """Generate an LLM finance summary from available data."""
        from core.llm.router import think

        summary_data = {}

        acct = self.account_summary()
        if acct.get("status") == "ok":
            summary_data["accounts"] = acct

        txn_result = self.recent_transactions(days=7)
        if txn_result.get("status") == "ok":
            summary_data["recent_transactions_count"] = txn_result.get("count", 0)

        spending = self.spending_analysis()
        if spending.get("status") == "ok":
            summary_data["spending_by_category"] = spending.get("category_totals", {})

        subs = self.subscription_tracker()
        if subs:
            summary_data["subscriptions"] = subs[:5]  # Top 5

        if not summary_data:
            return (
                "Financial data is not yet configured, sir. "
                "Set up Plaid integration to enable banking insights."
            )

        context = json.dumps(summary_data, indent=2, default=str)
        prompt = (
            f"You are JARVIS, an AI assistant. Generate a concise financial briefing "
            f"in JARVIS's professional style. Highlight notable spending, account health, "
            f"and any concerns. Keep it under 200 words.\n\nFinancial data:\n{context}"
        )
        return think(prompt)

    def bill_reminders(self) -> list:
        """
        Predict upcoming bills based on subscription patterns.
        Returns list of upcoming bills with estimated due dates.
        """
        subscriptions = self.subscription_tracker()
        if not subscriptions:
            return []

        today = datetime.now()
        reminders = []

        for sub in subscriptions:
            last_seen_str = sub.get("last_seen", "")
            try:
                last_seen = datetime.strptime(last_seen_str, "%Y-%m-%d")
            except (ValueError, TypeError):
                last_seen = today - timedelta(days=30)

            # Predict next charge ~30 days after last seen
            next_due = last_seen + timedelta(days=30)
            days_until = (next_due - today).days

            reminders.append({
                "name": sub["name"],
                "amount": sub["amount"],
                "estimated_due": next_due.strftime("%Y-%m-%d"),
                "days_until": days_until,
                "status": "upcoming" if days_until >= 0 else "possibly_overdue",
            })

        # Sort by days_until
        return sorted(reminders, key=lambda x: x["days_until"])


finance = FinanceIntelligence()
