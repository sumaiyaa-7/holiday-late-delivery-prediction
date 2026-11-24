"""
Run every query in sql/ against an in-memory SQLite database built from the
cleaned data, then add the statistics: Wilson ratings, a p-chart and a
chi-square hotspot test.

Writes outputs/*.csv  (scorecard, weekly tracker, hotspots, p-chart, claims...)
"""
import sqlite3

import numpy as np
import pandas as pd

import config as C
from stats_utils import chi_square_hotspots, p_chart_limits, rate_vs_tolerance, wilson


def load_db():
    con = sqlite3.connect(":memory:")
    f = pd.read_csv(C.CLEAN / "order_facts.csv")
    for b in ("delivery_known", "in_full", "tender_rejected", "shipped_imputed", "claimed"):
        f[b] = f[b].astype(int)
    f.to_sql("order_facts", con, index=False)
    pd.read_csv(C.CLEAN / "claims.csv").to_sql("claims", con, index=False)
    return con, f


def q(con, name):
    return pd.read_sql_query((C.SQL / name).read_text(), con)


def add_rating(df, k, n, tol, label):
    ci = [wilson(a, b) for a, b in zip(df[k], df[n])]
    df[f"{label}_rate"] = (df[k] / df[n]).round(4)
    df[f"{label}_ci_low"] = [round(c[0], 4) for c in ci]
    df[f"{label}_ci_high"] = [round(c[1], 4) for c in ci]
    df[f"{label}_rating"] = [rate_vs_tolerance(a, b, tol) for a, b in zip(df[k], df[n])]
    return df


def main():
    con, f = load_db()
    T = C.TOLERANCE

    # ---------------------------------------------------------------- scorecard by period
    p = q(con, "01_service_by_period.sql")
    tot = p.drop(columns=["period", "freight_per_unit"]).sum()
    tot["period"] = "Season total"
    tot["freight_per_unit"] = round(f.freight_cost.sum() / f.qty_shipped.sum(), 2)
    p = pd.concat([p, tot.to_frame().T], ignore_index=True)
    for c in p.columns.drop("period"):
        p[c] = pd.to_numeric(p[c])
    p["orders_n"] = p.orders
    p = add_rating(p, "late_orders", "delivery_known", T["late_delivery"], "late")
    p = add_rating(p, "not_otif", "delivery_known", T["not_otif"], "not_otif")
    p = add_rating(p, "not_in_full", "orders_n", T["not_in_full"], "not_in_full")
    # median order-to-ship hours (SQLite has no median)
    med = f.groupby("period").order_to_ship_hrs.median()
    med["Season total"] = f.order_to_ship_hrs.median()
    p["median_order_to_ship_hrs"] = p.period.map(med).round(1)
    # sensitivity: unknown deliveries all on time vs all late
    unk = f.groupby("period").delivery_known.apply(lambda s: (s == 0).sum())
    unk["Season total"] = (f.delivery_known == 0).sum()
    p["unknown_deliveries"] = p.period.map(unk)
    p["otif_best_case"] = (1 - p.not_otif / (p.delivery_known + p.unknown_deliveries)).round(4)
    p["otif_worst_case"] = (1 - (p.not_otif + p.unknown_deliveries)
                            / (p.delivery_known + p.unknown_deliveries)).round(4)
    p.drop(columns="orders_n").to_csv(C.OUT / "scorecard_by_period.csv", index=False)

    # ---------------------------------------------------------------- weekly tracker
    w = q(con, "02_weekly_tracker.sql")
    w = add_rating(w, "late_orders", "delivered", T["late_delivery"], "late")
    w = add_rating(w, "not_otif", "delivered", T["not_otif"], "not_otif")
    w = add_rating(w, "tender_rejections", "shipped", T["tender_rejection"], "tender_reject")
    w.to_csv(C.OUT / "weekly_tracker.csv", index=False)

    # ---------------------------------------------------------------- carriers
    c = q(con, "03_carrier_tender.sql")
    c = add_rating(c, "rejected", "loads_tendered", T["tender_rejection"], "reject")
    c.to_csv(C.OUT / "carrier_tender_rejection.csv", index=False)

    # ---------------------------------------------------------------- claims
    cl = q(con, "04_claims_by_category.sql")
    # rate the physical claims (damaged, short, lost) against tolerance;
    # late-delivery goodwill credits are a service cost, reported separately
    cl["physical_claims"] = cl.damaged + cl.shortage + cl.lost
    cl = add_rating(cl, "physical_claims", "shipments", T["claim_rate"], "physical_claim")
    cl["goodwill_rate"] = (cl.late_goodwill / cl.shipments).round(4)
    cl.to_csv(C.OUT / "claims_by_category.csv", index=False)

    # ---------------------------------------------------------------- hotspot test
    h = q(con, "05_hotspot_dc_category.sql")
    tab = np.c_[h.late_orders, h.delivered - h.late_orders]
    chi2, pval, dof, resid, exp = chi_square_hotspots(tab)
    h["late_rate"] = (h.late_orders / h.delivered).round(4)
    h["std_residual"] = resid.round(2)
    h["hotspot"] = (pval < 0.05) & (h.std_residual > 2)
    h = add_rating(h, "late_orders", "delivered", T["late_delivery"], "late")
    h.to_csv(C.OUT / "hotspots_dc_category.csv", index=False)
    pd.DataFrame([dict(test="chi-square, Dec promises, DC x category late rate",
                       chi2=round(chi2, 1), dof=dof, p_value=pval)]).to_csv(
        C.OUT / "hotspot_test.csv", index=False)
    q(con, "07_late_by_sourcing.sql").to_csv(C.OUT / "toys_by_sourcing.csv", index=False)

    # ---------------------------------------------------------------- p-chart
    d = q(con, "06_daily_late_rate.sql")
    d = d[d.delivered >= 50].copy()
    base = d[(d.promised_date >= "2026-11-04") & (d.promised_date <= "2026-11-24")]
    p_bar = base.late_orders.sum() / base.delivered.sum()
    d["p"] = d.late_orders / d.delivered
    d["p_bar"] = p_bar
    d["lcl"], d["ucl"] = p_chart_limits(p_bar, d.delivered)
    d["out_of_control"] = d.p > d.ucl
    d.to_csv(C.OUT / "pchart_daily_late.csv", index=False)

    print(p[["period", "orders", "late_rate", "late_rating", "not_otif_rate", "not_otif_rating",
             "not_in_full_rate", "not_in_full_rating", "median_order_to_ship_hrs"]].to_string(index=False))
    print(c.to_string(index=False))
    print(cl[["category", "shipments", "physical_claims", "physical_claim_rate", "physical_claim_rating",
              "late_goodwill", "claim_value", "avg_days_to_resolve"]].to_string(index=False))
    print(h[["dc", "category", "delivered", "late_rate", "std_residual", "hotspot"]].to_string(index=False))
    print(f"chi2={chi2:.1f} dof={dof} p={pval:.2e}; baseline p_bar={p_bar:.4f}; "
          f"days out of control={d.out_of_control.sum()} -> {list(d.promised_date[d.out_of_control])}")
    print(q(con, "07_late_by_sourcing.sql"))


if __name__ == "__main__":
    main()
