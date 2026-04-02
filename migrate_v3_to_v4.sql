-- Expensis Pro — v3 → v4 Migration
-- Run once against your expensis database.
-- Switches project budgets from single-wallet column to a join table,
-- enabling multiple wallet allocations per project.

USE expensis;

-- 1. Remove the single-wallet columns added in v3
--    (estimated_cost and priority_level stay — they live on the deadline row)
ALTER TABLE deadlines
    DROP COLUMN IF EXISTS linked_wallet,
    DROP COLUMN IF EXISTS budget_status;

-- 2. New join table: one deadline → many wallet allocations
CREATE TABLE IF NOT EXISTS project_wallet_allocations (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    deadline_id    INT             NOT NULL,
    wallet_name    VARCHAR(100)    NOT NULL,
    allocated_cost DECIMAL(12, 2)  NOT NULL,
    FOREIGN KEY (deadline_id) REFERENCES deadlines(id) ON DELETE CASCADE
);
