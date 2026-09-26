# Market Strategy Lab

**Can a rules-based trading strategy beat simply holding the S&P 500?**

I built a set of Python tools to answer that honestly: a swing-trading backtester, an out-of-sample strategy lab, and a portfolio analyzer. I tested my own swing-trading rules and 38 configurations of well-known systematic strategies across 20 years of daily market data.

**Short answer: no.** Once the tests were made fair, nothing I tested beat buy-and-hold of the S&P 500 on a risk-adjusted basis. Along the way, the most important finding was catching a bias in my own results that had made one strategy look like it returned 37.7% a year.

> Educational research project. Not financial advice.

---

## What's in this repo

| File | What it does |
|---|---|
| `backtester.py` | Swing-trading backtester. Simulates real trading rules day by day: position sizing by account risk, stop-losses, trailing stops, earnings-gap avoidance, slippage. Compares strategies side by side against the S&P 500. |
| `strategy_lab.py` | Tests research-backed strategy families (trend following, momentum, dual momentum, mean reversion) using a train/test split so settings can't be tuned to the answer. |
| `portfolio_analyzer.py` | Analyzes any portfolio: return, volatility, Sharpe ratio, max drawdown, beta, concentration, correlation, and sector exposure, with a plain-English summary. |

---

## Method

The goal was to avoid the ways backtests usually fool people.

- **No lookahead.** Every signal uses only data available at that day's close, and trades fill at the next day's open. Swing highs and lows only count once they're confirmed.
- **Out-of-sample testing.** In the strategy lab, each strategy's settings were chosen using **2007–2016 only**, then judged on **2017–2026**, a period those settings never saw.
- **Realistic costs.** Slippage on every fill, 0.1% cost per dollar traded, and uninvested cash earning the T-bill rate.
- **Risk-based position sizing.** Trades risk a fixed percentage of the account, the way disciplined traders size positions.
- **Earnings filter.** No new entries within 5 days of earnings, and open trades close before reports to avoid gap risk.
- **Bias checks.** Results from a hand-picked stock list were re-tested on sector funds that can't be cherry-picked (see findings).

---

## Results

### 1. Strategy lab: 20 years, out-of-sample

Training: Oct 2007 – Dec 2016. Test: Jan 2017 – Sep 2026. **The test period is the one that counts.**

| Strategy | Train CAGR | Train Sharpe | Train worst drop | **Test CAGR** | **Test Sharpe** | **Test worst drop** |
|---|---|---|---|---|---|---|
| **Buy & hold S&P 500** | +6.5% | 0.39 | -54.7% | **+15.4%** | **0.75** | -33.7% |
| Equal-weight 9 sectors | +7.4% | 0.43 | -52.3% | +13.0% | 0.65 | -36.9% |
| S&P 500 + 200-day trend filter | +9.6% | 0.78 | -17.3% | +8.9% | 0.55 | -25.0% |
| Sector momentum + trend filter | +10.0% | 0.76 | -22.3% | +8.6% | 0.49 | -23.8% |
| Sector momentum | +7.0% | 0.44 | -47.2% | +9.2% | 0.44 | -32.3% |
| Dual momentum (US / Intl / Bonds) | +8.1% | 0.62 | -17.3% | +5.9% | 0.29 | -33.7% |
| RSI(2) dip-buying on S&P 500 | +1.1% | 0.14 | -15.1% | +2.5% | 0.04 | -14.6% |
| *Stock momentum (biased list)* | *+23.5%* | *0.90* | *-51.0%* | *+37.7%* | *1.03* | *-37.0%* |

*CAGR = average yearly return. Sharpe = return above T-bills per unit of volatility. Worst drop = maximum drawdown.*

![Strategy lab growth](results/strategy_<img width="1430" height="715" alt="strategy_lab_growth" src="https://github.com/user-attachments/assets/1d912929-8aa9-4f7b-940d-de9b1509a97a" />


### 2. My swing-trading rules: 20 years, 48 stocks, 1% risk per trade

My rules: enter on pullbacks in an uptrend or breakouts above resistance; stop below the most recent higher low; exit when the trend breaks (a lower low, or a close below the 50-day average).

| | My rules | Generic pullback rules | S&P 500 |
|---|---|---|---|
| Yearly return (CAGR) | +7.5% | +7.7% | **+11.2%** |
| Worst drawdown | **-28.0%** | -26.3% | -55.2% |
| Trades | 1,616 | 1,692 | – |
| Win rate | 37% | 38% | – |
| Expectancy per trade | +0.12R | +0.13R | – |
| Profit factor | 1.29 | 1.28 | – |

*R = the amount risked on a trade. +0.12R means about $12 gained per $100 risked, on average.*

![Swing backtest](results/backtest_equity.png<img width="1300" height="624" alt="equity" src="https://github.com/user-attachments/assets/e384e92b-9d17-41ef-8bac-6b9963f10692" />
)

---

## Key findings

**1. The 37.7% strategy was an illusion, and I built the illusion.**
Stock momentum (buy the top 5 performers each month) appeared to crush the market in both periods. But I had chosen the 48-stock list in 2026, and it included stocks I already knew became huge winners (NVDA, PLTR, AVGO). The list also only contained companies that survived to today. To test fairly, I ran the same momentum idea on the 9 original S&P sector funds, which have existed since 1998 and can't be cherry-picked. **Sector momentum returned 9.2% a year, losing to the S&P 500 (15.4%) and even to owning all 9 sectors equally (13.0%).** The edge came from my hindsight, not the strategy.

**2. My swing rules have a real but small edge, and it's not enough.**
Over 1,616 trades the rules made money per trade, and they cut the worst drawdown roughly in half versus the S&P 500. But they returned 7.5% a year versus 11.2%. Raising risk per trade above 1% didn't close the gap. Returns actually fell, because larger positions hit cash and position-size limits and forced the system to skip trades.

**3. Risk reduction is real, but expensive.**
Trend filters reliably reduced the worst drawdown (about -34% to -25% in the test period) but gave up about 6.5 percentage points of return per year. That trade-off can suit someone who would otherwise panic-sell in a crash, but it isn't free.

**4. Published edges fade.**
Strategies with strong academic backing (momentum, trend following, short-term mean reversion) looked better in the training period than in the test period, consistent with research showing anomalies weaken after they become widely known and traded.

**Conclusion:** for a long-term investor, low-cost broad index investing was the strongest approach in every fair test I ran. Active strategies can reduce drawdowns, but in these tests they cost more in return than they saved in risk.

---

## Limitations

- Stock-level tests only include companies that still exist today (survivorship bias).
- Taxes aren't modeled. Monthly or swing strategies generate short-term gains outside tax-advantaged accounts, which would widen the gap versus buy-and-hold.
- Yahoo Finance data, daily bars only. Earnings dates may be incomplete for older years.
- 38 configurations were tested. Testing more combinations increases the chance that a "winner" is luck.

---

## How to run

```bash
pip3 install -r requirements.txt

python3 strategy_lab.py        # out-of-sample strategy comparison
python3 backtester.py          # swing-trading backtest (edit rules at the top of the file)
python3 portfolio_analyzer.py  # analyze a portfolio (edit HOLDINGS, or pass a CSV of ticker,shares)
```

Each script saves a Markdown report and charts in its own results folder. Settings live in clearly labeled sections at the top of each file.

**Built with:** Python, pandas, NumPy, Matplotlib, yfinance.

---

## About

Built by Michael Tyler, an incoming finance student interested in wealth management. This project started as a question about my own trading and turned into a lesson in how to test ideas without fooling yourself.
