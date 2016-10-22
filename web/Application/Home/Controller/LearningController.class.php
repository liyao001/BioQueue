<?php
namespace Home\Controller;
use Think\Controller;

class LearningController extends AuthController {
	public $userID = 0;
	public $userLEVEL = 0;
	public function _initialize(){
		$this->userID = session('user_auth')['id'];
		$this->userLEVEL = session('user_auth')['status'];
		if(intval(is_login()) < 1){
			$this->redirect('Protect/login');
			$this->tmp = session('user_auth');
		}
	}
	function index() {
		$proDB = M('protocol_list');
		if ($this->userLEVEL >= 2){
			$protocol = $proDB->select();
		}else{
			$map = array('user_id' => $this->userID);
			$protocol = $proDB->where($map)->select();
		}
		$this->assign('prol', $protocol);
		$this->display();
	}
	public function getCPU($hash) {
		$db = M('prediction');
		$map = array(
				'stephash'	=>	$hash,
				'type'	=>	'3',
		);
		$ret = $db->where($map)->select();
		if ($ret){
			$this->assign('hit', $ret[0]);
			echo $this->fetch('common');
		}else{
			echo 'Not enough records for evaluation.';
		}
	}
	public function getMem($hash) {
		$db = M('prediction');
		$map = array(
				'stephash'	=>	$hash,
				'type'	=>	'2',
		);
		$ret = $db->where($map)->select();
		if ($ret){
			$this->assign('hit', $ret[0]);
			echo $this->fetch('common');
		}else{
			echo 'Not enough records for evaluation.';
		}
	}
	public function getDisk($hash) {
		$db = M('prediction');
		$map = array(
				'stephash'	=>	$hash,
				'type'	=>	'1',
		);
		$ret = $db->where($map)->select();
		if ($ret){
			$this->assign('hit', $ret[0]);
			echo $this->fetch('common');
		}else{
			echo 'Not enough records for evaluation.';
		}
	}
	public function showSteps($pro){
		$queDB = M('protocol');
		if ($this->userLEVEL >= 2){
			$map = array('parent'   =>  $pro,);
			$protocol = $queDB->where($map)->select();
		}else{
			$map = array('user_id' => $this->userID, 'parent'   =>  $pro,);
			$protocol = $queDB->where($map)->select();
			//$que = $queDB->where($map)->order('id desc')->page($_GET['p'].',25')->select();
		}
		//$queDB = M('protocol');
		//$protocol = $queDB->where("parent='".intval($pro)."'")->select();
		$this->assign('stepl', $protocol);
		$this->display();
	}
	public function getML($hash, $type) {
		if (F('CPUs') && F('Memory')){
			$url = C('APIBUS').'share/h/'.$hash.'/t/'.$type.'/c/'.F('CPUs').'/m/'.F('Memory');
			$fp = fopen($url, 'r');
			$header = stream_get_meta_data($fp);
			while(!feof($fp)){
				$result .= fgets($fp, 1024);
			}
			$f = json_decode($result, true);
			$this->assign('hit', $f);
			$f['stephash'] = $hash;
			$f['type'] = $type;
			session('ml', $f);
			fclose($fp);
			$this->display();
		}else{
			echo 'You need to tell us how many processors and memory you have in your system, which can be assigned in the <a href="./System">system page</a>.';
		}
		
	}
	public function accept(){
		$data = session('ml');
		if ($data){
			$pre = M('prediction');
			$ret = $pre->add($data);
			if ($ret){
				$this->success('OK!');
			}else{
				$this->error($ret->getError());
			}
		}else{
			$this->error('Please check your session.');
		}
	}
}