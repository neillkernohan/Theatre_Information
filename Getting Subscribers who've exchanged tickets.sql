WITH RankedExchanges AS (
  SELECT *,
         ROW_NUMBER() OVER (PARTITION BY Customer, Performance_date ORDER BY Item_ID) AS rn
  FROM Theatre_Information.Ticket_Info
  WHERE Transaction_type = 'Exchange'
    AND Item_count = 1
    AND Show_name = 'Noises Off'
    AND Subscription_package <> ''
    AND Seat <> ''
)
SELECT 
  Item_ID,
  Customer,
  Performance_date,
  Seat,
  CASE 
    WHEN EXISTS (
      SELECT 1
      FROM Theatre_Information.Ticket_Info TI2
      WHERE TI2.Customer = RankedExchanges.Customer
        AND TI2.Subscription_package <> ''
        AND TI2.Performance_date > '2025-07-01'
    ) THEN 'Yes' ELSE 'No'
  END AS HasFutureSubscription
FROM RankedExchanges
WHERE rn = 1
ORDER BY Performance_date, Seat;
