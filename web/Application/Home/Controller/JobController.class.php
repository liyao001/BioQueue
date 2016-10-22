<?php
namespace Home\Controller;
use Think\Controller;
class JobController extends AuthController {
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
	public function ajob($p=1){
		$proDB = M('protocol_list');
		$queDB = M('queue');
		$logI = session('user_auth');
		if ($this->userLEVEL >= 2){
			$protocol = $proDB->order('name asc')->select();
		}else{
			$map = array('user_id' => $logI['id'], );
			$protocol = $proDB->where($map)->order('name asc')->select();
		}
		$this->assign('prol', $protocol);
		$this->display();
	}
	public function qjob($p=1){
		$queDB = M('queue');
		$logI = session('user_auth');
		if ($this->userLEVEL >= 2){
			$count = $queDB->count();
			$que = $queDB->order('id desc')->page($_GET['p'].',25')->select();
		}else{
			$map = array('user_id' => $logI['id'], );
			$count = $queDB->where($map)->count();
			$que = $queDB->where($map)->order('id desc')->page($_GET['p'].',25')->select();
		}
		$Page       = new \Think\Page($count,25);
		$show       = $Page->show();
		$this->assign('page', $show);
		$this->assign('quel', $que);
		$this->display();
	}
	public function reRun($job){
		if ($this->checkOwner('queue', array('user_id' => $this->userID))){
			$queue = M('queue');
			$data['status'] = 0;
			$data['resume'] = -1;
			$ret = $queue->where('id='.$job)->save($data);
			if ($ret){
				$this->success('ok');
			}else{
				$this->error('fail');
			}
		}else{
			$this->error('fail');
		}
	}
	public function resume($job){
		if ($this->checkOwner('queue', array('user_id' => $this->userID))){
			$queue = M('queue');
			$data['status'] = 0;
			$ret = $queue->where('id='.$job)->save($data);
			if ($ret){
				$this->success('ok');
			}else{
				$this->error('fail');
			}
		}else{
			$this->error('fail');
		}
	}
	public function terminate($job){
		if ($this->checkOwner('queue', array('user_id' => $this->userID))){
			$queue = M('queue');
			$data['ter'] = 1;
			$ret = $queue->where('id='.$job)->save($data);
			if ($ret){
				$this->success('ok');
			}else{
				$this->error('fail');
			}
		}else{
			$this->error('fail');
		}
	}
	private function delFolder($dir){
		$dh=opendir($dir);
		while ($file=readdir($dh)) {
			if($file!="." && $file!="..") {
				$fullpath=$dir."/".$file;
				if(!is_dir($fullpath)) {
					unlink($fullpath);
				} else {
					$this->delFolder($fullpath);
				}
			}
		}
		closedir($dh);
		if(rmdir($dir)) {
			return true;
		} else {
			return false;
		}
	}
	public function delJob($job){
		if ($this->checkOwner('queue', array('user_id' => $this->userID))){
			$queDB = M('queue');
			$jobStore = $queDB->where('id='.intval($job))->getField('result');
			$queDB->where('id='.intval($job))->delete();
			if ($jobStore != ''){
				$delPath = pathJoin(F('RUNFOLDER'), $this->userID, $jobStore);
				if ($this->delFolder($delPath)) {
					$this->success('Job deleted!');
				}else{
					$this->error('Job deleted, but the output file cannot be removed.');
				}
				
			}else{
				$this->success('Job deleted, but the output file cannot be removed.');
			}
			
		}else{
			$this->error('Permission denied.');
		}
	}
	public function newJob(){
		if (check_verify(I('verify'))) {
			$queDB = M('queue');
			$par = I('parameter');
			if (strpos($par, '=') === false){
				$data = array('protocol' => intval(I('protocol')),
						'inputFile' => I('inputFile'),
						'parameter' => $par,
						'run_dir' => F('RUNFOLDER'),
						'user_id' => $this->userID,);
			}else if (substr($par, -1, 1) != ';'){
				$data = array('protocol' => intval(I('protocol')),
						'inputFile' => I('inputFile'),
						'parameter' => $par.';',
						'run_dir' => F('RUNFOLDER'),
						'user_id' => $this->userID,);
			}else{
				$data = array('protocol' => intval(I('protocol')),
						'inputFile' => I('inputFile'),
						'parameter' => $par,
						'run_dir' => F('RUNFOLDER'),
						'user_id' => $this->userID,);
			}
	
			$queDB->add($data);
			$this->success('Successfully added job into queue.');
		}else{
			$this->error('Wrong code!');
		}
	}
	public function showFolder($job){
		if ($this->checkOwner('queue', array('user_id' => $this->userID))){
			$result = array();
			$queDB = M('queue');
			$jobStore = $queDB->where('id='.intval($job))->getField('result');
			$userPath = pathJoin(F('RUNFOLDER'), $this->userID);
			session('UP-'.$this->userID, $userPath);
			$storePath = pathJoin(F('RUNFOLDER'), $this->userID, $jobStore);
			$this->treeFolder($userPath, $storePath);
		}
	}
	public function showLog($jobId){
		if ($this->checkOwner('queue', array('id' => $jobId, ))){
			$fp = fopen(C('logStore').$jobId, 'r');
			$pos = -2;
			for ($i = 0; $i < 50; $i++) {
				$buffer = $this->rfgets($fp);
				if ($buffer){
					echo $buffer . '<br />';
				}
			}
		}else{
			echo 'Permission denied.';
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
	public function getFile($file, $name) {
		set_time_limit(0);
		ignore_user_abort(false);
		ini_set('output_buffering', 0);
		ini_set('zlib.output_compression', 0);
		$filepath = session('UP-'.$this->userID).'/'.base64_decode($file);
		$filename = base64_decode($name);
		$chunk = 10*1024*1024;
		if (file_exists($filepath)){
			$fh = fopen($filepath, 'rb');
		
			if ($fh === false) {
				echo "Unable to open file";
			}
		
			header('Content-Description: File Transfer');
			header('Content-Type: application/octet-stream');
			header('Content-Disposition: attachment; filename="' . $filename . '"');
			header('Expires: 0');
			header('Cache-Control: must-revalidate');
			header('Pragma: public');
			header('Content-Length: ' . filesize($filepath));
		
			while (!feof($fh)) {
				echo fread($fh, $chunk);
				ob_flush();
				flush();
			}
			exit;
		}else{
			$this->error('File does not exist!');
		}
	}
	public function delFile($file) {
		$filepath = session('UP-'.$this->userID).'/'.base64_decode($file);
		if (file_exists($filepath)){
			unlink($filepath);
			$this->success('ok');
		}else{
			$this->error('File does not exist!');
		}
	}
	private function rfgets($handle) {
		$line = null;
		$n = 0;
	
		if ($handle) {
			$line = '';
	
			$started = false;
			$gotline = false;
	
			while (!$gotline) {
				if (ftell($handle) == 0) {
					fseek($handle, -1, SEEK_END);
				} else {
					fseek($handle, -2, SEEK_CUR);
				}
	
				$readres = ($char = fgetc($handle));
	
				if (false === $readres) {
					$gotline = true;
				} elseif ($char == "\n" || $char == "\r") {
					if ($started)
						$gotline = true;
						else
							$started = true;
				} elseif ($started) {
					$line .= $char;
				}
			}
		}
	
		fseek($handle, 1, SEEK_CUR);
	
		return strrev($line);
	}
}
?>