"""
Build outputs/weekly_shipment_tracker.xlsx - the file an ops analyst would send
every Monday. Rates, Wilson lower bounds and GREEN/AMBER/RED ratings are live
Excel formulas driven by the tolerance cells on the Settings tab.
"""
import pandas as pd
from openpyxl import Workbook
from openpyxl.comments import Comment
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

import config as C

F = "Arial"
H_FILL = PatternFill("solid", fgColor="1F3A5F")
H_FONT = Font(name=F, bold=True, color="FFFFFF", size=10)
BODY = Font(name=F, size=10)
INPUT = Font(name=F, size=10, color="0000FF")
TITLE = Font(name=F, bold=True, size=14)
NOTE = Font(name=F, italic=True, size=9, color="52514E")
THIN = Border(bottom=Side(style="thin", color="DDDDDD"))
STATUS = {"GREEN": "C6EFCE", "AMBER": "FFEB9C", "RED": "FFC7CE"}
STATUS_TXT = {"GREEN": "006100", "AMBER": "9C5700", "RED": "9C0006"}
PCT, MONEY, MONEY2, INT = "0.0%", "$#,##0;($#,##0);-", "$#,##0.00", "#,##0"


def header(ws, row, cols, widths=None):
    for j, c in enumerate(cols, 1):
        cell = ws.cell(row=row, column=j, value=c)
        cell.fill, cell.font = H_FILL, H_FONT
        cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
    ws.row_dimensions[row].height = 32
    if widths:
        for j, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(j)].width = w
    ws.freeze_panes = ws.cell(row=row + 1, column=1)


def status_format(ws, rng):
    for k, fill in STATUS.items():
        ws.conditional_formatting.add(rng, CellIsRule(operator="equal", formula=[f'"{k}"'],
                                      fill=PatternFill("solid", fgColor=fill),
                                      font=Font(name=F, bold=True, color=STATUS_TXT[k])))


def title(ws, text, sub):
    ws["A1"], ws["A1"].font = text, TITLE
    ws["A2"], ws["A2"].font = sub, NOTE


def wilson_lo(k, n):
    """Excel formula for the Wilson 95% lower bound of k/n (z = Settings!$B$11)."""
    p = f"({k}/{n})"
    z = "Settings!$B$11"
    return (f"=IFERROR(({p}+{z}^2/(2*{n})-{z}*SQRT({p}*(1-{p})/{n}+{z}^2/(4*{n}^2)))"
            f"/(1+{z}^2/{n}),0)")


def rating(rate, lo, tol):
    return f'=IF({lo}>{tol},"RED",IF({rate}>{tol},"AMBER","GREEN"))'


