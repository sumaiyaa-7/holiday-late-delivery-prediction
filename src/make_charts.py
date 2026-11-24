"""Charts for the README (PNG). Palette: validated categorical order, one axis per chart."""
import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.ticker
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

import config as C

SURF, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
S1, S2, S3, S4 = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
CRIT = "#d03b3b"
SEQ = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]

plt.rcParams.update({
    "figure.facecolor": SURF, "axes.facecolor": SURF, "savefig.facecolor": SURF,
    "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "text.color": INK, "font.size": 10, "axes.titlesize": 12.5, "axes.titleweight": "bold",
    "axes.titlelocation": "left", "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
    "legend.frameon": False, "lines.linewidth": 2,
})
O = C.OUT


def subtitle(ax, text):
    ax.text(0, 1.02, text, transform=ax.transAxes, color=INK2, fontsize=9.5, va="bottom")


def save(fig, name):
    fig.tight_layout()
    fig.savefig(C.CHARTS / name, dpi=160)
    plt.close(fig)


def money_at_risk():
    d = pd.read_csv(O / "money_at_risk_daily.csv", parse_dates=["date"])
    d = d[d.date <= "2026-12-26"]
    fig, ax = plt.subplots(figsize=(10, 4.6))
    ax.fill_between(d.date, d.money_at_risk, color=S1, alpha=0.12, linewidth=0)
    ax.plot(d.date, d.money_at_risk, color=S1)
    for x, lab, ha in [(C.BLACK_FRIDAY, "Black Friday ", "right"), (C.CYBER_MONDAY, " Cyber Monday", "left"),
                       (C.GIFT_CRITICAL_FROM, " Gift-critical\n promises begin", "left")]:
        ax.axvline(pd.Timestamp(x), color=INK2, lw=0.8, ls=":")
        ax.text(pd.Timestamp(x), d.money_at_risk.max() * 1.08, lab, color=INK2, fontsize=8.5, va="bottom", ha=ha)
    pk = d.loc[d.money_at_risk.idxmax()]
    ax.annotate(f"Peak ${pk.money_at_risk / 1000:.1f}k on {pk.date:%b %d}", (pk.date, pk.money_at_risk),
                xytext=(30, -18), textcoords="offset points", fontsize=9, color=INK,
                arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8))
    ax.yaxis.set_major_formatter(lambda v, _: f"${v / 1000:.0f}k")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.set_ylim(0, d.money_at_risk.max() * 1.25)
    ax.yaxis.set_major_locator(matplotlib.ticker.MultipleLocator(5000))
    ax.set_title("Money at risk: expected loss riding on open delivery promises", pad=22)
    subtitle(ax, "Sum of PD x LGD x order value for every promise that is open and not yet due, by day")
    save(fig, "1_money_at_risk.png")


def pchart():
    d = pd.read_csv(O / "pchart_daily_late.csv", parse_dates=["promised_date"])
    fig, ax = plt.subplots(figsize=(10, 4.4))
    ax.plot(d.promised_date, d.p, color=S1, label="Daily late rate")
    ax.plot(d.promised_date, d.ucl, color=INK2, lw=1, ls="--", label="Upper control limit (3σ)")
    ax.axhline(d.p_bar.iloc[0], color=INK2, lw=1, label=f"Pre-peak baseline {d.p_bar.iloc[0]:.1%}")
    o = d[d.out_of_control]
    ax.scatter(o.promised_date, o.p, s=34, color=CRIT, zorder=3, edgecolor=SURF, linewidth=1.5,
               label=f"Out of control ({len(o)} days)")
    ax.yaxis.set_major_locator(matplotlib.ticker.MultipleLocator(0.05))
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.set_ylim(0, None)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.legend(loc="upper right", fontsize=8.5)
    ax.set_title("Late deliveries: real signal, not noise, from Nov 29 to Dec 18", pad=22)
    subtitle(ax, "p-chart by promised delivery date; limits from Nov 4-24 promises")
    save(fig, "2_p_chart_late_rate.png")


