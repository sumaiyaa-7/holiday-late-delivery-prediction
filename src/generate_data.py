"""
Generate one synthetic holiday season for a fictional US online retailer
("Northpine Goods") with two DCs, five categories and four carriers.

Writes:
  data/raw/    orders, shipments, shipment_events, claims, skus  (with defects)
  data/truth/  answer_key_injected_defects.csv  - every planted data defect
               order_truth.csv                  - true dates and root cause
                                                  (grading/simulation only)

Run:  python src/generate_data.py
"""
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

import config as C

rng = np.random.default_rng(C.SEED)


def daterange(a, b):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


def day_multiplier(d):
    if d in C.DAY_MULTIPLIER:
        return C.DAY_MULTIPLIER[d]
    if d.month == 12 and d.day in C.DEC_RAMP:
        return C.DEC_RAMP[d.day]
    return 1.0


def in_window(d, a, b):
    return a <= d <= b


# ---------------------------------------------------------------- SKUs
def make_skus():
    rows = []
    for cat, p in C.CATEGORIES.items():
        prefix = cat[:3].upper()
        for i in range(C.SKUS_PER_CATEGORY):
            rows.append(dict(
                sku=f"{prefix}-{i + 1:03d}", category=cat,
                sourcing="Asia" if rng.random() < p["asia"] else "Domestic",
                unit_price=round(float(p["price"] * rng.lognormal(0, 0.45)), 2),
                unit_weight_lb=round(float(p["wt"] * rng.lognormal(0, 0.3)), 2),
                popularity=float(rng.pareto(1.6) + 1),
            ))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- orders
def make_orders(skus):
    cats = list(C.CATEGORIES)
    sku_by_cat = {c: skus[skus.category == c].reset_index(drop=True) for c in cats}
    regions, rw = list(C.REGIONS), np.array(list(C.REGIONS.values()))
    rows, n = [], 0
    for d in daterange(C.FIRST_ORDER_DAY, C.LAST_ORDER_DAY):
        lam = C.BASE_ORDERS_PER_DAY * day_multiplier(d)
        k = rng.poisson(lam)
        cyber = in_window(d, C.THANKSGIVING, date(2026, 12, 2))
        w = np.array([C.CATEGORIES[c]["share"] * (C.CATEGORIES[c]["bf"] if cyber else
                      C.CATEGORIES[c]["dec"] if d.month == 12 else 1.0) for c in cats])
        w = w / w.sum()
        cat_draw = rng.choice(len(cats), size=k, p=w)
        reg_draw = rng.choice(len(regions), size=k, p=rw / rw.sum())
        secs = np.sort(rng.integers(0, 86400, size=k))
        for j in range(k):
            cat = cats[cat_draw[j]]
            pool = sku_by_cat[cat]
            s = pool.iloc[rng.choice(len(pool), p=(pool.popularity / pool.popularity.sum()).values)]
            region = regions[reg_draw[j]]
            dcs = C.REGION_DC[region]
            dc = rng.choice(list(dcs), p=list(dcs.values()))
            express = rng.random() < C.CATEGORIES[cat]["express"]
            qty = int(rng.choice([1, 1, 1, 1, 2, 2, 3]))
            ts = datetime.combine(d, datetime.min.time()) + timedelta(seconds=int(secs[j]))
            plan = C.TRANSIT_PLAN[(dc, region)]
            late_cut = 1 if ts.hour >= 14 else 0   # "order by 2pm" same-day cutoff
            promise = d + timedelta(days=(2 if express else 1 + plan + 1) + late_cut)
            n += 1
            rows.append(dict(
                order_id=f"NP{n:06d}", order_ts=ts, order_date=d,
                customer_region=region, dc=dc, category=cat, sku=s.sku,
                sourcing=s.sourcing, qty=qty, unit_price=s.unit_price,
                order_value=round(qty * s.unit_price, 2),
                unit_weight_lb=s.unit_weight_lb,
                ship_speed="Express" if express else "Standard",
                promised_date=promise,
            ))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- fulfilment simulation
