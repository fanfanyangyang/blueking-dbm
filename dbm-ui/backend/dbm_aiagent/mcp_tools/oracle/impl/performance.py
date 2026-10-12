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
from typing import Optional

from backend.dbm_aiagent.mcp_tools.exceptions import DBMMcpUnsafeIdentifierException
from backend.dbm_aiagent.mcp_tools.oracle.constants import ORACLE_MAX_ROWS, ORACLE_MAX_SQL_TEXT_LEN
from backend.dbm_aiagent.mcp_tools.oracle.enums import OracleSortBy
from backend.dbm_aiagent.mcp_tools.oracle.helpers.oracle_conn import fetch_dicts, oracle_cursor

# Top SQL：按不同维度排序。sort_by 列名由白名单枚举控制，可安全拼接。
SQL_TOP_SQL_TMPL = """
SELECT * FROM (
    SELECT
        sql_id,
        parsing_schema_name,
        executions,
        elapsed_time   / 1000000 AS elapsed_sec,
        cpu_time       / 1000000 AS cpu_sec,
        buffer_gets,
        disk_reads,
        rows_processed,
        CASE WHEN executions > 0 THEN elapsed_time / executions / 1000 END AS avg_elapsed_ms,
        SUBSTR(sql_text, 1, :sql_text_len) AS sql_text
    FROM v$sqlstats
    WHERE executions > 0
    ORDER BY {sort_col} DESC NULLS LAST
) WHERE ROWNUM <= :row_limit
"""

SORT_COL_MAP = {
    OracleSortBy.ELAPSED_TIME.value: "elapsed_time",
    OracleSortBy.CPU_TIME.value: "cpu_time",
    OracleSortBy.BUFFER_GETS.value: "buffer_gets",
    OracleSortBy.DISK_READS.value: "disk_reads",
    OracleSortBy.EXECUTIONS.value: "executions",
}


# Top SQL by CPU：固定按 CPU 排序
SQL_TOP_SQL_BY_IO = """
SELECT * FROM (
    SELECT
        sql_id,
        parsing_schema_name,
        executions,
        disk_reads,
        direct_writes,
        buffer_gets,
        physical_read_bytes,
        physical_write_bytes,
        SUBSTR(sql_text, 1, :sql_text_len) AS sql_text
    FROM v$sqlstats
    WHERE executions > 0
    ORDER BY (disk_reads + direct_writes) DESC NULLS LAST
) WHERE ROWNUM <= :row_limit
"""

# 等待事件 Top：按累计等待时间排序
SQL_WAIT_EVENTS = """
SELECT * FROM (
    SELECT
        event,
        wait_class,
        total_waits,
        total_timeouts,
        time_waited           AS time_waited_cs,
        time_waited_micro,
        average_wait          AS avg_wait_cs
    FROM v$system_event
    WHERE wait_class <> 'Idle'
    ORDER BY time_waited_micro DESC NULLS LAST
) WHERE ROWNUM <= :row_limit
"""

# 执行计划：按 sql_id（必要时带 child_number）
SQL_PLAN = """
SELECT
    plan_hash_value,
    id          AS step_id,
    parent_id,
    operation,
    options,
    object_owner,
    object_name,
    cost,
    cardinality,
    bytes,
    cpu_cost,
    io_cost,
    access_predicates,
    filter_predicates
FROM v$sql_plan
WHERE sql_id = :sql_id
  AND (:child_number IS NULL OR child_number = :child_number)
ORDER BY plan_hash_value, id
"""


def _sort_col(sort_by: str) -> str:
    col = SORT_COL_MAP.get(sort_by)
    if not col:
        raise DBMMcpUnsafeIdentifierException(msg=f"invalid sort_by: {sort_by}")
    return col


def get_top_sql_by_cpu(
    immute_domain: str,
    addr: Optional[str] = None,
    sort_by: str = OracleSortBy.CPU_TIME.value,
    limit: int = ORACLE_MAX_ROWS,
) -> dict:
    """Top SQL（默认按 CPU 时间排序；支持按 elapsed/cpu/buffer_gets/disk_reads/executions）。"""
    limit = min(int(limit or ORACLE_MAX_ROWS), ORACLE_MAX_ROWS)
    sql = SQL_TOP_SQL_TMPL.format(sort_col=_sort_col(sort_by))
    with oracle_cursor(immute_domain, addr) as cur:
        cur.execute(sql, {"row_limit": limit, "sql_text_len": ORACLE_MAX_SQL_TEXT_LEN})
        rows = fetch_dicts(cur)
    return {"sort_by": sort_by, "top_sql": rows, "count": len(rows)}


def get_top_sql_by_io(immute_domain: str, addr: Optional[str] = None, limit: int = ORACLE_MAX_ROWS) -> dict:
    """Top SQL by IO（按 disk_reads + direct_writes 排序）。"""
    limit = min(int(limit or ORACLE_MAX_ROWS), ORACLE_MAX_ROWS)
    with oracle_cursor(immute_domain, addr) as cur:
        cur.execute(SQL_TOP_SQL_BY_IO, {"row_limit": limit, "sql_text_len": ORACLE_MAX_SQL_TEXT_LEN})
        rows = fetch_dicts(cur)
    return {"top_sql": rows, "count": len(rows)}


def get_wait_events(immute_domain: str, addr: Optional[str] = None, limit: int = ORACLE_MAX_ROWS) -> dict:
    """Top 等待事件（v$system_event，剔除 Idle）。"""
    limit = min(int(limit or ORACLE_MAX_ROWS), ORACLE_MAX_ROWS)
    with oracle_cursor(immute_domain, addr) as cur:
        cur.execute(SQL_WAIT_EVENTS, {"row_limit": limit})
        rows = fetch_dicts(cur)
    return {"events": rows, "count": len(rows)}


def get_sql_plan(
    immute_domain: str,
    sql_id: str,
    addr: Optional[str] = None,
    child_number: Optional[int] = None,
) -> dict:
    """查询指定 sql_id 的执行计划（v$sql_plan）。"""
    if not sql_id or not sql_id.replace("_", "").isalnum():
        raise DBMMcpUnsafeIdentifierException(msg=f"invalid sql_id: {sql_id}")
    with oracle_cursor(immute_domain, addr) as cur:
        cur.execute(
            SQL_PLAN,
            {"sql_id": sql_id, "child_number": child_number},
        )
        rows = fetch_dicts(cur)
    return {"sql_id": sql_id, "plan_steps": rows, "count": len(rows)}