def heatmap():
    h = pd.read_csv(O / "hotspots_dc_category.csv")
    piv = h.pivot(index="dc", columns="category", values="late_rate")
    res = h.pivot(index="dc", columns="category", values="std_residual")
    fig, ax = plt.subplots(figsize=(10, 3.4))
    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list("seq", SEQ)
    ax.imshow(piv.values, cmap=cmap, vmin=0, vmax=0.28, aspect="auto")
    ax.grid(False)
    for i in range(piv.shape[0]):
        for j in range(piv.shape[1]):
            v = piv.values[i, j]
            ax.text(j, i, f"{v:.1%}\nresid {res.values[i, j]:+.1f}", ha="center", va="center", fontsize=9,
                    color="white" if v > 0.15 else INK)
    i, j = list(piv.index).index("TX"), list(piv.columns).index("Toys")
    ax.add_patch(plt.Rectangle((j - .48, i - .48), .96, .96, fill=False, ec=CRIT, lw=2))
    ax.set_xticks(range(piv.shape[1]), piv.columns)
    ax.set_yticks(range(piv.shape[0]), [f"{x} DC" for x in piv.index])
    for s in ax.spines.values():
        s.set_visible(False)
    t = pd.read_csv(O / "hotspot_test.csv").iloc[0]
    ax.set_title("Where December promises break: TX DC x Toys", pad=22)
    subtitle(ax, f"Late rate (promises due Dec 1-24). Chi-square p = {t.p_value:.0e}; "
                 "outlined cell: standardized residual > 2")
    save(fig, "3_hotspot_dc_category.png")


def lead():
    d = pd.read_csv(O / "misses_by_decision_lead.csv").sort_values("days_before_promise", ascending=True)
    fig, ax = plt.subplots(figsize=(10, 3.6))
    y = [f"{k} day{'s' if k > 1 else ''} before" for k in d.days_before_promise]
    left = np.zeros(len(d))
    for col, colr, lab in [("waiting_for_stock", S1, "Waiting for stock (reroute can help)"),
                           ("in_dc_not_shipped", S3, "In the DC, not shipped (expedite can help)"),
                           ("already_shipped", S2, "Already on a truck (only a heads-up helps)")]:
        ax.barh(y, d[col], left=left, color=colr, label=lab, height=0.6, edgecolor=SURF, linewidth=2)
        for yi, l, v in zip(y, left, d[col]):
            if v > 0.06:
                ax.text(l + v / 2, yi, f"{v:.0%}", ha="center", va="center", fontsize=9,
                        color="white" if colr != S3 else INK)
        left += d[col].values
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.set_xlim(0, 1)
    ax.grid(axis="y", visible=False)
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=3, fontsize=8.5)
    ax.set_title("Look earlier: where the Christmas-window misses stood at decision time", pad=22)
    subtitle(ax, "Share of the 770 promises that were eventually missed (due Dec 7-24)")
    save(fig, "4_misses_by_decision_lead.png")


def frontier():
    f = pd.read_csv(O / "policy_frontier.csv")
    p = pd.read_csv(O / "policy_comparison.csv")
    fig, ax = plt.subplots(figsize=(10, 5.2))
    for fam, colr, lab in [("Model threshold", S1, "Act on orders with PD above a threshold"),
                           ("Expected-loss rule (value of a kept promise x)", S2,
                            "Expected-loss rule, valuing a kept promise at 1x-30x")]:
        g = f[f.family == fam].sort_values("on_time_rate")
        ax.plot(g.on_time_rate, g.total_cost, color=colr, label=lab, marker="o", ms=4)
    base = p.total_cost.iloc[0]
    ax.axhline(base, color=INK2, lw=0.8, ls=":")
    ax.text(0.9235, base * 1.02, "cost of doing nothing", color=INK2, fontsize=8.5)
    offs = {"A": (8, -14), "B": (-8, 10), "C": (-10, 10), "D": (8, -14), "E": (8, -16)}
    for _, r in p.iterrows():
        k = r.policy[0]
        ax.scatter(r.on_time_rate, r.total_cost, s=70, color=INK, zorder=4, edgecolor=SURF, linewidth=2)
        ax.annotate(k, (r.on_time_rate, r.total_cost), xytext=offs[k], textcoords="offset points",
                    fontsize=10, fontweight="bold", ha="right" if offs[k][0] < 0 else "left")
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.1%}")
    ax.yaxis.set_major_formatter(lambda v, _: f"${v / 1000:.0f}k")
    ax.set_xlabel("Promises kept on time (Dec 7-24)")
    ax.set_ylabel("Total cost = action spend + loss from missed promises")
    ax.legend(loc="upper left", fontsize=8.5)
    ax.set_title("The trade-off: every point is a policy; lower-right is better", pad=22)
    subtitle(ax, "A nothing · B fix all unshipped · C model top-k · D lowest cost · E best service at no extra cost")
    save(fig, "5_cost_vs_service_frontier.png")