def simulate(orders):
    o = orders.copy()
    n = len(o)
    # 1. inventory: is the item in the building when ordered?
    bo_p = o.category.map(lambda c: C.CATEGORIES[c]["bo"]).values.copy()
    cyber = (o.order_date >= C.THANKSGIVING) & (o.order_date <= date(2026, 12, 2))
    bo_p = np.where(cyber, bo_p * 2.0, bo_p)
    h = C.HIDDEN_ISSUE
    hidden = ((o.dc == h["dc"]) & (o.category == h["category"]) & (o.sourcing == h["sourcing"])
              & (o.order_date >= h["start"]) & (o.order_date <= h["end"])).values
    bo_p = np.where(hidden, h["backorder_prob"], bo_p)
    backordered = rng.random(n) < bo_p
    bo_delay = np.where(hidden, rng.integers(h["delay_days"][0], h["delay_days"][1] + 1, n),
                        rng.integers(2, 6, n))
    bo_delay = np.where(backordered, bo_delay, 0)
    order_ts = pd.to_datetime(o.order_ts)
    alloc_ts = order_ts + pd.to_timedelta(rng.integers(60, 1800, n), unit="s")
    alloc_ts = np.where(backordered,
                        pd.to_datetime(o.order_date) + pd.to_timedelta(bo_delay, "D")
                        + pd.to_timedelta(rng.integers(6 * 3600, 10 * 3600, n), "s"),
                        alloc_ts)
    o["backordered"] = backordered
    o["allocated_ts"] = pd.to_datetime(alloc_ts)
    # ready for picking the day after allocation if allocated late in the day
    ready = o.allocated_ts.dt.normalize() + pd.to_timedelta(
        (o.allocated_ts.dt.hour >= 14).astype(int), "D")
    o["ready_date"] = ready.dt.date

    # 2. DC queue: each day pack up to capacity; Express first, then oldest
    o["pack_date"] = pd.NaT
    pack = {}
    for dc, cap in C.DC_CAPACITY.items():
        sub = o[o.dc == dc]
        by_ready = {}
        for idx, rd in zip(sub.index, sub.ready_date):
            by_ready.setdefault(rd, []).append(idx)
        queue = []
        for d in daterange(C.FIRST_ORDER_DAY, date(2027, 1, 5)):
            queue.extend(by_ready.get(d, []))
            f = C.CAPACITY_FACTOR.get(d, 1.0)
            if date(2026, 11, 26) <= d <= date(2026, 12, 20):
                f *= C.PEAK_OVERTIME
            c = int(cap * f * rng.normal(1, 0.05))
            if not queue or c <= 0:
                continue
            queue.sort(key=lambda i: (o.at[i, "ship_speed"] != "Express", o.at[i, "ready_date"],
                                      o.at[i, "order_ts"]))
            done, queue = queue[:c], queue[c:]
            for i in done:
                pack[i] = d
    o["pack_date"] = o.index.map(pack)
    o["queue_days"] = [(p - r).days for p, r in zip(o.pack_date, o.ready_date)]

    # 3. carrier + tender rejection
    names = list(C.CARRIERS)
    carrier = np.empty(n, dtype=object)
    for dc, col in (("NJ", 0), ("TX", 1)):
        m = (o.dc == dc).values
        p = np.array([C.CARRIERS[c][col] for c in names])
        carrier[m] = rng.choice(names, size=m.sum(), p=p / p.sum())
    peak = o.pack_date.between(*C.TENDER_PEAK).values
    rej_p = np.array([C.CARRIERS[c][3] if pk else C.CARRIERS[c][2] for c, pk in zip(carrier, peak)])
    rejected = rng.random(n) < rej_p
    tender_delay = np.where(rejected, rng.choice([1, 1, 2, 2, 3], n), 0)
    original = carrier.copy()
    for i in np.where(rejected)[0]:
        others = [c for c in names if c != original[i]]
        carrier[i] = rng.choice(others)
    o["original_carrier"], o["carrier"], o["tender_rejected"] = original, carrier, rejected
    o["tender_delay"] = tender_delay
    o["ship_date"] = [p + timedelta(days=int(t)) for p, t in zip(o.pack_date, tender_delay)]

    # 4. transit
    plan = np.array([C.TRANSIT_PLAN[(d, r)] for d, r in zip(o.dc, o.customer_region)])
    express = (o.ship_speed == "Express").values
    base = np.where(express, 1, plan)
    noise = rng.choice([0, 1, 2, 3], n, p=[.88, .09, .025, .005])
    noise = np.where(express, rng.choice([0, 1], n, p=[.93, .07]), noise)
    sd = pd.to_datetime(o.ship_date)
    congest = ((sd >= "2026-11-28") & (sd <= "2026-12-08") & (rng.random(n) < .25)) | \
              ((sd >= "2026-12-15") & (sd <= "2026-12-23") & (rng.random(n) < .20))
    blue = (carrier == "BlueLine Freight") & (rng.random(n) < .10)
    extra = noise + congest.astype(int) + blue.astype(int)
    o["transit_extra"] = extra
    deliv = [s + timedelta(days=int(b + e)) for s, b, e in zip(o.ship_date, base, extra)]
    deliv = [d + timedelta(days=1) if d == C.CHRISTMAS else d for d in deliv]
    o["delivered_date"] = deliv
    lost = rng.random(n) < C.LOST_IN_TRANSIT
    o["lost"] = lost
    o.loc[lost, "delivered_date"] = None

    # 5. in-full
    short_p = np.where(cyber, 0.015, 0.006)
    short = (rng.random(n) < short_p) & (o.qty.values > 1)
    short |= (rng.random(n) < 0.002)  # single-unit lines shipped as 0 (mis-pick)
    o["qty_shipped"] = np.where(short, np.maximum(o.qty.values - 1, 0), o.qty.values)

    # 6. freight cost
    zone = np.where(plan >= 4, 3.0, np.where(plan == 3, 2.0, 1.0))
    cost = 6 + 0.45 * o.unit_weight_lb.values * o.qty.values * zone
    cost *= np.where(express, 2.6, 1.0)
    in_peak = (sd >= "2026-11-23") & (sd <= "2026-12-24")
    cost += np.where(in_peak, 1.50, 0) + np.where(rejected, 4.0, 0)
    o["freight_cost"] = np.round(cost * rng.normal(1, .05, n), 2)

    # 7. truth: late? root cause = largest delay component
    late = np.array([(dd is None) or (dd > pr) for dd, pr in zip(o.delivered_date, o.promised_date)])
    o["true_late"] = late
    comp = pd.DataFrame({"Backorder": bo_delay, "DC backlog": o.queue_days.values,
                         "Tender rejection": tender_delay, "Transit": extra})
    cause = comp.idxmax(axis=1)
    cause[o.lost.values] = "Lost in transit"
    o["root_cause"] = np.where(late, cause, "")
    return o


