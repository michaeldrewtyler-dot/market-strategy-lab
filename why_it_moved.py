"""
Why It Moved

Breaks any stock's daily move into three parts: how much was the whole market,
how much was its industry, and how much was the company itself. Then it checks
what else happened that day (earnings, a Fed decision, interest rates, fear
in the market) and explains it in plain English. Educational tool.

Setup (one time):
    pip3 install yfinance pandas matplotlib
Run:
    python3 why_it_moved.py NVDA                 -> NVDA's latest trading day
    python3 why_it_moved.py NVDA 2025-04-03      -> a specific day
    python3 why_it_moved.py NVDA biggest         -> its 10 biggest moves of the past year
    python3 why_it_moved.py NVDA 2025-04-03 SOXX -> compare against an industry fund you pick

Opens a page in your browser and saves it in a folder called why_it_moved.
"""

import html
import json
import os
import sys
import webbrowser
import numpy as np
import pandas as pd
import yfinance as yf

# ======================= SETTINGS =======================
ESTIMATION_DAYS = 252      # a year of history to learn how the stock normally moves
GAP_DAYS = 10              # skip the days right before the event so it doesn't learn from itself
TOP_MOVES = 10             # how many moves "biggest" mode explains
OUT_DIR = "why_it_moved"
OPEN_PAGE = True
MY_EVENTS = "my_events.csv"  # optional: your own dates to flag (columns: date,label)
# ========================================================

# Fed rate decision days, taken from federalreserve.gov (2021 onward).
FOMC = pd.to_datetime([
    "2021-01-27", "2021-03-17", "2021-04-28", "2021-06-16", "2021-07-28", "2021-09-22", "2021-11-03", "2021-12-15",
    "2022-01-26", "2022-03-16", "2022-05-04", "2022-06-15", "2022-07-27", "2022-09-21", "2022-11-02", "2022-12-14",
    "2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14", "2023-07-26", "2023-09-20", "2023-11-01", "2023-12-13",
    "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12", "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18", "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
])

SECTOR_ETF = {
    "Technology": "XLK", "Financial Services": "XLF", "Healthcare": "XLV", "Energy": "XLE",
    "Industrials": "XLI", "Consumer Cyclical": "XLY", "Consumer Defensive": "XLP",
    "Utilities": "XLU", "Basic Materials": "XLB", "Real Estate": "XLRE",
    "Communication Services": "XLC",
}
INDUSTRY_ETF = {           # closer peers for industries that move as a pack
    "Semiconductors": "SMH", "Semiconductor Equipment & Materials": "SMH",
    "Software - Infrastructure": "IGV", "Software - Application": "IGV",
    "Biotechnology": "XBI", "Banks - Regional": "KRE", "Oil & Gas E&P": "XOP",
    "Aerospace & Defense": "ITA", "Gold": "GDX",
}
MACRO = {"^VIX": "vix", "^TNX": "tnx", "CL=F": "oil"}


# ---------------- data ----------------
def describe_ticker(t):
    try:
        info = yf.Ticker(t).info or {}
    except Exception:
        info = {}
    name = info.get("shortName") or info.get("longName") or t
    if info.get("quoteType") in ("ETF", "MUTUALFUND", "INDEX"):
        IT["word"] = "the fund itself"
        return name, None, None
    ind, sec = info.get("industry"), info.get("sector")
    peer = INDUSTRY_ETF.get(ind) or SECTOR_ETF.get(sec)
    return name, peer, ind or sec


def earnings_dates(t):
    """Earnings report times in New York time (the hour tells us before-open vs after-close)."""
    try:
        ed = yf.Ticker(t).get_earnings_dates(limit=40)
        idx = pd.DatetimeIndex(ed.index)
        if idx.tz is not None:
            idx = idx.tz_convert("America/New_York").tz_localize(None)
        return sorted(set(idx))
    except Exception:
        return []


