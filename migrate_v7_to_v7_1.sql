-- migrate_v7_to_v7_1.sql
-- Adds:
--   1. is_transfer flag on income table (wallet transfer tracking)
--   2. fixed_bills table (monthly recurring obligations: rent, utilities, etc.)
-- Safe to re-run. MySQL 5.7 compatible.

USE expensis;

-- ── 1. is_transfer column on income ───────────────────────────────────────
SET @col = (SELECT COUNT(*) FROM information_schema.columns
    WHERE table_schema = DATABASE() AND table_name = 'income' AND column_name = 'is_transfer');
SET @sql = IF(@col = 0,
    'ALTER TABLE income ADD COLUMN is_transfer TINYINT(1) NOT NULL DEFAULT 0',
    'SELECT 1');
PREPARE s FROM @sql; EXECUTE s; DEALLOCATE PREPARE s;

-- ── 2. fixed_bills table ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fixed_bills (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    user_id    INT             NOT NULL,
    name       VARCHAR(200)    NOT NULL,
    amount     DECIMAL(12, 2)  NOT NULL DEFAULT 0,
    wallet     VARCHAR(100)    NOT NULL DEFAULT '',
    created_at DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

SET @i = (SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema=DATABASE() AND table_name='fixed_bills' AND index_name='idx_fixed_bills_user');
SET @s = IF(@i=0,'CREATE INDEX idx_fixed_bills_user ON fixed_bills (user_id)','SELECT 1');
PREPARE st FROM @s; EXECUTE st; DEALLOCATE PREPARE st;

SELECT 'Migration v7->v7.1 complete.' AS status;
