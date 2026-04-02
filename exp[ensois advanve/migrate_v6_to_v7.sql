-- migrate_v6_to_v7.sql
-- Adds: financial_profile, loans, credit_cards, planned_purchases
-- MySQL 5.7 compatible. Safe to re-run.

USE expensis;

-- ── financial_profile ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS financial_profile (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    user_id        INT             NOT NULL UNIQUE,
    monthly_salary DECIMAL(12, 2)  NOT NULL DEFAULT 0,
    updated_at     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                   ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- ── loans ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS loans (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    user_id          INT             NOT NULL,
    loan_name        VARCHAR(200)    NOT NULL,
    bank             VARCHAR(200)    NOT NULL DEFAULT '',
    total_amount     DECIMAL(12, 2)  NOT NULL DEFAULT 0,
    monthly_payment  DECIMAL(12, 2)  NOT NULL DEFAULT 0,
    months_remaining INT             NOT NULL DEFAULT 0,
    interest_rate    DECIMAL(5, 2)   NOT NULL DEFAULT 0,
    created_at       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

SET @i = (SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema=DATABASE() AND table_name='loans' AND index_name='idx_loans_user');
SET @s = IF(@i=0,'CREATE INDEX idx_loans_user ON loans (user_id)','SELECT 1');
PREPARE st FROM @s; EXECUTE st; DEALLOCATE PREPARE st;

-- ── credit_cards ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS credit_cards (
    id                   INT AUTO_INCREMENT PRIMARY KEY,
    user_id              INT             NOT NULL,
    card_name            VARCHAR(200)    NOT NULL,
    bank                 VARCHAR(200)    NOT NULL DEFAULT '',
    credit_limit         DECIMAL(12, 2)  NOT NULL DEFAULT 0,
    current_balance      DECIMAL(12, 2)  NOT NULL DEFAULT 0,
    minimum_payment_pct  DECIMAL(5, 2)   NOT NULL DEFAULT 2.00,
    payment_due_day      TINYINT         NOT NULL DEFAULT 1,
    created_at           DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

SET @i = (SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema=DATABASE() AND table_name='credit_cards' AND index_name='idx_cards_user');
SET @s = IF(@i=0,'CREATE INDEX idx_cards_user ON credit_cards (user_id)','SELECT 1');
PREPARE st FROM @s; EXECUTE st; DEALLOCATE PREPARE st;

-- ── planned_purchases ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS planned_purchases (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    user_id        INT             NOT NULL,
    item_name      VARCHAR(300)    NOT NULL,
    price          DECIMAL(12, 2)  NOT NULL,
    wallet         VARCHAR(100)    NOT NULL DEFAULT '',
    payment_method VARCHAR(20)     NOT NULL DEFAULT 'cash',
    status         VARCHAR(20)     NOT NULL DEFAULT 'planned',
    notes          TEXT,
    created_at     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

SET @i = (SELECT COUNT(*) FROM information_schema.statistics
    WHERE table_schema=DATABASE() AND table_name='planned_purchases' AND index_name='idx_purchases_user');
SET @s = IF(@i=0,'CREATE INDEX idx_purchases_user ON planned_purchases (user_id)','SELECT 1');
PREPARE st FROM @s; EXECUTE st; DEALLOCATE PREPARE st;

SELECT 'Migration v6->v7 complete.' AS status;
SHOW TABLES;
