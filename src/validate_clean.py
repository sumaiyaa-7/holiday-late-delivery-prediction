"""
Validate and clean the raw exports, log every rule that fired, and check the
rules against the answer key of planted defects.

Writes:
  data/clean/order_facts.csv   one row per order with derived dates and flags
  data/clean/claims.csv        valid claims;  data/clean/claims_quarantine.csv
  outputs/dq_log.csv           each check: rows checked, flagged, action
  outputs/detection_check_vs_answer_key.csv
"""
import numpy as np
import pandas as pd

import config as C

EVENT_ORDER = ["ORDER_PLACED", "ALLOCATED", "PICKED", "PACKED", "SHIPPED", "DELIVERED"]


def main():
    C.CLEAN.mkdir(parents=True, exist_ok=True)
    C.OUT.mkdir(parents=True, exist_ok=True)
    orders = pd.read_csv(C.RAW / "orders.csv", parse_dates=["order_ts"])
    ship = pd.read_csv(C.RAW / "shipments.csv")
    ev = pd.read_csv(C.RAW / "shipment_events.csv", parse_dates=["event_ts"])
    claims = pd.read_csv(C.RAW / "claims.csv", parse_dates=["filed_date", "resolved_date"])
    log, flags = [], []          # flags: (rule, record_id)

    def record(check, table, checked, ids, action):
        ids = list(ids)
        log.append(dict(check=check, table=table, rows_checked=checked,
                        rows_flagged=len(ids), pct_flagged=round(len(ids) / checked, 4),
                        action=action))
        flags.extend((check, i) for i in ids)

    # 1. duplicate order rows -------------------------------------------------
    d = orders[orders.duplicated("order_id", keep="first")]
    record("DUPLICATE_ORDER_ROW", "orders", len(orders), d.order_id.unique(),
           "dropped repeat rows, kept first")
    orders = orders.drop_duplicates("order_id", keep="first")

    # 2. duplicate events (same shipment + event type) -------------------------
    ev = ev.sort_values("event_ts")
    d = ev[ev.duplicated(["shipment_id", "event_type"], keep="first")]
    record("DUPLICATE_EVENT", "shipment_events", len(ev), d.shipment_id.unique(),
           "kept earliest scan of each type")
    ev = ev.drop_duplicates(["shipment_id", "event_type"], keep="first")
    w = ev.pivot(index="shipment_id", columns="event_type", values="event_ts").reindex(columns=EVENT_ORDER)

    # 3. PACKED before PICKED -> swap (scanner clock / scan order issue) ---------
    m = w.PACKED < w.PICKED
    record("PACKED_BEFORE_PICKED", "shipment_events", int(w.PACKED.notna().sum()), w.index[m],
           "swapped the two timestamps")
    w.loc[m, ["PICKED", "PACKED"]] = w.loc[m, ["PACKED", "PICKED"]].values

    # 4. DELIVERED before SHIPPED -> delivery time not trustworthy -------------
    m = w.DELIVERED.notna() & w.SHIPPED.notna() & (w.DELIVERED < w.SHIPPED)
    record("DELIVERED_BEFORE_SHIPPED", "shipment_events", int(w.DELIVERED.notna().sum()), w.index[m],
           "delivery time set to unknown")
    w.loc[m, "DELIVERED"] = pd.NaT

    # 5. missing SHIPPED scan but PACKED exists -> impute ----------------------
    w["shipped_imputed"] = False
    m = w.SHIPPED.isna() & w.PACKED.notna()
    gap = (w.SHIPPED - w.PACKED).median()
    record("MISSING_SHIPPED_SCAN", "shipment_events", len(w), w.index[m],
           f"imputed = PACKED + median gap ({gap})")
    w.loc[m, "SHIPPED"] = w.loc[m, "PACKED"] + gap
    w.loc[m, "shipped_imputed"] = True

    # 6. shipped but no delivery scan by extract date --------------------------
    m = w.SHIPPED.notna() & w.DELIVERED.isna() & ~w.index.isin([f for r, f in flags
                                                                 if r == "DELIVERED_BEFORE_SHIPPED"])
    record("MISSING_DELIVERED_SCAN", "shipment_events", int(w.SHIPPED.notna().sum()), w.index[m],
           "delivery unknown: excluded from on-time KPIs, bounded in sensitivity check")

    # 7. shipments: qty shipped > qty ordered; negative freight ----------------
    s = ship.merge(orders[["order_id", "qty"]], on="order_id")
    m = s.qty_shipped > s.qty
    record("QTY_SHIPPED_TOO_HIGH", "shipments", len(s), s.shipment_id[m], "capped at qty ordered")
    s.loc[m, "qty_shipped"] = s.loc[m, "qty"]
    m = s.freight_cost <= 0
    record("NEGATIVE_FREIGHT", "shipments", len(s), s.shipment_id[m],
           "set to median freight of same carrier")
    s.loc[m, "freight_cost"] = np.nan
    s["freight_cost"] = s.freight_cost.fillna(s.groupby("carrier").freight_cost.transform("median"))

    # 8. claims that point to a shipment that does not exist --------------------
    m = ~claims.shipment_id.isin(s.shipment_id)
    record("ORPHAN_CLAIM", "claims", len(claims), claims.claim_id[m], "quarantined for manual match")
    claims[m].to_csv(C.CLEAN / "claims_quarantine.csv", index=False)
    claims = claims[~m]
    claims.to_csv(C.CLEAN / "claims.csv", index=False)

    # ---------------------------------------------------------------- order facts
    w = w.rename(columns={"ALLOCATED": "allocated_ts", "PICKED": "picked_ts", "PACKED": "packed_ts",
                          "SHIPPED": "shipped_ts", "DELIVERED": "delivered_ts"}).drop(columns="ORDER_PLACED")
    f = orders.merge(s.drop(columns=["qty", "dc"]), on="order_id").merge(w, left_on="shipment_id",
                                                                          right_index=True)
    f["ship_date"] = f.shipped_ts.dt.date
    f["delivered_date"] = f.delivered_ts.dt.date
    f["delivery_known"] = f.delivered_ts.notna()
    pr = pd.to_datetime(f.promised_date)
    f["late"] = np.where(f.delivery_known, f.delivered_ts.dt.normalize() > pr, np.nan)
    f["in_full"] = f.qty_shipped >= f.qty
    f["otif"] = np.where(f.delivery_known, (f.late == 0) & f.in_full, np.nan)
    f["days_late"] = np.where(f.delivery_known, (f.delivered_ts.dt.normalize() - pr).dt.days, np.nan)
    f["order_to_ship_hrs"] = (f.shipped_ts - f.order_ts).dt.total_seconds() / 3600
    per = pd.Series(index=f.index, dtype=object)
    od = pd.to_datetime(f.order_ts).dt.date
    for name, a, b in C.PERIODS:
        per[(od >= a) & (od <= b)] = name
    f["period"] = per
    f["week_start"] = (pd.to_datetime(f.order_ts).dt.normalize()
                       - pd.to_timedelta(pd.to_datetime(f.order_ts).dt.weekday, "D")).dt.date
    f["claimed"] = f.shipment_id.isin(claims.shipment_id)
    f.to_csv(C.CLEAN / "order_facts.csv", index=False)

    # ---------------------------------------------------------------- logs
    dq = pd.DataFrame(log)
    dq.to_csv(C.OUT / "dq_log.csv", index=False)

    ak = pd.read_csv(C.TRUTH / "answer_key_injected_defects.csv")
    fl = pd.DataFrame(flags, columns=["defect_type", "record_id"]).drop_duplicates()
    rows = []
    for t in dq.check:
        planted = set(ak.record_id[ak.defect_type == t])
        found = set(fl.record_id[fl.defect_type == t])
        rows.append(dict(defect_type=t, planted=len(planted), flagged=len(found),
                         planted_and_flagged=len(planted & found),
                         recall=round(len(planted & found) / len(planted), 3) if planted else None,
                         flagged_not_planted=len(found - planted)))
    det = pd.DataFrame(rows)
    det.to_csv(C.OUT / "detection_check_vs_answer_key.csv", index=False)

    # imputation accuracy check vs truth
    t = pd.read_csv(C.TRUTH / "order_truth.csv", parse_dates=["ship_date"])
    imp = f[f.shipped_imputed].merge(t[["order_id", "ship_date"]], on="order_id", suffixes=("", "_true"))
    acc = (pd.to_datetime(imp.ship_date) == imp.ship_date_true).mean()
    print(dq.to_string(index=False))
    print(det.to_string(index=False))
    print(f"imputed ship dates exactly right: {acc:.1%} of {len(imp)}")
    print(f"order facts: {len(f):,} rows; delivery known {f.delivery_known.mean():.2%}")


if __name__ == "__main__":
    main()
