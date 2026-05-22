-- SkillFlow cleanup migration for existing local databases.
-- Fresh installs should use skillflow_schema.sql.

USE `skillflow_db`;

-- Keep email as the only UNIQUE identity constraint on user accounts.
-- If this fails, the index may already be absent; continue with the next step.
ALTER TABLE `users` DROP INDEX `username`;

ALTER TABLE `users`
  ADD COLUMN IF NOT EXISTS `is_premium` BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS `premium_unlocked_at` TIMESTAMP NULL,
  ADD COLUMN IF NOT EXISTS `premium_expiry_date` TIMESTAMP NULL,
  ADD COLUMN IF NOT EXISTS `xp_points` INT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS `current_streak` INT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS `longest_streak` INT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS `last_activity_date` DATE DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS `last_reward_claimed_at` DATETIME DEFAULT NULL;

ALTER TABLE `payments`
  ADD COLUMN IF NOT EXISTS `premium_start_date` TIMESTAMP NULL DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS `premium_expiry_date` TIMESTAMP NULL DEFAULT NULL,
  ADD COLUMN IF NOT EXISTS `updated_at` TIMESTAMP NULL DEFAULT NULL;

