-- Fresh-install schema for the USRP B210 Spectrum Monitoring System.
-- This file provisions structure only; it contains no credentials or seed data.
-- Configure the project-root .env file, then create an administrator separately with:
--     python -m backend.bootstrap_admin

CREATE DATABASE IF NOT EXISTS `usrp_monitoring`
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE `usrp_monitoring`;

CREATE TABLE IF NOT EXISTS `users` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `username` VARCHAR(100) NOT NULL,
    `password` VARCHAR(128) NOT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_users_username` (`username`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `machines` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `name` VARCHAR(100) NOT NULL,
    `description` TEXT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    KEY `ix_machines_id` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `channels` (
    `id` INT NOT NULL AUTO_INCREMENT,
    `machine_id` INT NOT NULL,
    `channel_number` VARCHAR(20) NOT NULL,
    `input_mode` VARCHAR(50) NOT NULL,
    `input_fcn` INT NOT NULL,
    `freq_dl_mhz` DECIMAL(12,6) NULL,
    `freq_ul_mhz` DECIMAL(12,6) NULL,
    `fcn_dl` INT NULL,
    `fcn_ul` INT NULL,
    `band` VARCHAR(30) NOT NULL,
    `mode` VARCHAR(50) NOT NULL,
    `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (`id`),
    UNIQUE KEY `uq_machine_channel_number` (`machine_id`, `channel_number`),
    KEY `ix_channels_id` (`id`),
    KEY `ix_channels_machine_id` (`machine_id`),
    CONSTRAINT `fk_channels_machine_id`
        FOREIGN KEY (`machine_id`) REFERENCES `machines` (`id`)
        ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