def my_events():
    if not os.path.exists(MY_EVENTS):
        return {}
    try:
        df = pd.read_csv(MY_EVENTS)
        return {pd.Timestamp(d).normalize(): str(l) for d, l in zip(df["date"], df["label"])}
    except Exception:
        print(f"  Couldn't read {MY_EVENTS} (needs columns: date,label).")
        return {}


def download(tickers, start, end):
    raw = yf.download(tickers, start=start, end=end, auto_adjust=True, progress=False,
                      group_by="ticker")
    out = {}
    for t in tickers:
        try:
            s = (raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw)["Close"].dropna()
            if len(s):
                out[t] = s
        except Exception:
            pass
    return pd.DataFrame(out)


def recent_news(t, day):
    """Yahoo only keeps recent headlines, so this only helps for the last week or so."""
    try:
        items = yf.Ticker(t).news or []
    except Exception:
        return []
    out = []
    for it in items:
        c = it.get("content", it)
        title = c.get("title")
        when = c.get("pubDate") or c.get("displayTime") or it.get("providerPublishTime")
        src = (c.get("provider") or {}).get("displayName") or it.get("publisher") or ""
        try:
            ts = (pd.Timestamp(when, unit="s") if isinstance(when, (int, float))
                  else pd.Timestamp(when)).tz_localize(None) if when else None
        except Exception:
            ts = None
        if title and ts is not None and abs((ts.normalize() - day).days) <= 1:
            out.append((ts, title, src))
    return sorted(out, reverse=True)[:5]


# ---------------- the math ----------------
def decompose(r, day):
    """Split the stock's return on `day` into market, industry and company parts.

    Model (fit on the year before the event):
        stock = a + b_mkt * market + b_ind * (industry move beyond what the market explains) + noise
    """
    i = r.index.get_loc(day)
    lo, hi = max(0, i - GAP_DAYS - ESTIMATION_DAYS), i - GAP_DAYS
    est = r.iloc[lo:hi].dropna()
    if len(est) < 60:
        return None
    has_peer = "peer" in r.columns and est["peer"].notna().all()
    m = est["mkt"].values
    if has_peer:
        b_pm = np.polyfit(m, est["peer"].values, 1)[0]             # industry's own market beta
        ind = est["peer"].values - b_pm * m
        X = np.column_stack([np.ones(len(m)), m, ind])
    else:
        X = np.column_stack([np.ones(len(m)), m])
    coef, *_ = np.linalg.lstsq(X, est["stock"].values, rcond=None)
    resid = est["stock"].values - X @ coef
    sigma = resid.std(ddof=X.shape[1])

    row = r.loc[day]
    total = row["stock"]
    market = coef[1] * row["mkt"]
    industry = coef[2] * (row["peer"] - b_pm * row["mkt"]) if has_peer else 0.0
    company = total - market - industry
    z = company / sigma if sigma > 0 else np.nan
    typical = float(np.mean(np.abs(resid)))
    rarer = float(np.mean(np.abs(resid) >= abs(company)))       # share of normal days this extreme
    fit = X @ coef
    r2 = 1 - resid.var() / est["stock"].var() if est["stock"].var() > 0 else np.nan
    return dict(total=total, market=market, industry=industry, company=company, z=z,
                beta=coef[1], b_ind=coef[2] if has_peer else None, sigma=sigma,
                typical=typical, rarer=rarer, r2=r2, has_peer=has_peer, n=len(est))


