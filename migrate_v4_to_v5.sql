-- migrate_v4_to_v5.sql
-- Adds a compound index on (user_id, date) for the expenses table.
-- Compatible with MySQL 5.7 and all MySQL 8.x versions.

-- Check if index already exists before creating (avoids duplicate key error)
SET @exists = (
    SELECT COUNT(*)
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
      AND table_name   = 'expenses'
      AND index_name   = 'idx_exp_user_date'
);

SET @sql = IF(
    @exists = 0,
    'ALTER TABLE expenses ADD INDEX idx_exp_user_date (user_id, date)',
    'SELECT ''Index idx_exp_user_date already exists, skipping.'''
);

PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
