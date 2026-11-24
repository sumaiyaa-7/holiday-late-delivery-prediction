-- Weekly shipment tracker (week = Monday of order week).
SELECT week_start,
       COUNT(*)                                   AS orders,
       SUM(CASE WHEN ship_date IS NOT NULL THEN 1 ELSE 0 END) AS shipped,
       SUM(delivery_known)                        AS delivered,
       SUM(CASE WHEN late = 1 THEN 1 ELSE 0 END)  AS late_orders,
       SUM(CASE WHEN delivery_known = 1 AND otif = 0 THEN 1 ELSE 0 END) AS not_otif,
       SUM(CASE WHEN in_full = 0 THEN 1 ELSE 0 END) AS not_in_full,
       SUM(tender_rejected)                       AS tender_rejections,
       ROUND(SUM(freight_cost), 0)                AS freight_cost,
       ROUND(SUM(freight_cost) * 1.0 / SUM(qty_shipped), 2) AS freight_per_unit,
       SUM(shipped_imputed)                       AS imputed_ship_scans,
       SUM(1 - delivery_known)                    AS unknown_deliveries
FROM order_facts
GROUP BY week_start
ORDER BY week_start;
