# Research grounding

These sources support the experimental design, not a profitability assertion for HERO.

| Classification | Source | What it supports / what it does not |
|---|---|---|
| Empirical, broader intraday setting | Heston, Korajczyk & Sadka, *Intraday Patterns in the Cross-section of Stock Returns* (2010), https://arxiv.org/abs/1005.3535 | Reports short-horizon reversals associated with liquidity imbalances and bid–ask bounce, alongside intraday continuation patterns. Does not validate this 30m failure rule or its option implementation. |
| Empirical practitioner research, different strategy | Zarattini, Barbon & Aziz, *A Profitable Day Trading Strategy For The U.S. Equity Market* (2024), https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284 and authors' summary https://concretumgroup.com/a-profitable-day-trading-strategy-for-the-u-s-equity-market/ | Investigates opening-range continuation. Its existence argues against inferring that all breakouts are bad from one losing day. Search abstract/author summary reviewed; full SSRN paper was not accessible in this review. No reported backtest return was adopted. |
| Model/theory, not empirical proof | Leung & Li, *Optimal Mean Reversion Trading with Transaction Costs and Stop-Loss Exit* (2014), https://arxiv.org/abs/1411.5062 | Entry/exit choices depend on costs and stop-loss constraints under an assumed mean-reverting process. Does not establish that an ETF price actually follows that process after an ORB failure. |
| Exchange market structure | NYSE trading information, https://www.nyse.com/trade/trading-information | Opening/closing auctions and session structure matter for bar/session handling. A 5m candle alone cannot identify who swept liquidity or their intention. |
| Broker engineering | https://docs.alpaca.markets/us/docs/working-with-orders and https://docs.alpaca.markets/us/docs/websocket-streaming | Client identifiers and distinct partial-fill/order states support auditable execution recovery. Broker documentation is not strategy validation. |
| Official event calendar | https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm | Confirms the uploaded September 23 FOMC label is inconsistent with the 2026 September 15–16 meeting. Verified calendars must replace hand-entered future-event assumptions. |

**Practitioner heuristics:** wick/CLV interpretation, a failed auction or “liquidity sweep” label, VWAP as an equilibrium reference, and stopping beyond a local extreme. OHLC observations justify descriptive labels, not claims about hidden institutional activity.

**Our testable hypothesis:** a breach followed by failure and confirmation has better cost-adjusted expectancy than a comparable continuation entry under specified regimes. Neither the cited work nor the supplied files establishes this claim.

Pre-register configurations before collecting evaluation sessions. Compare fixed A/B/C policies on separate mode records, stratify by attempt/time/RVOL/width/ATR-depth/VIC, and avoid mixing overlapping bar observations into independent trade counts. Use an untouched holdout or walk-forward period. Compare net option economics only once contemporaneous quotes, filled quantity, slippage and fees are available. Do not promote a rule because one day, one ticker or one small bin looks favorable.
