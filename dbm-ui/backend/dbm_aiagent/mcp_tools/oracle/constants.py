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
import os

# Oracle 连接使用的 service_name（连接账号由 DRS 侧 ORACLE_READ_USER / ORACLE_READ_PASSWORD 配置）
ORACLE_SERVICE_NAME = os.getenv("ORACLE_SERVICE_NAME", "CFDB")

# AWR 功能开关，默认关闭。
# ASH（v$active_session_history / dba_hist_*）与 AWR 同属 Diagnostics Pack，共用此开关
ORACLE_ENABLE_AWR = os.getenv("ORACLE_ENABLE_AWR", "false").lower() == "true"

# ASH 分析时间窗口（分钟）：默认值与上限（内存 ASH 通常只保留约 1 小时）
ORACLE_ASH_DEFAULT_MINUTES = 30
ORACLE_ASH_MAX_MINUTES = 180

# 结果行数上限
ORACLE_MAX_ROWS = int(os.getenv("ORACLE_MCP_MAX_ROWS", "200"))

# DRS 建连超时（秒）
ORACLE_CONNECT_TIMEOUT = int(os.getenv("ORACLE_MCP_CONNECT_TIMEOUT", "5"))

# 单条查询超时（秒）
ORACLE_QUERY_TIMEOUT = int(os.getenv("ORACLE_MCP_QUERY_TIMEOUT", "60"))

# 时间点入参格式。end_interval_time 为不带时区的 TIMESTAMP，
# 所有时间点均按「数据库服务器本地时间」解释，不做时区换算。
ORACLE_TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
ORACLE_SQL_TIME_FORMAT = "YYYY-MM-DD HH24:MI:SS"

# AWR 报告由 pipelined function 按行返回，不受 ORACLE_MAX_ROWS 约束；
# DRS 侧上限为 10 万行，达到该行数说明报告已被静默截断。
ORACLE_AWR_MAX_LINES = 100000

# 按时间生成 AWR 报告的最大跨度（小时）。
# 跨度过大时各项统计被平均稀释，失去诊断价值。
ORACLE_AWR_MAX_SPAN_HOURS = 24

# 执行计划文本行数上限。DBMS_XPLAN 按行返回，ADVANCED 格式含 Outline Data 可达数百行，
# 这里独立于 ORACLE_MAX_ROWS（200）设置，避免计划被中途截断。
ORACLE_XPLAN_MAX_LINES = 1000
