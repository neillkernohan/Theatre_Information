-- Add inventory_manager to the users.role enum.
-- Run once against the theatre_auditions database.
ALTER TABLE users MODIFY COLUMN role ENUM(
    'super_admin', 'auditions_creator', 'director', 'producer', 'stage_manager',
    'admin', 'viewer', 'actor', 'inventory_manager', 'no_rights'
) NOT NULL DEFAULT 'actor';
