-- Expensis Pro — v2 → v3 Migration
-- Run once against your expensis database.
-- All new columns are nullable so existing rows are unaffected.

ALTER TABLE deadlines
    ADD COLUMN estimated_cost  DECIMAL(12,2)            DEFAULT NULL,
    ADD COLUMN linked_wallet   VARCHAR(100)              DEFAULT NULL,
    ADD COLUMN priority_level  ENUM('High','Medium','Low') DEFAULT NULL,
    ADD COLUMN budget_status   VARCHAR(20)               DEFAULT NULL;

-- budget_status values:
--   NULL         → no budget assigned
--   'funded'     → wallet can fully cover this project
--   'at_risk'    → wallet covers it but leaves < 20% remaining
--   'unfunded'   → wallet cannot cover this project
