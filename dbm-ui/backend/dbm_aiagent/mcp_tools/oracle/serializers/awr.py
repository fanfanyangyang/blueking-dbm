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
from datetime import datetime, timedelta

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from backend.dbm_aiagent.mcp_tools.oracle.constants import (
    ORACLE_AWR_MAX_SPAN_HOURS,
    ORACLE_MAX_ROWS,
    ORACLE_TIME_FORMAT,
)
from backend.dbm_aiagent.mcp_tools.oracle.enums import OracleAwrFormat
from backend.dbm_aiagent.mcp_tools.oracle.serializers.basic_info import OracleAddrMixin


class ListAwrSnapshotsInputSerializer(OracleAddrMixin):
    days = serializers.IntegerField(required=False, default=7, min_value=1, max_value=90, help_text=_("回溯天数"))
    limit = serializers.IntegerField(required=False, default=ORACLE_MAX_ROWS, min_value=1, max_value=ORACLE_MAX_ROWS)


class ListAwrSnapshotsOutputSerializer(serializers.Serializer):
    snapshots = serializers.ListField(child=serializers.DictField())
    count = serializers.IntegerField()
    days = serializers.IntegerField()


class AwrFormatMixin(serializers.Serializer):
    """AWR 报告格式入参：默认 text（体积约为 html 的 1/4，便于裁剪与 LLM 分析）。"""

    format = serializers.ChoiceField(
        choices=OracleAwrFormat.get_choices(),
        required=False,
        default=OracleAwrFormat.TEXT.value,
        help_text=_("报告格式：text（默认，供分析）/ html（供人工查看）"),
    )


class AwrReportOutputMixin(serializers.Serializer):
    begin_snap = serializers.IntegerField()
    end_snap = serializers.IntegerField()
    format = serializers.CharField(help_text=_("实际使用的报告格式"))
    report = serializers.CharField(help_text=_("完整报告内容，体积很大"))
    report_size = serializers.IntegerField(help_text=_("报告字符数"))
    truncated = serializers.BooleanField(help_text=_("是否因触达 DRS 行数上限而被截断"))
    warnings = serializers.ListField(child=serializers.CharField(), help_text=_("影响报告可信度的提示"))


class GenerateAwrReportInputSerializer(OracleAddrMixin, AwrFormatMixin):
    begin_snap = serializers.IntegerField(min_value=1, help_text=_("起始快照 ID"))
    end_snap = serializers.IntegerField(min_value=1, help_text=_("结束快照 ID（> begin_snap）"))

    def validate(self, attrs):
        if attrs["end_snap"] <= attrs["begin_snap"]:
            raise serializers.ValidationError(_("end_snap 必须大于 begin_snap"))
        return attrs


class GenerateAwrReportOutputSerializer(AwrReportOutputMixin):
    pass


class GenerateAwrReportByTimeInputSerializer(OracleAddrMixin, AwrFormatMixin):
    begin_time = serializers.CharField(help_text=_("起始时间，格式 YYYY-MM-DD HH:MM:SS（数据库服务器本地时间）"))
    end_time = serializers.CharField(help_text=_("结束时间，格式 YYYY-MM-DD HH:MM:SS（晚于 begin_time）"))

    @staticmethod
    def _parse(value: str, field: str) -> datetime:
        # 不使用 DateTimeField：USE_TZ=True 时它会返回 UTC aware datetime，
        # 而 dba_hist_snapshot.end_interval_time 是不带时区的服务器本地时间，直接比较会整体偏移
        try:
            return datetime.strptime(value, ORACLE_TIME_FORMAT)
        except ValueError:
            raise serializers.ValidationError({field: _("时间格式必须为 YYYY-MM-DD HH:MM:SS")})

    def validate(self, attrs):
        begin = self._parse(attrs["begin_time"], "begin_time")
        end = self._parse(attrs["end_time"], "end_time")
        if end <= begin:
            raise serializers.ValidationError(_("end_time 必须晚于 begin_time"))
        if end - begin > timedelta(hours=ORACLE_AWR_MAX_SPAN_HOURS):
            raise serializers.ValidationError(
                _("时间跨度不能超过 {hours} 小时，跨度过大时统计量会被平均稀释").format(hours=ORACLE_AWR_MAX_SPAN_HOURS)
            )
        return attrs


class GenerateAwrReportByTimeOutputSerializer(AwrReportOutputMixin):
    requested_begin_time = serializers.CharField(help_text=_("请求的起始时间"))
    requested_end_time = serializers.CharField(help_text=_("请求的结束时间"))
    actual_begin_time = serializers.CharField(help_text=_("begin_snap 对应时刻，可能早于请求起点"))
    actual_end_time = serializers.CharField(help_text=_("end_snap 对应时刻，可能晚于请求终点"))
