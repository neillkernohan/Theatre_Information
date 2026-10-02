-- Respectful Space Policy sign-offs.
-- Run once against the theatre_auditions database
-- (or run `flask init-auditions-db`, which creates any missing tables).
CREATE TABLE IF NOT EXISTS respectful_space_signatures (
    id INT AUTO_INCREMENT PRIMARY KEY,
    first_name VARCHAR(100) NOT NULL,
    last_name VARCHAR(100) NOT NULL,
    email VARCHAR(255) NOT NULL,
    production VARCHAR(255),
    signature_name VARCHAR(255) NOT NULL,
    policy_version VARCHAR(20) NOT NULL,
    season VARCHAR(20) NOT NULL,
    signed_at DATETIME NOT NULL,
    ip_address VARCHAR(64),
    user_agent VARCHAR(500),
    user_id INT NULL,
    INDEX ix_respectful_space_signatures_email (email),
    INDEX ix_respectful_space_signatures_season (season),
    CONSTRAINT fk_rs_user FOREIGN KEY (user_id) REFERENCES users (id)
);
