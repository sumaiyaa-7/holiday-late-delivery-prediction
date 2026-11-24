-- December promises: late rate by DC x category (input to the chi-square test).
SELECT dc, category,
       SUM(delivery_known)                        AS delivered,
       SUM(CASE WHEN late = 1 THEN 1 ELSE 0 END)  AS late_orders
FROM order_facts
WHERE promised_date BETWEEN '2026-12-01' AND '2026-12-24'
GROUP BY dc, category
ORDER BY dc, category;
