#!/usr/bin/env python
# coding=utf-8
# Created by: Li Yao
# Created on: 8/2/20
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json
import hashlib
from django.apps import apps
from QueueDB.models import Profile


class Api(object):
    @staticmethod
    def ret_info(valid, results):
        json_data = dict()
        json_data['valid'] = valid
        json_data['results'] = results
        return JsonResponse(json_data)

    def _valid(self):
        """
        Validate API request

        :return: bool
        """
        try:
            user_profile = Profile.objects.get(api_key=self.api_key)
            api_secret = user_profile.api_secret
            m = hashlib.md5()
            par_str = json.dumps(self.pars, sort_keys=True) + api_secret
            m.update(par_str.encode())
            if self.check_sum == m.hexdigest():
                self.user = user_profile.delegate
                return True
            else:
                return False
        except Profile.DoesNotExist:
            return False

    def __init__(self, target_model, api_key, pars, check_sum):
        self.api_key = api_key
        self.check_sum = check_sum
        self._protected_models = {"Job", "Protocol", "ProtocolList", "Profile", "VirtualEnvironment", "Prediction",
                                  "Reference", "Resource", "Training", "Experiment", "Sample", "FileArchives",
                                  "Workspace"}
        self.is_valid = 1
        del pars["check_sum"]
        del pars["model"]
        self.pars = pars
        self.user = None
        if target_model in self._protected_models:
            self.is_valid = 0
        if not self._valid():
            self.is_valid = 0

    @property
    def protected_models(self):
        return self._protected_models

    def create_data(self):
        form_mod = __import__("..plugins.{model}", fromlist=["create_obj", ])
        if form_mod.create_obj(self.pars, self.user):
            return Api.ret_info(valid=1, results="Saved")
        else:
            return Api.ret_info(valid=0, results="Failed")


@csrf_exempt
def plugin_post(request):
    models = set(model.__name__ for model in apps.get_models())
    if "model" in request.POST and "API_key" in request.POST and "check_sum" in request.POST:
        if request.POST["model"] in models and request.POST["API_key"] is not None:
            api_obj = Api(request.POST["model"], request.POST["API_key"],
                          request.POST.copy(), request.POST["check_sum"])
            return api_obj.create_data()
    else:
        return JsonResponse()

