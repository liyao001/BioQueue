-- --------------------------------------------------------
-- Queue Database Structure
-- MySQL:         5.7.10-log - MySQL Community Server (GPL)
-- --------------------------------------------------------

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET NAMES utf8mb4 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;

-- Table prediction
DROP TABLE IF EXISTS `y_prediction`;
CREATE TABLE `y_prediction` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `stephash` varchar(50) DEFAULT '0',
  `a` varchar(50) DEFAULT '0',
  `b` varchar(50) DEFAULT '0',
  `r` varchar(50) DEFAULT '0',
  `img` varchar(50) DEFAULT '0',
  `type` tinyint(4) DEFAULT NULL,
  KEY `id` (`id`),
  KEY `stephash` (`stephash`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

-- Table protocol
DROP TABLE IF EXISTS `y_protocol`;
CREATE TABLE `y_protocol` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `software` varchar(50) DEFAULT NULL,
  `parameter` text,
  `parent` varchar(50) DEFAULT NULL,
  `user_id` varchar(50) DEFAULT NULL,
  `hash` varchar(50) DEFAULT NULL,
  UNIQUE KEY `id` (`id`),
  KEY `parent` (`parent`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

-- Table protocol_list
DROP TABLE IF EXISTS `y_protocol_list`;
CREATE TABLE `y_protocol_list` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `name` varchar(50) DEFAULT '0',
  `user_id` varchar(50) DEFAULT NULL,
  KEY `rec_id` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

-- Table queue
DROP TABLE IF EXISTS `y_queue`;
CREATE TABLE `y_queue` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `protocol` int(11) DEFAULT NULL,
  `inputFile` text,
  `parameter` text,
  `run_dir` text,
  `result` text,
  `status` int(11) DEFAULT '0',
  `updatetime` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `ctime` datetime DEFAULT CURRENT_TIMESTAMP,
  `user_id` varchar(50) DEFAULT NULL,
  `resume` INT(11) NULL DEFAULT '-1',
  `ter` INT(11) NULL DEFAULT '0',
  UNIQUE KEY `rec_id` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

-- Table references
DROP TABLE IF EXISTS `y_references`;
CREATE TABLE `y_references` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `name` varchar(50) DEFAULT '0',
  `path` varchar(50) DEFAULT '0',
  `user_id` varchar(50) DEFAULT NULL,
  KEY `rec_id` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

-- Table training
DROP TABLE IF EXISTS `y_training`;
CREATE TABLE `y_training` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `step` varchar(50) DEFAULT NULL,
  `in` varchar(45) DEFAULT NULL,
  `out` varchar(45) DEFAULT NULL,
  `mem` varchar(45) DEFAULT NULL,
  `cpu` varchar(45) DEFAULT NULL,
  `ctime` datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `FK_training_protocol` (`step`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

-- Table user
DROP TABLE IF EXISTS `y_user`;
CREATE TABLE `y_user` (
  `id` bigint(20) NOT NULL AUTO_INCREMENT,
  `user` varchar(50) NOT NULL DEFAULT '0',
  `passwd` varchar(50) NOT NULL DEFAULT '0',
  `salt` varchar(50) NOT NULL DEFAULT '0',
  `createat` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `status` tinyint(4) NOT NULL DEFAULT '0',
  UNIQUE KEY `id` (`id`),
  UNIQUE KEY `user` (`user`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8;

-- Table resource
DROP TABLE IF EXISTS `y_resource`;
CREATE TABLE `resource` (
	`cpu` VARCHAR(50) NULL DEFAULT NULL,
	`mem` VARCHAR(50) NULL DEFAULT NULL,
	`disk` VARCHAR(50) NULL DEFAULT NULL,
	`own` VARCHAR(5) NULL DEFAULT 'sys',
	`lock` TINYINT(4) NULL DEFAULT '0'
)
COLLATE='utf8_general_ci'
ENGINE=MyISAM
;

/*!40101 SET SQL_MODE=IFNULL(@OLD_SQL_MODE, '') */;
/*!40014 SET FOREIGN_KEY_CHECKS=IF(@OLD_FOREIGN_KEY_CHECKS IS NULL, 1, @OLD_FOREIGN_KEY_CHECKS) */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;