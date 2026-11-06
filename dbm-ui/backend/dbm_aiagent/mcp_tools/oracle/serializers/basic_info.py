# -*- coding: utf-8 -*-
"""
TencentBlueKing is pleased to support the open source community by making 蓝鲸智云-DB管理系统(BlueKing-BK-DBM) available.
Copyright (C) 2017-2023 THL A29 Limited, a Tencent company. All rights reserved.
Licensed under the MIT License (the "License"); you may not use this file except in compliance with the License.
You may obtain a copy of the License at https://opensource.org/licenses/MIT
Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on
an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the
specific language governing permissions and limitations under the License.
"""
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers


class OracleAddrMixin(serializers.Serializer):
    """所有 Oracle MCP 工具的通用入参：bk_cloud_id 和 address 均必填。"""

    bk_cloud_id = serializers.IntegerField(help_text=_("云区域 ID"))
    address = serializers.CharField(help_text=_("ip:port 形式的实例地址（鉴权维度）"))


class GetInstanceInfoInputSerializer(OracleAddrMixin):
    pass


class GetInstanceInfoOutputSerializer(serializers.Serializer):
    instance = serializers.DictField(help_text=_("v$instance 关键字段"))
    database = serializers.DictField(help_text=_("v$database 关键字段"))


class GetDbVersionInputSerializer(OracleAddrMixin):
    pass


class GetDbVersionOutputSerializer(serializers.Serializer):
    banners = serializers.ListField(child=serializers.CharField(), help_text=_("版本信息行"))


class GetDbParametersInputSerializer(OracleAddrMixin):
    names = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_empty=True,
        help_text=_("参数名列表，为空则返回全部（截断到 ORACLE_MAX_ROWS）"),
    )


class GetDbParametersOutputSerializer(serializers.Serializer):
    parameters = serializers.ListField(child=serializers.DictField())
    truncated = serializers.BooleanField(help_text=_("是否因超出上限被截断"))
