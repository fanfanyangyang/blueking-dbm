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
from backend.dbm_aiagent.mcp_tools.oracle.enums import OracleSortBy
from backend.dbm_aiagent.mcp_tools.oracle.serializers.basic_info import OracleAddrMixin


class GetTopSqlByCpuInputSerializer(OracleAddrMixin):
    sort_by = serializers.ChoiceField(
        choices=OracleSortBy.get_choices(),
        required=False,
        default=OracleSortBy.CPU_TIME.value,
        help_text=_("排序维度"),
    )
    limit = serializers.IntegerField(required=False, default=ORACLE_MAX_ROWS, min_value=1, max_value=ORACLE_MAX_ROWS)


class GetTopSqlByCpuOutputSerializer(serializers.Serializer):
    sort_by = serializers.CharField()
    top_sql = serializers.ListField(child=serializers.DictField())
    count = serializers.IntegerField()


class GetTopSqlByIoInputSerializer(OracleAddrMixin):
    limit = serializers.IntegerField(required=False, default=ORACLE_MAX_ROWS, min_value=1, max_value=ORACLE_MAX_ROWS)


class GetTopSqlByIoOutputSerializer(serializers.Serializer):
    top_sql = serializers.ListField(child=serializers.DictField())
    count = serializers.IntegerField()


class GetWaitEventsInputSerializer(OracleAddrMixin):
    limit = serializers.IntegerField(required=False, default=ORACLE_MAX_ROWS, min_value=1, max_value=ORACLE_MAX_ROWS)


class GetWaitEventsOutputSerializer(serializers.Serializer):
    events = serializers.ListField(child=serializers.DictField())
    count = serializers.IntegerField()


class GetSqlPlanInputSerializer(OracleAddrMixin):
    sql_id = serializers.CharField(help_text=_("SQL ID（Oracle v$sql.sql_id）"))
    child_number = serializers.IntegerField(required=False, allow_null=True, default=None)


class GetSqlPlanOutputSerializer(serializers.Serializer):
    sql_id = serializers.CharField()
    plan_steps = serializers.ListField(child=serializers.DictField())
    count = serializers.IntegerField()
