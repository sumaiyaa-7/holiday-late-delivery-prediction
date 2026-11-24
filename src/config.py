"""
Every assumption in one place. Nothing here is real company data; values are
chosen to be plausible for a mid-size US online retailer and are documented
so a reader can disagree with them and re-run.
"""
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"            # what the "systems" export (with defects)
TRUTH = DATA / "truth"        # answer key + simulation truth (grading only)
CLEAN = DATA / "clean"        # output of validate_clean.py
OUT = ROOT / "outputs"
CHARTS = ROOT / "charts"
SQL = ROOT / "sql"

SEED = 2026

# ---------------------------------------------------------------- calendar
FIRST_ORDER_DAY = date(2026, 11, 2)
LAST_ORDER_DAY = date(2026, 12, 21)
EXTRACT_DATE = date(2027, 1, 10)       # data pulled from systems on this day
THANKSGIVING = date(2026, 11, 26)
BLACK_FRIDAY = date(2026, 11, 27)
CYBER_MONDAY = date(2026, 11, 30)
CHRISTMAS = date(2026, 12, 25)

# Periods by order date (used in scorecards)
PERIODS = [
    ("1 Pre-peak", date(2026, 11, 2), date(2026, 11, 25)),
    ("2 Cyber Week", date(2026, 11, 26), date(2026, 12, 2)),
    ("3 December build", date(2026, 12, 3), date(2026, 12, 15)),
    ("4 Last-call week", date(2026, 12, 16), date(2026, 12, 21)),
]

# ---------------------------------------------------------------- demand
BASE_ORDERS_PER_DAY = 380
DAY_MULTIPLIER = {  # anything not listed = 1.0
    date(2026, 11, 26): 1.9, date(2026, 11, 27): 3.1, date(2026, 11, 28): 2.3,
    date(2026, 11, 29): 2.0, date(2026, 11, 30): 3.4, date(2026, 12, 1): 2.2,
    date(2026, 12, 2): 1.8, date(2026, 12, 3): 1.6, date(2026, 12, 4): 1.5,
}
DEC_RAMP = {  # Dec 5 .. Dec 21: gift buying builds, then drops after the shipping cutoff
    5: 1.30, 6: 1.30, 7: 1.40, 8: 1.45, 9: 1.50, 10: 1.55, 11: 1.60, 12: 1.65,
    13: 1.70, 14: 1.80, 15: 1.85, 16: 1.70, 17: 1.50, 18: 1.20, 19: 0.80,
    20: 0.60, 21: 0.50,
}

REGIONS = {"Northeast": 0.22, "Southeast": 0.22, "Midwest": 0.20,
           "Southwest": 0.16, "West": 0.20}
# Which DC serves which region (Midwest is split)
REGION_DC = {"Northeast": {"NJ": 1.0}, "Southeast": {"NJ": 1.0},
             "Midwest": {"NJ": 0.6, "TX": 0.4},
             "Southwest": {"TX": 1.0}, "West": {"TX": 1.0}}
# Planned ground transit days (the number the website uses to make promises)
TRANSIT_PLAN = {
    ("NJ", "Northeast"): 2, ("NJ", "Southeast"): 3, ("NJ", "Midwest"): 3,
    ("TX", "Midwest"): 3, ("TX", "Southwest"): 2, ("TX", "West"): 4,
}

# Category behaviour. bf = multiplier of share on Cyber Week, dec = in December
CATEGORIES = {
    #             share  bf    dec   price  wt_lb asia  backorder damage express
    "Electronics": dict(share=.22, bf=1.6, dec=1.0, price=180, wt=4,  asia=.70, bo=.020, dmg=.008, express=.22),
    "Toys":        dict(share=.20, bf=1.0, dec=1.5, price=45,  wt=3,  asia=.85, bo=.025, dmg=.004, express=.18),
    "Apparel":     dict(share=.24, bf=0.9, dec=0.9, price=55,  wt=1.5, asia=.60, bo=.015, dmg=.002, express=.12),
    "Home & Kitchen": dict(share=.18, bf=1.1, dec=0.8, price=95, wt=14, asia=.50, bo=.020, dmg=.012, express=.08),
    "Beauty & Gift Sets": dict(share=.16, bf=0.8, dec=1.4, price=48, wt=1.2, asia=.20, bo=.015, dmg=.005, express=.15),
}
SKUS_PER_CATEGORY = 30