def claims():
    c = pd.read_csv(O / "claims_by_category.csv").sort_values("physical_claim_rate")
    fig, ax = plt.subplots(figsize=(10, 3.8))
    y = np.arange(len(c))
    ax.hlines(y, c.physical_claim_ci_low, c.physical_claim_ci_high, color=S1, lw=2)
    ax.scatter(c.physical_claim_rate, y, s=60, color=S1, zorder=3, edgecolor=SURF, linewidth=2)
    for yi, r in zip(y, c.itertuples()):
        ax.text(r.physical_claim_ci_high + 0.0006, yi, f"{r.physical_claim_rate:.2%}  {r.physical_claim_rating}",
                va="center", fontsize=9, color=INK2)
    ax.axvline(C.TOLERANCE["claim_rate"], color=CRIT, lw=1, ls="--")
    ax.text(C.TOLERANCE["claim_rate"], -0.45, " 1% tolerance", color=CRIT, fontsize=8.5, va="bottom")
    ax.set_yticks(y, c.category)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.1%}")
    ax.set_xlim(0, 0.026)
    ax.grid(axis="y", visible=False)
    ax.set_title("Damage, shortage and loss claims by category", pad=22)
    subtitle(ax, "Claims per shipment with Wilson 95% interval; RED = whole interval above tolerance")
    save(fig, "6_claims_by_category.png")


def model_vs_rule():
    m = pd.read_csv(O / "model_vs_rule.csv")
    fig, ax = plt.subplots(figsize=(10, 3.6))
    metrics = ["recall", "precision"]
    labels = ["Recall: share of misses caught", "Precision: share of alerts that were real"]
    w = 0.36
    for k, (colr, row) in enumerate(zip([S2, S1], m.itertuples())):
        vals = [getattr(row, x) for x in metrics]
        cis = [tuple(map(float, getattr(row, x + "_ci").split("-"))) for x in metrics]
        ypos = np.arange(2) + (k - 0.5) * w
        ax.barh(ypos, vals, height=w, color=colr, label=row.method, edgecolor=SURF, linewidth=2)
        ax.errorbar(vals, ypos, xerr=[[v - c[0] for v, c in zip(vals, cis)], [c[1] - v for v, c in zip(vals, cis)]],
                    fmt="none", ecolor=INK, elinewidth=1, capsize=3)
        for v, yy, c in zip(vals, ypos, cis):
            ax.text(c[1] + 0.01, yy, f"{v:.0%}", va="center", fontsize=9)
    ax.set_yticks(range(2), labels)
    ax.invert_yaxis()
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.set_xlim(0, 1)
    ax.grid(axis="y", visible=False)
    ax.legend(loc="lower right", fontsize=8.5)
    ax.set_title("Same number of alerts, more misses caught", pad=22)
    subtitle(ax, f"Christmas-window test set (n = 9,955 promises); bars = bootstrap 95% CI; {m.alerts.iloc[0]:,} alerts each")
    save(fig, "7_model_vs_rule.png")


def main():
    C.CHARTS.mkdir(exist_ok=True)
    for fn in (money_at_risk, pchart, heatmap, lead, frontier, claims, model_vs_rule):
        fn()
    print("charts written:", sorted(p.name for p in C.CHARTS.glob("*.png")))


if __name__ == "__main__":
    main()