# ---------------------------------------------------------------- events
def make_events(o):
    n = len(o)
    ev = []
    def add(et, ts):
        ev.append(pd.DataFrame({"shipment_id": o.shipment_id.values, "event_type": et,
                                "event_ts": ts}))
    add("ORDER_PLACED", o.order_ts.values)
    add("ALLOCATED", o.allocated_ts.values)
    pk = pd.to_datetime(o.pack_date)
    picked = pk + pd.to_timedelta(rng.integers(7 * 3600, 13 * 3600, n), "s")
    packed = picked + pd.to_timedelta(rng.integers(1800, 4 * 3600, n), "s")
    shipped = pd.to_datetime(o.ship_date) + pd.to_timedelta(rng.integers(17 * 3600, 22 * 3600, n), "s")
    add("PICKED", picked.values)
    add("PACKED", packed.values)
    add("SHIPPED", shipped.values)
    dl = pd.to_datetime(o.delivered_date) + pd.to_timedelta(rng.integers(9 * 3600, 20 * 3600, n), "s")
    add("DELIVERED", dl.values)
    e = pd.concat(ev, ignore_index=True)
    return e[e.event_ts.notna()].reset_index(drop=True)


# ---------------------------------------------------------------- claims
def make_claims(o):
    rows = []
    dmg = o.category.map(lambda c: C.CATEGORIES[c]["dmg"]).values
    r = rng.random(len(o))
    for i, row in enumerate(o.itertuples()):
        base_day = row.delivered_date if row.delivered_date is not None else row.promised_date
        kind = None
        if row.lost and rng.random() < .8:
            kind, val, lag = "LOST", row.order_value, rng.integers(5, 16)
        elif row.delivered_date is not None and r[i] < dmg[i]:
            kind, val, lag = "DAMAGED", row.order_value, rng.integers(1, 10)
        elif row.qty_shipped < row.qty and rng.random() < .7:
            kind, val, lag = "SHORTAGE", (row.qty - row.qty_shipped) * row.unit_price, rng.integers(1, 8)
        elif row.true_late and not row.lost:
            gift = row.promised_date >= C.GIFT_CRITICAL_FROM
            if rng.random() < (.30 if gift else .08):
                kind, val, lag = "LATE_GOODWILL", max(5.0, .15 * row.order_value), rng.integers(0, 6)
        if kind is None:
            continue
        filed = base_day + timedelta(days=int(lag))
        busy = 1.8 if date(2026, 12, 1) <= filed <= date(2027, 1, 5) else 1.0
        res_days = int(np.ceil(rng.gamma(2.0, 3.0) * busy))
        resolved = filed + timedelta(days=res_days)
        rows.append(dict(shipment_id=row.shipment_id, claim_type=kind,
                         claim_value=round(float(val), 2), filed_date=filed,
                         resolved_date=resolved if resolved <= C.EXTRACT_DATE else None,
                         status="RESOLVED" if resolved <= C.EXTRACT_DATE else "OPEN"))
    c = pd.DataFrame(rows).sort_values("filed_date").reset_index(drop=True)
    c.insert(0, "claim_id", [f"CL{i + 1:05d}" for i in range(len(c))])
    return c


