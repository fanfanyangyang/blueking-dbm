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
import logging

from django.utils.translation import gettext_lazy as _
from rest_framework.response import Response

from backend.constants import IP_PORT_DIVIDER
from backend.db_meta.enums import ClusterType, MachineType
from backend.db_meta.models import Machine
from backend.dbm_aiagent.mcp_tools.common.auth_parser.base import auth_parse_instances
from backend.dbm_aiagent.mcp_tools.constants import DBMMCPTags, DBMMcpTools
from backend.dbm_aiagent.mcp_tools.decorators import mcp_tools_api_decorator
from backend.dbm_aiagent.mcp_tools.exceptions import (
    DBMMcpInstanceNotFoundException,
    DBMMcpNotSupportMachineTypeException,
)
from backend.dbm_aiagent.mcp_tools.oracle.helpers.assert_clustertype import assert_cluster_type
from backend.dbm_aiagent.mcp_tools.oracle.impl.awr import (
    generate_awr_report,
    generate_awr_report_by_time,
    list_awr_snapshots,
)
from backend.dbm_aiagent.mcp_tools.oracle.impl.capacity import get_sga_pga_usage, get_tablespace_usage, get_undo_usage
from backend.dbm_aiagent.mcp_tools.oracle.impl.performance import (
    get_ash_top_events,
    get_ash_top_sql,
    get_ash_wait_class,
    get_sql_plan,
)
from backend.dbm_aiagent.mcp_tools.oracle.impl.session_activity import (
    get_active_sessions,
    get_blocking_sessions,
    get_long_running_queries,
)
from backend.dbm_aiagent.mcp_tools.oracle.impl.status import check_instance_status, get_alert_log_errors
from backend.dbm_aiagent.mcp_tools.oracle.serializers.awr import (
    GenerateAwrReportByTimeInputSerializer,
    GenerateAwrReportByTimeOutputSerializer,
    GenerateAwrReportInputSerializer,
    GenerateAwrReportOutputSerializer,
    ListAwrSnapshotsInputSerializer,
    ListAwrSnapshotsOutputSerializer,
)
from backend.dbm_aiagent.mcp_tools.oracle.serializers.capacity import (
    GetSgaPgaUsageInputSerializer,
    GetSgaPgaUsageOutputSerializer,
    GetTablespaceUsageInputSerializer,
    GetTablespaceUsageOutputSerializer,
    GetUndoUsageInputSerializer,
    GetUndoUsageOutputSerializer,
)
from backend.dbm_aiagent.mcp_tools.oracle.serializers.performance import (
    GetAshTopEventsInputSerializer,
    GetAshTopEventsOutputSerializer,
    GetAshTopSqlInputSerializer,
    GetAshTopSqlOutputSerializer,
    GetAshWaitClassInputSerializer,
    GetAshWaitClassOutputSerializer,
    GetSqlPlanInputSerializer,
    GetSqlPlanOutputSerializer,
)
from backend.dbm_aiagent.mcp_tools.oracle.serializers.session_activity import (
    GetActiveSessionsInputSerializer,
    GetActiveSessionsOutputSerializer,
    GetBlockingSessionsInputSerializer,
    GetBlockingSessionsOutputSerializer,
    GetLongRunningInputSerializer,
    GetLongRunningOutputSerializer,
)
from backend.dbm_aiagent.mcp_tools.oracle.serializers.status import (
    CheckInstanceStatusInputSerializer,
    CheckInstanceStatusOutputSerializer,
    GetAlertLogErrorsInputSerializer,
    GetAlertLogErrorsOutputSerializer,
)
from backend.dbm_aiagent.mcp_tools.views import McpToolsViewSet
from backend.iam_app.handlers.drf_perm.base import DBManagePermission
from backend.iam_app.handlers.drf_perm.mcp import McpClusterDetailPermission

logger = logging.getLogger("root")


