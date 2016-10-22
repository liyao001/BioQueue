<?php
namespace Home\Controller;
use Think\Controller;

class ProtocolController extends AuthController {
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
	public function index() {
    	$this->display();
	}
	public function newProtocol(){
		if (check_verify(I('verify'))) {
			$queDB = M('protocol_list');
			$data = array('name' => I('name'),
					'user_id' => $this->userID,);
			$ret = $queDB->add($data);
			if ($ret){
				$this->success('New protocol is created successfully!');
			}else{
				$this->error($ret->getError());
			}
		}else{
			$this->error('Wrong code!');
		}
	}
	public function lprotocol($p = 1) {
		$proDB = M('protocol_list');
		if ($this->userLEVEL >= 2){
			$count = $proDB->count();
			$protocol = $proDB->page($p.',5')->select();
		}else{
			$map = array('user_id' => $this->userID);
			$count = $proDB->where($map)->count();
			$protocol = $proDB->where($map)->page($p.',5')->select();
		}
		$Page       = new \Think\Page($count, 5);
		$show       = $Page->show();
		$this->assign('page', $show);
		$this->assign('prol', $protocol);
		$this->display();
	}
	public function delProtocol($pro){
		if ($this->checkOwner('references', array('user_id' => $this->userID))){
			$proDB = M('protocol_list');
			$proDB->where('id='.intval($pro))->delete();
			$prolDB = M('protocol');
			$prolDB->where('parent='.intval($pro))->delete();
			$this->success('Delete successfully~');
		}else{
			$this->error('Permission denied.');
		}
	}
	public function newStep($pro){
		$this->assign('id', $pro);
		$this->display();
	}
	public function newStepO(){
		if (check_verify(I('verify'))) {
			$proDB = M('protocol');
			$refD = M('references');
			$map = array('user_id' => $this->userID);
			$refT = $refD->where($map)->getField('name, path');
			$para = I('parameter');
			foreach ($refT as $key => $value) {
				$para = str_replace('{'.$key.'}', $value, $para);
			}
			$data = array('software' => I('software'),
					'parameter' => $para,
					'parent' => intval(I('parent')),
					'user_id' => $this->userID,
					'hash'	=>	$this->hashStep(I('software'), I('parameter')),
			);
			$ret = $proDB->add($data);
			if ($ret){
				$this->success('New step is created successfully!');
			}else{
				$this->error($ret->getError());
			}
		}else{
			$this->error('Wrong code!');
		}
	}
	public function updateParameter(){
		$preMap = array('id'	=>	I('parent'));
		if ($this->checkOwner('protocol_list', $preMap)){
			$map = array(
					'id'	=>	I('step'),
					'parent' => I('parent'),
			);
			$data['parameter'] = I('parameter');
			$stepDb = M('protocol');
			$ret = $stepDb->where($map)->save($data);
			if ($ret){
				$this->success('OK.');
			}else{
				$this->error($ret->getError());
			}
		}else{
			$this->error('No permission!');
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
		}
		$this->assign('stepl', $protocol);
		$this->display();
	}
	public function shareWithPeer($pro, $peer){
		if ($this->checkOwner('protocol_list', array('user_id'	=>	$this->userID))){
			$peerId = checkExistence($peer);
			if ($peerId && $peerId != $this->userID){
				$protDB = M('protocol_list');
				$oldName = $protDB->where('id='.$pro)->getField('name');
				
				$pld = array('name'	=>	$oldName,
					'user_id'	=>	$peerId,
				);
				$ret = $protDB->data($pld)->add();
				if ($ret){
					$protocol = M('protocol');
					$steps = $protocol->where(array('parent'	=>	$pro))->select();
					$data = array();
					foreach ($steps as $step) {
						unset($step['id']);
						$step['parent'] = $ret;
						$step['user_id'] = $peerId;
						$data[] = $step;
					}
					$protocol->addAll($data);
					$this->success('You\'ve successfully shared your protocol with your peer.');
				}else{
					$this->error($ret->getError());
				}
				
			}else{
				$this->error('Peer does not exist!');
			}
			
		}else{
			$this->error('denied.');
		}
	}
	public function shareWithPublic($pro){
		if ($this->checkOwner('protocol_list', array('user_id'	=>	$this->userID))){
			$ret = array();
			$protDB = M('protocol_list');
			$name = $protDB->where('id='.$pro)->getField('name');
			$ret['name'] = $name;
			$ret['donator'] = $u;
			if ($name){
				$protocol = M('protocol');
				$steps = $protocol->where(array('parent'	=>	$pro))->select();
				foreach ($steps as $key => $step) {
					unset($steps[$key]['id']);
					unset($steps[$key]['parent']);
					unset($steps[$key]['user_id']);
				}
				$ret['steps'] = $steps;
				
				$this->success('Your protocol is in CPBQueue\'s pending list now.');
			}else{
				$this->error($ret->getError());
			}
		}else{
			$this->error('denied.');
		}
	}
	public function delStep($pro){
		if ($this->checkOwner('protocol', array('user_id' => $this->userID))){
			$proDB = M('protocol');
			$ret = $proDB->where('id='.intval($pro))->delete();
			if ($ret){
				$this->success('Delete successfully~');
			}else{
				$this->error($ret->getError());
			}
		}else{
			$this->error('Permission denied.');
		}
	}
}
