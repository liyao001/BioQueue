<?php
function check_verify($code, $id = 1){
    $verify = new \Think\Verify();
    return $verify->check($code, $id);
}
function check_verify_t($code, $id = ''){
    $verify = new \Think\Verify();
    return $verify->check($code, $id);
}
function salt($namespace='CPBQueue'){
	static $guid = '';
    $uid = uniqid("", true);
    $data = $namespace;
    $data .= $_SERVER['REQUEST_TIME'];
    $data .= $_SERVER['HTTP_USER_AGENT'];
    $data .= $_SERVER['LOCAL_ADDR'];
    $data .= $_SERVER['LOCAL_PORT'];
    $data .= $_SERVER['REMOTE_ADDR'];
    $data .= $_SERVER['REMOTE_PORT'];
    $hash = strtoupper(hash('ripemd128', $uid . $guid . md5($data)));
    $guid = '{' .   
            substr($hash,  0,  8) . 
            '-' .
            substr($hash,  8,  4) .
            '-' .
            substr($hash, 12,  4) .
            '-' .
            substr($hash, 16,  4) .
            '-' .
            substr($hash, 20, 12) .
            '}';
    return $guid;
}
function md5plus($passwd, $salt){
	$encrypted = $passwd.$salt;
	for ($i = 0; $i < 5; $i++){
		$encrypted = md5($encrypted);
	}
	return $encrypted;
}
function data_auth_sign($data) {
	if(!is_array($data)){
		$data = (array)$data;
	}
	ksort($data);
	$code = http_build_query($data);
	$sign = sha1($code);
	return $sign;
}
function is_login(){
	$user = session('user_auth');
	if (empty($user)) {
		return 0;
	} else {
		return session('user_auth_sign') == data_auth_sign($user) ? $user['status'] : 0;
	}
}
function pathJoin(){
    $args = func_get_args();
    if (strtoupper(substr(PHP_OS, 0, 3)) === 'WIN') {//for windows
        $path = array_shift($args);
        $tmp = splitdrive($path);
        $result_drive=$tmp[0]; $result_path=$tmp[1];
        foreach ($args as $p) {
            $tmp = splitdrive($p);
            $p_drive=$tmp[0]; $p_path=$tmp[1];

            if ($p_path && ($p_path[0] == '\\' || $p_path[0] == '/')){
                if ($p_drive || !$result_drive){
                    $result_drive = $p_drive;
                }
                $result_path = $p_path;
                continue;
            }elseif ($p_drive && $p_drive != $result_drive) {
                if (strtolower($p_drive) != strtolower($result_drive)){
                    $result_drive = $p_drive;
                    $result_path = $p_path;
                    continue;
                }
                $result_drive = $p_drive;
            }
            if ($result_path && !(substr($result_path, -1, 1) == '\\' || substr($result_path, -1, 1) == '/')){
                $result_path = $result_path.'\\';
            }
            $result_path = $result_path.$p_path;
        }
        if ($result_path && !($result_path[0] == '\\' || $result_path[0] == '/') && $result_drive && substr($result_drive, -1) != ':'){
            return $result_drive.'\\'.$result_path;
        }
        return $result_drive.$result_path;
    }else{//for POSIX-based OS
        $path = $args[0];
        for ($i=1; $i < count($args); $i++) { 
            $b = $args[$i];
            if (strpos($b, '/') === 0){
                $path = $b;
            }elseif ($path == '' || substr($path, -1, 1) === '/') {
                $path .= $b;
            }else{
                $path .= '/'.$b;
            }
        }
    }
    return $path;
}
function splitdrive($p){
    $sep = '\\';
    $altsep = '/';
    $res = array();
    if (strlen($p) > 1){
        $normp = str_replace('/', '\\', $p);
        if (substr($normp, 0, 2) == '\\\\' && substr($normp, 2, 2) != '\\'){
            $index = strpos($normp, '\\', 2);
            if ($index === false){
                $res[0]='';
                $res[1]=$p;
                return $res;
            }
            $index2 = strpos($normp, '\\', $index+1);
            if ($index2 == $index + 1){
                $res[0]='';
                $res[1]=$p;
                return $res;
            }elseif ($index2 === false) {
                $index2 = strlen($p);
            }
            $res[0]=substr($p, 0, $index2);
            $res[1]=substr($p, $index2);
            return $res;
        }
        if (substr($p, 1, 1) == ':'){
            $res[0] = substr($p, 0, 2);
            $res[1] = substr($p, 2);
            return $res;
        }
        $res[0] = '';
        $res[1] = $p;
        return $res;
    }else{
    	$res[0] = '';
    	$res[1] = $p;
    	return $res;
    }
}
function getFreeSpace($drive) {
	return disk_free_space($drive);
}
function checkExistence($user){
	$userDb = M('user');
	$ext = $userDb->where(array('user'	=>	$user))->getField('id');
	if ($ext){
		return $ext;
	}else{
		return 0;
	}
}
?>