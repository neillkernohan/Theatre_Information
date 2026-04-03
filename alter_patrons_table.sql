-- Add new columns to Patrons table to match updated CSV export
ALTER TABLE Patrons
    ADD COLUMN Home_Phone varchar(50) AFTER Notes,
    ADD COLUMN Cell_Phone varchar(50) AFTER Home_Phone,
    ADD COLUMN Work_Phone varchar(50) AFTER Cell_Phone,
    ADD COLUMN Created datetime AFTER Work_Phone,
    ADD COLUMN Last_Activity datetime AFTER Created,
    ADD COLUMN Updated datetime AFTER Last_Activity;

-- If columns already exist as date, change them to datetime:
-- ALTER TABLE Patrons
--     MODIFY COLUMN Created datetime,
--     MODIFY COLUMN Last_Activity datetime,
--     MODIFY COLUMN Updated datetime;
