-- Tender rejection by the carrier first offered the load, peak window vs rest.
SELECT original_carrier AS carrier,
       CASE WHEN DATE(packed_ts) BETWEEN '2026-11-27' AND '2026-12-02'
            THEN 'Peak (Nov 27-Dec 2)' ELSE 'Rest of season' END AS window,
       COUNT(*)              AS loads_tendered,
       SUM(tender_rejected)  AS rejected
FROM order_facts
GROUP BY 1, 2
ORDER BY 1, 2;