# ---------------------------------------------------------------- defects
def inject_defects(orders, ship, events, claims):
    key = []
    D = C.DEFECTS
    sids = ship.shipment_id.values

    # orders: duplicated rows (same order_id)
    dup = orders.sample(frac=D["dup_order_rows"], random_state=C.SEED)
    key += [("DUPLICATE_ORDER_ROW", "orders", x) for x in dup.order_id]
    orders = pd.concat([orders, dup]).sort_values("order_ts").reset_index(drop=True)

    # events: pick disjoint shipment sets for each event defect (delivered only where relevant)
    delivered = set(events.loc[events.event_type == "DELIVERED", "shipment_id"])
    pool = list(rng.permutation(sids))
    def take(rate, need_delivered=False):
        k = int(rate * len(sids))
        out = []
        while len(out) < k:
            s = pool.pop()
            if need_delivered and s not in delivered:
                continue
            out.append(s)
        return out
    miss_ship = take(D["missing_shipped_scan"])
    miss_del = take(D["missing_delivered_scan"], True)
    dup_ev = take(D["dup_events"])
    swap = take(D["packed_before_picked"])
    bad_clock = take(D["delivered_before_shipped"], True)

    drop = ((events.shipment_id.isin(miss_ship)) & (events.event_type == "SHIPPED")) | \
           ((events.shipment_id.isin(miss_del)) & (events.event_type == "DELIVERED"))
    events = events[~drop].copy()
    key += [("MISSING_SHIPPED_SCAN", "shipment_events", s) for s in miss_ship]
    key += [("MISSING_DELIVERED_SCAN", "shipment_events", s) for s in miss_del]

    extra = []
    for s in dup_ev:
        e = events[events.shipment_id == s].sample(1, random_state=int(rng.integers(1e9))).copy()
        e["event_ts"] = e.event_ts + pd.Timedelta(seconds=int(rng.integers(5, 120)))
        extra.append(e)
    events = pd.concat([events] + extra)
    key += [("DUPLICATE_EVENT", "shipment_events", s) for s in dup_ev]

    for s in swap:
        m_pi = (events.shipment_id == s) & (events.event_type == "PICKED")
        m_pa = (events.shipment_id == s) & (events.event_type == "PACKED")
        a, b = events.loc[m_pi, "event_ts"].values[0], events.loc[m_pa, "event_ts"].values[0]
        events.loc[m_pi, "event_ts"], events.loc[m_pa, "event_ts"] = b, a
    key += [("PACKED_BEFORE_PICKED", "shipment_events", s) for s in swap]

    for s in bad_clock:
        sh = events.loc[(events.shipment_id == s) & (events.event_type == "SHIPPED"), "event_ts"].values[0]
        m = (events.shipment_id == s) & (events.event_type == "DELIVERED")
        events.loc[m, "event_ts"] = sh - np.timedelta64(int(rng.integers(20, 60)), "h")
    key += [("DELIVERED_BEFORE_SHIPPED", "shipment_events", s) for s in bad_clock]
    events = events.sample(frac=1, random_state=C.SEED).reset_index(drop=True)  # arrival order

    # shipments: keying errors
    hi = ship.sample(frac=D["qty_shipped_too_high"], random_state=C.SEED + 1).index
    ship.loc[hi, "qty_shipped"] = ship.loc[hi, "qty_shipped"] + 10
    key += [("QTY_SHIPPED_TOO_HIGH", "shipments", s) for s in ship.loc[hi, "shipment_id"]]
    neg = ship.drop(hi).sample(frac=D["negative_freight"], random_state=C.SEED + 2).index
    ship.loc[neg, "freight_cost"] = -ship.loc[neg, "freight_cost"]
    key += [("NEGATIVE_FREIGHT", "shipments", s) for s in ship.loc[neg, "shipment_id"]]

    # claims: shipment id typo -> orphan
    orph = claims.sample(frac=D["orphan_claims"], random_state=C.SEED + 3).index
    claims.loc[orph, "shipment_id"] = ["SH9" + s[3:] for s in claims.loc[orph, "shipment_id"]]
    key += [("ORPHAN_CLAIM", "claims", c) for c in claims.loc[orph, "claim_id"]]

    ak = pd.DataFrame(key, columns=["defect_type", "table", "record_id"])
    return orders, ship, events, claims, ak