# ---------------------------------------------------------------- DC capacity
DC_CAPACITY = {"NJ": 380, "TX": 300}          # orders packed per day, normal
PEAK_OVERTIME = 1.20                           # Nov 26 - Dec 20
CAPACITY_FACTOR = {THANKSGIVING: 0.5, CHRISTMAS: 0.0}

# ---------------------------------------------------------------- carriers (fictional)
CARRIERS = {
    #                share_NJ share_TX base_reject peak_reject
    "ParcelOne":        (0.42, 0.35, 0.02, 0.10),
    "SwiftShip":        (0.30, 0.25, 0.02, 0.09),
    "BlueLine Freight": (0.16, 0.32, 0.03, 0.27),
    "Regional Express": (0.12, 0.08, 0.01, 0.05),
}
TENDER_PEAK = (date(2026, 11, 27), date(2026, 12, 2))

# ---------------------------------------------------------------- the planted operational problem
# An ocean container of Asia-sourced toys bound for the TX DC is late.
# Orders for those SKUs at TX placed in this window wait for the container.
HIDDEN_ISSUE = dict(dc="TX", category="Toys", sourcing="Asia",
                    start=date(2026, 12, 1), end=date(2026, 12, 12),
                    backorder_prob=0.45, delay_days=(6, 10))

# ---------------------------------------------------------------- data defects (rates)
DEFECTS = dict(
    dup_order_rows=0.015,        # OMS re-sent the order message
    missing_shipped_scan=0.030,
    missing_delivered_scan=0.015,
    dup_events=0.020,
    packed_before_picked=0.010,
    delivered_before_shipped=0.005,
    qty_shipped_too_high=0.003,
    negative_freight=0.003,
    orphan_claims=0.020,
)
LOST_IN_TRANSIT = 0.003           # real (not a data defect): never delivered

# ---------------------------------------------------------------- KPI tolerances (exception-rate form)
# Rating: RED if the Wilson 95% lower bound > tolerance; AMBER if rate > tolerance
# but the interval still reaches it; GREEN otherwise. Same rule as my loan project.
TOLERANCE = {
    "late_delivery": 0.05,       # i.e. on-time target 95%
    "not_otif": 0.06,            # OTIF target 94%
    "not_in_full": 0.01,
    "tender_rejection": 0.05,
    "claim_rate": 0.01,
    "data_incomplete": 0.02,
}

# ---------------------------------------------------------------- promise-risk economics (assumptions)
DECISION_LEAD_DAYS = 2          # we score each promise 2 days before it is due
TRAIN_PROMISE_END = date(2026, 12, 6)    # train on promises due on/before this
TEST_PROMISE_END = date(2026, 12, 24)    # test = "Christmas window" Dec 7-24
# Loss given a missed promise, as a share of order value, plus a fixed
# cost for the "where is my order?" contact it triggers.
LGD_GIFT_CRITICAL = 0.30        # promise due Dec 14-24: gift misses Christmas
LGD_REGULAR = 0.06
WISMO_CONTACT_COST = 4.00
# A missed Christmas gift can cost the customer, not just the order:
CHURN_PROB_GIFT = 0.15          # chance a gift-critical miss loses the customer
CHURN_PROB_REGULAR = 0.02
FUTURE_MARGIN_PER_CUSTOMER = 150.0   # margin from a retained customer's next 2 years
GIFT_CRITICAL_FROM = date(2026, 12, 14)
# Actions
EXPEDITE_COST = {"Electronics": 14, "Toys": 12, "Apparel": 9,
                 "Home & Kitchen": 26, "Beauty & Gift Sets": 9}
EXPEDITE_SAVE = 0.80        # priority pick + air upgrade rescues a late, in-stock order 80% of the time
# Item not in the building? Expediting can't help. Ship it from the other DC instead
# (express, cross-region). Works if the other DC has it and the longer lane still makes it.
REROUTE_EXTRA_COST = 6.0     # on top of the expedite cost
REROUTE_SAVE = 0.70
NOTICE_COST = 0.50                  # proactive "your order is delayed" message
NOTICE_LOSS_REDUCTION = 0.30
