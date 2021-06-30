#!/usr/bin/env python
# -*- coding: utf-8 -*-
# @Author: Li Yao
# @Date: 12/29/20
# 
# BioQueue is free for personal use and is licensed under
# the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, 
# or (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

from django.db import models
from QueueDB.models import _OwnerModel


class GoogleDriveConnection(_OwnerModel):
    credential_pickle = models.CharField(max_length=255)
    folder_id = models.CharField(max_length=255)
