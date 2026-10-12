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

from backend.dbm_aiagent.mcp_tools.oracle.constants import ORACLE_MAX_ROWS
from backend.dbm_aiagent.mcp_tools.oracle.serializers.basic_info import OracleAddrMixin


class ListAwrSnapshotsInputSerializer(OracleAddrMixin):
    days = serializers.IntegerField(required=False, default=7, min_value=1, max_value=90, help_text=_("回溯天数"))
    limit = serializers.IntegerField(required=False, default=ORACLE_MAX_ROWS, min_value=1, max_value=ORACLE_MAX_ROWS)


class ListAwrSnapshotsOutputSerializer(serializers.Serializer):
    snapshots = serializers.ListField(child=serializers.DictField())
    count = serializers.IntegerField()
    days = serializers.IntegerField()


class GenerateAwrReportInputSerializer(OracleAddrMixin):
    begin_snap = serializers.IntegerField(min_value=1, help_text=_("起始快照 ID"))
    end_snap = serializers.IntegerField(min_value=1, help_text=_("结束快照 ID（> begin_snap）"))
    dbid = serializers.IntegerField(required=False, allow_null=True, default=None)
    inst_num = serializers.IntegerField(required=False, allow_null=True, default=None)

    def validate(self, attrs):
        if attrs["end_snap"] <= attrs["begin_snap"]:
            raise serializers.ValidationError(_("end_snap 必须大于 begin_snap"))
        return attrs


class GenerateAwrReportOutputSerializer(serializers.Serializer):
    dbid = serializers.IntegerField()
    instance_number = serializers.IntegerField()
    begin_snap = serializers.IntegerField()
    end_snap = serializers.IntegerField()
    report_html = serializers.CharField()
    report_size = serializers.IntegerField()
