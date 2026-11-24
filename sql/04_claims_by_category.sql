-- Claims per category: rate is claims / shipments, value in dollars.
WITH c AS (
  SELECT f.category, cl.claim_type, cl.claim_value,
         JULIANDAY(cl.resolved_date) - JULIANDAY(cl.filed_date) AS days_to_resolve
  FROM claims cl JOIN order_facts f USING (shipment_id)
)
SELECT f.category,
       (SELECT COUNT(*) FROM order_facts x WHERE x.category = f.category) AS shipments,
       COUNT(c.claim_type)                                         AS claims,
       SUM(CASE WHEN c.claim_type = 'DAMAGED' THEN 1 ELSE 0 END)   AS damaged,
       SUM(CASE WHEN c.claim_type = 'SHORTAGE' THEN 1 ELSE 0 END)  AS shortage,
       SUM(CASE WHEN c.claim_type = 'LOST' THEN 1 ELSE 0 END)      AS lost,
       SUM(CASE WHEN c.claim_type = 'LATE_GOODWILL' THEN 1 ELSE 0 END) AS late_goodwill,
       ROUND(SUM(c.claim_value), 0)                                AS claim_value,
       ROUND(AVG(c.days_to_resolve), 1)                            AS avg_days_to_resolve
FROM (SELECT DISTINCT category FROM order_facts) f
LEFT JOIN c ON c.category = f.category
GROUP BY f.category
ORDER BY claims * 1.0 / shipments DESC;