def main():
    for p in (C.RAW, C.TRUTH):
        p.mkdir(parents=True, exist_ok=True)
    skus = make_skus()
    orders = make_orders(skus)
    sim = simulate(orders)
    sim["shipment_id"] = ["SH" + x[2:] for x in sim.order_id]

    events = make_events(sim)
    claims = make_claims(sim)

    order_cols = ["order_id", "order_ts", "order_date", "customer_region", "dc", "category", "sku",
                  "sourcing", "qty", "unit_price", "order_value", "ship_speed", "promised_date"]
    ship = sim[["shipment_id", "order_id", "dc", "original_carrier", "carrier", "tender_rejected",
                "qty_shipped", "freight_cost"]].copy()
    orders_raw, ship, events, claims, ak = inject_defects(sim[order_cols].copy(), ship, events, claims)

    skus.drop(columns="popularity").to_csv(C.RAW / "skus.csv", index=False)
    orders_raw.to_csv(C.RAW / "orders.csv", index=False)
    ship.to_csv(C.RAW / "shipments.csv", index=False)
    events.to_csv(C.RAW / "shipment_events.csv", index=False)
    claims.to_csv(C.RAW / "claims.csv", index=False)
    ak.to_csv(C.TRUTH / "answer_key_injected_defects.csv", index=False)
    sim[["order_id", "shipment_id", "backordered", "queue_days", "tender_delay", "transit_extra",
         "ship_date", "delivered_date", "lost", "true_late", "root_cause"]].to_csv(
        C.TRUTH / "order_truth.csv", index=False)

    print(f"orders {len(sim):,}  events {len(events):,}  claims {len(claims):,}  "
          f"defects planted {len(ak):,}")
    print(f"true late rate {sim.true_late.mean():.2%}")
    print(sim.groupby(["dc", "category"]).true_late.mean().unstack().round(3))


if __name__ == "__main__":
    main()
