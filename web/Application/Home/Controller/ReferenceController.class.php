<?php
namespace Home\Controller;
use Think\Controller;

class ReferenceController extends AuthController {
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
	public function index(){
    	$refDB = M('references');
        if ($this->userLEVEL >= 2){
            $references = $refDB->select();
        }else{
            $map = array('user_id' => $this->userID);
            $references = $refDB->where($map)->select();
        }
    	$this->assign('refl', $references);
    	$this->display();
    }
    public function newReference(){
    	if (check_verify(I('verify'))) {
    		$refDB = M('references');
    		$data = array('name' => I('name'),
    				'path' => I('path'),
    				'user_id' => $this->userID,);
    		$ret = $refDB->add($data);
    		if ($ret){
    			$this->success($ret);
    		}else{
    			$this->error($ret->getError());
    		}
    	}else{
    		$this->error('Wrong CAPTCHA code!');
    	}
    }
    public function delRef($pro){
    	if ($this->checkOwner('references', array('user_id' => $this->userID))){
    		$queDB = M('references');
    		$queDB->where('id='.intval($pro))->delete();
    		$this->success('Deleted!');
    	}else{
    		$this->error('Permission denied.');
    	}
    	 
    }
}