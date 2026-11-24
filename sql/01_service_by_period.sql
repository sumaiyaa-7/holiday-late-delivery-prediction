-- Service KPIs by order period. Late/OTIF use only orders whose delivery is known.
SELECT period,
       COUNT(*)                                   AS orders,
       SUM(qty)                                   AS units_ordered,
       SUM(qty_shipped)                           AS units_shipped,
       SUM(delivery_known)                        AS delivery_known,
       SUM(CASE WHEN late = 1 THEN 1 ELSE 0 END)  AS late_orders,
       SUM(CASE WHEN delivery_known = 1 AND otif = 0 THEN 1 ELSE 0 END) AS not_otif,
       SUM(CASE WHEN in_full = 0 THEN 1 ELSE 0 END) AS not_in_full,
       ROUND(SUM(freight_cost) * 1.0 / SUM(qty_shipped), 2) AS freight_per_unit,
       ROUND(SUM(order_value), 0)                 AS order_value
FROM order_facts
GROUP BY period
ORDER BY period;
