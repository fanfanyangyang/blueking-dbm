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

from backend.dbm_aiagent.mcp_tools.oracle.constants import (
    ORACLE_ASH_DEFAULT_MINUTES,
    ORACLE_ASH_MAX_MINUTES,
    ORACLE_MAX_ROWS,
)
from backend.dbm_aiagent.mcp_tools.oracle.enums import OracleXplanFormat
from backend.dbm_aiagent.mcp_tools.oracle.serializers.basic_info import OracleAddrMixin


class GetSqlPlanInputSerializer(OracleAddrMixin):
    sql_id = serializers.CharField(help_text=_("SQL ID（Oracle v$sql.sql_id）"))
    child_number = serializers.IntegerField(
        required=False, allow_null=True, default=None, help_text=_("子游标号，不传则输出全部子游标")
    )
    format = serializers.ChoiceField(
        choices=OracleXplanFormat.get_choices(),
        required=False,
        default=OracleXplanFormat.ALL.value,
        help_text=_(
            "计划格式：ALL（默认，含谓词与列投影）/ TYPICAL / ADVANCED（含 Outline Data）/ "
            "ALLSTATS LAST（含实际执行统计，要求 SQL 执行时带 GATHER_PLAN_STATISTICS 或 STATISTICS_LEVEL=ALL）"
        ),
    )


class GetSqlPlanOutputSerializer(serializers.Serializer):
    sql_id = serializers.CharField()
    format = serializers.CharField(help_text=_("实际使用的计划格式"))
    found = serializers.BooleanField(help_text=_("游标是否仍在共享池中"))
    plan_text = serializers.CharField(help_text=_("DBMS_XPLAN 格式化后的计划文本"))
    line_count = serializers.IntegerField(help_text=_("计划文本行数"))
    warnings = serializers.ListField(child=serializers.CharField(), help_text=_("影响计划可用性的提示"))


# ---------- ASH ----------


class AshWindowInputMixin(OracleAddrMixin):
    minutes = serializers.IntegerField(
        required=False,
        default=ORACLE_ASH_DEFAULT_MINUTES,
        min_value=1,
        max_value=ORACLE_ASH_MAX_MINUTES,
        help_text=_("分析最近多少分钟（内存 ASH 通常只保留约 1 小时，超出部分以 window.truncated 标识）"),
    )


class GetAshWaitClassInputSerializer(AshWindowInputMixin):
    pass


class GetAshWaitClassOutputSerializer(serializers.Serializer):
    window = serializers.DictField(
        help_text=_(
            "实际统计窗口；truncated=true 表示 ASH 数据不足请求窗口；total_aas 为窗口内前台会话整体 AAS；"
            "load 为 AAS(ON CPU) 与 cpu_count 对比得出的 CPU 繁忙度（level + summary + wait_dominant）"
        )
    )
    wait_classes = serializers.ListField(child=serializers.DictField())
    count = serializers.IntegerField()


class GetAshTopEventsInputSerializer(AshWindowInputMixin):
    limit = serializers.IntegerField(required=False, default=20, min_value=1, max_value=ORACLE_MAX_ROWS)


class GetAshTopEventsOutputSerializer(serializers.Serializer):
    window = serializers.DictField(
        help_text=_(
            "实际统计窗口；truncated=true 表示 ASH 数据不足请求窗口；total_aas 为窗口内前台会话整体 AAS；"
            "load 为 AAS(ON CPU) 与 cpu_count 对比得出的 CPU 繁忙度（level + summary + wait_dominant）"
        )
    )
    events = serializers.ListField(child=serializers.DictField())
    count = serializers.IntegerField()


class GetAshTopSqlInputSerializer(AshWindowInputMixin):
    limit = serializers.IntegerField(required=False, default=15, min_value=1, max_value=ORACLE_MAX_ROWS)


class GetAshTopSqlOutputSerializer(serializers.Serializer):
    window = serializers.DictField(
        help_text=_(
            "实际统计窗口；truncated=true 表示 ASH 数据不足请求窗口；total_aas 为窗口内前台会话整体 AAS；"
            "load 为 AAS(ON CPU) 与 cpu_count 对比得出的 CPU 繁忙度（level + summary + wait_dominant）"
        )
    )
    top_sql = serializers.ListField(child=serializers.DictField())
    count = serializers.IntegerField()
