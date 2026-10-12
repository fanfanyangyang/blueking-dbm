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
from blue_krill.data_types.enum import EnumField, StrStructuredEnum


class OracleWaitClass(StrStructuredEnum):
    """等待事件分类（Oracle 内置分类）"""

    ADMINISTRATIVE = EnumField("Administrative", "Administrative")
    APPLICATION = EnumField("Application", "Application")
    CLUSTER = EnumField("Cluster", "Cluster")
    COMMIT = EnumField("Commit", "Commit")
    CONCURRENCY = EnumField("Concurrency", "Concurrency")
    CONFIGURATION = EnumField("Configuration", "Configuration")
    IDLE = EnumField("Idle", "Idle")
    NETWORK = EnumField("Network", "Network")
    OTHER = EnumField("Other", "Other")
    SCHEDULER = EnumField("Scheduler", "Scheduler")
    SYSTEM_IO = EnumField("System I/O", "System I/O")
    USER_IO = EnumField("User I/O", "User I/O")


class OracleAwrFormat(StrStructuredEnum):
    """
    AWR 报告格式，对应 DBMS_WORKLOAD_REPOSITORY.awr_report_{text,html}。

    枚举值会拼入 SQL 函数名，仅允许这两个取值（调用前会再次白名单校验）。
    text 体积约为 html 的 1/4，且段落以固定标题分隔便于裁剪，供 LLM 分析时优先使用。
    """

    TEXT = EnumField("text", "text")
    HTML = EnumField("html", "html")


class OracleXplanFormat(StrStructuredEnum):
    """
    DBMS_XPLAN.DISPLAY_CURSOR 的 format 参数。

    作为绑定变量传入（非拼接），但仍以枚举约束取值：
    DBMS_XPLAN 会静默忽略无法识别的格式关键字，错误拼写不会报错而是降级输出。

    - ALL：默认。含 Query Block Name / Object Alias、Predicate Information、Column Projection，
      不依赖执行时统计，任何环境都可用。
    - TYPICAL：Oracle 默认格式，信息少于 ALL。
    - ALLSTATS LAST：含 A-Rows / A-Time / Buffers 等实际执行统计，可对比 E-Rows 判断基数估算偏差。
      **前提**：SQL 执行时带 /*+ GATHER_PLAN_STATISTICS */ 或 STATISTICS_LEVEL=ALL；
      否则不报错，仅退化为无实际统计的计划并附 Note。
    - ADVANCED：ALL 再加 Outline Data，输出可达数百行。
    """

    ALL = EnumField("ALL", "ALL")
    TYPICAL = EnumField("TYPICAL", "TYPICAL")
    ALLSTATS_LAST = EnumField("ALLSTATS LAST", "ALLSTATS LAST")
    ADVANCED = EnumField("ADVANCED", "ADVANCED")
