<?php
namespace Home\Controller;
use Think\Controller;
class SystemController extends AuthController {
public function delDeadlock(){
        $logI = session('user_auth');
        if ($logI['status'] >= 1){
            $queue = M("queue"); 
            $data['status'] = '-3';
            $queue->where('status>0')->save($data);
            $this->success('Clean successfully.');
        }else{
            $this->error('Permission denied.');
        }
    }
	public function user($p=1){
		$logI = session('user_auth');
		if ($logI['status'] >= 2){
			$userDB = M('user');
    		$que = $userDB->order('id desc')->page($_GET['p'].',25')->select();
			$count      = $userDB->count();
			$Page       = new \Think\Page($count,15);
			$show       = $Page->show();
			$this->assign('page', $show);
			$this->assign('usl', $que);
			$this->display('user');
		}else{
			$this->error('Permission denied!');
		}
	}
	public function deleteUser($toD){
		$logI = session('user_auth');
		if ($logI['status'] >= 2){
			$userDB = M('user');
			$map = array('id'=>intval($toD));
			$ret = $userDB->where($map)->find();
			if ($ret['status'] == 3){
				$this->error('Cannot modify founder\'s infomation!');
			}else if ($ret['status'] == 2){
				if ($logI['status'] == 3){
					$userDB->where('id='.intval($toD))->delete();
					$this->success('OK!');
				}else{
					$this->error('Cannot modify founder\'s infomation!');
				}
			}else{
				$userDB->where('id='.intval($toD))->delete();
				$this->success('OK!');
			}
		}
	}
	public function asAdmin($toD){
		$logI = session('user_auth');
		if ($logI['status'] >= 2){
			$userDB = M('user');
			$map = array('id'=>intval($toD));
			$ret = $userDB->where($map)->find();
			if ($ret['status'] == 3){
				$this->error('Cannot modify founder\'s infomation!');
			}else if ($ret['status'] == 2){
				$this->error('Cannot modify founder\'s infomation!');
			}else{
				$data['status'] = 2;
				$userDB->where('id='.intval($toD))->save($data);
				$this->success('OK!');
			}
		}
	}
	public function asNUser($toD){
		$logI = session('user_auth');
		if ($logI['status'] >= 2){
			$userDB = M('user');
			$map = array('id'=>intval($toD));
			$ret = $userDB->where($map)->find();
			if ($ret['status'] == 3){
				$this->error('Cannot modify founder\'s infomation!');
			}else if ($ret['status'] == 1){
				$this->error('Cannot modify founder\'s infomation!');
			}else{
				$data['status'] = 1;
				$userDB->where('id='.intval($toD))->save($data);
				$this->success('OK!');
			}
		}
	}
    public function index(){
        $logI = session('user_auth');
        if ($logI['status'] >= 2){
            $this->display();
        }else{
            $this->error('Permission denied.');
        }
    }
    public function updateSystemSettings() {
    	$logI = session('user_auth');
    	if ($logI['status'] >= 2){
	    	F('RUNFOLDER', I('path'));
	    	F('CPU', I('cpu'));
	    	F('MEM', I('mem'));
	    	$this->success('OK!');
    	}else{
    		$this->error('Permission denied.');
    	}
    }
}
?>