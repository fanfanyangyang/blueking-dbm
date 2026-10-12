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

from backend.dbm_aiagent.mcp_tools.common.auth_parser.base import auth_parse_clusters
from backend.dbm_aiagent.mcp_tools.constants import DBMMCPTags, DBMMcpTools
from backend.dbm_aiagent.mcp_tools.decorators import mcp_tools_api_decorator
from backend.dbm_aiagent.mcp_tools.oracle.impl.awr import generate_awr_report, list_awr_snapshots
from backend.dbm_aiagent.mcp_tools.oracle.impl.basic_info import get_db_parameters, get_db_version, get_instance_info
from backend.dbm_aiagent.mcp_tools.oracle.impl.capacity import get_sga_pga_usage, get_tablespace_usage, get_undo_usage
from backend.dbm_aiagent.mcp_tools.oracle.impl.health_check import get_alert_log_errors
from backend.dbm_aiagent.mcp_tools.oracle.impl.performance import (
    get_sql_plan,
    get_top_sql_by_cpu,
    get_top_sql_by_io,
    get_wait_events,
)
from backend.dbm_aiagent.mcp_tools.oracle.impl.session_activity import (
    get_active_sessions,
    get_blocking_sessions,
    get_long_running_queries,
)
from backend.dbm_aiagent.mcp_tools.oracle.impl.status import check_instance_status
from backend.dbm_aiagent.mcp_tools.oracle.serializers.awr import (
    GenerateAwrReportInputSerializer,
    GenerateAwrReportOutputSerializer,
    ListAwrSnapshotsInputSerializer,
    ListAwrSnapshotsOutputSerializer,
)
from backend.dbm_aiagent.mcp_tools.oracle.serializers.basic_info import (
    GetDbParametersInputSerializer,
    GetDbParametersOutputSerializer,
    GetDbVersionInputSerializer,
    GetDbVersionOutputSerializer,
    GetInstanceInfoInputSerializer,
    GetInstanceInfoOutputSerializer,
)
from backend.dbm_aiagent.mcp_tools.oracle.serializers.capacity import (
    GetSgaPgaUsageInputSerializer,
    GetSgaPgaUsageOutputSerializer,
    GetTablespaceUsageInputSerializer,
    GetTablespaceUsageOutputSerializer,
    GetUndoUsageInputSerializer,
    GetUndoUsageOutputSerializer,
)
from backend.dbm_aiagent.mcp_tools.oracle.serializers.health_check import (
    GetAlertLogErrorsInputSerializer,
    GetAlertLogErrorsOutputSerializer,
)
from backend.dbm_aiagent.mcp_tools.oracle.serializers.performance import (
    GetSqlPlanInputSerializer,
    GetSqlPlanOutputSerializer,
    GetTopSqlByCpuInputSerializer,
    GetTopSqlByCpuOutputSerializer,
    GetTopSqlByIoInputSerializer,
    GetTopSqlByIoOutputSerializer,
    GetWaitEventsInputSerializer,
    GetWaitEventsOutputSerializer,
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
)
from backend.dbm_aiagent.mcp_tools.views import McpToolsViewSet
from backend.iam_app.handlers.drf_perm.base import DBManagePermission
from backend.iam_app.handlers.drf_perm.mcp import McpClusterDetailPermission

logger = logging.getLogger("root")


