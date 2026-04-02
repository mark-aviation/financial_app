-- migrate_v5_to_v6.sql
-- Adds Goal Tracker tables: project_goals and goal_completions
-- Safe to run on existing data. MySQL 5.7 compatible.

USE expensis;

-- ── project_goals ─────────────────────────────────────────────────────────
-- One row per goal. Goals persist across all weeks.
CREATE TABLE IF NOT EXISTS project_goals (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    deadline_id INT          NOT NULL,
    user_id     INT          NOT NULL,
    goal_name   VARCHAR(300) NOT NULL,
    created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (deadline_id) REFERENCES deadlines(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id)     REFERENCES users(id)     ON DELETE CASCADE
);

SET @i = (SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema=DATABASE() AND table_name='project_goals' AND index_name='idx_goals_deadline');
SET @s = IF(@i=0,'CREATE INDEX idx_goals_deadline ON project_goals (deadline_id)','SELECT 1');
PREPARE st FROM @s; EXECUTE st; DEALLOCATE PREPARE st;

-- ── goal_completions ──────────────────────────────────────────────────────
-- One row per (goal × date). Upserted on checkbox toggle.
-- UNIQUE key prevents duplicate rows; use INSERT ... ON DUPLICATE KEY UPDATE.
CREATE TABLE IF NOT EXISTS goal_completions (
    id              INT  AUTO_INCREMENT PRIMARY KEY,
    goal_id         INT  NOT NULL,
    user_id         INT  NOT NULL,
    completion_date DATE NOT NULL,
    is_completed    TINYINT(1) NOT NULL DEFAULT 0,
    FOREIGN KEY (goal_id)  REFERENCES project_goals(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id)  REFERENCES users(id)         ON DELETE CASCADE,
    UNIQUE KEY uq_goal_date (goal_id, completion_date)
);

SET @i = (SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema=DATABASE() AND table_name='goal_completions' AND index_name='idx_completions_goal_date');
SET @s = IF(@i=0,'CREATE INDEX idx_completions_goal_date ON goal_completions (goal_id, completion_date)','SELECT 1');
PREPARE st FROM @s; EXECUTE st; DEALLOCATE PREPARE st;

SET @i = (SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema=DATABASE() AND table_name='goal_completions' AND index_name='idx_completions_user_date');
SET @s = IF(@i=0,'CREATE INDEX idx_completions_user_date ON goal_completions (user_id, completion_date)','SELECT 1');
PREPARE st FROM @s; EXECUTE st; DEALLOCATE PREPARE st;

-- ── Verify ────────────────────────────────────────────────────────────────
SELECT 'Migration v5->v6 complete.' AS status;
SHOW TABLES;
