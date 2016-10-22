<?php
function check_env(){
	$items = array(
			'os'      => array('Operation System', 'Any', 'Unix-like', PHP_OS, 'ok-sign'),
			'php'     => array('PHP Version', '5.3', '5.3+', PHP_VERSION, 'ok-sign'),
			'upload'  => array('Upload File', 'Any', '2M+', 'Unknown', 'ok-sign'),
			'gd'      => array('GD Library', '2.0', '2.0+', 'Unknown', 'ok-sign'),
			'disk'    => array('Disk Space', '1024M', '10240M', 'Unknown', 'ok-sign'),
	);

	if($items['php'][3] < $items['php'][1]){
		$items['php'][4] = 'remove-circle';
		session('error', true);
	}

	if(@ini_get('file_uploads'))
		$items['upload'][3] = ini_get('upload_max_filesize');

		$tmp = function_exists('gd_info') ? gd_info() : array();
		if(empty($tmp['GD Version'])){
			$items['gd'][3] = 'Not installed';
			$items['gd'][4] = 'remove-circle';
			session('error', true);
		} else {
			$items['gd'][3] = $tmp['GD Version'];
		}
		unset($tmp);

		if(function_exists('disk_free_space')) {
			$items['disk'][3] = floor(disk_free_space(INSTALL_APP_PATH) / (1024*1024)).'M';
			if (str_replace('M', '', $items['disk'][3]) < str_replace('M', '', $items['disk'][1])){
				$items['disk'][4] = 'remove-circle';
				session('error', true);
			}
		}

		return $items;
}

function check_dirfile(){
	$items = array(
			array('dir',  'Writable', 'ok-sign', './Workspace'),
			array('dir',  'Writable', 'ok-sign', './Public/img/mls'),
			array('dir',  'Writable', 'ok-sign', './logs'),
			array('dir',  'Writable', 'ok-sign', './Application/Runtime'),
			array('dir', 'Writable', 'ok-sign', './Application/Home/Conf'),
			array('file', 'Writable', 'ok-sign', './Application/Common/Conf/config.php'),
			array('file', 'Writable', 'ok-sign', './config.conf'),
	);

	foreach ($items as &$val) {
		if('dir' == $val[0]){
			if(!is_writable(INSTALL_APP_PATH . $val[3])) {
				if(is_dir($items[1])) {
					$val[1] = 'Cannot write file!';
					$val[2] = 'error';
					session('error', true);
				} else {
					$val[1] = 'Cannot write file!';
					$val[2] = 'error';
					session('error', true);
				}
			}
		} else {
			if(file_exists(INSTALL_APP_PATH . $val[3])) {
				if(!is_writable(INSTALL_APP_PATH . $val[3])) {
					$val[1] = 'Cannot write file!';
					$val[2] = 'error';
					session('error', true);
				}
			} else {
				if(!is_writable(dirname(INSTALL_APP_PATH . $val[3]))) {
					$val[1] = 'Cannot write file!';
					$val[2] = 'error';
					session('error', true);
				}
			}
		}
	}

	return $items;
}

function check_func(){
	$items = array(
			array('mysql_connect',     'Enabled', 'ok-sign'),
			array('file_get_contents', 'Enabled', 'ok-sign'),
			array('mb_strlen',		   'Enabled', 'ok-sign'),
	);

	foreach ($items as &$val) {
		if(!function_exists($val[0])){
			$val[1] = 'Disabled';
			$val[2] = 'remove-circle';
			$val[3] = 'Enable';
			session('error', true);
		}
	}

	return $items;
}

function write_config($config){
	if(is_array($config)){
		$conf = file_get_contents(MODULE_PATH . 'Data/conf.tpl');
		foreach ($config as $name => $value) {
			$conf = str_replace("[{$name}]", $value, $conf);
		}

		if(!IS_WRITE){
			return 'We cannot get permission to edit the config file, please copy content below and paste them into your config file.<p>'.realpath(APP_PATH).'/Common/Conf/config.php</p>
			<textarea name="" style="width:650px;height:185px">'.$conf.'</textarea>
			<p>'.realpath(APP_PATH).'/User/Conf/config.php</p>
			<textarea name="" style="width:650px;height:125px">'.$user.'</textarea>';
		}else{
			if(file_put_contents(APP_PATH . 'Common/Conf/config.php', $conf)){
				show_msg('Configure file has created.');
			} else {
				show_msg('Fail to create the configure file.', 'error');
				session('error', true);
			}
			return '';
		}

	}
}

function create_tables($db, $prefix = ''){
	$sql = file_get_contents(MODULE_PATH . 'Data/install.sql');
	$sql = str_replace("\r", "\n", $sql);
	$sql = explode(";\n", $sql);

	$orginal = C('ORIGINAL_TABLE_PREFIX');
	$sql = str_replace(" `{$orginal}", " `{$prefix}", $sql);
	show_msg('Creating tables...');
	foreach ($sql as $value) {
		$value = trim($value);
		if(empty($value)) continue;
		if(substr($value, 0, 12) == 'CREATE TABLE') {
			$name = preg_replace("/^CREATE TABLE `(\w+)` .*/s", "\\1", $value);
			$msg  = "Creating {$name}";
			if(false !== $db->execute($value)){
				show_msg($msg . '...ok!');
			} else {
				show_msg($msg . '...fail!', 'error');
				session('error', true);
			}
		} else {
			$db->execute($value);
		}

	}
}

function show_msg($msg, $class = ''){
	echo "<script type=\"text/javascript\">showmsg(\"{$msg}\", \"{$class}\")</script>";
	flush();
	ob_flush();
}

function write_client_config($conf) {
	$ini = new \Org\Net\IniParser();
	$ini->init('config.conf');
	$ini->setValue('db', 'user', $conf['DB_USER']);
	$ini->setValue('db', 'host', $conf['DB_HOST']);
	$ini->setValue('db', 'db_name', $conf['DB_NAME']);
	$ini->setValue('db', 'password', $conf['DB_PWD']);
	$ini->setValue('db', 'port', $conf['DB_PORT']);
	$ini->setValue('datasets', 'protocolDb', $conf['DB_PREFIX'].'protocol');
	$ini->setValue('datasets', 'jobDb', $conf['DB_PREFIX'].'queue');
	$ini->setValue('datasets', 'trainStore', $conf['DB_PREFIX'].'training');
	$ini->setValue('datasets', 'equation', $conf['DB_PREFIX'].'prediction');
	$ini->setValue('env', 'log', realpath(APP_HOME).'/logs');
	$ini->setValue('ml', 'trainStore', realpath(APP_HOME).'/logs');
	$ini->setValue('ml', 'imgStore', realpath(APP_HOME).'/Public/img/mls');
	$ini->save();
	show_msg('-----------------------');
	show_msg('Queue system is ready now!');
}