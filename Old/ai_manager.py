import os
from datetime import datetime
import pandas as pd
import yfinance as yf
from dotenv import load_dotenv

# Load local credentials if present
for path in [
    "/Users/vic/Desktop/Coding/.env",
    "/Users/vic/trading_bot/.env",
    ".env",
]:
    if os.path.exists(path):
        load_dotenv(path)


class AITradingManager:
    """
    Autonomous Risk & Operations Officer.
    Monitors market regime, evaluates intraday trade setups,
    and produces executive pre-market and post-market audits.
    """

    def __init__(self):
        self.market_bias = "NEUTRAL"
        self.max_daily_risk = 0.02  # 2% maximum portfolio loss threshold

    def evaluate_macro_regime(self) -> dict:
        """
        Pulls VIX, SPY, and QQQ to determine underlying market health.
        """
        symbols = ["^VIX", "SPY", "QQQ"]
        data = {}

        for sym in symbols:
            try:
                tk = yf.Ticker(sym)
                hist = tk.history(period="5d", interval="1d")
                if not hist.empty and len(hist) >= 2:
                    curr = hist["Close"].iloc[-1]
                    prev = hist["Close"].iloc[-2]
                    pct_change = ((curr - prev) / prev) * 100.0
                    data[sym] = {
                        "price": round(float(curr), 2),
                        "pct_change": round(float(pct_change), 2),
                    }
            except Exception as e:
                data[sym] = {"price": 0.0, "pct_change": 0.0, "error": str(e)}

        vix_val = data.get("^VIX", {}).get("price", 20.0)
        spy_chg = data.get("SPY", {}).get("pct_change", 0.0)
        qqq_chg = data.get("QQQ", {}).get("pct_change", 0.0)

        # Quantitative Bias Matrix
        if vix_val >= 25.0:
            bias = "CAPITAL_PRESERVATION"
            rationale = f"Elevated VIX ({vix_val}). Volatility spikes suggest high slippage and wide spreads."
        elif spy_chg > 0.4 and qqq_chg > 0.4 and vix_val < 18.0:
            bias = "AGGRESSIVE_TREND_LONG"
            rationale = f"Strong multi-index momentum (SPY +{spy_chg}%, QQQ +{qqq_chg}%) with compressed VIX ({vix_val})."
        elif spy_chg < -0.4 and qqq_chg < -0.4:
            bias = "SELECTIVE_SHORT_OR_DEFENSIVE"
            rationale = f"Broad market distribution (SPY {spy_chg}%, QQQ {qqq_chg}%). Favor PUT breakdowns."
        else:
            bias = "SELECTIVE_CHOP"
            rationale = f"Mixed index action (SPY {spy_chg}%, QQQ {qqq_chg}%). Enforce strict ORB boundary retests."

        self.market_bias = bias

        return {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "bias": bias,
            "rationale": rationale,
            "metrics": {
                "vix": vix_val,
                "spy_change_pct": spy_chg,
                "qqq_change_pct": qqq_chg,
            },
        }

    def audit_trade_candidate(self, symbol: str, direction: str, alpha_score: float) -> dict:
        """
        Risk Officer gatekeeper: Approves or rejects setups before execution.
        """
        if self.market_bias == "CAPITAL_PRESERVATION":
            return {
                "approved": False,
                "reason": "REJECTED: Portfolio in Capital Preservation mode (High VIX).",
            }

        if self.market_bias == "SELECTIVE_SHORT_OR_DEFENSIVE" and direction == "CALL":
            return {
                "approved": False,
                "reason": "REJECTED: Counter-trend CALL rejected under defensive market regime.",
            }

        if alpha_score < 60.0:
            return {
                "approved": False,
                "reason": f"REJECTED: Alpha Score ({alpha_score:.1f}/100) below minimum quality gate (60.0).",
            }

        return {
            "approved": True,
            "reason": f"APPROVED: Aligned with {self.market_bias} bias and Alpha Score {alpha_score:.1f}.",
        }

    def generate_premarket_briefing(self) -> str:
        """
        Builds executive text briefing.
        """
        macro = self.evaluate_macro_regime()
        m = macro["metrics"]

        briefing = (
            f"=== 🏛️ TACTICAL AI DESK MANAGER BRIEFING ===\n"
            f"Time: {macro['timestamp']}\n"
            f"Operational Bias: {macro['bias']}\n"
            f"VIX: {m['vix']} | SPY: {m['spy_change_pct']:+0.2f}% | QQQ: {m['qqq_change_pct']:+0.2f}%\n"
            f"Assessment: {macro['rationale']}\n"
            f"============================================"
        )
        return briefing


if __name__ == "__main__":
    manager = AITradingManager()
    print(manager.generate_premarket_briefing())