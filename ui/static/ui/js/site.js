$(document)
	.ajaxStart(function(){
		$("button:submit").attr("disabled", true);
	})
	.ajaxStop(function(){
		$("button:submit").attr("disabled", false);
	});
//update verify image
$(function(){
	var verifyimg = $(".verifyimg").attr("src");
	$(".reloadverify").click(function(){
		if( verifyimg.indexOf('?')>0){
			$(".verifyimg").attr("src", verifyimg+'&random='+Math.random());
		}else{
			$(".verifyimg").attr("src", verifyimg.replace(/\?.*$/,'')+'?'+Math.random());
		}
	});
});