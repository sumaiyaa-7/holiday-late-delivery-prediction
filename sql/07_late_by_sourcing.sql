-- Drill-down for the hotspot: DC x category x sourcing, December promises.
SELECT dc, category, sourcing,
       SUM(delivery_known)                        AS delivered,
       SUM(CASE WHEN late = 1 THEN 1 ELSE 0 END)  AS late_orders,
       ROUND(AVG(JULIANDAY(allocated_ts) - JULIANDAY(order_ts)), 2) AS avg_days_to_allocate
FROM order_facts
WHERE promised_date BETWEEN '2026-12-01' AND '2026-12-24' AND category = 'Toys'
GROUP BY dc, category, sourcing;
