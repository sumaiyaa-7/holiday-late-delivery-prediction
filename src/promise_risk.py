"""
Holiday late-delivery prediction & triage: score every delivery promise the way
a bank scores a loan.

  Expected loss (EL) = PD  x  LGD  x  EAD
  PD  = probability the promise is missed, from a logistic regression that
        only uses what is known 2 days before the promise is due
  EAD = order value ("exposure": what is riding on the promise)
  LGD = share of that value lost if the promise is missed (goodwill credit,
        cancellation, lost repeat business) + the cost of the WISMO contact

Then: compare a common rule ("expedite anything not shipped at D-2") with
a model-ranked list and with an expected-loss policy that picks the cheapest
action that is worth it for each order.

Train on promises due Nov 2 - Dec 6, test on the Christmas window Dec 7 - 24.
Outcomes of each policy are simulated against the truth file, using the same
random draws for every policy so the comparison is fair.
"""
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, roc_auc_score
from sklearn.model_selection import cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

import config as C
from stats_utils import bootstrap_ci

CAT = ["dc", "category", "sourcing", "ship_speed", "stage", "carrier_known"]
NUM = ["days_to_promise", "planned_transit", "days_open", "days_since_ship",
       "dc_backlog_ratio", "tender_rejected_known", "not_alloc_x_asia"]


def snapshot_features(f):
    """Everything the ops team could see at the decision time (D-2, midnight)."""
    ts = {c: pd.to_datetime(f[c]) for c in ("order_ts", "allocated_ts", "packed_ts", "shipped_ts")}
    promise = pd.to_datetime(f.promised_date)
    snap = (promise - pd.Timedelta(days=C.DECISION_LEAD_DAYS)).where(
        lambda s: s > ts["order_ts"], ts["order_ts"])
    x = pd.DataFrame(index=f.index)
    for c in ("dc", "category", "sourcing", "ship_speed"):
        x[c] = f[c]
    alloc = ts["allocated_ts"] <= snap
    packed = ts["packed_ts"] <= snap
    shipped = ts["shipped_ts"] <= snap
    x["stage"] = np.select([shipped, packed, alloc], ["shipped", "packed", "allocated"], "not allocated")
    x["carrier_known"] = np.where(packed, f.carrier, "not yet")
    x["days_to_promise"] = (promise + pd.Timedelta(days=1) - snap).dt.total_seconds() / 86400
    x["planned_transit"] = [1 if s == "Express" else C.TRANSIT_PLAN[(d, r)]
                            for s, d, r in zip(f.ship_speed, f.dc, f.customer_region)]
    x["days_open"] = (snap - ts["order_ts"]).dt.total_seconds() / 86400
    x["days_since_ship"] = np.where(shipped, (snap - ts["shipped_ts"]).dt.total_seconds() / 86400, 0)
    x["tender_rejected_known"] = (f.tender_rejected.astype(bool) & packed).astype(int)
    x["not_alloc_x_asia"] = ((~alloc) & (f.sourcing == "Asia")).astype(int)
    # DC backlog at snapshot: allocated but not yet packed, as multiple of a day's capacity
    x["dc_backlog_ratio"] = 0.0
    for dc, cap in C.DC_CAPACITY.items():
        m = (f.dc == dc).values
        a = np.sort(ts["allocated_ts"][m].dropna().values)
        p = np.sort(ts["packed_ts"][m].dropna().values)
        s = snap[m].values
        x.loc[m, "dc_backlog_ratio"] = (np.searchsorted(a, s) - np.searchsorted(p, s)) / cap
    x["snapshot_ts"] = snap
    x["actionable"] = ~shipped          # can still be expedited
    x["allocated_at_snap"] = alloc
    return x


def model():
    pre = ColumnTransformer([("cat", OneHotEncoder(handle_unknown="ignore"), CAT),
                             ("num", StandardScaler(), NUM)])
    return Pipeline([("pre", pre), ("lr", LogisticRegression(C=1.0, max_iter=3000))])


