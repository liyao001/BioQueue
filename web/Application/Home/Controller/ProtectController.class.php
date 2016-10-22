<?php
namespace Home\Controller;
use Think\Controller;
class ProtectController extends Controller {
	public function login(){
		C('TOKEN_ON',false);
		$this->display();	
	}
	public function log(){
		if (check_verify(I('verify'), '')) {
			$user = M('user');
			$map = array('user'=>I('email'));
			$ret = $user->where($map)->find();
			if ($ret){
				if ($ret['passwd'] == md5plus(I('pw'), $ret['salt'])){
					session ( 'user_auth', $ret );
					session ( 'user_auth_sign', data_auth_sign ( $ret ) );
					$this->success('Log in successfully', U('Index/index'));
				}else{
					$this->error('Wrong password!');
				}
			}else{
				$this->error('User doesn\'t exists!');
			}
		}else{
			$this->error('Wrong CAPTCHA code!');
		}
	}
	public function reg(){
		$user = M('user');
		$isInit = $user->where('status=3')->find();
		if (!$isInit) {
			$_POST['status'] = 3;
		}else{
			$_POST['status'] = 0;
		}
		$_POST['salt'] = salt();
		$_POST['passwd'] = md5plus($_POST['passwd'], $_POST['salt']);
		if ($user->create()){
			$result = $user->add();
    		if($result){
        		#$insertId = $result;
				$this->success($result);
    		}else{
				$this->error($result);
			}
		}else{
			$this->error($user->getError());
		}
	}
	public function hehe(){
		$Verify = new \Think\Verify();
		$Verify->entry();
	}
}
?>