def context(day, prices, earn, custom):
    """What else happened: earnings, Fed, rates, fear, oil, your own events."""
    c = {}
    prev = prices.index[prices.index.get_loc(day) - 1]
    c["earnings"] = None
    for e in earn:
        ed, hr = e.normalize(), e.hour + e.minute / 60
        if ed == day and 0 < hr < 9.5:
            c["earnings"] = "Earnings came out before the market opened that morning"
        elif ed == day and hr == 0:
            c["earnings"] = "Earnings came out that day"
        elif prev <= ed < day and (hr >= 16 or ed > prev):
            c["earnings"] = "Earnings came out after the close the day before"
    c["fomc"] = day in set(FOMC)
    if "tnx" in prices and not pd.isna(prices.at[day, "tnx"]) and not pd.isna(prices.at[prev, "tnx"]):
        lvl, chg = prices.at[day, "tnx"], prices.at[day, "tnx"] - prices.at[prev, "tnx"]
        scale = 100 if lvl < 20 else 10                           # Yahoo quotes 4.25 = 4.25%
        c["yield_bp"], c["yield_lvl"] = chg * scale, lvl if lvl < 20 else lvl / 10
    if "vix" in prices and not pd.isna(prices.at[day, "vix"]):
        c["vix"], c["vix_chg"] = prices.at[day, "vix"], prices.at[day, "vix"] - prices.at[prev, "vix"]
    if "oil" in prices and not pd.isna(prices.at[day, "oil"]) and prices.at[prev, "oil"] > 0:
        c["oil"] = prices.at[day, "oil"] / prices.at[prev, "oil"] - 1
    c["custom"] = custom.get(day)
    return c


# ---------------- plain English ----------------
def pp(x):
    v = x * 100
    return "0.0%" if abs(v) < 0.05 else f"{v:+.1f}%"


IT = {"word": "the company itself"}   # becomes "the fund itself" for ETFs


def biggest_part(d):
    parts = {"the market": d["market"], "its industry": d["industry"], IT["word"]: d["company"]}
    return max(parts, key=lambda k: abs(parts[k]))


def explain(t, day, d, c, mkt_move, peer, peer_label):
    verb = "rose" if d["total"] > 0 else "fell"
    lines = []
    lines.append(f"{t} {verb} {abs(d['total']) * 100:.1f}% on {day.strftime('%B %-d, %Y')}.")
    main = biggest_part(d)
    lines.append(
        f"Market: the S&P 500 moved {pp(mkt_move)}. With a beta of {d['beta']:.2f}, {t} typically moves "
        f"about {d['beta']:.1f}x the market, so the market alone accounts for about {pp(d['market'])}.")
    if d["has_peer"]:
        lines.append(f"Industry ({peer}, {peer_label}): the industry's own move, beyond what the market "
                     f"did, adds about {pp(d['industry'])}.")
    z = abs(d["z"])
    if z >= 3:
        size = "a huge"
    elif z >= 2:
        size = "a big"
    elif z >= 1:
        size = "a modest"
    else:
        size = "a normal-sized"
    rare = (f"only {d['rarer']:.0%} of normal days were this extreme" if d["rarer"] > 0
            else "bigger than any normal day in the past year")
    kind = "fund" if IT["word"] == "the fund itself" else "company"
    lines.append(f"{kind.capitalize()}-specific: the remaining {pp(d['company'])} was about {t} itself. That's "
                 f"{size} {kind}-specific move ({z:.1f}x its usual size; {rare}).")

    why = []
    if c.get("earnings"):
        why.append(f"{c['earnings']}. Earnings are the most common reason for big company-specific moves.")
    if c.get("fomc"):
        why.append("It was a Fed rate decision day, which often moves the whole market.")
    if abs(c.get("yield_bp", 0)) >= 8:
        dirn = "jumped" if c["yield_bp"] > 0 else "dropped"
        eff = ("Higher rates usually weigh on fast-growing tech stocks, since their profits are further "
               "in the future." if c["yield_bp"] > 0 else
               "Lower rates usually help fast-growing tech stocks, since their future profits are worth more today.")
        why.append(f"The 10-year Treasury yield {dirn} {abs(c['yield_bp']):.0f} basis points "
                   f"(to {c['yield_lvl']:.2f}%). {eff}")
    if c.get("vix_chg", 0) >= 3 or (c.get("vix") and c.get("vix_chg", 0) / max(c["vix"] - c["vix_chg"], 1) >= 0.15):
        why.append(f"Fear spiked: the VIX 'fear index' rose {c['vix_chg']:.1f} points to {c['vix']:.1f}.")
    elif c.get("vix_chg", 0) <= -3:
        why.append(f"Fear eased: the VIX fell {abs(c['vix_chg']):.1f} points to {c['vix']:.1f}.")
    if abs(c.get("oil", 0)) >= 0.03:
        why.append(f"Oil moved {pp(c['oil'])}, which matters most for energy, airline, and transport stocks.")
    if c.get("custom"):
        why.append(f"Your note for this date: {c['custom']}.")

    if main == "the company itself" and abs(d["z"]) >= 2 and not c.get("earnings"):
        why.append(f"No earnings that day, so look for {t}-specific news: an analyst upgrade or downgrade, "
                   f"a product announcement, a deal, or a regulator.")
    if main == "the market":
        summary = f"Mostly a market day: {t} was carried by the whole market more than anything about the company."
    elif main == "its industry":
        summary = f"Mostly an industry day: {t} moved with its industry peers."
    else:
        summary = f"Mostly about {t} itself: the market and industry don't explain most of this move."
    return summary, lines, why


