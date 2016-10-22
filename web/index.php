<?php
if(version_compare(PHP_VERSION,'5.3.0','<'))  die('require PHP > 5.3.0 !');

define('APP_DEBUG',True);

define('APP_PATH','./Application/');
define('APP_HOME','./');

if(!is_file(APP_PATH . 'Common/Conf/config.php')){
	header('Location: install.php');
	exit;
}

require './ThinkPHP/ThinkPHP.php';
