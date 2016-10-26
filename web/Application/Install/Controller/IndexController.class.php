<?php
namespace Install\Controller;
use Think\Controller;
use Think\Db;
use Think\Storage;

class IndexController extends Controller {
	function index() {
		if(Storage::has(MODULE_PATH . 'Data/install.lock')){
			$this->error('You have installed BQS already!');
		}else{
			$this->display();
		}
	}
	public function step1() {
		session('error', false);
		$env = check_env();
		$dirfile = check_dirfile();
		$func = check_func();
		if (ini_get('allow_url_fopen')){
			$func[] = array('fopen(url)', 'Enabled', 'ok-sign');
		}else{
			$func[] = array('fopen(url)', 'Disabled', 'remove-sign');
		}
		session('step', 1);
		$this->assign('env', $env);
		$this->assign('dirfile', $dirfile);
		$this->assign('func', $func);
		$this->display();
	}
	public function step2($db = null) {
		session('error', '');
		if (IS_POST){
			if (!is_array($db) || empty($db[0]) || empty($db[1]) || empty($db[2]) || empty($db[3])){
				$this->error('You must provide all those information!');
			}else{
				$DB = array();
				list($DB['DB_TYPE'], $DB['DB_HOST'], $DB['DB_NAME'], $DB['DB_USER'], $DB['DB_PWD'],
					 $DB['DB_PORT'], $DB['DB_PREFIX']) = $db;
				$DB['logStore'] = realpath(APP_HOME).'/logs';
				F('RUNFOLDER', realpath(APP_HOME).'/Workspace');
				F('CPU', I('cpu'));
				F('MEM', I('mem'));
				
				$ui = array(
						'user'	=>	I('user'),
						'passwd'	=>	I('passwd'),
				);
				
				session('db_config', $DB);
				session('user_config', $ui);
				
				$dbname = $DB['DB_NAME'];
				unset($DB['DB_NAME']);
				$db = Db::getInstance($DB);
				$sql = "CREATE DATABASE IF NOT EXISTS `{$dbname}` DEFAULT CHARACTER SET utf8";
				$db->execute($sql) || $this->error($db->getError());
			}
			$this->redirect('step3');
		} else {
			session('error') && $this->error('Your system environment doesn\'t match our requirements, the install has to be canceled.');

			$step = session('step');
			if($step != 1 && $step != 2){
				$this->redirect('step1');
			}

			session('step', 2);
			$this->display();
		}
	}
	
		public function step3(){
		if(session('step') != 2){
			$this->redirect('step2');
		}
		
		$this->display();
		
		$dbconfig = session('db_config');
		$db = Db::getInstance($dbconfig);
		
		create_tables($db, $dbconfig['DB_PREFIX']);
		
		$conf 	=	write_config($dbconfig);
		session('config_file', $conf);
		$clientConf = write_client_config($dbconfig);
		$this->reg($db, session('user_config'));
		if(session('error')){
			//show_msg();
		} else {
			session('step', 3);
			Storage::put(MODULE_PATH . 'Data/install.lock', 'lock');
			$this->redirect('Home', array(), 3, 'Queue system is ready now!');
		}
	}
	private function reg($db, $udb){
		$user = $udb['user'];
		$salt = salt();
		$pw = md5plus($udb['passwd'], $salt);

		$sql = "INSERT INTO `user` (`user`, `passwd`, `salt`, `status`) VALUES ('$user', '$pw', '$salt', 3);";
		$db->execute($sql) || $this->error($db->getError());
	}
}