# ---------------- page ----------------
PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Newsreader:opsz,wght@6..72,400;6..72,500&family=Public+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root { --paper:#F5F7FA; --panel:#FFFFFF; --ink:#14213D; --soft:#55607A; --rule:#D9DEE7;
  --gain:#2E6B4F; --loss:#9B2C2C; --mkt:#5B6B8C; --ind:#A9824A; --co:#14213D;
  --serif:"Newsreader","Iowan Old Style",Georgia,serif; --sans:"Public Sans","Helvetica Neue",Arial,sans-serif; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --paper:#0E1729; --panel:#131F36; --ink:#E6EAF2; --soft:#9AA6BE; --rule:#27344E;
  --gain:#62B38C; --loss:#E07C7E; --mkt:#8C9BBB; --ind:#D3AF73; --co:#E6EAF2; } }
* { box-sizing: border-box; }
html, body { margin:0; background:var(--paper); color:var(--ink); font:16px/1.6 var(--sans);
  font-variant-numeric: tabular-nums; }
main { max-width: 860px; margin: 0 auto; padding: 56px 28px 72px; }
.kicker { color: var(--soft); font-size: 14px; margin: 0 0 12px; }
h1 { font: 500 clamp(30px, 4.6vw, 46px)/1.12 var(--serif); margin: 0 0 16px; letter-spacing: -0.01em; }
.summary { font: 400 21px/1.45 var(--serif); margin: 0 0 36px; max-width: 40ch; }
h2 { font: 500 23px/1.3 var(--serif); margin: 56px 0 8px; }
.lede { color: var(--soft); font-size: 15px; margin: 0 0 18px; max-width: 64ch; }
.split { position: relative; height: 56px; margin: 8px 0 10px; }
.axis { position: absolute; top: 0; bottom: 0; width: 1px; background: var(--soft); }
.piece { position: absolute; height: 36px; top: 10px; border-radius: 3px; }
.piece.market { background: var(--mkt); } .piece.industry { background: var(--ind); }
.piece.company { background: var(--co); }
.total { position: absolute; height: 4px; top: 50px; border-radius: 2px; }
.key { display: grid; grid-template-columns: 14px 1fr auto; gap: 6px 12px; align-items: baseline;
  margin: 18px 0 0; }
.key i { width: 12px; height: 12px; border-radius: 2px; display: inline-block; transform: translateY(1px); }
.key .num { font-weight: 600; text-align: right; }
.key .sum { border-top: 1px solid var(--ink); padding-top: 8px; }
.up { color: var(--gain); } .down { color: var(--loss); }
.detail p { max-width: 66ch; margin: 0 0 12px; }
ul.why { list-style: none; padding: 0; margin: 0; }
ul.why li { border-left: 2px solid var(--ind); padding: 6px 0 6px 16px; margin: 0 0 12px; max-width: 66ch; }
table { border-collapse: collapse; width: 100%; font-size: 15px; }
th, td { padding: 9px 8px; text-align: right; }
thead th { font-weight: 500; color: var(--soft); font-size: 13px; border-bottom: 1px solid var(--ink); }
tbody tr + tr > * { border-top: 1px solid var(--rule); }
td.l, th.l { text-align: left; }
.mini { display: flex; height: 12px; width: 140px; margin-left: auto; border-radius: 2px; overflow: hidden;
  background: var(--rule); }
.mini span { display: block; height: 100%; }
.tag { font-size: 13px; color: var(--soft); }
.scroll { overflow-x: auto; }
.chart { width: 100%; height: auto; display: block; aspect-ratio: 860 / 260; }
.chart .grid { stroke: var(--rule); vector-effect: non-scaling-stroke; }
.chart text { fill: var(--soft); font: 12px var(--sans); }
.chart .line { fill: none; stroke-width: 2; vector-effect: non-scaling-stroke; }
.chart .s { stroke: var(--co); stroke-width: 2.6; } .chart .m { stroke: var(--mkt); } .chart .p { stroke: var(--ind); }
.chart .ev { stroke: var(--loss); stroke-dasharray: 4 4; vector-effect: non-scaling-stroke; }
.legend { display: flex; gap: 20px; font-size: 14px; color: var(--soft); margin: 0 0 6px; flex-wrap: wrap; }
.legend span::before { content: ""; display: inline-block; width: 16px; height: 3px; margin-right: 8px;
  vertical-align: middle; border-radius: 2px; background: var(--c); }
footer { margin-top: 64px; padding-top: 18px; border-top: 1px solid var(--rule); color: var(--soft); font-size: 13px; }
@media (max-width: 700px) { main { padding: 36px 18px 56px; } .summary { font-size: 19px; }
  .chart text { font-size: 24px; } }
</style></head><body><main>
__BODY__
<footer>How it works: using the year before the move, the tool learns how much this stock normally moves
with the S&amp;P 500 (its beta) and with its industry fund. On the day itself, it applies those sensitivities
to what the market and industry actually did. Whatever's left over is the company-specific part.
Educational tool, not financial advice. Prices from Yahoo Finance.</footer>
</main></body></html>"""


def split_bar(d):
    """Horizontal bar: pieces stacked from zero, each scaled to the largest cumulative extent."""
    parts = [("market", d["market"]), ("industry", d["industry"]), ("company", d["company"])]
    pos, ext = 0.0, [0.0]
    for _, v in parts:
        pos += v
        ext.append(pos)
    span = max(abs(min(ext)), abs(max(ext)), 1e-9)
    lo = min(0.0, min(ext)) / span
    hi = max(0.0, max(ext)) / span
    to_pct = lambda v: (v / span - lo) / (hi - lo) * 100
    out, pos = [], 0.0
    for name, v in parts:
        a, b = sorted([to_pct(pos), to_pct(pos + v)])
        if b - a > 0.2:
            out.append(f'<span class="piece {name}" style="left:{a:.2f}%;width:{b - a:.2f}%"></span>')
        pos += v
    a, b = sorted([to_pct(0), to_pct(d["total"])])
    cls = "up" if d["total"] >= 0 else "down"
    out.append(f'<span class="total" style="left:{a:.2f}%;width:{b - a:.2f}%;'
               f'background:var(--{"gain" if cls == "up" else "loss"})"></span>')
    out.append(f'<span class="axis" style="left:{to_pct(0):.2f}%"></span>')
    return f'<div class="split" role="img" aria-label="Move split into market, industry and company parts">{"".join(out)}</div>'


def key_rows(d, peer):
    def row(color, label, v, cls=""):
        c = "" if abs(v) < 0.0005 else "up" if v > 0 else "down"
        return (f'<i style="background:{color}"></i><span class="{cls}">{label}</span>'
                f'<span class="num {c} {cls}">{pp(v)}</span>')
    rows = [row("var(--mkt)", "The market", d["market"])]
    if d["has_peer"]:
        rows.append(row("var(--ind)", f"Its industry ({html.escape(peer)})", d["industry"]))
    rows.append(row("var(--co)", IT["word"].capitalize(), d["company"]))
    rows.append('<i></i><span class="sum"><strong>Total move</strong></span>'
                f'<span class="num sum {"up" if d["total"] >= 0 else "down"}">{pp(d["total"])}</span>')
    return f'<div class="key">{"".join(rows)}</div>'


def around_chart(prices, day, t, peer):
    i = prices.index.get_loc(day)
    w = prices.iloc[max(0, i - 30): i + 16]
    cols = [("stock", t, "s"), ("mkt", "S&P 500", "m")] + ([("peer", peer, "p")] if peer and "peer" in w else [])
    base = w.iloc[0]
    series = [(lbl, (w[c] / base[c] - 1) * 100, cls) for c, lbl, cls in cols if w[c].notna().all()]
    W, H, L, R, T, B = 860, 260, 84, 10, 10, 30
    allv = np.concatenate([s.values for _, s, _ in series])
    lo, hi = float(allv.min()), float(allv.max())
    pad = (hi - lo) * 0.08 or 1
    lo, hi = lo - pad, hi + pad
    n = len(w)
    x = lambda k: L + (W - L - R) * k / max(n - 1, 1)
    y = lambda v: T + (H - T - B) * (hi - v) / (hi - lo)
    parts = []
    step = 10 ** np.floor(np.log10(max((hi - lo) / 4, 1e-9)))
    step = step * (5 if (hi - lo) / step > 20 else 2 if (hi - lo) / step > 8 else 1)
    v = np.ceil(lo / step) * step
    while v <= hi:
        parts.append(f'<line class="grid" x1="{L}" x2="{W - R}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>'
                     f'<text x="{L - 6}" y="{y(v) + 4:.1f}" text-anchor="end">{v:+.0f}%</text>')
        v += step
    k_ev = w.index.get_loc(day)
    parts.append(f'<line class="ev" x1="{x(k_ev):.1f}" x2="{x(k_ev):.1f}" y1="{T}" y2="{H - B}"/>')
    for k in (0, k_ev, n - 1):
        anchor = "start" if k == 0 else "end" if k == n - 1 else "middle"
        parts.append(f'<text x="{x(k):.1f}" y="{H - 6}" text-anchor="{anchor}">{w.index[k].strftime("%b %-d")}</text>')
    for _, s, cls in series:
        pts = " ".join(f"{x(k):.1f},{y(val):.1f}" for k, val in enumerate(s.values))
        parts.append(f'<polyline class="line {cls}" points="{pts}"/>')
    legend = "".join(f'<span style="--c:var(--{"co" if c == "s" else "mkt" if c == "m" else "ind"})">'
                     f'{html.escape(lbl)}</span>' for lbl, _, c in series)
    return (f'<div class="legend">{legend}</div><svg class="chart" viewBox="0 0 {W} {H}" '
            f'preserveAspectRatio="none" role="img" aria-label="Six weeks around the move">{"".join(parts)}</svg>')


def day_page(t, name, day, d, c, summary, lines, why, news, prices, peer, peer_label):
    verb = "rose" if d["total"] > 0 else "fell"
    body = [f'<p class="kicker">{html.escape(name)} ({t})</p>',
            f'<h1>{t} {verb} {abs(d["total"]) * 100:.1f}% on {day.strftime("%B %-d, %Y")}.</h1>',
            f'<p class="summary">{html.escape(summary)}</p>',
            split_bar(d), key_rows(d, peer),
            '<h2>How the move breaks down</h2>',
            '<div class="detail">' + "".join(f"<p>{html.escape(s)}</p>" for s in lines[1:]) + "</div>",
            '<h2>What else was going on</h2>',
            '<ul class="why">' + ("".join(f"<li>{html.escape(s)}</li>" for s in why)
                                  or "<li>Nothing unusual in rates, fear, oil, earnings, or the Fed that day.</li>")
            + "</ul>"]
    if news:
        body.append("<h2>Headlines that day</h2><ul class='why'>" + "".join(
            f"<li>{html.escape(ti)} <span class='tag'>{html.escape(src)}</span></li>" for _, ti, src in news)
            + "</ul>")
    body += ['<h2>Six weeks around the move</h2>',
             '<p class="lede">Percent change from the start of the window. The dashed line is the day of the move.</p>',
             around_chart(prices, day, t, peer)]
    return PAGE.replace("__TITLE__", f"Why {t} moved, {day.date()}").replace("__BODY__", "".join(body))


def biggest_page(t, name, rows, stats):
    trs = []
    for r in rows:
        d = r["d"]
        tot = abs(d["market"]) + abs(d["industry"]) + abs(d["company"]) or 1
        mini = "".join(f'<span style="width:{abs(d[k]) / tot * 100:.1f}%;background:var(--{v})"></span>'
                       for k, v in (("market", "mkt"), ("industry", "ind"), ("company", "co")))
        tags = ", ".join(x for x in [("earnings" if r["c"].get("earnings") else ""),
                                     ("Fed day" if r["c"].get("fomc") else "")] if x) or ""
        trs.append(f'<tr><td class="l">{r["day"].strftime("%b %-d, %Y")}</td>'
                   f'<td class="{"up" if d["total"] >= 0 else "down"}"><strong>{pp(d["total"])}</strong></td>'
                   f'<td>{pp(d["market"])}</td><td>{pp(d["industry"])}</td><td>{pp(d["company"])}</td>'
                   f'<td><div class="mini">{mini}</div></td><td class="l tag">{html.escape(r["main"])}'
                   f'{" (" + tags + ")" if tags else ""}</td></tr>')
    body = [f'<p class="kicker">{html.escape(name)} ({t})</p>',
            f'<h1>{t}\'s {len(rows)} biggest moves of the past year, explained.</h1>',
            f'<p class="summary">{html.escape(stats)}</p>',
            '<div class="legend"><span style="--c:var(--mkt)">The market</span>'
            f'<span style="--c:var(--ind)">Its industry</span><span style="--c:var(--co)">{IT["word"].capitalize()}</span></div>',
            '<div class="scroll"><table><thead><tr><th class="l">Day</th><th>Move</th><th>Market</th>'
            '<th>Industry</th><th>Company</th><th>Mix</th><th class="l">Mostly</th></tr></thead><tbody>'
            + "".join(trs) + "</tbody></table></div>",
            f'<p class="lede" style="margin-top:18px">Run <code>python3 why_it_moved.py {t} YYYY-MM-DD</code> '
            'on any of these days for the full story.</p>']
    return PAGE.replace("__TITLE__", f"{t}'s biggest moves").replace("__BODY__", "".join(body))


# ---------------- main ----------------
def main():
    if len(sys.argv) < 2:
        raise SystemExit("Usage: python3 why_it_moved.py TICKER [YYYY-MM-DD | biggest] [PEER_ETF]")
    t = sys.argv[1].strip().upper()
    mode = sys.argv[2].strip().lower() if len(sys.argv) > 2 else "latest"
    if t in ("SPY", "VOO", "IVV", "^GSPC"):
        raise SystemExit(f"{t} is the market itself, so there's nothing to split. Try a stock or a sector fund.")
    name, peer, peer_label = describe_ticker(t)
    if len(sys.argv) > 3:
        peer, peer_label = sys.argv[3].strip().upper(), "your pick"

    today = pd.Timestamp.today().normalize()
    if mode in ("latest", "biggest"):
        target, start, end = None, today - pd.DateOffset(years=3), today + pd.Timedelta(days=1)
    else:
        try:
            target = pd.Timestamp(mode).normalize()
        except Exception:
            raise SystemExit("Date must look like 2025-04-03, or use 'biggest'.")
        start, end = target - pd.DateOffset(years=2), min(target + pd.Timedelta(days=40), today + pd.Timedelta(days=1))

    tickers = list(dict.fromkeys([t, "SPY"] + ([peer] if peer else []) + list(MACRO)))
    print(f"Downloading {', '.join(tickers)}...")
    px = download(tickers, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    if t not in px or px[t].dropna().empty:
        raise SystemExit(f"No price data for {t}. Check the ticker.")
    px = px[px[t].notna() & px["SPY"].notna()]
    prices = pd.DataFrame({"stock": px[t], "mkt": px["SPY"]})
    if peer and peer in px:
        prices["peer"] = px[peer]
    elif peer:
        print(f"  Couldn't get {peer}; using the market only.")
        peer = None
    for k, v in MACRO.items():
        if k in px:
            prices[v] = px[k].ffill()
    r = prices[["stock", "mkt"] + (["peer"] if peer else [])].pct_change()

    earn = earnings_dates(t)
    custom = my_events()
    os.makedirs(OUT_DIR, exist_ok=True)

    if mode == "biggest":
        last_year = r.index[r.index >= r.index[-1] - pd.DateOffset(years=1)]
        top = r.loc[last_year, "stock"].abs().nlargest(TOP_MOVES).index.sort_values()
        rows = []
        for day in top:
            d = decompose(r, day)
            if d is None:
                continue
            c = context(day, prices, earn, custom)
            rows.append(dict(day=day, d=d, c=c, main=biggest_part(d)))
        if not rows:
            raise SystemExit("Not enough history to explain those moves.")
        n_co = sum(x["main"] == IT["word"] for x in rows)
        n_mk = sum(x["main"] == "the market" for x in rows)
        n_in = len(rows) - n_co - n_mk
        n_earn = sum(bool(x["c"].get("earnings")) for x in rows if x["main"] == IT["word"])
        stats = (f"Of these {len(rows)} moves, {n_co} were mostly about {t} itself"
                 f"{f' ({n_earn} on earnings)' if n_co else ''}, {n_mk} were mostly the market, "
                 f"and {n_in} were mostly its industry.")
        print("\n" + stats + "\n")
        print(f"  {'Day':12} {'Move':>7} {'Market':>7} {'Industry':>9} {'Company':>8}  Mostly")
        for x in rows:
            d = x["d"]
            extra = " (earnings)" if x["c"].get("earnings") else ""
            print(f"  {x['day'].strftime('%Y-%m-%d'):12} {pp(d['total']):>7} {pp(d['market']):>7} "
                  f"{pp(d['industry']):>9} {pp(d['company']):>8}  {x['main']}{extra}")
        page = biggest_page(t, name, rows, stats)
        path = os.path.join(OUT_DIR, f"{t}_biggest.html")
    else:
        if target is None:
            day = r.index[-1]
        else:
            later = r.index[r.index >= target]
            if len(later) == 0:
                raise SystemExit("That date is after the latest data.")
            day = later[0]
            if day != target:
                print(f"  {target.date()} wasn't a trading day; using {day.date()}.")
        d = decompose(r, day)
        if d is None:
            raise SystemExit("Not enough history before that date (needs about 3 months).")
        c = context(day, prices, earn, custom)
        summary, lines, why = explain(t, day, d, c, r.at[day, "mkt"], peer, peer_label)
        news = recent_news(t, day) if (today - day).days <= 7 else []
        print()
        print(summary)
        print()
        for s in lines:
            print("  " + s)
        if why:
            print("\nWhat else was going on:")
            for s in why:
                print("  - " + s)
        if news:
            print("\nHeadlines:")
            for _, ti, src in news:
                print(f"  - {ti} ({src})")
        page = day_page(t, name, day, d, c, summary, lines, why, news, prices, peer, peer_label)
        path = os.path.join(OUT_DIR, f"{t}_{day.date()}.html")

    with open(path, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"\nSaved: {os.path.abspath(path)}")
    if OPEN_PAGE:
        webbrowser.open("file://" + os.path.abspath(path))


if __name__ == "__main__":
    main()
