-- phpMyAdmin SQL Dump
-- Database: `skillflow_db`

CREATE DATABASE IF NOT EXISTS `skillflow_db` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
USE `skillflow_db`;

-- --------------------------------------------------------

--
-- Table structure for table `users`
--

CREATE TABLE `users` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `username` VARCHAR(25) NOT NULL,
  `email` VARCHAR(190) NOT NULL,
  `password_hash` VARCHAR(255) NOT NULL,
  `is_admin` BOOLEAN DEFAULT FALSE,
  `is_blocked` BOOLEAN DEFAULT FALSE,
  `is_deleted` BOOLEAN DEFAULT FALSE,
  `deleted_at` TIMESTAMP NULL,
  `deleted_by_user` BOOLEAN DEFAULT FALSE,
  `profile_visibility` BOOLEAN DEFAULT TRUE,
  `is_verified` BOOLEAN DEFAULT TRUE,
  `verification_otp` VARCHAR(10) DEFAULT NULL,
  `verification_token` VARCHAR(120) DEFAULT NULL,
  `verification_expiry` DATETIME DEFAULT NULL,
  `verification_last_sent_at` DATETIME DEFAULT NULL,
  `email_notifications` BOOLEAN DEFAULT TRUE,
  `match_notifications` BOOLEAN DEFAULT TRUE,
  `full_name` VARCHAR(100) DEFAULT NULL,
  `location` VARCHAR(120) DEFAULT NULL,
  `skills_offered` VARCHAR(255) DEFAULT NULL,
  `skills_wanted` VARCHAR(255) DEFAULT NULL,
  `bio` TEXT DEFAULT NULL,
  `phone` VARCHAR(20) DEFAULT NULL,
  `contact_number` VARCHAR(30) DEFAULT NULL,
  `instagram_id` VARCHAR(120) DEFAULT NULL,
  `video_url` VARCHAR(255) DEFAULT NULL,
  `video_description` TEXT DEFAULT NULL,
  `contact_sharing` BOOLEAN DEFAULT FALSE,
  `allow_contact_after_payment` BOOLEAN DEFAULT FALSE,
  `avatar_url` VARCHAR(255) DEFAULT NULL,
  `user_session_version` INT DEFAULT 1,
  `reset_code` VARCHAR(10) DEFAULT NULL,
  `reset_code_expiry` DATETIME DEFAULT NULL,
  `is_premium` BOOLEAN DEFAULT FALSE,
  `premium_unlocked_at` TIMESTAMP NULL,
  `premium_expiry_date` TIMESTAMP NULL,
  `xp_points` INT NOT NULL DEFAULT 0,
  `current_streak` INT NOT NULL DEFAULT 0,
  `longest_streak` INT NOT NULL DEFAULT 0,
  `last_activity_date` DATE DEFAULT NULL,
  `last_reward_claimed_at` DATETIME DEFAULT NULL,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `email` (`email`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `disposable_email_attempts`
--

CREATE TABLE `disposable_email_attempts` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `email` VARCHAR(190) NOT NULL,
  `domain` VARCHAR(120) NOT NULL,
  `source` VARCHAR(40) NOT NULL DEFAULT 'registration',
  `ip_address` VARCHAR(80) DEFAULT NULL,
  `user_agent` VARCHAR(255) DEFAULT NULL,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `domain` (`domain`),
  KEY `created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `skills`
--

CREATE TABLE `skills` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `user_id` INT(11) NOT NULL,
  `skill_name` VARCHAR(100) NOT NULL,
  `skill_type` ENUM('teach', 'learn') NOT NULL,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `user_id` (`user_id`),
  CONSTRAINT `fk_skills_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `exchange_requests`
--

CREATE TABLE `exchange_requests` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `sender_id` INT(11) NOT NULL,
  `receiver_id` INT(11) NOT NULL,
  `status` ENUM('pending', 'accepted', 'rejected') NOT NULL DEFAULT 'pending',
  `message` TEXT DEFAULT NULL,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `sender_id` (`sender_id`),
  KEY `receiver_id` (`receiver_id`),
  CONSTRAINT `fk_requests_sender` FOREIGN KEY (`sender_id`) REFERENCES `users` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_requests_receiver` FOREIGN KEY (`receiver_id`) REFERENCES `users` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `requests`
--

CREATE TABLE `requests` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `sender_id` INT(11) NOT NULL,
  `receiver_id` INT(11) NOT NULL,
  `skill_requested` VARCHAR(255) NOT NULL,
  `skill_offered` VARCHAR(255) NOT NULL,
  `status` ENUM('pending', 'accepted', 'rejected') NOT NULL DEFAULT 'pending',
  `payment_status` ENUM('pending', 'paid', 'expired') NOT NULL DEFAULT 'pending',
  `payment_date` TIMESTAMP NULL,
  `expiry_date` TIMESTAMP NULL,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `sender_id` (`sender_id`),
  KEY `receiver_id` (`receiver_id`),
  KEY `idx_requests_sender_status` (`sender_id`, `status`, `created_at`),
  KEY `idx_requests_receiver_status` (`receiver_id`, `status`, `created_at`),
  KEY `idx_requests_pair` (`sender_id`, `receiver_id`),
  CONSTRAINT `fk_requests_sender_v2` FOREIGN KEY (`sender_id`) REFERENCES `users` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_requests_receiver_v2` FOREIGN KEY (`receiver_id`) REFERENCES `users` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `matches`
--

CREATE TABLE `matches` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `request_id` INT(11) DEFAULT NULL,
  `user1_id` INT(11) NOT NULL,
  `user2_id` INT(11) NOT NULL,
  `skill_exchange_details` VARCHAR(255) DEFAULT NULL,
  `matched_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `request_id` (`request_id`),
  KEY `user1_id` (`user1_id`),
  KEY `user2_id` (`user2_id`),
  KEY `idx_matches_user1` (`user1_id`, `matched_at`),
  KEY `idx_matches_user2` (`user2_id`, `matched_at`),
  CONSTRAINT `fk_matches_request` FOREIGN KEY (`request_id`) REFERENCES `requests` (`id`) ON DELETE SET NULL ON UPDATE CASCADE,
  CONSTRAINT `fk_matches_user1` FOREIGN KEY (`user1_id`) REFERENCES `users` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_matches_user2` FOREIGN KEY (`user2_id`) REFERENCES `users` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `unfollow_reports`
--

CREATE TABLE `unfollow_reports` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `match_id` INT(11) DEFAULT NULL,
  `request_id` INT(11) DEFAULT NULL,
  `unfollower_id` INT(11) NOT NULL,
  `unfollowed_user_id` INT(11) NOT NULL,
  `action_type` VARCHAR(40) NOT NULL DEFAULT 'unfollow',
  `previous_request_status` VARCHAR(40) DEFAULT NULL,
  `reason` VARCHAR(80) NOT NULL,
  `custom_reason` TEXT DEFAULT NULL,
  `status` VARCHAR(40) NOT NULL DEFAULT 'pending',
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `match_id` (`match_id`),
  KEY `request_id` (`request_id`),
  KEY `idx_unfollow_reports_request` (`request_id`),
  KEY `idx_unfollow_reports_user` (`unfollower_id`, `unfollowed_user_id`),
  KEY `unfollower_id` (`unfollower_id`),
  KEY `unfollowed_user_id` (`unfollowed_user_id`),
  KEY `reason` (`reason`),
  KEY `status` (`status`),
  CONSTRAINT `fk_unfollow_reports_unfollower` FOREIGN KEY (`unfollower_id`) REFERENCES `users` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_unfollow_reports_unfollowed` FOREIGN KEY (`unfollowed_user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_unfollow_reports_request` FOREIGN KEY (`request_id`) REFERENCES `requests` (`id`) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `messages`
--

CREATE TABLE `messages` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `request_id` INT(11) NOT NULL,
  `sender_id` INT(11) NOT NULL,
  `receiver_id` INT(11) NOT NULL,
  `content` TEXT NOT NULL,
  `message_text` TEXT DEFAULT NULL,
  `is_read` TINYINT(1) NOT NULL DEFAULT 0,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `request_id` (`request_id`),
  KEY `sender_id` (`sender_id`),
  KEY `receiver_id` (`receiver_id`),
  KEY `idx_messages_request_created` (`request_id`, `created_at`),
  KEY `idx_messages_sender_receiver` (`sender_id`, `receiver_id`, `created_at`),
  CONSTRAINT `fk_messages_request` FOREIGN KEY (`request_id`) REFERENCES `requests` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_messages_sender` FOREIGN KEY (`sender_id`) REFERENCES `users` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_messages_receiver` FOREIGN KEY (`receiver_id`) REFERENCES `users` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

--
-- Table structure for table `payments` (Optional but mentioned previously)
--

CREATE TABLE `payments` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `user_id` INT(11) NOT NULL,
  `request_id` INT(11) DEFAULT NULL,
  `merchant_order_id` VARCHAR(120) DEFAULT NULL,
  `transaction_id` VARCHAR(120) DEFAULT NULL,
  `amount` DECIMAL(10,2) NOT NULL,
  `status` ENUM('created', 'successful', 'failed') NOT NULL DEFAULT 'created',
  `gateway` VARCHAR(30) NOT NULL DEFAULT 'phonepe',
  `payment_status` VARCHAR(30) NOT NULL DEFAULT 'pending',
  `premium_start_date` TIMESTAMP NULL DEFAULT NULL,
  `premium_expiry_date` TIMESTAMP NULL DEFAULT NULL,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` TIMESTAMP NULL DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `user_id` (`user_id`),
  KEY `request_id` (`request_id`),
  KEY `idx_payments_user_status` (`user_id`, `payment_status`, `status`),
  KEY `idx_payments_merchant_order` (`merchant_order_id`),
  CONSTRAINT `fk_payments_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_payments_request` FOREIGN KEY (`request_id`) REFERENCES `requests` (`id`) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

CREATE TABLE `user_achievements` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `user_id` INT(11) NOT NULL,
  `badge_key` VARCHAR(60) NOT NULL,
  `badge_name` VARCHAR(120) NOT NULL,
  `icon` VARCHAR(80) DEFAULT 'fa-solid fa-award',
  `earned_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `user_badge` (`user_id`, `badge_key`),
  KEY `user_id` (`user_id`),
  CONSTRAINT `fk_user_achievements_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `user_reviews` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `reviewer_id` INT(11) NOT NULL,
  `reviewed_user_id` INT(11) NOT NULL,
  `request_id` INT(11) DEFAULT NULL,
  `rating` INT NOT NULL,
  `feedback` VARCHAR(500) DEFAULT NULL,
  `experience_tag` VARCHAR(120) DEFAULT NULL,
  `status` ENUM('visible', 'removed') NOT NULL DEFAULT 'visible',
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` TIMESTAMP NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `reviewer_reviewed` (`reviewer_id`, `reviewed_user_id`),
  KEY `reviewed_user_id` (`reviewed_user_id`),
  KEY `request_id` (`request_id`),
  KEY `status` (`status`),
  CONSTRAINT `fk_user_reviews_reviewer` FOREIGN KEY (`reviewer_id`) REFERENCES `users` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_user_reviews_reviewed` FOREIGN KEY (`reviewed_user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_user_reviews_request` FOREIGN KEY (`request_id`) REFERENCES `requests` (`id`) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `user_favorites` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `user_id` INT(11) NOT NULL,
  `favorite_user_id` INT(11) NOT NULL,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `user_favorite` (`user_id`, `favorite_user_id`),
  KEY `user_id` (`user_id`),
  KEY `favorite_user_id` (`favorite_user_id`),
  CONSTRAINT `fk_user_favorites_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_user_favorites_favorite` FOREIGN KEY (`favorite_user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `user_notifications` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `user_id` INT(11) NOT NULL,
  `notification_type` VARCHAR(50) NOT NULL DEFAULT 'system',
  `title` VARCHAR(160) NOT NULL,
  `message` VARCHAR(500) DEFAULT NULL,
  `related_id` INT(11) DEFAULT NULL,
  `is_read` BOOLEAN NOT NULL DEFAULT FALSE,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `user_unread` (`user_id`, `is_read`),
  KEY `created_at` (`created_at`),
  CONSTRAINT `fk_user_notifications_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `user_activity` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `user_id` INT(11) NOT NULL,
  `activity_type` VARCHAR(60) NOT NULL,
  `title` VARCHAR(160) NOT NULL,
  `points` INT NOT NULL DEFAULT 0,
  `related_id` INT(11) DEFAULT NULL,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `user_created` (`user_id`, `created_at`),
  CONSTRAINT `fk_user_activity_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `skill_categories` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `category_name` VARCHAR(120) NOT NULL,
  `icon` VARCHAR(80) DEFAULT 'fa-solid fa-layer-group',
  `keywords` TEXT DEFAULT NULL,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `category_name` (`category_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `user_skill_categories` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `user_id` INT(11) NOT NULL,
  `category_id` INT(11) NOT NULL,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `user_category` (`user_id`, `category_id`),
  KEY `user_id` (`user_id`),
  KEY `category_id` (`category_id`),
  CONSTRAINT `fk_user_skill_categories_user` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_user_skill_categories_category` FOREIGN KEY (`category_id`) REFERENCES `skill_categories` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

CREATE TABLE `reports` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `reported_user_id` INT(11) NOT NULL,
  `reported_by` INT(11) NOT NULL,
  `reporter_user_id` INT(11) DEFAULT NULL,
  `reporter_username` VARCHAR(120) DEFAULT NULL,
  `reported_username` VARCHAR(120) DEFAULT NULL,
  `report_type` ENUM('Spam', 'Abuse', 'Fake', 'Other') NOT NULL DEFAULT 'Other',
  `reason` ENUM('Spam', 'Abuse', 'Fake', 'Other') NOT NULL,
  `description` TEXT DEFAULT NULL,
  `status` ENUM('pending', 'under_review', 'resolved', 'rejected') NOT NULL DEFAULT 'pending',
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `reported_user_id` (`reported_user_id`),
  KEY `reported_by` (`reported_by`),
  KEY `reporter_user_id` (`reporter_user_id`),
  CONSTRAINT `fk_reports_reported_user` FOREIGN KEY (`reported_user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE ON UPDATE CASCADE,
  CONSTRAINT `fk_reports_reporter` FOREIGN KEY (`reported_by`) REFERENCES `users` (`id`) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- --------------------------------------------------------

CREATE TABLE `platform_plans` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `name` VARCHAR(50) NOT NULL,
  `platform_fee_percent` DECIMAL(5,2) NOT NULL DEFAULT 0,
  `minimum_transaction_amount` DECIMAL(10,2) NOT NULL DEFAULT 0,
  `is_active` BOOLEAN DEFAULT TRUE,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `plan_name` (`name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

INSERT INTO `platform_plans` (`name`, `platform_fee_percent`, `minimum_transaction_amount`) VALUES
('Basic', 5.00, 100.00),
('Premium', 8.00, 250.00),
('Expert', 10.00, 500.00);

CREATE TABLE `admin_settings` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `setting_key` VARCHAR(80) NOT NULL,
  `setting_value` TEXT DEFAULT NULL,
  `updated_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `setting_key` (`setting_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `admin_accounts` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `username` VARCHAR(120) NOT NULL,
  `email` VARCHAR(190) NOT NULL,
  `password` VARCHAR(255) NOT NULL,
  `reset_code` VARCHAR(10) DEFAULT NULL,
  `reset_code_expiry` DATETIME DEFAULT NULL,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `username` (`username`),
  UNIQUE KEY `email` (`email`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `admin_actions` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `user_id` INT(11) DEFAULT NULL,
  `username` VARCHAR(120) DEFAULT NULL,
  `action_type` VARCHAR(40) NOT NULL,
  `admin_name` VARCHAR(120) NOT NULL,
  `account_status` VARCHAR(40) DEFAULT NULL,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `user_id` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

CREATE TABLE `admin_notifications` (
  `id` INT(11) NOT NULL AUTO_INCREMENT,
  `notification_type` VARCHAR(40) NOT NULL DEFAULT 'system',
  `title` VARCHAR(190) NOT NULL,
  `message` TEXT DEFAULT NULL,
  `related_id` INT(11) DEFAULT NULL,
  `icon` VARCHAR(80) DEFAULT 'fa-solid fa-bell',
  `is_read` BOOLEAN NOT NULL DEFAULT FALSE,
  `created_at` TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `read_at` TIMESTAMP NULL,
  PRIMARY KEY (`id`),
  KEY `notification_type` (`notification_type`),
  KEY `is_read` (`is_read`),
  KEY `created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

COMMIT;
