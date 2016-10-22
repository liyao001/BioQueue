<?php
namespace Home\Controller;
use Think\Controller;
class AuthController extends Controller {
    public $tmp;
    
	public function _initialize(){
		if(intval(is_login()) < 1){
			$this->redirect('Protect/login');
            $this->tmp = session('user_auth');
		}
	}
	public function checkOwner($model, $map){
		$logI = session('user_auth');
		if ($logI['status'] >= 1){
			$modelDB = M($model);
			$uid = $modelDB->where($map)->getField('user_id');
			if ($uid == $logI['id'] || $logI['status'] >= 2){
				return 1;
			}else{
				return 0;
			}
		}else{
			return 0;
		}
	}
	public function verify(){
		$verify = new \Think\Verify();
		#$verify->useImgBg = true;
		$verify->entry(1);
	}
	public function logout(){
		session ( 'user_auth', null );
		session ( 'user_auth_sign', null );
		$this->redirect('Protect/login');
	}
	protected function hashStep($software, $parameters){
		$trimedParameter = ltrim(rtrim($parameters));
		return md5($software.' '.$parameters);
	}
}
?>