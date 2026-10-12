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

# Oracle MCP 查询使用的只读账号用户名（固定使用该账号登录目标 Oracle 实例）
ORACLE_MCP_USER = os.getenv("ORACLE_MCP_USER", "dbm_mcp_ro")

# AWR 功能开关，默认关闭
ORACLE_ENABLE_AWR = os.getenv("ORACLE_ENABLE_AWR", "false").lower() == "true"

# 结果行数上限
ORACLE_MAX_ROWS = int(os.getenv("ORACLE_MCP_MAX_ROWS", "200"))

# SQL 文本字段截断长度
ORACLE_MAX_SQL_TEXT_LEN = int(os.getenv("ORACLE_MCP_MAX_SQL_TEXT_LEN", "4000"))

# 连接超时（秒）
ORACLE_CONNECT_TIMEOUT = int(os.getenv("ORACLE_MCP_CONNECT_TIMEOUT", "10"))

# 单次查询超时（秒）
ORACLE_QUERY_TIMEOUT = int(os.getenv("ORACLE_MCP_QUERY_TIMEOUT", "60"))

# 连接池参数
ORACLE_POOL_MIN = int(os.getenv("ORACLE_MCP_POOL_MIN", "1"))
ORACLE_POOL_MAX = int(os.getenv("ORACLE_MCP_POOL_MAX", "4"))
ORACLE_POOL_INCREMENT = int(os.getenv("ORACLE_MCP_POOL_INCREMENT", "1"))
