"""services/investment.py — stock/crypto analysis, educational only, never
financial advice. yfinance/pycoingecko are optional dependencies — both
degrade to "data unavailable" rather than crashing if not installed."""
try:
    import yfinance as yf
    _YFINANCE_OK = True
except ImportError:
    _YFINANCE_OK = False

try:
    from pycoingecko import CoinGeckoAPI
    _COINGECKO_OK = True
except ImportError:
    _COINGECKO_OK = False


class InvestmentAnalyzer:

    def analyze_stock(self, symbol: str) -> dict:
        from core.tools.web import search
        from core.llm.router import think

        price, pe, mktcap, name = "N/A", "N/A", 0, symbol
        if _YFINANCE_OK:
            try:
                info = yf.Ticker(symbol).info
                price = info.get("currentPrice", "N/A")
                pe = info.get("trailingPE", "N/A")
                mktcap = info.get("marketCap", 0) or 0
                name = info.get("longName", symbol)
            except Exception:
                pass

        news_results = search(f"{symbol} stock news", max_results=3)
        news_context = "\n".join(f"• {r.get('snippet','')}" for r in news_results)

        analysis = think(
            f"Analyze {name} ({symbol}) as an investment:\n"
            f"Price: ${price}\nP/E Ratio: {pe}\nMarket Cap: ${mktcap:,}\n"
            f"Recent news: {news_context}\n\n"
            f"Provide: fundamental analysis, technical outlook, risks, opportunities, "
            f"and a balanced view.\nNOT financial advice — educational analysis only.",
            force_model="fable",
        )

        return {
            "symbol": symbol, "name": name, "price": price, "pe": pe,
            "analysis": analysis, "disclaimer": "Not financial advice.",
            "data_available": _YFINANCE_OK,
        }

    def compare(self, symbols: list[str]) -> dict:
        from core.llm.router import think
        analyses = {s: self.analyze_stock(s) for s in symbols[:3]}
        comparison = think(
            f"Compare these investments objectively:\n"
            + "\n".join(f"{s}: {a['analysis'][:300]}" for s, a in analyses.items()),
            force_model="opus",
        )
        return {"comparison": comparison, "details": analyses}

    def crypto_analysis(self, coin: str) -> dict:
        from core.llm.router import think

        price, change_24h = "N/A", "N/A"
        if _COINGECKO_OK:
            try:
                data = CoinGeckoAPI().get_coin_by_id(coin.lower())
                price = data["market_data"]["current_price"]["usd"]
                change_24h = data["market_data"]["price_change_percentage_24h"]
            except Exception:
                pass

        analysis = think(
            f"Analyze {coin} cryptocurrency:\nPrice: ${price}\n24h change: {change_24h}%\n"
            f"Give balanced educational analysis. Not financial advice.",
            force_model="standard",
        )
        return {"coin": coin, "price": price, "change_24h": change_24h, "analysis": analysis,
                "data_available": _COINGECKO_OK}


investor = InvestmentAnalyzer()
