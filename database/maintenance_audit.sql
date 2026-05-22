-- SkillFlow database integrity audit.
-- Run this before demos to find duplicate/corrupted records that block UNIQUE
-- indexes or cause confusing signup/login behavior.

USE `skillflow_db`;

-- Email must be unique. This query should return zero rows.
SELECT LOWER(email) AS email_key, COUNT(*) AS duplicate_count
FROM users
GROUP BY LOWER(email)
HAVING COUNT(*) > 1;

-- Usernames are app-validated but not database-unique. Duplicates should still
-- be reviewed because they confuse profile URLs and admin screens.
SELECT LOWER(username) AS username_key, COUNT(*) AS duplicate_count
FROM users
GROUP BY LOWER(username)
HAVING COUNT(*) > 1;

-- Orphan records should return zero rows.
SELECT r.id AS request_id
FROM requests r
LEFT JOIN users s ON s.id = r.sender_id
LEFT JOIN users u ON u.id = r.receiver_id
WHERE s.id IS NULL OR u.id IS NULL;

SELECT m.id AS message_id
FROM messages m
LEFT JOIN requests r ON r.id = m.request_id
LEFT JOIN users s ON s.id = m.sender_id
LEFT JOIN users u ON u.id = m.receiver_id
WHERE r.id IS NULL OR s.id IS NULL OR u.id IS NULL;

SELECT p.id AS payment_id
FROM payments p
LEFT JOIN users u ON u.id = p.user_id
LEFT JOIN requests r ON r.id = p.request_id
WHERE u.id IS NULL OR (p.request_id IS NOT NULL AND r.id IS NULL);

