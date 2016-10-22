<?php
if(version_compare(PHP_VERSION,'5.3.0','<'))  die('require PHP > 5.3.0 !');

$_GET['m'] = 'Install';

define ( 'APP_DEBUG', true );
define ( 'APP_PATH', './Application/' );
define('APP_HOME','./');
#define ( 'RUNTIME_PATH', './Runtime/' );
if(is_file(APP_PATH . 'Common/Conf/config.php')){
	header('Location: ../index.php');
	exit;
}
require './ThinkPHP/ThinkPHP.php';