class OracleQueryMcpToolsViewSet(McpToolsViewSet):
    """Oracle 只读查询 MCP 工具集（oracle-query）。

    鉴权维度：集群（immute_domain）；统一走 McpClusterDetailPermission + auth_parse_clusters。
    对应 MCP server: `oracle-query`，覆盖基础信息 / 状态探活 / 会话与活动 / 性能分析 /
    容量 / 健康检查 / AWR 报告 等能力。
    """

    default_permission_class = [DBManagePermission()]

    # region 基础信息（3）

    @mcp_tools_api_decorator(
        description=str(_("查询 Oracle 实例概览（v$instance + v$database），包括版本、角色、启动时间、归档模式等。")),
        request_slz=GetInstanceInfoInputSerializer,
        response_slz=GetInstanceInfoOutputSerializer,
        permission_classes=[McpClusterDetailPermission],
        mcp_auth_parser=auth_parse_clusters,
        tags=[DBMMCPTags.READ],
        mcp=[DBMMcpTools.ORACLE_QUERY],
        name_prefix="oracle_query",
    )
    def get_instance_info(self, request, *args, **kwargs):
        return Response(
            get_instance_info(
                immute_domain=self.get_param("cluster_domain"),
                addr=self.get_param("addr"),
            )
        )

    @mcp_tools_api_decorator(
        description=str(_("查询 Oracle 数据库版本（v$version banner）。")),
        request_slz=GetDbVersionInputSerializer,
        response_slz=GetDbVersionOutputSerializer,
        permission_classes=[McpClusterDetailPermission],
        mcp_auth_parser=auth_parse_clusters,
        tags=[DBMMCPTags.READ],
        mcp=[DBMMcpTools.ORACLE_QUERY],
        name_prefix="oracle_query",
    )
    def get_db_version(self, request, *args, **kwargs):
        return Response(
            get_db_version(
                immute_domain=self.get_param("cluster_domain"),
                addr=self.get_param("addr"),
            )
        )

    @mcp_tools_api_decorator(
        description=str(
            _(
                "查询 Oracle 初始化参数（v$parameter）。names 为空时返回全部并按 ORACLE_MAX_ROWS 截断；"
                "传入 names 列表时精确匹配指定参数名（白名单+绑定变量，防注入）。"
            )
        ),
        request_slz=GetDbParametersInputSerializer,
        response_slz=GetDbParametersOutputSerializer,
        permission_classes=[McpClusterDetailPermission],
        mcp_auth_parser=auth_parse_clusters,
        tags=[DBMMCPTags.READ],
        mcp=[DBMMcpTools.ORACLE_QUERY],
        name_prefix="oracle_query",
    )
    def get_db_parameters(self, request, *args, **kwargs):
        return Response(
            get_db_parameters(
                immute_domain=self.get_param("cluster_domain"),
                addr=self.get_param("addr"),
                names=self.get_param("names"),
            )
        )

    # endregion

    # region 状态探活（1）

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
        mcp_auth_parser=auth_parse_clusters,
        tags=[DBMMCPTags.READ],
        mcp=[DBMMcpTools.ORACLE_QUERY],
        name_prefix="oracle_query",
    )
    def check_instance_status(self, request, *args, **kwargs):
        return Response(
            check_instance_status(
                immute_domain=self.get_param("cluster_domain"),
                addr=self.get_param("addr"),
            )
        )

    # endregion

    # region 会话与活动（3）

    @mcp_tools_api_decorator(
        description=str(_("查询 Oracle 活跃会话（v$session, status=ACTIVE 且非 Idle 等待类）。")),
        request_slz=GetActiveSessionsInputSerializer,
        response_slz=GetActiveSessionsOutputSerializer,
        permission_classes=[McpClusterDetailPermission],
        mcp_auth_parser=auth_parse_clusters,
        tags=[DBMMCPTags.READ],
        mcp=[DBMMcpTools.ORACLE_QUERY],
        name_prefix="oracle_query",
    )
    def get_active_sessions(self, request, *args, **kwargs):
        return Response(
            get_active_sessions(
                immute_domain=self.get_param("cluster_domain"),
                addr=self.get_param("addr"),
                limit=self.get_param("limit"),
            )
        )

    @mcp_tools_api_decorator(
        description=str(_("查询 Oracle 阻塞链（blocker → waiter），用于锁争用排查。")),
        request_slz=GetBlockingSessionsInputSerializer,
        response_slz=GetBlockingSessionsOutputSerializer,
        permission_classes=[McpClusterDetailPermission],
        mcp_auth_parser=auth_parse_clusters,
        tags=[DBMMCPTags.READ],
        mcp=[DBMMcpTools.ORACLE_QUERY],
        name_prefix="oracle_query",
    )
    def get_blocking_sessions(self, request, *args, **kwargs):
        return Response(
            get_blocking_sessions(
                immute_domain=self.get_param("cluster_domain"),
                addr=self.get_param("addr"),
                limit=self.get_param("limit"),
            )
        )

    @mcp_tools_api_decorator(
        description=str(_("查询长时间运行的 SQL（基于 v$session.last_call_et），min_seconds 可指定最小阈值。")),
        request_slz=GetLongRunningInputSerializer,
        response_slz=GetLongRunningOutputSerializer,
        permission_classes=[McpClusterDetailPermission],
        mcp_auth_parser=auth_parse_clusters,
        tags=[DBMMCPTags.READ],
        mcp=[DBMMcpTools.ORACLE_QUERY],
        name_prefix="oracle_query",
    )
    def get_long_running_queries(self, request, *args, **kwargs):
        return Response(
            get_long_running_queries(
                immute_domain=self.get_param("cluster_domain"),
                addr=self.get_param("addr"),
                min_seconds=self.get_param("min_seconds"),
                limit=self.get_param("limit"),
            )
        )

    # endregion

    # region 性能分析（4）

    @mcp_tools_api_decorator(
        description=str(_("Top SQL（默认按 CPU 时间排序，可选 elapsed_time/cpu_time/buffer_gets/disk_reads/executions）。")),
        request_slz=GetTopSqlByCpuInputSerializer,
        response_slz=GetTopSqlByCpuOutputSerializer,
        permission_classes=[McpClusterDetailPermission],
        mcp_auth_parser=auth_parse_clusters,
        tags=[DBMMCPTags.READ],
        mcp=[DBMMcpTools.ORACLE_QUERY],
        name_prefix="oracle_query",
    )
    def get_top_sql_by_cpu(self, request, *args, **kwargs):
        return Response(
            get_top_sql_by_cpu(
                immute_domain=self.get_param("cluster_domain"),
                addr=self.get_param("addr"),
                sort_by=self.get_param("sort_by"),
                limit=self.get_param("limit"),
            )
        )

    @mcp_tools_api_decorator(
        description=str(_("Top SQL by IO（按 disk_reads + direct_writes 排序，用于 IO 热点定位）。")),
        request_slz=GetTopSqlByIoInputSerializer,
        response_slz=GetTopSqlByIoOutputSerializer,
        permission_classes=[McpClusterDetailPermission],
        mcp_auth_parser=auth_parse_clusters,
        tags=[DBMMCPTags.READ],
        mcp=[DBMMcpTools.ORACLE_QUERY],
        name_prefix="oracle_query",
    )
    def get_top_sql_by_io(self, request, *args, **kwargs):
        return Response(
            get_top_sql_by_io(
                immute_domain=self.get_param("cluster_domain"),
                addr=self.get_param("addr"),
                limit=self.get_param("limit"),
            )
        )

    @mcp_tools_api_decorator(
        description=str(_("Top 等待事件（v$system_event，剔除 Idle 类）。")),
        request_slz=GetWaitEventsInputSerializer,
        response_slz=GetWaitEventsOutputSerializer,
        permission_classes=[McpClusterDetailPermission],
        mcp_auth_parser=auth_parse_clusters,
        tags=[DBMMCPTags.READ],
        mcp=[DBMMcpTools.ORACLE_QUERY],
        name_prefix="oracle_query",
    )
    def get_wait_events(self, request, *args, **kwargs):
        return Response(
            get_wait_events(
                immute_domain=self.get_param("cluster_domain"),
                addr=self.get_param("addr"),
                limit=self.get_param("limit"),
            )
        )

    @mcp_tools_api_decorator(
        description=str(_("查询指定 sql_id 的执行计划（v$sql_plan），可选 child_number 精确定位子游标。")),
        request_slz=GetSqlPlanInputSerializer,
        response_slz=GetSqlPlanOutputSerializer,
        permission_classes=[McpClusterDetailPermission],
        mcp_auth_parser=auth_parse_clusters,
        tags=[DBMMCPTags.READ],
        mcp=[DBMMcpTools.ORACLE_QUERY],
        name_prefix="oracle_query",
    )
    def get_sql_plan(self, request, *args, **kwargs):
        return Response(
            get_sql_plan(
                immute_domain=self.get_param("cluster_domain"),
                sql_id=self.get_param("sql_id"),
                addr=self.get_param("addr"),
                child_number=self.get_param("child_number"),
            )
        )

    # endregion

    # region 容量（3）

    @mcp_tools_api_decorator(
        description=str(_("查询 Oracle 表空间使用率（按已用占比降序，含 autoextensible 与 max_mb）。")),
        request_slz=GetTablespaceUsageInputSerializer,
        response_slz=GetTablespaceUsageOutputSerializer,
        permission_classes=[McpClusterDetailPermission],
        mcp_auth_parser=auth_parse_clusters,
        tags=[DBMMCPTags.READ],
        mcp=[DBMMcpTools.ORACLE_QUERY],
        name_prefix="oracle_query",
    )
    def get_tablespace_usage(self, request, *args, **kwargs):
        return Response(
            get_tablespace_usage(
                immute_domain=self.get_param("cluster_domain"),
                addr=self.get_param("addr"),
                limit=self.get_param("limit"),
            )
        )

    @mcp_tools_api_decorator(
        description=str(_("查询 Oracle Undo 表空间使用情况（按 ACTIVE/UNEXPIRED/EXPIRED 分组）。")),
        request_slz=GetUndoUsageInputSerializer,
        response_slz=GetUndoUsageOutputSerializer,
        permission_classes=[McpClusterDetailPermission],
        mcp_auth_parser=auth_parse_clusters,
        tags=[DBMMCPTags.READ],
        mcp=[DBMMcpTools.ORACLE_QUERY],
        name_prefix="oracle_query",
    )
    def get_undo_usage(self, request, *args, **kwargs):
        return Response(
            get_undo_usage(
                immute_domain=self.get_param("cluster_domain"),
                addr=self.get_param("addr"),
            )
        )

    @mcp_tools_api_decorator(
        description=str(_("查询 Oracle SGA / PGA 使用情况（v$sga + v$pgastat）。")),
        request_slz=GetSgaPgaUsageInputSerializer,
        response_slz=GetSgaPgaUsageOutputSerializer,
        permission_classes=[McpClusterDetailPermission],
        mcp_auth_parser=auth_parse_clusters,
        tags=[DBMMCPTags.READ],
        mcp=[DBMMcpTools.ORACLE_QUERY],
        name_prefix="oracle_query",
    )
    def get_sga_pga_usage(self, request, *args, **kwargs):
        return Response(
            get_sga_pga_usage(
                immute_domain=self.get_param("cluster_domain"),
                addr=self.get_param("addr"),
            )
        )

    # endregion

    # region 健康检查（1）

    @mcp_tools_api_decorator(
        description=str(_("查询近 N 小时的 Oracle 告警日志错误（v$diag_alert_ext），默认 24 小时。")),
        request_slz=GetAlertLogErrorsInputSerializer,
        response_slz=GetAlertLogErrorsOutputSerializer,
        permission_classes=[McpClusterDetailPermission],
        mcp_auth_parser=auth_parse_clusters,
        tags=[DBMMCPTags.READ],
        mcp=[DBMMcpTools.ORACLE_QUERY],
        name_prefix="oracle_query",
    )
    def get_alert_log_errors(self, request, *args, **kwargs):
        return Response(
            get_alert_log_errors(
                immute_domain=self.get_param("cluster_domain"),
                addr=self.get_param("addr"),
                hours=self.get_param("hours"),
                limit=self.get_param("limit"),
            )
        )

    # endregion

    # region AWR 报告（2，通过 ORACLE_ENABLE_AWR 环境变量控制开关，默认关闭）

    @mcp_tools_api_decorator(
        description=str(_("列出最近 N 天的 AWR 快照（dba_hist_snapshot），默认 7 天。")),
        request_slz=ListAwrSnapshotsInputSerializer,
        response_slz=ListAwrSnapshotsOutputSerializer,
        permission_classes=[McpClusterDetailPermission],
        mcp_auth_parser=auth_parse_clusters,
        tags=[DBMMCPTags.READ],
        mcp=[DBMMcpTools.ORACLE_QUERY],
        name_prefix="oracle_query",
    )
    def list_awr_snapshots(self, request, *args, **kwargs):
        return Response(
            list_awr_snapshots(
                immute_domain=self.get_param("cluster_domain"),
                addr=self.get_param("addr"),
                days=self.get_param("days"),
                limit=self.get_param("limit"),
            )
        )

    @mcp_tools_api_decorator(
        description=str(_("生成指定快照区间 [begin_snap, end_snap] 的 AWR HTML 报告（dbms_workload_repository.awr_report_html）。")),
        request_slz=GenerateAwrReportInputSerializer,
        response_slz=GenerateAwrReportOutputSerializer,
        permission_classes=[McpClusterDetailPermission],
        mcp_auth_parser=auth_parse_clusters,
        tags=[DBMMCPTags.READ],
        mcp=[DBMMcpTools.ORACLE_QUERY],
        name_prefix="oracle_query",
    )
    def generate_awr_report(self, request, *args, **kwargs):
        return Response(
            generate_awr_report(
                immute_domain=self.get_param("cluster_domain"),
                begin_snap=self.get_param("begin_snap"),
                end_snap=self.get_param("end_snap"),
                addr=self.get_param("addr"),
                dbid=self.get_param("dbid"),
                inst_num=self.get_param("inst_num"),
            )
        )

    # endregion
