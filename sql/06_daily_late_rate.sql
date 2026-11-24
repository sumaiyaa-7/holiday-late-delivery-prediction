-- Daily late-delivery rate by promised date (input to the p-chart).
SELECT promised_date,
       SUM(delivery_known)                        AS delivered,
       SUM(CASE WHEN late = 1 THEN 1 ELSE 0 END)  AS late_orders
FROM order_facts
WHERE promised_date <= '2026-12-24'
GROUP BY promised_date
ORDER BY promised_date;
