-- =============================================================================
-- Migration 001 — Unified Auth
--
-- Run once against the auditions database (AUDITIONS_DB_URI).
--
-- Changes:
--   1. Allow password_hash to be NULL  (staff sign in via Google; no password)
--   2. Add google_id column            (set on first Google OAuth login)
--   3. Add last_login column           (updated on every login)
--   4. Clear dummy password hashes for existing admin/viewer accounts
--      so they are treated as Google-only from here on.
-- =============================================================================

-- 1. Make password_hash nullable
ALTER TABLE users
    MODIFY COLUMN password_hash VARCHAR(255) NULL;

-- 2. Add google_id (unique, nullable)
ALTER TABLE users
    ADD COLUMN google_id VARCHAR(255) NULL UNIQUE AFTER password_hash;

-- 3. Add last_login (nullable datetime)
ALTER TABLE users
    ADD COLUMN last_login DATETIME NULL AFTER created_at;

-- 4. Wipe stored password hashes for staff (admin/viewer) accounts.
--    They sign in exclusively via Google going forward; the hashes are no
--    longer used and having them set could be confusing.
UPDATE users
   SET password_hash = NULL
 WHERE role IN ('admin', 'viewer');