def main():
    wb = Workbook()

    # ---------------------------------------------------------------- Settings
    s = wb.active
    s.title = "Settings"
    title(s, "Settings and how to read this workbook",
          "Blue cells are inputs. Change a tolerance and every rating in the workbook updates.")
    s["A4"], s["A4"].font = "Tolerance (max acceptable exception rate)", Font(name=F, bold=True)
    tol_rows = [("Late delivery", "late_delivery"), ("Not OTIF", "not_otif"), ("Not in full", "not_in_full"),
                ("Tender rejection", "tender_rejection"), ("Physical claims", "claim_rate"),
                ("Data incomplete", "data_incomplete")]
    for i, (lab, k) in enumerate(tol_rows, 5):
        s.cell(row=i, column=1, value=lab).font = BODY
        c = s.cell(row=i, column=2, value=C.TOLERANCE[k])
        c.font, c.number_format = INPUT, PCT
    s["B5"].comment = Comment("Assumption: on-time target 95%. Real thresholds come from the customer promise "
                              "policy and carrier contracts.", "analyst")
    s["A11"], s["B11"] = "z for 95% interval", 1.96
    s["A11"].font, s["B11"].font = BODY, INPUT
    s["A13"], s["A13"].font = "Rating rule", Font(name=F, bold=True)
    rules = ["RED: even the low end of the 95% Wilson interval is above tolerance (a clear breach).",
             "AMBER: the rate is above tolerance, but the interval still reaches it (watch).",
             "GREEN: the rate is at or under tolerance."]
    for i, r in enumerate(rules, 14):
        s.cell(row=i, column=1, value=r).font = BODY
    s["A18"], s["A18"].font = "Tabs", Font(name=F, bold=True)
    tabs = [("Weekly tracker", "One row per order week: volume, late, OTIF, tender rejections, freight, data gaps."),
            ("Scorecard", "Same KPIs by season period (pre-peak, Cyber Week, December build, last-call week)."),
            ("Action queue Dec 18", "The morning list: promises due Dec 20, ranked by expected loss, with the action."),
            ("Carriers", "Tender rejections by carrier, peak window vs the rest of the season."),
            ("Claims", "Damage / shortage / lost claims by category, plus late-delivery goodwill credits."),
            ("Policies", "Simulated outcome of five ways to run the Christmas window (from promise_risk.py)."),
            ("Data quality", "Every cleaning rule that fired, and whether it found every planted defect.")]
    for i, (t, d) in enumerate(tabs, 19):
        s.cell(row=i, column=1, value=t).font = Font(name=F, bold=True, size=10)
        s.cell(row=i, column=2, value=d).font = BODY
    s["A27"], s["A27"].font = "Abbreviations", Font(name=F, bold=True)
    gl = [("OTIF", "On Time In Full: delivered by the promised date AND with every unit ordered."),
          ("PD", "Probability of a missed promise (from the logistic regression)."),
          ("LGD", "Loss Given a miss: share of order value lost if the promise is missed."),
          ("EL", "Expected Loss = PD x LGD x order value (+ contact cost)."),
          ("DC", "Distribution center (warehouse that ships the orders)."),
          ("WISMO", "'Where is my order?' customer contact."),
          ("D-2", "Two days before the promised delivery date (when the model scores each order).")]
    for i, (a, d) in enumerate(gl, 28):
        s.cell(row=i, column=1, value=a).font = Font(name=F, bold=True, size=10)
        s.cell(row=i, column=2, value=d).font = BODY
    s.column_dimensions["A"].width = 38
    s.column_dimensions["B"].width = 100

    # ---------------------------------------------------------------- Weekly tracker
    w = pd.read_csv(C.OUT / "weekly_tracker.csv")
    ws = wb.create_sheet("Weekly tracker")
    title(ws, "Weekly shipment tracker - Northpine Goods (synthetic), holiday 2026",
          "Week = Monday of the order week. Late / OTIF use delivered orders only; unknown deliveries are shown "
          "separately. Rates, intervals and ratings are formulas.")
    cols = ["Week of", "Orders", "Shipped", "Delivered (known)", "Late", "Late rate", "Late rate low (95%)",
            "Late rating", "Not OTIF", "OTIF %", "Not-OTIF rating", "Tender rejections", "Rejection rate",
            "Rejection rating", "Freight ($)", "Freight per unit ($)", "Imputed ship scans", "Unknown deliveries"]
    header(ws, 4, cols, [12, 9, 9, 11, 8, 9, 11, 10, 9, 9, 11, 11, 11, 11, 11, 11, 11, 11])
    r0 = 5
    for i, row in enumerate(w.itertuples(), r0):
        vals = [pd.Timestamp(row.week_start).to_pydatetime(), row.orders, row.shipped, row.delivered,
                row.late_orders]
        for j, v in enumerate(vals, 1):
            ws.cell(row=i, column=j, value=v).font = INPUT if j > 1 else BODY
        ws.cell(row=i, column=1).number_format = "mmm d, yyyy"
        ws.cell(row=i, column=6, value=f"=IFERROR(E{i}/D{i},0)")
        ws.cell(row=i, column=7, value=wilson_lo(f"E{i}", f"D{i}"))
        ws.cell(row=i, column=8, value=rating(f"F{i}", f"G{i}", "Settings!$B$5"))
        ws.cell(row=i, column=9, value=row.not_otif).font = INPUT
        ws.cell(row=i, column=10, value=f"=IFERROR(1-I{i}/D{i},0)")
        ws.cell(row=i, column=11, value=rating(f"(1-J{i})", wilson_lo(f"I{i}", f"D{i}")[1:], "Settings!$B$6"))
        ws.cell(row=i, column=12, value=row.tender_rejections).font = INPUT
        ws.cell(row=i, column=13, value=f"=IFERROR(L{i}/C{i},0)")
        ws.cell(row=i, column=14, value=rating(f"M{i}", wilson_lo(f"L{i}", f"C{i}")[1:], "Settings!$B$8"))
        ws.cell(row=i, column=15, value=row.freight_cost).font = INPUT
        ws.cell(row=i, column=16, value=row.freight_per_unit).font = INPUT
        ws.cell(row=i, column=17, value=row.imputed_ship_scans).font = INPUT
        ws.cell(row=i, column=18, value=row.unknown_deliveries).font = INPUT
        for j, fmt in [(2, INT), (3, INT), (4, INT), (5, INT), (6, PCT), (7, PCT), (9, INT), (10, PCT), (12, INT),
                       (13, PCT), (15, MONEY), (16, MONEY2), (17, INT), (18, INT)]:
            ws.cell(row=i, column=j).number_format = fmt
        for j in range(1, 19):
            ws.cell(row=i, column=j).border = THIN
            if ws.cell(row=i, column=j).font != INPUT:
                ws.cell(row=i, column=j).font = BODY
    last = r0 + len(w) - 1
    t = last + 1
    ws.cell(row=t, column=1, value="Season").font = Font(name=F, bold=True)
    for j in (2, 3, 4, 5, 9, 12, 15, 17, 18):
        L = get_column_letter(j)
        ws.cell(row=t, column=j, value=f"=SUM({L}{r0}:{L}{last})").number_format = MONEY if j == 15 else INT
    ws.cell(row=t, column=6, value=f"=IFERROR(E{t}/D{t},0)").number_format = PCT
    ws.cell(row=t, column=7, value=wilson_lo(f"E{t}", f"D{t}")).number_format = PCT
    ws.cell(row=t, column=8, value=rating(f"F{t}", f"G{t}", "Settings!$B$5"))
    ws.cell(row=t, column=10, value=f"=IFERROR(1-I{t}/D{t},0)").number_format = PCT
    ws.cell(row=t, column=11, value=rating(f"(1-J{t})", wilson_lo(f"I{t}", f"D{t}")[1:], "Settings!$B$6"))
    ws.cell(row=t, column=13, value=f"=IFERROR(L{t}/C{t},0)").number_format = PCT
    ws.cell(row=t, column=14, value=rating(f"M{t}", wilson_lo(f"L{t}", f"C{t}")[1:], "Settings!$B$8"))
    for j in range(1, 19):
        ws.cell(row=t, column=j).font = Font(name=F, bold=True, size=10)
    for col in ("H", "K", "N"):
        status_format(ws, f"{col}{r0}:{col}{t}")
    ws.cell(row=t + 2, column=1, value="Blue = values from the SQL queries (sql/02_weekly_tracker.sql); "
            "black = Excel formulas.").font = NOTE

    # ---------------------------------------------------------------- Scorecard
    p = pd.read_csv(C.OUT / "scorecard_by_period.csv")
    ws = wb.create_sheet("Scorecard")
    title(ws, "KPI scorecard by season period", "Ratings are formulas on the Settings tolerances. "
          "OTIF best/worst case bound the effect of unknown deliveries.")
    cols = ["Period", "Orders", "Delivered (known)", "Late", "Late rate", "Late rating", "Not OTIF", "OTIF %",
            "OTIF rating", "Not in full", "In-full rate", "In-full rating", "Median order-to-ship (hrs)",
            "Freight per unit ($)", "Unknown deliveries", "OTIF if unknowns on time", "OTIF if unknowns late"]
    header(ws, 4, cols, [18, 9, 11, 8, 9, 10, 9, 9, 10, 9, 9, 10, 12, 11, 11, 12, 12])
    for i, row in enumerate(p.itertuples(), 5):
        bold = row.period == "Season total"
        vals = {1: row.period, 2: row.orders, 3: row.delivery_known, 4: row.late_orders, 7: row.not_otif,
                10: row.not_in_full, 13: row.median_order_to_ship_hrs, 14: row.freight_per_unit,
                15: row.unknown_deliveries}
        for j, v in vals.items():
            ws.cell(row=i, column=j, value=v).font = Font(name=F, size=10, bold=bold,
                                                         color="0000FF" if j > 1 else "000000")
        ws.cell(row=i, column=5, value=f"=IFERROR(D{i}/C{i},0)")
        ws.cell(row=i, column=6, value=rating(f"E{i}", wilson_lo(f"D{i}", f"C{i}")[1:], "Settings!$B$5"))
        ws.cell(row=i, column=8, value=f"=IFERROR(1-G{i}/C{i},0)")
        ws.cell(row=i, column=9, value=rating(f"(1-H{i})", wilson_lo(f"G{i}", f"C{i}")[1:], "Settings!$B$6"))
        ws.cell(row=i, column=11, value=f"=IFERROR(1-J{i}/B{i},0)")
        ws.cell(row=i, column=12, value=rating(f"(1-K{i})", wilson_lo(f"J{i}", f"B{i}")[1:], "Settings!$B$7"))
        ws.cell(row=i, column=16, value=f"=IFERROR(1-G{i}/(C{i}+O{i}),0)")
        ws.cell(row=i, column=17, value=f"=IFERROR(1-(G{i}+O{i})/(C{i}+O{i}),0)")
        for j, fmt in [(2, INT), (3, INT), (4, INT), (5, PCT), (7, INT), (8, PCT), (10, INT), (11, PCT),
                       (13, "0.0"), (14, MONEY2), (15, INT), (16, PCT), (17, PCT)]:
            ws.cell(row=i, column=j).number_format = fmt
        for j in (5, 6, 8, 9, 11, 12, 16, 17):
            ws.cell(row=i, column=j).font = Font(name=F, size=10, bold=bold)
    for col in ("F", "I", "L"):
        status_format(ws, f"{col}5:{col}{4 + len(p)}")

    # ---------------------------------------------------------------- Action queue
    q = pd.read_csv(C.OUT / "action_queue_2026-12-18.csv")
    ws = wb.create_sheet("Action queue Dec 18")
    title(ws, "Morning action queue - Fri Dec 18, 2026 (promises due Sun Dec 20, gift-critical)",
          "Ranked by expected loss. EL = PD x loss if missed. Only orders where an action pays for itself are listed.")
    ws["A3"], ws["C3"] = "Total expected loss in queue", f"=SUM(K6:K{5 + len(q)})"
    ws["E3"], ws["G3"] = "Total action cost", f"=SUM(M6:M{5 + len(q)})"
    for c in ("A3", "E3"):
        ws[c].font = Font(name=F, bold=True, size=10)
    for c in ("C3", "G3"):
        ws[c].font, ws[c].number_format = Font(name=F, bold=True, size=10), MONEY
    cols = ["Order", "DC", "Category", "Carrier", "Speed", "Promised", "Order value ($)", "Status at D-2",
            "PD", "Loss if missed ($)", "Expected loss ($)", "Action", "Action cost ($)"]
    header(ws, 5, cols, [11, 6, 18, 17, 10, 11, 12, 13, 8, 12, 12, 11, 11])
    for i, row in enumerate(q.itertuples(), 6):
        cost = row.fix_cost if row.el_action in ("EXPEDITE", "REROUTE") else C.NOTICE_COST
        vals = [row.order_id, row.dc, row.category, row.carrier, row.ship_speed,
                pd.Timestamp(row.promised_date).to_pydatetime(), row.order_value, row.stage_at_decision,
                row.pd, row.loss_if_missed, f"=I{i}*J{i}", row.el_action, cost]
        for j, v in enumerate(vals, 1):
            c = ws.cell(row=i, column=j, value=v)
            c.font, c.border = BODY, THIN
        for j, fmt in [(6, "mmm d"), (7, MONEY2), (9, "0%"), (10, MONEY2), (11, MONEY2), (13, MONEY2)]:
            ws.cell(row=i, column=j).number_format = fmt
    ws.cell(row=7 + len(q), column=1, value=f"Action costs: notice ${C.NOTICE_COST:.2f}; expedite/reroute by "
            "category (see src/config.py). Loss if missed = 30% of order value + $4 contact cost + 15% x $150 "
            "future margin for gift-critical promises (assumptions).").font = NOTE

    # ---------------------------------------------------------------- Carriers
    c = pd.read_csv(C.OUT / "carrier_tender_rejection.csv")
    ws = wb.create_sheet("Carriers")
    title(ws, "Tender rejections by carrier", "A rejected tender = the carrier refused the load and it had to "
          "be re-offered to another carrier (usually 1-3 days lost).")
    header(ws, 4, ["Carrier", "Window", "Loads tendered", "Rejected", "Rejection rate", "Low (95%)", "Rating"],
           [18, 22, 13, 10, 13, 11, 10])
    for i, row in enumerate(c.itertuples(), 5):
        for j, v in enumerate([row.carrier, row.window, row.loads_tendered, row.rejected], 1):
            ws.cell(row=i, column=j, value=v).font = INPUT if j > 2 else BODY
        ws.cell(row=i, column=5, value=f"=IFERROR(D{i}/C{i},0)").number_format = PCT
        ws.cell(row=i, column=6, value=wilson_lo(f"D{i}", f"C{i}")).number_format = PCT
        ws.cell(row=i, column=7, value=rating(f"E{i}", f"F{i}", "Settings!$B$8"))
        for j in (5, 6, 7):
            ws.cell(row=i, column=j).font = BODY
    status_format(ws, f"G5:G{4 + len(c)}")

    # ---------------------------------------------------------------- Claims
    cl = pd.read_csv(C.OUT / "claims_by_category.csv")
    ws = wb.create_sheet("Claims")
    title(ws, "Claims by category", "Physical claims (damaged + shortage + lost) are rated against tolerance; "
          "late-delivery goodwill credits are a service cost shown separately.")
    cols = ["Category", "Shipments", "Damaged", "Shortage", "Lost", "Physical claims", "Physical claim rate",
            "Low (95%)", "Rating", "Late goodwill credits", "Claim value ($)", "Avg days to resolve"]
    header(ws, 4, cols, [20, 10, 9, 9, 8, 10, 11, 10, 9, 11, 12, 11])
    for i, row in enumerate(cl.itertuples(), 5):
        vals = {1: row.category, 2: row.shipments, 3: row.damaged, 4: row.shortage, 5: row.lost,
                10: row.late_goodwill, 11: row.claim_value, 12: row.avg_days_to_resolve}
        for j, v in vals.items():
            ws.cell(row=i, column=j, value=v).font = INPUT if j > 1 else BODY
        ws.cell(row=i, column=6, value=f"=C{i}+D{i}+E{i}")
        ws.cell(row=i, column=7, value=f"=IFERROR(F{i}/B{i},0)").number_format = "0.00%"
        ws.cell(row=i, column=8, value=wilson_lo(f"F{i}", f"B{i}")).number_format = "0.00%"
        ws.cell(row=i, column=9, value=rating(f"G{i}", f"H{i}", "Settings!$B$9"))
        ws.cell(row=i, column=11).number_format = MONEY
        for j in (6, 7, 8, 9):
            ws.cell(row=i, column=j).font = BODY
    status_format(ws, f"I5:I{4 + len(cl)}")

    # ---------------------------------------------------------------- Policies
    pol = pd.read_csv(C.OUT / "policy_comparison.csv")
    ws = wb.create_sheet("Policies")
    title(ws, "How to run the Christmas window: five policies compared (promises due Dec 7-24)",
          "Simulated outcomes from src/promise_risk.py, scored against the true outcomes, same random draws "
          "for every policy.")
    cols = ["Policy", "Setting", "Expedites", "Reroutes", "Notices", "Action spend ($)", "Late promises",
            "On-time rate", "Loss from missed promises ($)", "Total cost ($)", "Saving vs rule B ($)",
            "Promises rescued", "Spend per promise rescued ($)", "Actions on orders that were fine"]
    header(ws, 4, cols, [52, 11, 10, 10, 10, 13, 10, 10, 14, 12, 13, 11, 13, 13])
    for i, row in enumerate(pol.itertuples(), 5):
        vals = [row.policy, "" if pd.isna(row.setting) else row.setting, row.expedites, row.reroutes,
                row.notices, row.action_spend, row.late_promises, row.on_time_rate,
                row.loss_from_missed_promises, f"=F{i}+I{i}", f"=$J$6-J{i}", f"=$G$5-G{i}",
                f'=IF(L{i}>0,F{i}/L{i},"-")', row.wasted_actions_pct]
        for j, v in enumerate(vals, 1):
            c = ws.cell(row=i, column=j, value=v)
            c.font, c.border = (INPUT if j in (3, 4, 5, 6, 7, 8, 9, 14) else BODY), THIN
        for j, fmt in [(6, MONEY), (8, PCT), (9, MONEY), (10, MONEY), (11, MONEY), (13, MONEY), (14, "0%")]:
            ws.cell(row=i, column=j).number_format = fmt
    for i in (8, 9):  # D and E rows
        for j in range(1, 15):
            ws.cell(row=i, column=j).fill = PatternFill("solid", fgColor="EAF2FB")

    # ---------------------------------------------------------------- Data quality
    dq = pd.read_csv(C.OUT / "dq_log.csv")
    det = pd.read_csv(C.OUT / "detection_check_vs_answer_key.csv")
    ws = wb.create_sheet("Data quality")
    title(ws, "Data quality log and answer-key check", "Every rule that fired during cleaning; then whether "
          "it caught every defect that was planted on purpose.")
    header(ws, 4, ["Check", "Table", "Rows checked", "Rows flagged", "% flagged", "Action taken",
                   "Planted", "Caught", "Recall", "Flagged but not planted"], [26, 16, 12, 12, 10, 60, 9, 9, 9, 12])
    for i, (a, b) in enumerate(zip(dq.itertuples(), det.itertuples()), 5):
        vals = [a.check, a.table, a.rows_checked, a.rows_flagged, f"=IFERROR(D{i}/C{i},0)", a.action,
                b.planted, b.planted_and_flagged, f"=IFERROR(H{i}/G{i},0)", b.flagged_not_planted]
        for j, v in enumerate(vals, 1):
            c = ws.cell(row=i, column=j, value=v)
            c.font, c.border = BODY, THIN
        ws.cell(row=i, column=5).number_format = "0.00%"
        ws.cell(row=i, column=9).number_format = "0%"
    n = 5 + len(dq)
    ws.cell(row=n + 1, column=1, value="The 69 extra 'missing delivery scans' are real parcels lost in transit: "
            "the data cannot tell a lost parcel from a missed scan, so both are excluded from on-time KPIs "
            "and bounded on the Scorecard.").font = NOTE

    for sh in wb.worksheets:
        sh.sheet_view.showGridLines = False
    wb.save(C.OUT / "weekly_shipment_tracker.xlsx")
    print("saved", C.OUT / "weekly_shipment_tracker.xlsx")


if __name__ == "__main__":
    main()
