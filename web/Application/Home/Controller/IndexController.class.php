<?php
namespace Home\Controller;
use Think\Controller;
class IndexController extends AuthController {
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
    	$q = M('queue');
    	$map = array();
        if ($this->userLEVEL < 2){
            $map['user_id'] = array('eq', $this->userID);
        }
    	$map['status'] = array('gt', 0);
    	$n = $q->where($map)->count();
    	$this->assign('RUNNING', $n);
		$this->display();
    }
    public function updatePW() {
    	if (I('pw') != I('pw2')) {
    		$this->error('The two password you enter is not the same!');
    	}else{
    		$user = M('user');
    		$map = array('id'	=>	$this->userID,);
    		$salt = $user->where($map)->getField('salt');
    		$data['passwd'] = md5plus(I('pw'), $salt);
    		$ret = $user->where($map)->data($data)->save();
    		if ($ret){
    			$this->logout();
    		}else{
    			$this->error($ret->getError());
    		}
    	}
    }
    public function showWorkspace(){
    	if ($this->checkOwner('queue', array('user_id' => $this->userID))){
    		$userPath = pathJoin(F('RUNFOLDER'), $this->userID);
    		session('UP-'.$this->userID, $userPath);
    		$this->treeFolder($userPath, $userPath);
    	}
    }
    private function treeFolder($up, $directory){
    	$mydir=dir($directory);
    	echo "<ul>";
    	$basedir = str_replace($up, '', $directory);
    	if ($mydir){
    		while(@$file=$mydir->read()){
    			$trace = base64_encode($basedir.'/'.$file);
    			if((is_dir("$directory/$file")) AND ($file!=".") AND ($file!="..")){
    				echo "<li><strong>$file</strong></li>";
    				$this->treeFolder($up, "$directory/$file");
    			}else{
    				if ($file != '.' && $file != '..'){
    					echo "<li><a href='".U('Job/getFile',array('file'=>urldecode($trace),'name'=>urldecode(base64_encode($file))))."'>$file - ".filesize($directory.'/'.$file)."Bytes - ".date("F d Y H:i:s",filemtime($directory.'/'.$file))."</a> - <span class='label label-important' data-path='$trace' style='cursor:pointer;' onclick=delFile(this);>Delete</span></li>";
    				}
    			}
    		}
    		echo "</ul>";
    		$mydir->close();
    	}else{
    		echo 'No Permission.';
    	}
    }
    public function delFile($file) {
    	$filepath = session('UP-'.$this->userID).base64_decode($file);
    	if (file_exists($filepath)){
    		unlink($filepath);
    		$this->success('ok');
    	}else{
    		$this->error('File does not exist!');
    	}
    }
}