class OracleQueryMcpToolsViewSet(McpToolsViewSet):
    """Oracle 只读查询 MCP 工具集（oracle-query）。

    鉴权维度：实例所属集群（bk_cloud_id + address）；统一走 McpClusterDetailPermission + auth_parse_instances。
    对应 MCP server: `oracle-query`，覆盖状态探活 / 会话与活动 / 性能分析 /
    容量 / AWR 报告 等能力。
    """

    default_permission_class = [DBManagePermission()]

    # region 状态探活（2）

    @mcp_tools_api_decorator(
        description=str(
            _(
                "Oracle 实例综合状态探活：连接是否可达、v$instance/v$database 关键状态、会话数与上限使用率、"
                "DG 角色与切换状态，聚合输出 healthy/warning/critical 结论与原因列表，以及本次探活耗时。"
            )
        ),
        request_slz=CheckInstanceStatusInputSerializer,
        response_slz=CheckInstanceStatusOutputSerializer,
        permission_classes=[McpClusterDetailPermission],
        mcp_auth_parser=auth_parse_instances,
        tags=[DBMMCPTags.READ],
        mcp=[DBMMcpTools.ORACLE_QUERY],
        name_prefix="oracle_query",
    )
    def check_instance_status(self, request, *args, **kwargs):
        bk_cloud_id = self.get_param("bk_cloud_id")
        address = self.get_param("address")

        machine_obj = _validate_and_get_machine(bk_cloud_id, address)
        assert_cluster_type(machine_obj, [ClusterType.OraclePrimaryStandby, ClusterType.OracleSingleNone])

        return Response(
            check_instance_status(
                addr=address,
            )
        )

    @mcp_tools_api_decorator(
        description=str(_("查询近 N 分钟的 Oracle 告警日志错误（v$diag_alert_ext），默认 120 分钟。")),
        request_slz=GetAlertLogErrorsInputSerializer,
        response_slz=GetAlertLogErrorsOutputSerializer,
        permission_classes=[McpClusterDetailPermission],
        mcp_auth_parser=auth_parse_instances,
        tags=[DBMMCPTags.READ],
        mcp=[DBMMcpTools.ORACLE_QUERY],
        name_prefix="oracle_query",
    )
    def get_alert_log_errors(self, request, *args, **kwargs):
        bk_cloud_id = self.get_param("bk_cloud_id")
        address = self.get_param("address")

        machine_obj = _validate_and_get_machine(bk_cloud_id, address)
        assert_cluster_type(machine_obj, [ClusterType.OraclePrimaryStandby, ClusterType.OracleSingleNone])

        return Response(
            get_alert_log_errors(
                addr=address,
                minutes=self.get_param("minutes"),
                limit=self.get_param("limit"),
            )
        )

    # endregion

    # region 会话与活动（3）

    @mcp_tools_api_decorator(
        description=str(_("查询 Oracle 活跃会话（v$session, status=ACTIVE 且非 Idle 等待类）。")),
        request_slz=GetActiveSessionsInputSerializer,
        response_slz=GetActiveSessionsOutputSerializer,
        permission_classes=[McpClusterDetailPermission],
        mcp_auth_parser=auth_parse_instances,
        tags=[DBMMCPTags.READ],
        mcp=[DBMMcpTools.ORACLE_QUERY],
        name_prefix="oracle_query",
    )
    def get_active_sessions(self, request, *args, **kwargs):
        bk_cloud_id = self.get_param("bk_cloud_id")
        address = self.get_param("address")

        machine_obj = _validate_and_get_machine(bk_cloud_id, address)
        assert_cluster_type(machine_obj, [ClusterType.OraclePrimaryStandby, ClusterType.OracleSingleNone])

        return Response(
            get_active_sessions(
                addr=address,
                limit=self.get_param("limit"),
            )
        )

    @mcp_tools_api_decorator(
        description=str(_("查询 Oracle 阻塞链（blocker → waiter），用于锁争用排查。")),
        request_slz=GetBlockingSessionsInputSerializer,
        response_slz=GetBlockingSessionsOutputSerializer,
        permission_classes=[McpClusterDetailPermission],
        mcp_auth_parser=auth_parse_instances,
        tags=[DBMMCPTags.READ],
        mcp=[DBMMcpTools.ORACLE_QUERY],
        name_prefix="oracle_query",
    )
    def get_blocking_sessions(self, request, *args, **kwargs):
        bk_cloud_id = self.get_param("bk_cloud_id")
        address = self.get_param("address")

        machine_obj = _validate_and_get_machine(bk_cloud_id, address)
        assert_cluster_type(machine_obj, [ClusterType.OraclePrimaryStandby, ClusterType.OracleSingleNone])

        return Response(
            get_blocking_sessions(
                addr=address,
                limit=self.get_param("limit"),
            )
        )

    @mcp_tools_api_decorator(
        description=str(_("查询长时间运行的 SQL（基于 v$session.last_call_et），min_seconds 可指定最小阈值。")),
        request_slz=GetLongRunningInputSerializer,
        response_slz=GetLongRunningOutputSerializer,
        permission_classes=[McpClusterDetailPermission],
        mcp_auth_parser=auth_parse_instances,
        tags=[DBMMCPTags.READ],
        mcp=[DBMMcpTools.ORACLE_QUERY],
        name_prefix="oracle_query",
    )
    def get_long_running_queries(self, request, *args, **kwargs):
        bk_cloud_id = self.get_param("bk_cloud_id")
        address = self.get_param("address")

        machine_obj = _validate_and_get_machine(bk_cloud_id, address)
        assert_cluster_type(machine_obj, [ClusterType.OraclePrimaryStandby, ClusterType.OracleSingleNone])

        return Response(
            get_long_running_queries(
                addr=address,
                min_seconds=self.get_param("min_seconds"),
                limit=self.get_param("limit"),
            )
        )

    # endregion

    # region 性能分析（4，其中 ASH 3 个受 ORACLE_ENABLE_AWR 开关控制）

    @mcp_tools_api_decorator(
        description=str(
            _(
                "查询指定 sql_id 的执行计划（DBMS_XPLAN.DISPLAY_CURSOR），返回带缩进的执行树、"
                "Predicate Information 与 Note 等官方格式化文本。"
                "format=ALL（默认）/ TYPICAL / ADVANCED / 'ALLSTATS LAST'（含实际执行统计，"
                "要求 SQL 执行时带 GATHER_PLAN_STATISTICS hint 或 STATISTICS_LEVEL=ALL）。"
                "依赖共享池，SQL 被 age out 后 found=false。不传 child_number 则输出全部子游标。"
            )
        ),
        request_slz=GetSqlPlanInputSerializer,
        response_slz=GetSqlPlanOutputSerializer,
        permission_classes=[McpClusterDetailPermission],
        mcp_auth_parser=auth_parse_instances,
        tags=[DBMMCPTags.READ],
        mcp=[DBMMcpTools.ORACLE_QUERY],
        name_prefix="oracle_query",
    )
    def get_sql_plan(self, request, *args, **kwargs):
        bk_cloud_id = self.get_param("bk_cloud_id")
        address = self.get_param("address")

        machine_obj = _validate_and_get_machine(bk_cloud_id, address)
        assert_cluster_type(machine_obj, [ClusterType.OraclePrimaryStandby, ClusterType.OracleSingleNone])

        return Response(
            get_sql_plan(
                sql_id=self.get_param("sql_id"),
                addr=address,
                child_number=self.get_param("child_number"),
                plan_format=self.get_param("format"),
            )
        )

    @mcp_tools_api_decorator(
        description=str(
            _(
                "ASH 下钻第 1 步：最近 N 分钟（默认 30）前台会话 DB time 按 wait_class 汇总"
                "（v$active_session_history，1 样本≈1 秒），用于判断时间主要花在 CPU / User I/O / Concurrency / "
                "Application 等哪个方向。返回 db_time_sec、aas、pct；window.truncated=true 表示 ASH 数据不足请求窗口；"
                "window.total_aas 为整体平均活跃会话数，可与 cpu_count 对比判断负载水平。"
                "需开启 ORACLE_ENABLE_AWR（Diagnostics Pack）。"
            )
        ),
        request_slz=GetAshWaitClassInputSerializer,
        response_slz=GetAshWaitClassOutputSerializer,
        permission_classes=[McpClusterDetailPermission],
        mcp_auth_parser=auth_parse_instances,
        tags=[DBMMCPTags.READ],
        mcp=[DBMMcpTools.ORACLE_QUERY],
        name_prefix="oracle_query",
    )
    def get_ash_wait_class(self, request, *args, **kwargs):
        bk_cloud_id = self.get_param("bk_cloud_id")
        address = self.get_param("address")

        machine_obj = _validate_and_get_machine(bk_cloud_id, address)
        assert_cluster_type(machine_obj, [ClusterType.OraclePrimaryStandby, ClusterType.OracleSingleNone])

        return Response(get_ash_wait_class(addr=address, minutes=self.get_param("minutes")))

    @mcp_tools_api_decorator(
        description=str(
            _(
                "ASH 下钻第 2 步：最近 N 分钟（默认 30）前台会话 Top 等待事件，含 db_time_sec、aas、pct、"
                "pct_cum（累计占比）、sessions（涉及会话数）、top_sql_id（该事件下贡献最多的 SQL）。"
                "反映的是最近时间段的等待分布。需开启 ORACLE_ENABLE_AWR。"
            )
        ),
        request_slz=GetAshTopEventsInputSerializer,
        response_slz=GetAshTopEventsOutputSerializer,
        permission_classes=[McpClusterDetailPermission],
        mcp_auth_parser=auth_parse_instances,
        tags=[DBMMCPTags.READ],
        mcp=[DBMMcpTools.ORACLE_QUERY],
        name_prefix="oracle_query",
    )
    def get_ash_top_events(self, request, *args, **kwargs):
        bk_cloud_id = self.get_param("bk_cloud_id")
        address = self.get_param("address")

        machine_obj = _validate_and_get_machine(bk_cloud_id, address)
        assert_cluster_type(machine_obj, [ClusterType.OraclePrimaryStandby, ClusterType.OracleSingleNone])

        return Response(
            get_ash_top_events(addr=address, minutes=self.get_param("minutes"), limit=self.get_param("limit"))
        )

    @mcp_tools_api_decorator(
        description=str(
            _(
                "ASH 下钻第 3 步：最近 N 分钟（默认 30）按 DB time 排序的 Top SQL，含 aas、pct_of_db_time、"
                "top_event / top_event_pct（主要等待）、plan_count（窗口内执行计划个数，>1 可能发生计划变化）、"
                "top_plan_hash_value、sql_text。可继续用 get_sql_plan 查看执行计划。需开启 ORACLE_ENABLE_AWR。"
            )
        ),
        request_slz=GetAshTopSqlInputSerializer,
        response_slz=GetAshTopSqlOutputSerializer,
        permission_classes=[McpClusterDetailPermission],
        mcp_auth_parser=auth_parse_instances,
        tags=[DBMMCPTags.READ],
        mcp=[DBMMcpTools.ORACLE_QUERY],
        name_prefix="oracle_query",
    )
    def get_ash_top_sql(self, request, *args, **kwargs):
        bk_cloud_id = self.get_param("bk_cloud_id")
        address = self.get_param("address")

        machine_obj = _validate_and_get_machine(bk_cloud_id, address)
        assert_cluster_type(machine_obj, [ClusterType.OraclePrimaryStandby, ClusterType.OracleSingleNone])

        return Response(
            get_ash_top_sql(addr=address, minutes=self.get_param("minutes"), limit=self.get_param("limit"))
        )

    # endregion

    # region 容量（3）

    @mcp_tools_api_decorator(
        description=str(_("查询 Oracle 表空间使用率（按已用占比降序，含 autoextensible 与 max_mb）。")),
        request_slz=GetTablespaceUsageInputSerializer,
        response_slz=GetTablespaceUsageOutputSerializer,
        permission_classes=[McpClusterDetailPermission],
        mcp_auth_parser=auth_parse_instances,
        tags=[DBMMCPTags.READ],
        mcp=[DBMMcpTools.ORACLE_QUERY],
        name_prefix="oracle_query",
    )
    def get_tablespace_usage(self, request, *args, **kwargs):
        bk_cloud_id = self.get_param("bk_cloud_id")
        address = self.get_param("address")

        machine_obj = _validate_and_get_machine(bk_cloud_id, address)
        assert_cluster_type(machine_obj, [ClusterType.OraclePrimaryStandby, ClusterType.OracleSingleNone])

        return Response(
            get_tablespace_usage(
                addr=address,
                limit=self.get_param("limit"),
            )
        )

    @mcp_tools_api_decorator(
        description=str(_("查询 Oracle Undo 表空间使用情况（按 ACTIVE/UNEXPIRED/EXPIRED 分组）。")),
        request_slz=GetUndoUsageInputSerializer,
        response_slz=GetUndoUsageOutputSerializer,
        permission_classes=[McpClusterDetailPermission],
        mcp_auth_parser=auth_parse_instances,
        tags=[DBMMCPTags.READ],
        mcp=[DBMMcpTools.ORACLE_QUERY],
        name_prefix="oracle_query",
    )
    def get_undo_usage(self, request, *args, **kwargs):
        bk_cloud_id = self.get_param("bk_cloud_id")
        address = self.get_param("address")

        machine_obj = _validate_and_get_machine(bk_cloud_id, address)
        assert_cluster_type(machine_obj, [ClusterType.OraclePrimaryStandby, ClusterType.OracleSingleNone])

        return Response(
            get_undo_usage(
                addr=address,
            )
        )

    @mcp_tools_api_decorator(
        description=str(_("查询 Oracle SGA / PGA 使用情况（v$sga + v$pgastat）。")),
        request_slz=GetSgaPgaUsageInputSerializer,
        response_slz=GetSgaPgaUsageOutputSerializer,
        permission_classes=[McpClusterDetailPermission],
        mcp_auth_parser=auth_parse_instances,
        tags=[DBMMCPTags.READ],
        mcp=[DBMMcpTools.ORACLE_QUERY],
        name_prefix="oracle_query",
    )
    def get_sga_pga_usage(self, request, *args, **kwargs):
        bk_cloud_id = self.get_param("bk_cloud_id")
        address = self.get_param("address")

        machine_obj = _validate_and_get_machine(bk_cloud_id, address)
        assert_cluster_type(machine_obj, [ClusterType.OraclePrimaryStandby, ClusterType.OracleSingleNone])

        return Response(
            get_sga_pga_usage(
                addr=address,
            )
        )

    # endregion

    # region AWR 报告（3，通过 ORACLE_ENABLE_AWR 环境变量控制开关，默认关闭）

    @mcp_tools_api_decorator(
        description=str(_("列出最近 N 天的 AWR 快照（dba_hist_snapshot），默认 7 天。")),
        request_slz=ListAwrSnapshotsInputSerializer,
        response_slz=ListAwrSnapshotsOutputSerializer,
        permission_classes=[McpClusterDetailPermission],
        mcp_auth_parser=auth_parse_instances,
        tags=[DBMMCPTags.READ],
        mcp=[DBMMcpTools.ORACLE_QUERY],
        name_prefix="oracle_query",
    )
    def list_awr_snapshots(self, request, *args, **kwargs):
        bk_cloud_id = self.get_param("bk_cloud_id")
        address = self.get_param("address")

        machine_obj = _validate_and_get_machine(bk_cloud_id, address)
        assert_cluster_type(machine_obj, [ClusterType.OraclePrimaryStandby, ClusterType.OracleSingleNone])

        return Response(
            list_awr_snapshots(
                addr=address,
                days=self.get_param("days"),
                limit=self.get_param("limit"),
            )
        )

    @mcp_tools_api_decorator(
        description=str(
            _(
                "生成指定快照区间 [begin_snap, end_snap] 的 AWR 报告（dbms_workload_repository）。"
                "format=text（默认）供分析，html 供人工查看。"
                "【警告】返回完整报告，体积通常 200KB-2MB，必须由脚本/CLI 调用后裁剪再使用，"
                "禁止直接调用，否则会占满上下文。若只需定位时间范围，请先用 list_awr_snapshots。"
            )
        ),
        request_slz=GenerateAwrReportInputSerializer,
        response_slz=GenerateAwrReportOutputSerializer,
        permission_classes=[McpClusterDetailPermission],
        mcp_auth_parser=auth_parse_instances,
        tags=[DBMMCPTags.READ],
        mcp=[DBMMcpTools.ORACLE_QUERY],
        name_prefix="oracle_query",
    )
    def generate_awr_report(self, request, *args, **kwargs):
        bk_cloud_id = self.get_param("bk_cloud_id")
        address = self.get_param("address")

        machine_obj = _validate_and_get_machine(bk_cloud_id, address)
        assert_cluster_type(machine_obj, [ClusterType.OraclePrimaryStandby, ClusterType.OracleSingleNone])

        return Response(
            generate_awr_report(
                begin_snap=self.get_param("begin_snap"),
                end_snap=self.get_param("end_snap"),
                addr=address,
                report_format=self.get_param("format"),
            )
        )

    @mcp_tools_api_decorator(
        description=str(
            _(
                "按时间区间生成 AWR 报告：自动把 [begin_time, end_time] 解析为快照区间，无需先查 snap_id。"
                "时间格式 YYYY-MM-DD HH:MM:SS，为数据库服务器本地时间，跨度上限 24 小时。"
                "快照按外扩策略选取，实际区间可能宽于请求，由出参 actual_begin_time / actual_end_time 回显。"
                "format=text（默认）供分析，html 供人工查看。"
                "【警告】返回完整报告，体积通常 200KB-2MB，必须由脚本/CLI 调用后裁剪再使用，"
                "禁止直接调用，否则会占满上下文。"
            )
        ),
        request_slz=GenerateAwrReportByTimeInputSerializer,
        response_slz=GenerateAwrReportByTimeOutputSerializer,
        permission_classes=[McpClusterDetailPermission],
        mcp_auth_parser=auth_parse_instances,
        tags=[DBMMCPTags.READ],
        mcp=[DBMMcpTools.ORACLE_QUERY],
        name_prefix="oracle_query",
    )
    def generate_awr_report_by_time(self, request, *args, **kwargs):
        bk_cloud_id = self.get_param("bk_cloud_id")
        address = self.get_param("address")

        machine_obj = _validate_and_get_machine(bk_cloud_id, address)
        assert_cluster_type(machine_obj, [ClusterType.OraclePrimaryStandby, ClusterType.OracleSingleNone])

        return Response(
            generate_awr_report_by_time(
                addr=address,
                begin_time=self.get_param("begin_time"),
                end_time=self.get_param("end_time"),
                report_format=self.get_param("format"),
            )
        )

    # endregion


def _validate_and_get_machine(bk_cloud_id: int, address: str) -> Machine:
    """根据云区域和实例地址获取 Oracle 机器。"""
    ip = address.rsplit(IP_PORT_DIVIDER, 1)[0]
    machine_obj = Machine.objects.filter(ip=ip, bk_cloud_id=bk_cloud_id).first()
    if not machine_obj:
        raise DBMMcpInstanceNotFoundException(msg=f"machine not found: bk_cloud_id={bk_cloud_id}, ip={ip}")

    if machine_obj.machine_type != MachineType.ORACLE:
        raise DBMMcpNotSupportMachineTypeException(machine_type=machine_obj.machine_type)

    return machine_obj
