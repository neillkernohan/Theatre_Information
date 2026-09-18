-- ============================================================
-- Updated stored procedures — 2026-09-18
-- Fix: Season Totals and Show Detail disagreed on performance
--      count / % of capacity / opening & closing dates.
--
--      Season Totals counted every Performance_date that had any
--      Ticket_Info row; Show Detail counted only dates with sold
--      seats but still took opening/closing from all rows.
--      Cancelled or phantom dates (all sales exchanged/refunded
--      away, nothing reserved) were therefore counted on one page
--      and not the other.
--
--      Both procedures now use the same rule: a performance is
--      "active" if it has net seats sold (> 0) or any Reserve row.
-- ============================================================

-- ============================================================
-- 1. GetSeasonShowTotals
-- ============================================================
DELIMITER $
DROP PROCEDURE IF EXISTS GetSeasonShowTotals$
CREATE PROCEDURE GetSeasonShowTotals(IN season_date DATE, IN shows_only INT)
BEGIN

    -- --------------------------------------------------------
    -- Sold: seated shows (DISTINCT Seat, net > 0, no Reserves)
    -- --------------------------------------------------------
    DROP TEMPORARY TABLE IF EXISTS tmp_sold_seated;
    CREATE TEMPORARY TABLE tmp_sold_seated AS
        SELECT
            TI.Show_name,
            TI.Performance_date,
            TI.Seat,
            SUBSTRING_INDEX(
                GROUP_CONCAT(TI.Person_type_edited ORDER BY TI.Item_ID DESC SEPARATOR ','),
                ',', 1
            ) AS Person_type_edited
        FROM Theatre_Information.Ticket_Info TI
        WHERE TI.Season = season_date
          AND TI.Transaction_type != 'Reserve'
          AND TI.Seat IS NOT NULL AND TI.Seat != ''
        GROUP BY TI.Show_name, TI.Performance_date, TI.Seat
        HAVING SUM(TI.Item_count) > 0;

    -- --------------------------------------------------------
    -- Sold: GA shows (no seat, SUM Item_count, no Reserves)
    -- --------------------------------------------------------
    DROP TEMPORARY TABLE IF EXISTS tmp_sold_ga;
    CREATE TEMPORARY TABLE tmp_sold_ga AS
        SELECT
            TI.Show_name,
            TI.Person_type_edited,
            SUM(TI.Item_count) AS Ticket_Count
        FROM Theatre_Information.Ticket_Info TI
        WHERE TI.Season = season_date
          AND TI.Transaction_type != 'Reserve'
          AND (TI.Seat IS NULL OR TI.Seat = '')
        GROUP BY TI.Show_name, TI.Person_type_edited
        HAVING SUM(TI.Item_count) > 0;

    -- --------------------------------------------------------
    -- Reserved: Reserve rows not already in sold set
    -- --------------------------------------------------------
    DROP TEMPORARY TABLE IF EXISTS tmp_reserved;
    CREATE TEMPORARY TABLE tmp_reserved AS
        SELECT
            TI.Show_name,
            TI.Performance_date,
            TI.Seat,
            SUBSTRING_INDEX(
                GROUP_CONCAT(TI.Person_type_edited ORDER BY TI.Item_ID DESC SEPARATOR ','),
                ',', 1
            ) AS Person_type_edited
        FROM Theatre_Information.Ticket_Info TI
        WHERE TI.Season = season_date
          AND TI.Transaction_type = 'Reserve'
          AND TI.Seat IS NOT NULL AND TI.Seat != ''
          AND NOT EXISTS (
              SELECT 1 FROM tmp_sold_seated s
              WHERE s.Show_name = TI.Show_name
                AND s.Performance_date = TI.Performance_date
                AND s.Seat = TI.Seat
          )
        GROUP BY TI.Show_name, TI.Performance_date, TI.Seat;

    -- --------------------------------------------------------
    -- Active performances: dates with net seats sold or held.
    -- Cancelled/phantom dates (everything exchanged or refunded
    -- away, nothing reserved) are excluded from performance
    -- counts, opening dates and % of capacity.
    -- Same rule as GetShowDetailData.
    -- --------------------------------------------------------
    DROP TEMPORARY TABLE IF EXISTS tmp_perfs;
    CREATE TEMPORARY TABLE tmp_perfs AS
        SELECT TI.Show_name, TI.Performance_date
        FROM Theatre_Information.Ticket_Info TI
        WHERE TI.Season = season_date
        GROUP BY TI.Show_name, TI.Performance_date
        HAVING SUM(CASE WHEN TI.Transaction_type != 'Reserve' THEN TI.Item_count ELSE 0 END) > 0
            OR SUM(TI.Transaction_type = 'Reserve') > 0;

    -- --------------------------------------------------------
    -- Final result: one row per show, ordered by opening date
    -- --------------------------------------------------------
    SELECT
        show_agg.Show_name,
        opening.Opening_Date,
        COALESCE(show_agg.Regular_Sold, 0)                                       AS Regular_Sold,
        COALESCE(show_agg.Senior_Sold, 0)                                        AS Senior_Sold,
        COALESCE(show_agg.Youth_Sold, 0)                                         AS Youth_Sold,
        COALESCE(show_agg.Total_Sold, 0)                                         AS Total_Sold,
        COALESCE(rev.Ticket_Revenue, 0)                                          AS Ticket_Revenue,
        COALESCE(res.Regular_Reserved, 0)                                        AS Regular_Reserved,
        COALESCE(res.Senior_Reserved, 0)                                         AS Senior_Reserved,
        COALESCE(res.Youth_Reserved, 0)                                          AS Youth_Reserved,
        COALESCE(show_agg.Total_Sold, 0) + COALESCE(res.Total_Reserved, 0)      AS Total_Booked,
        ROUND(
            (COALESCE(show_agg.Total_Sold, 0) + COALESCE(res.Total_Reserved, 0))
            / (opening.Perf_Count * 154) * 100
        , 1)                                                                     AS Pct_Capacity,
        COALESCE(fees.Per_Item_Fees, 0)                                          AS Per_Item_Fees,
        COALESCE(exp.Production_costs, 0)                                        AS Production_Costs,
        COALESCE(exp.Rights, 0)                                                  AS Rights,
        COALESCE(rev.Ticket_Revenue, 0)
            - COALESCE(fees.Per_Item_Fees, 0)
            - COALESCE(exp.Production_costs, 0)
            - COALESCE(exp.Rights, 0)                                            AS Net_Income
    FROM (
        SELECT Show_name,
               SUM(Regular_Sold) AS Regular_Sold,
               SUM(Senior_Sold)  AS Senior_Sold,
               SUM(Youth_Sold)   AS Youth_Sold,
               SUM(Total_Sold)   AS Total_Sold
        FROM (
            SELECT Show_name,
                   SUM(CASE WHEN Person_type_edited = 'Regular' THEN 1 ELSE 0 END) AS Regular_Sold,
                   SUM(CASE WHEN Person_type_edited = 'Senior'  THEN 1 ELSE 0 END) AS Senior_Sold,
                   SUM(CASE WHEN Person_type_edited = 'Student' THEN 1 ELSE 0 END) AS Youth_Sold,
                   COUNT(*)                                                         AS Total_Sold
            FROM tmp_sold_seated
            GROUP BY Show_name
            UNION ALL
            SELECT Show_name,
                   SUM(CASE WHEN Person_type_edited = 'Regular' THEN Ticket_Count ELSE 0 END) AS Regular_Sold,
                   SUM(CASE WHEN Person_type_edited = 'Senior'  THEN Ticket_Count ELSE 0 END) AS Senior_Sold,
                   SUM(CASE WHEN Person_type_edited = 'Student' THEN Ticket_Count ELSE 0 END) AS Youth_Sold,
                   SUM(Ticket_Count)                                                           AS Total_Sold
            FROM tmp_sold_ga
            GROUP BY Show_name
        ) combined
        GROUP BY Show_name
    ) show_agg
    LEFT JOIN (
        SELECT TI.Show_name, SUM(TI.Amount) AS Ticket_Revenue
        FROM Theatre_Information.Ticket_Info TI
        WHERE TI.Season = season_date
          AND TI.Transaction_type != 'Reserve'
        GROUP BY TI.Show_name
    ) rev ON show_agg.Show_name = rev.Show_name
    LEFT JOIN (
        SELECT Show_name,
               SUM(CASE WHEN Person_type_edited = 'Regular' THEN 1 ELSE 0 END) AS Regular_Reserved,
               SUM(CASE WHEN Person_type_edited = 'Senior'  THEN 1 ELSE 0 END) AS Senior_Reserved,
               SUM(CASE WHEN Person_type_edited = 'Student' THEN 1 ELSE 0 END) AS Youth_Reserved,
               COUNT(*)                                                         AS Total_Reserved
        FROM tmp_reserved
        GROUP BY Show_name
    ) res ON show_agg.Show_name = res.Show_name
    JOIN (
        SELECT Show_name,
               MIN(Performance_date) AS Opening_Date,
               COUNT(*)              AS Perf_Count
        FROM tmp_perfs
        GROUP BY Show_name
    ) opening ON show_agg.Show_name = opening.Show_name
    LEFT JOIN (
        SELECT TI.Show_name, SUM(TI.Per_item_fee) AS Per_Item_Fees
        FROM Theatre_Information.Ticket_Info TI
        WHERE TI.Season = season_date
          AND TI.Transaction_type != 'Reserve'
        GROUP BY TI.Show_name
    ) fees ON show_agg.Show_name = fees.Show_name
    LEFT JOIN (
        SELECT e1.Show_name, e1.Production_costs, e1.Rights
        FROM Theatre_Information.Expenses e1
        INNER JOIN (
            SELECT Show_name, MAX(Update_date) AS Latest
            FROM Theatre_Information.Expenses
            GROUP BY Show_name
        ) e2 ON e1.Show_name = e2.Show_name AND e1.Update_date = e2.Latest
    ) exp ON show_agg.Show_name = exp.Show_name
    LEFT JOIN Theatre_Information.Show_Types ST
        ON show_agg.Show_name = ST.Show_name
    WHERE shows_only = 0 OR ST.Show_type != 'Special'
    ORDER BY opening.Opening_Date;

    DROP TEMPORARY TABLE IF EXISTS tmp_sold_seated;
    DROP TEMPORARY TABLE IF EXISTS tmp_sold_ga;
    DROP TEMPORARY TABLE IF EXISTS tmp_reserved;
    DROP TEMPORARY TABLE IF EXISTS tmp_perfs;

