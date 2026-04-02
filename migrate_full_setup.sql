-- migrate_full_setup.sql
-- MySQL 5.7 compatible — no IF NOT EXISTS on ALTER TABLE ADD COLUMN
-- Run once against your expensis database.

USE expensis;

-- ─────────────────────────────────────────────────────────────────────────────
-- v2 → v3: Add columns to deadlines (skips each if already present)
-- ─────────────────────────────────────────────────────────────────────────────

-- priority_level
SET @col = (SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'deadlines' AND column_name = 'priority_level');
SET @sql = IF(@col = 0,
    'ALTER TABLE deadlines ADD COLUMN priority_level VARCHAR(20) NULL',
    'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- estimated_cost
SET @col = (SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'deadlines' AND column_name = 'estimated_cost');
SET @sql = IF(@col = 0,
    'ALTER TABLE deadlines ADD COLUMN estimated_cost DECIMAL(12,2) NULL',
    'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- project_name
SET @col = (SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'deadlines' AND column_name = 'project_name');
SET @sql = IF(@col = 0,
    'ALTER TABLE deadlines ADD COLUMN project_name VARCHAR(200) NULL',
    'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- ─────────────────────────────────────────────────────────────────────────────
-- v3 → v4: Remove old single-wallet columns if they exist
-- ─────────────────────────────────────────────────────────────────────────────

SET @col = (SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'deadlines' AND column_name = 'linked_wallet');
SET @sql = IF(@col > 0, 'ALTER TABLE deadlines DROP COLUMN linked_wallet', 'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

SET @col = (SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'deadlines' AND column_name = 'budget_status');
SET @sql = IF(@col > 0, 'ALTER TABLE deadlines DROP COLUMN budget_status', 'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- ─────────────────────────────────────────────────────────────────────────────
-- v3 → v4: Create project_wallet_allocations join table
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS project_wallet_allocations (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    deadline_id    INT            NOT NULL,
    wallet_name    VARCHAR(100)   NOT NULL,
    allocated_cost DECIMAL(12,2)  NOT NULL,
    FOREIGN KEY (deadline_id) REFERENCES deadlines(id) ON DELETE CASCADE
);

-- ─────────────────────────────────────────────────────────────────────────────
-- v4 → v5: Add performance index on expenses (user_id, date)
-- ─────────────────────────────────────────────────────────────────────────────

SET @idx = (SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema = DATABASE() AND table_name = 'expenses' AND index_name = 'idx_exp_user_date');
SET @sql = IF(@idx = 0,
    'ALTER TABLE expenses ADD INDEX idx_exp_user_date (user_id, date)',
    'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- ─────────────────────────────────────────────────────────────────────────────
-- Verify
-- ─────────────────────────────────────────────────────────────────────────────

SELECT 'Migration complete.' AS status;

SELECT table_name FROM information_schema.tables
WHERE table_schema = DATABASE()
ORDER BY table_name;