def main():
    f = pd.read_csv(C.CLEAN / "order_facts.csv")
    truth = pd.read_csv(C.TRUTH / "order_truth.csv")[["order_id", "true_late", "root_cause"]]
    f = f.merge(truth, on="order_id")
    x = snapshot_features(f)
    pdate = pd.to_datetime(f.promised_date)
    train = (pdate <= pd.Timestamp(C.TRAIN_PROMISE_END)) & f.delivery_known
    window = (pdate > pd.Timestamp(C.TRAIN_PROMISE_END)) & (pdate <= pd.Timestamp(C.TEST_PROMISE_END))
    test = window & f.delivery_known
    y = f.late.astype(float)

    m = model().fit(x[train], y[train])
    pdv = np.full(len(f), np.nan)
    pdv[train.values] = cross_val_predict(model(), x[train], y[train], cv=5, method="predict_proba")[:, 1]
    pdv[~train.values] = m.predict_proba(x[~train])[:, 1]
    f["pd"] = pdv

    # ---------------------------------------------------------------- model vs rule (test window)
    yt, pt = y[test].values, f.pd[test].values
    rule = (~x.loc[test, "stage"].eq("shipped")).values          # "not shipped at D-2"
    k = int(rule.sum())
    top = np.zeros_like(rule)
    top[np.argsort(-pt)[:k]] = True

    def pr(flag, yy):
        tp = (flag & (yy == 1)).sum()
        return tp / max(flag.sum(), 1), tp / max((yy == 1).sum(), 1)

    rp, rr = pr(rule, yt)
    mp, mr = pr(top, yt)
    n = len(yt)
    ci_mr = bootstrap_ci(lambda i: pr(top[i], yt[i])[1], n, seed=1)
    ci_rr = bootstrap_ci(lambda i: pr(rule[i], yt[i])[1], n, seed=1)
    ci_mp = bootstrap_ci(lambda i: pr(top[i], yt[i])[0], n, seed=1)
    ci_rp = bootstrap_ci(lambda i: pr(rule[i], yt[i])[0], n, seed=1)
    ci_d = bootstrap_ci(lambda i: pr(top[i], yt[i])[1] - pr(rule[i], yt[i])[1], n, seed=1)
    auc, ap, brier = roc_auc_score(yt, pt), average_precision_score(yt, pt), brier_score_loss(yt, pt)
    auc_ci = bootstrap_ci(lambda i: roc_auc_score(yt[i], pt[i]), n, B=1000, seed=2)
    metrics = pd.DataFrame([
        dict(method="Rule: not shipped at D-2", alerts=k, precision=rp, precision_ci=f"{ci_rp[0]:.3f}-{ci_rp[1]:.3f}",
             recall=rr, recall_ci=f"{ci_rr[0]:.3f}-{ci_rr[1]:.3f}"),
        dict(method="Model: top-k by PD (same k)", alerts=k, precision=mp, precision_ci=f"{ci_mp[0]:.3f}-{ci_mp[1]:.3f}",
             recall=mr, recall_ci=f"{ci_mr[0]:.3f}-{ci_mr[1]:.3f}"),
    ]).round(3)
    metrics.to_csv(C.OUT / "model_vs_rule.csv", index=False)
    summary = dict(test_orders=n, test_late=int(yt.sum()), test_late_rate=yt.mean(),
                   auc=auc, auc_ci=f"{auc_ci[0]:.3f}-{auc_ci[1]:.3f}", pr_auc=ap,
                   pr_auc_baseline=yt.mean(), brier=brier,
                   recall_gain_vs_rule=mr - rr, recall_gain_ci=f"{ci_d[0]:.3f}-{ci_d[1]:.3f}")
    pd.DataFrame([summary]).round(4).to_csv(C.OUT / "model_summary.csv", index=False)

    # calibration (deciles) and drivers
    cal = pd.DataFrame({"pd": pt, "y": yt})
    cal["bin"] = pd.qcut(cal.pd.rank(method="first"), 10, labels=False)
    cal.groupby("bin").agg(mean_pd=("pd", "mean"), actual_late=("y", "mean"), n=("y", "size")).round(4) \
        .to_csv(C.OUT / "calibration.csv")
    names = m.named_steps["pre"].get_feature_names_out()
    coef = pd.DataFrame({"feature": [s.split("__", 1)[1] for s in names],
                         "coef": m.named_steps["lr"].coef_[0]})
    coef["odds_ratio"] = np.exp(coef.coef)
    coef.sort_values("coef", ascending=False).round(3).to_csv(C.OUT / "model_drivers.csv", index=False)

    # ---------------------------------------------------------------- expected loss and policies
    gift = pdate >= pd.Timestamp(C.GIFT_CRITICAL_FROM)
    f["lgd"] = np.where(gift, C.LGD_GIFT_CRITICAL, C.LGD_REGULAR)
    churn = np.where(gift, C.CHURN_PROB_GIFT, C.CHURN_PROB_REGULAR)
    f["loss_if_missed"] = f.lgd * f.order_value + C.WISMO_CONTACT_COST + churn * C.FUTURE_MARGIN_PER_CUSTOMER
    f["expected_loss"] = f.pd * f.loss_if_missed
    f["stage"] = x.stage
    f["fix_action"] = np.select([x.stage.eq("shipped"), ~x.allocated_at_snap], ["NONE", "REROUTE"], "EXPEDITE")
    f["fix_cost"] = f.category.map(C.EXPEDITE_COST) + np.where(f.fix_action == "REROUTE", C.REROUTE_EXTRA_COST, 0)
    f["fix_save"] = np.select([f.fix_action == "EXPEDITE", f.fix_action == "REROUTE"],
                              [C.EXPEDITE_SAVE, C.REROUTE_SAVE], 0.0)
    f["benefit_fix"] = np.where(f.fix_action != "NONE", f.pd * f.fix_save * f.loss_if_missed - f.fix_cost, -np.inf)
    f["benefit_notice"] = f.pd * C.NOTICE_LOSS_REDUCTION * f.loss_if_missed - C.NOTICE_COST
    best = np.where(f.benefit_fix >= f.benefit_notice, f.fix_action, "NOTICE")
    f["el_action"] = np.where(np.maximum(f.benefit_fix, f.benefit_notice) > 0, best, "NONE")

    w = f[window].copy()                     # all promises in the Christmas window (truth known)
    xw = x[window]
    u = np.random.default_rng(C.SEED).random(len(w))        # common random numbers
    late = w.true_late.values.astype(bool)
    loss = w.loss_if_missed.values
    rank_top = np.zeros(len(w), bool)
    kk = int((~xw.stage.eq("shipped")).sum())
    fix = w.fix_action.values
    rank_top[np.argsort(-w.pd.values)[:kk]] = True
    policies = {
        "A. Do nothing": np.full(len(w), "NONE"),
        "B. Rule: fix everything not shipped at D-2": fix,
        "C. Model top-k: fix if possible, else notify": np.where(
            rank_top, np.where(fix != "NONE", fix, "NOTICE"), "NONE"),
        "D. Expected-loss rule: lowest total cost": w.el_action.values,
    }
    def simulate(act):
        fx = (act == "EXPEDITE") | (act == "REROUTE")
        notc = act == "NOTICE"
        spend = np.where(fx, w.fix_cost.values, 0) + np.where(notc, C.NOTICE_COST, 0)
        saved = fx & late & (u < w.fix_save.values)
        still_late = late & ~saved
        realized = np.where(still_late, loss * np.where(notc, 1 - C.NOTICE_LOSS_REDUCTION, 1), 0)
        acted = fx | notc
        row = dict(expedites=int((act == "EXPEDITE").sum()), reroutes=int((act == "REROUTE").sum()),
                   notices=int(notc.sum()), action_spend=spend.sum(), late_promises=int(still_late.sum()),
                   on_time_rate=1 - still_late.mean(), loss_from_missed_promises=realized.sum(),
                   total_cost=spend.sum() + realized.sum(),
                   wasted_actions_pct=(acted & ~late).sum() / max(acted.sum(), 1))
        return row, spend + realized

    def el_actions(mult):
        """Expected-loss policy where a kept promise is valued at `mult` x the modelled loss."""
        bf = np.where(fix != "NONE", w.pd * w.fix_save * w.loss_if_missed * mult - w.fix_cost, -np.inf)
        bn = w.pd * C.NOTICE_LOSS_REDUCTION * w.loss_if_missed * mult - C.NOTICE_COST
        choice = np.where(bf >= bn, fix, "NOTICE")
        return np.where(np.maximum(bf, bn) > 0, choice, "NONE")

    # frontier: total cost vs on-time rate, for the model threshold family and the EL family
    front = []
    for tau in np.r_[np.linspace(0.95, 0.05, 19), 0.03, 0.02, 0.01]:
        act = np.where(w.pd.values >= tau, np.where(fix != "NONE", fix, "NOTICE"), "NONE")
        r, _ = simulate(act)
        front.append(dict(family="Model threshold", setting=round(tau, 3), **r))
    for mult in np.r_[1, 1.5, 2, 3, 4, 5, 6, 8, 10, 13, 16, 20, 25, 30]:
        r, _ = simulate(el_actions(mult))
        front.append(dict(family="Expected-loss rule (value of a kept promise x)", setting=mult, **r))
    front = pd.DataFrame(front)

    rows, per_order = [], {}
    for name, act in policies.items():
        r, c = simulate(act)
        rows.append(dict(policy=name, setting="", **r))
        per_order[name] = c
    # E: the highest on-time rate available without spending more in total than doing nothing
    free = front[front.total_cost <= rows[0]["total_cost"]].sort_values(["on_time_rate", "total_cost"],
                                                                         ascending=[False, True]).iloc[0]
    if free.family == "Model threshold":
        act = np.where(w.pd.values >= free.setting, np.where(fix != "NONE", fix, "NOTICE"), "NONE")
        label = f"PD >= {free.setting:g}"
    else:
        act = el_actions(free.setting)
        label = f"x{free.setting:g}"
    r, c = simulate(act)
    rows.append(dict(policy="E. Best on-time rate at no extra total cost", setting=label, **r))
    per_order["E"] = c
    front.round(4).to_csv(C.OUT / "policy_frontier.csv", index=False)

    pol = pd.DataFrame(rows)
    base = pol.iloc[0]
    pol["net_benefit_vs_nothing"] = base.total_cost - pol.total_cost
    pol["promises_rescued"] = base.late_promises - pol.late_promises
    pol["cost_per_promise_rescued"] = np.where(pol.promises_rescued > 0,
                                               pol.action_spend / pol.promises_rescued.clip(lower=1), np.nan)
    names_ = list(policies)
    bcost = per_order[names_[1]]
    ci_d = bootstrap_ci(lambda i: bcost[i].sum() - per_order[names_[3]][i].sum(), len(w), seed=3)
    ci_e = bootstrap_ci(lambda i: bcost[i].sum() - per_order["E"][i].sum(), len(w), seed=3)
    pol["saving_vs_rule"] = pol.total_cost.iloc[1] - pol.total_cost
    pol["saving_vs_rule_95ci"] = ["", "", "", f"${ci_d[0]:,.0f} to ${ci_d[1]:,.0f}",
                                  f"${ci_e[0]:,.0f} to ${ci_e[1]:,.0f}"]
    pol.round(4).to_csv(C.OUT / "policy_comparison.csv", index=False)

    # ---------------------------------------------------------------- money at risk on open promises (daily)
    od = pd.to_datetime(f.order_ts).dt.normalize()
    dd = pd.to_datetime(f.delivered_ts).dt.normalize().fillna(pd.Timestamp("2027-01-31"))
    days = pd.date_range("2026-11-02", "2026-12-31")
    debt = [f.expected_loss[(od <= t) & (dd > t) & (pdate >= t)].sum() for t in days]
    exposure = [f.order_value[(od <= t) & (dd > t) & (pdate >= t)].sum() for t in days]
    realized = f.loss_if_missed.where(f.true_late, 0).groupby(pdate).sum().reindex(days, fill_value=0)
    expected_due = f.expected_loss.groupby(pdate).sum().reindex(days, fill_value=0)
    pd.DataFrame({"date": days.date, "money_at_risk": np.round(debt, 0), "open_exposure": np.round(exposure, 0),
                  "expected_loss_due": expected_due.round(0).values,
                  "realized_loss_due": realized.round(0).values}).to_csv(C.OUT / "money_at_risk_daily.csv", index=False)

    # ---------------------------------------------------------------- how early do you need to look?
    late_w = f[window & f.true_late]
    lead_rows = []
    keep = C.DECISION_LEAD_DAYS
    for lead in (1, 2, 3, 4):
        C.DECISION_LEAD_DAYS = lead
        st = snapshot_features(late_w).stage.value_counts(normalize=True)
        lead_rows.append(dict(days_before_promise=lead, already_shipped=st.get("shipped", 0),
                              waiting_for_stock=st.get("not allocated", 0),
                              in_dc_not_shipped=st.get("allocated", 0) + st.get("packed", 0)))
    C.DECISION_LEAD_DAYS = keep
    pd.DataFrame(lead_rows).round(3).to_csv(C.OUT / "misses_by_decision_lead.csv", index=False)
    print(pd.DataFrame(lead_rows).round(3).to_string(index=False))

    # ---------------------------------------------------------------- example morning queue for the tracker
    day = pd.Timestamp("2026-12-18")          # promises due Dec 20 (gift-critical)
    q = f[(pdate == day + pd.Timedelta(days=C.DECISION_LEAD_DAYS))].copy()
    q["stage_at_decision"] = x.loc[q.index, "stage"]
    q = q[q.el_action != "NONE"].sort_values("expected_loss", ascending=False)
    q[["order_id", "dc", "category", "carrier", "ship_speed", "promised_date", "order_value", "stage_at_decision",
       "pd", "loss_if_missed", "expected_loss", "el_action", "fix_cost"]].round(3) \
        .to_csv(C.OUT / "action_queue_2026-12-18.csv", index=False)
    f[["order_id", "pd", "expected_loss", "el_action"]].to_csv(C.CLEAN / "order_scores.csv", index=False)

    print(metrics.to_string(index=False))
    print(pd.Series(summary).to_string())
    with pd.option_context("display.width", 250, "display.max_columns", 30):
        print(pol.round(3).to_string(index=False))
    print(coef.sort_values("coef", ascending=False).round(2).to_string(index=False))
    print("queue size Dec 18:", len(q), q.el_action.value_counts().to_dict())


if __name__ == "__main__":
    main()