END$
DELIMITER ;

-- ============================================================
-- 2. GetShowDetailData
-- ============================================================
DELIMITER $
DROP PROCEDURE IF EXISTS GetShowDetailData$
CREATE PROCEDURE GetShowDetailData(IN ShowName VARCHAR(256))
BEGIN

    -- --------------------------------------------------------
    -- Occupied seats for this show (current state)
    -- --------------------------------------------------------
    DROP TEMPORARY TABLE IF EXISTS tmp_detail_seats;
    CREATE TEMPORARY TABLE tmp_detail_seats AS
        SELECT Performance_date, Seat,
               SUBSTRING_INDEX(
                   GROUP_CONCAT(Person_type_edited ORDER BY Item_ID DESC SEPARATOR ','),
                   ',', 1
               ) AS Person_type_edited
        FROM Theatre_Information.Ticket_Info
        WHERE Show_name = ShowName
          AND Transaction_type != 'Reserve'
          AND Seat IS NOT NULL AND Seat != ''
        GROUP BY Performance_date, Seat
        HAVING SUM(Item_count) > 0;

    -- --------------------------------------------------------
    -- Reserved seats not already sold
    -- --------------------------------------------------------
    DROP TEMPORARY TABLE IF EXISTS tmp_detail_reserved;
    CREATE TEMPORARY TABLE tmp_detail_reserved AS
        SELECT Performance_date, Seat
        FROM Theatre_Information.Ticket_Info
        WHERE Show_name = ShowName
          AND Transaction_type = 'Reserve'
          AND Seat IS NOT NULL AND Seat != ''
          AND NOT EXISTS (
              SELECT 1 FROM tmp_detail_seats s
              WHERE s.Performance_date = Ticket_Info.Performance_date
                AND s.Seat = Ticket_Info.Seat
          )
        GROUP BY Performance_date, Seat;

    -- Pre-aggregate reserved per performance
    DROP TEMPORARY TABLE IF EXISTS tmp_detail_res_agg;
    CREATE TEMPORARY TABLE tmp_detail_res_agg AS
        SELECT Performance_date, COUNT(*) AS Reserved
        FROM tmp_detail_reserved
        GROUP BY Performance_date;

    SELECT COUNT(*) INTO @total_reserved FROM tmp_detail_reserved;

    -- --------------------------------------------------------
    -- Active performances: dates with net seats sold or held.
    -- Cancelled/phantom dates (everything exchanged or refunded
    -- away, nothing reserved) are excluded from performance
    -- counts, opening/closing dates and % of capacity.
    -- Same rule as GetSeasonShowTotals.
    -- --------------------------------------------------------
    DROP TEMPORARY TABLE IF EXISTS tmp_detail_perfs;
    CREATE TEMPORARY TABLE tmp_detail_perfs AS
        SELECT Performance_date
        FROM Theatre_Information.Ticket_Info
        WHERE Show_name = ShowName
        GROUP BY Performance_date
        HAVING SUM(CASE WHEN Transaction_type != 'Reserve' THEN Item_count ELSE 0 END) > 0
            OR SUM(Transaction_type = 'Reserve') > 0;

    -- A temp table can only be referenced once per statement,
    -- so pull the summary values into variables.
    SELECT MIN(Performance_date), MAX(Performance_date), COUNT(*)
      INTO @opening_date, @closing_date, @perf_count
    FROM tmp_detail_perfs;

    -- --------------------------------------------------------
    -- Result 0: Per-performance tickets (Regular/Senior/Youth/Total/Reserved)
    -- One row per active performance, even if nothing is sold yet.
    -- --------------------------------------------------------
    SELECT
        CASE
            WHEN TIME(p.Performance_date) = '13:30:00' THEN CONCAT(DATE_FORMAT(p.Performance_date, '%W, %M %e'), ' Matinee')
            WHEN TIME(p.Performance_date) = '19:30:00' THEN CONCAT(DATE_FORMAT(p.Performance_date, '%W, %M %e'), ' Evening')
            ELSE DATE_FORMAT(p.Performance_date, '%W, %M %e, %Y')
        END AS Perf_Label,
        SUM(CASE WHEN s.Person_type_edited = 'Regular' THEN 1 ELSE 0 END) AS Regular,
        SUM(CASE WHEN s.Person_type_edited = 'Senior'  THEN 1 ELSE 0 END) AS Senior,
        SUM(CASE WHEN s.Person_type_edited = 'Student' THEN 1 ELSE 0 END) AS Youth,
        COUNT(s.Seat)                                                       AS Total_Sold,
        COALESCE(r.Reserved, 0)                                            AS Reserved
    FROM tmp_detail_perfs p
    LEFT JOIN tmp_detail_seats s   ON s.Performance_date = p.Performance_date
    LEFT JOIN tmp_detail_res_agg r ON r.Performance_date = p.Performance_date
    GROUP BY p.Performance_date, r.Reserved
    ORDER BY p.Performance_date;

    -- --------------------------------------------------------
    -- Result 1: Overall totals + performance count
    -- --------------------------------------------------------
    SELECT
        SUM(CASE WHEN Person_type_edited = 'Regular' THEN 1 ELSE 0 END) AS Regular,
        SUM(CASE WHEN Person_type_edited = 'Senior'  THEN 1 ELSE 0 END) AS Senior,
        SUM(CASE WHEN Person_type_edited = 'Student' THEN 1 ELSE 0 END) AS Youth,
        COUNT(*)                                                          AS Total_Sold,
        @total_reserved                                                   AS Reserved,
        COUNT(*) + @total_reserved                                        AS Total_Booked,
        @perf_count                                                       AS Perf_Count
    FROM tmp_detail_seats;

    -- --------------------------------------------------------
    -- Result 2: Per-performance revenue (sold + reserved)
    -- --------------------------------------------------------
    SELECT
        CASE
            WHEN TIME(TI.Performance_date) = '13:30:00' THEN CONCAT(DATE_FORMAT(TI.Performance_date, '%W, %M %e'), ' Matinee')
            WHEN TIME(TI.Performance_date) = '19:30:00' THEN CONCAT(DATE_FORMAT(TI.Performance_date, '%W, %M %e'), ' Evening')
            ELSE DATE_FORMAT(TI.Performance_date, '%W, %M %e, %Y')
        END AS Perf_Label,
        SUM(CASE WHEN TI.Transaction_type != 'Reserve' THEN TI.Amount         ELSE 0 END) AS Revenue,
        SUM(CASE WHEN TI.Transaction_type =  'Reserve' THEN TI.Reserve_amount ELSE 0 END) AS Reserve_Revenue
    FROM Theatre_Information.Ticket_Info TI
    JOIN tmp_detail_perfs p ON p.Performance_date = TI.Performance_date
    WHERE TI.Show_name = ShowName
    GROUP BY TI.Performance_date
    ORDER BY TI.Performance_date;

    -- --------------------------------------------------------
    -- Result 3: Financial summary
    -- --------------------------------------------------------
    SELECT
        SUM(TI.Amount)                        AS Ticket_Revenue,
        SUM(TI.Per_item_fee)                  AS Per_Item_Fees,
        COALESCE(exp.Production_costs, 0)     AS Production_Costs,
        COALESCE(exp.Rights, 0)               AS Rights,
        SUM(TI.Amount)
            - SUM(TI.Per_item_fee)
            - COALESCE(exp.Production_costs, 0)
            - COALESCE(exp.Rights, 0)         AS Net_Income
    FROM Theatre_Information.Ticket_Info TI
    LEFT JOIN (
        SELECT e1.Show_name, e1.Production_costs, e1.Rights
        FROM Theatre_Information.Expenses e1
        INNER JOIN (
            SELECT Show_name, MAX(Update_date) AS Latest
            FROM Theatre_Information.Expenses
            GROUP BY Show_name
        ) e2 ON e1.Show_name = e2.Show_name AND e1.Update_date = e2.Latest
    ) exp ON TI.Show_name = exp.Show_name
    WHERE TI.Show_name = ShowName
      AND TI.Transaction_type != 'Reserve'
    GROUP BY exp.Production_costs, exp.Rights;

    -- --------------------------------------------------------
    -- Result 4: Show type, season, opening/closing dates
    -- --------------------------------------------------------
    SELECT
        COALESCE(ST.Show_type, 'Unknown') AS Show_type,
        TI.Season,
        CAST(@opening_date AS DATETIME)    AS Opening_Date,
        CAST(@closing_date AS DATETIME)    AS Closing_Date
    FROM Theatre_Information.Ticket_Info TI
    LEFT JOIN Theatre_Information.Show_Types ST ON TI.Show_name = ST.Show_name
    WHERE TI.Show_name = ShowName
    GROUP BY ST.Show_type, TI.Season;

    -- --------------------------------------------------------
    -- Determine show type for ranking queries
    -- --------------------------------------------------------
    SELECT ST.Show_type INTO @show_type
    FROM Theatre_Information.Show_Types ST
    WHERE ST.Show_name = ShowName
    LIMIT 1;

    -- --------------------------------------------------------
    -- Result 5: Ranked shows by tickets (same show type, all seasons)
    -- --------------------------------------------------------
    WITH correct_tickets AS (
        SELECT Show_name, COUNT(*) AS Tickets
        FROM (
            SELECT TI.Show_name, TI.Performance_date, TI.Seat
            FROM Theatre_Information.Ticket_Info TI
            WHERE TI.Transaction_type != 'Reserve'
              AND TI.Seat IS NOT NULL AND TI.Seat != ''
            GROUP BY TI.Show_name, TI.Performance_date, TI.Seat
            HAVING SUM(TI.Item_count) > 0
        ) seated
        GROUP BY Show_name
        UNION ALL
        SELECT Show_name, SUM(Item_count) AS Tickets
        FROM Theatre_Information.Ticket_Info
        WHERE Transaction_type != 'Reserve'
          AND (Seat IS NULL OR Seat = '')
        GROUP BY Show_name
        HAVING SUM(Item_count) > 0
    ),
    show_totals AS (
        SELECT Show_name, SUM(Tickets) AS Total_Tickets
        FROM correct_tickets
        GROUP BY Show_name
    )
    SELECT st.Show_name, st.Total_Tickets,
           RANK() OVER (ORDER BY st.Total_Tickets DESC) AS Rank_Num
    FROM show_totals st
    JOIN Theatre_Information.Show_Types stype ON st.Show_name = stype.Show_name
    WHERE stype.Show_type = @show_type
    ORDER BY st.Total_Tickets DESC;

    -- --------------------------------------------------------
    -- Result 6: Ranked shows by revenue (same show type, all seasons)
    -- --------------------------------------------------------
    WITH rev_totals AS (
        SELECT TI.Show_name, SUM(TI.Amount) AS Revenue
        FROM Theatre_Information.Ticket_Info TI
        WHERE TI.Transaction_type != 'Reserve'
        GROUP BY TI.Show_name
    )
    SELECT rt.Show_name, rt.Revenue,
           RANK() OVER (ORDER BY rt.Revenue DESC) AS Rank_Num
    FROM rev_totals rt
    JOIN Theatre_Information.Show_Types stype ON rt.Show_name = stype.Show_name
    WHERE stype.Show_type = @show_type
    ORDER BY rt.Revenue DESC;

    -- --------------------------------------------------------
    -- Result 7: Previous same-type show comparison
    -- Tickets and revenue for the previous show of the same type,
    -- measured at the same days-before/after-opening offset as today.
    -- Uses correct seated counting up to the cutoff purchase date.
    -- --------------------------------------------------------
    SET @this_opening = @opening_date;

    SET @days_diff = DATEDIFF(@this_opening, CURDATE());  -- negative = show has opened

    -- Previous show of same type (most recent before this one)
    SELECT TI.Show_name INTO @prev_show
    FROM Theatre_Information.Ticket_Info TI
    JOIN Theatre_Information.Show_Types ST ON TI.Show_name = ST.Show_name
    WHERE ST.Show_type = @show_type
      AND TI.Performance_date < @this_opening
    GROUP BY TI.Show_name
    ORDER BY MAX(TI.Performance_date) DESC
    LIMIT 1;

    -- Opening of the previous show, using the same active-performance rule
    SELECT MIN(Performance_date) INTO @prev_opening
    FROM (
        SELECT Performance_date
        FROM Theatre_Information.Ticket_Info
        WHERE Show_name = @prev_show
        GROUP BY Performance_date
        HAVING SUM(CASE WHEN Transaction_type != 'Reserve' THEN Item_count ELSE 0 END) > 0
            OR SUM(Transaction_type = 'Reserve') > 0
    ) prev_perfs;

    -- Cutoff: same days-before-opening offset applied to previous show
    SET @prev_cutoff = DATE_SUB(@prev_opening, INTERVAL @days_diff DAY);

    SELECT
        @prev_show                                                     AS Prev_Show,
        @days_diff                                                     AS Days_Diff,
        (
            SELECT COUNT(*)
            FROM (
                SELECT Seat, Performance_date
                FROM Theatre_Information.Ticket_Info
                WHERE Show_name = @prev_show
                  AND Transaction_type != 'Reserve'
                  AND Seat IS NOT NULL AND Seat != ''
                  AND DATE(Purchase_date) < @prev_cutoff
                GROUP BY Seat, Performance_date
                HAVING SUM(Item_count) > 0
            ) prev_seated
        )                                                              AS Prev_Tickets,
        (
            SELECT SUM(Amount)
            FROM Theatre_Information.Ticket_Info
            WHERE Show_name = @prev_show
              AND Transaction_type != 'Reserve'
              AND DATE(Purchase_date) < @prev_cutoff
        )                                                              AS Prev_Revenue;

    -- --------------------------------------------------------
    -- Result 8: Overall ranking by tickets (all show types)
    -- --------------------------------------------------------
    WITH correct_tickets_all AS (
        SELECT Show_name, COUNT(*) AS Tickets
        FROM (
            SELECT TI.Show_name, TI.Performance_date, TI.Seat
            FROM Theatre_Information.Ticket_Info TI
            WHERE TI.Transaction_type != 'Reserve'
              AND TI.Seat IS NOT NULL AND TI.Seat != ''
            GROUP BY TI.Show_name, TI.Performance_date, TI.Seat
            HAVING SUM(TI.Item_count) > 0
        ) seated
        GROUP BY Show_name
        UNION ALL
        SELECT Show_name, SUM(Item_count) AS Tickets
        FROM Theatre_Information.Ticket_Info
        WHERE Transaction_type != 'Reserve'
          AND (Seat IS NULL OR Seat = '')
        GROUP BY Show_name
        HAVING SUM(Item_count) > 0
    ),
    all_totals AS (
        SELECT Show_name, SUM(Tickets) AS Total_Tickets
        FROM correct_tickets_all
        GROUP BY Show_name
    )
    SELECT at.Show_name,
           COALESCE(stype.Show_type, 'Unknown') AS Show_type,
           at.Total_Tickets,
           RANK() OVER (ORDER BY at.Total_Tickets DESC) AS Rank_Num
    FROM all_totals at
    LEFT JOIN Theatre_Information.Show_Types stype ON at.Show_name = stype.Show_name
    ORDER BY at.Total_Tickets DESC;

    -- --------------------------------------------------------
    -- Result 9: Overall ranking by revenue (all show types)
    -- --------------------------------------------------------
    WITH all_rev AS (
        SELECT TI.Show_name, SUM(TI.Amount) AS Revenue
        FROM Theatre_Information.Ticket_Info TI
        WHERE TI.Transaction_type != 'Reserve'
        GROUP BY TI.Show_name
    )
    SELECT ar.Show_name,
           COALESCE(stype.Show_type, 'Unknown') AS Show_type,
           ar.Revenue,
           RANK() OVER (ORDER BY ar.Revenue DESC) AS Rank_Num
    FROM all_rev ar
    LEFT JOIN Theatre_Information.Show_Types stype ON ar.Show_name = stype.Show_name
    ORDER BY ar.Revenue DESC;

    DROP TEMPORARY TABLE IF EXISTS tmp_detail_seats;
    DROP TEMPORARY TABLE IF EXISTS tmp_detail_reserved;
    DROP TEMPORARY TABLE IF EXISTS tmp_detail_res_agg;
    DROP TEMPORARY TABLE IF EXISTS tmp_detail_perfs;

END$
DELIMITER ;
