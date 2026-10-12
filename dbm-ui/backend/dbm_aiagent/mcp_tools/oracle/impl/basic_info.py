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
from typing import List, Optional

from backend.dbm_aiagent.mcp_tools.oracle.constants import ORACLE_MAX_ROWS
from backend.dbm_aiagent.mcp_tools.oracle.helpers.oracle_conn import fetch_dicts, oracle_cursor

SQL_INSTANCE_INFO = """
SELECT
    instance_name,
    host_name,
    version,
    startup_time,
    status,
    database_status,
    instance_role,
    thread#        AS thread_num,
    archiver,
    logins
FROM v$instance
"""

SQL_DATABASE_INFO = """
SELECT
    name           AS db_name,
    db_unique_name,
    database_role,
    open_mode,
    log_mode,
    flashback_on,
    protection_mode,
    dbid,
    created
FROM v$database
"""

SQL_DB_VERSION = """
SELECT banner
FROM v$version
WHERE banner IS NOT NULL
"""

SQL_DB_PARAMETERS_ALL = """
SELECT * FROM (
    SELECT
        name,
        value,
        display_value,
        isdefault,
        ismodified,
        isbasic,
        description
    FROM v$parameter
    WHERE ({name_filter})
    ORDER BY name
) WHERE ROWNUM <= :row_limit
"""


def get_instance_info(immute_domain: str, addr: Optional[str] = None) -> dict:
    """获取 Oracle 实例概览：v$instance + v$database 合并返回。"""
    with oracle_cursor(immute_domain, addr) as cur:
        cur.execute(SQL_INSTANCE_INFO)
        inst_rows = fetch_dicts(cur, limit=1)
        cur.execute(SQL_DATABASE_INFO)
        db_rows = fetch_dicts(cur, limit=1)

    return {
        "instance": inst_rows[0] if inst_rows else {},
        "database": db_rows[0] if db_rows else {},
    }


def get_db_version(immute_domain: str, addr: Optional[str] = None) -> dict:
    """获取 Oracle 版本信息（v$version banner）。11.2 返回多行（DB/PLSQL/CORE/TNS/NLSRTL）。"""
    with oracle_cursor(immute_domain, addr) as cur:
        cur.execute(SQL_DB_VERSION)
        rows = fetch_dicts(cur, limit=10)
    return {"banners": [r["banner"] for r in rows if r.get("banner")]}


def get_db_parameters(
    immute_domain: str,
    addr: Optional[str] = None,
    names: Optional[List[str]] = None,
) -> dict:
    """
    查询 Oracle 初始化参数。
    - names 为空：返回全部（截断到 ORACLE_MAX_ROWS）
    - names 非空：精确匹配指定参数名列表
    """
    if names:
        # 参数名白名单：只允许大小写字母+数字+下划线，防 SQL 注入
        safe = [n for n in names if n.replace("_", "").isalnum()]
        if not safe:
            return {"parameters": [], "truncated": False}
        placeholders = ", ".join([f":n{i}" for i in range(len(safe))])
        name_filter = f"LOWER(name) IN ({placeholders})"
        binds = {f"n{i}": safe[i].lower() for i in range(len(safe))}
    else:
        name_filter = "1=1"
        binds = {}

    binds["row_limit"] = ORACLE_MAX_ROWS
    sql = SQL_DB_PARAMETERS_ALL.format(name_filter=name_filter)
    with oracle_cursor(immute_domain, addr) as cur:
        cur.execute(sql, binds)
        rows = fetch_dicts(cur)
    return {"parameters": rows, "truncated": len(rows) >= ORACLE_MAX_ROWS}
