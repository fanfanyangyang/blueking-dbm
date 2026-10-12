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
from typing import Any, Dict, List, Optional, Tuple

from backend.dbm_aiagent.mcp_tools.exceptions import DBMMcpFeatureDisabledException, DBMMcpUnsafeIdentifierException
from backend.dbm_aiagent.mcp_tools.oracle.constants import (
    ORACLE_ASH_DEFAULT_MINUTES,
    ORACLE_ASH_MAX_MINUTES,
    ORACLE_ENABLE_AWR,
    ORACLE_MAX_ROWS,
    ORACLE_XPLAN_MAX_LINES,
)
from backend.dbm_aiagent.mcp_tools.oracle.enums import OracleXplanFormat
from backend.dbm_aiagent.mcp_tools.oracle.helpers.oracle_conn import run_queries, run_query

# 执行计划：DBMS_XPLAN.DISPLAY_CURSOR
SQL_PLAN = """
SELECT plan_table_output AS output
FROM TABLE(DBMS_XPLAN.DISPLAY_CURSOR(:sql_id, :child_number, :plan_format))
WHERE ROWNUM <= :row_limit
"""

# ---------- ASH ----------
# 实际可用的统计窗口：请求窗口起点与 ASH 最早样本取较晚者，避免 ASH 已被覆盖时 aas 被低估
# total_db_time_sec：窗口内全部前台样本数 → 整体 AAS（并发规模）
# cpu_db_time_sec：其中 session_state='ON CPU' 的样本数 → AAS(CPU)
SQL_ASH_WINDOW = """
SELECT
    TO_CHAR(SYSDATE - :mins / 1440, 'YYYY-MM-DD HH24:MI:SS')              AS window_begin,
    TO_CHAR(SYSDATE, 'YYYY-MM-DD HH24:MI:SS')                             AS window_end,
    TO_CHAR(o.oldest_sample_time, 'YYYY-MM-DD HH24:MI:SS')                AS oldest_sample_time,
    ROUND((SYSDATE - GREATEST(SYSDATE - :mins / 1440,
                              NVL(CAST(o.oldest_sample_time AS DATE), SYSDATE))) * 86400) AS effective_sec,
    o.total_samples                                                       AS total_db_time_sec,
    o.cpu_samples                                                         AS cpu_db_time_sec,
    (SELECT TO_NUMBER(value) FROM v$parameter WHERE name = 'cpu_count')   AS cpu_count
FROM (
    SELECT MIN(sample_time) AS oldest_sample_time,
           COUNT(CASE WHEN sample_time >= CAST(SYSDATE - :mins / 1440 AS TIMESTAMP)
                       AND session_type = 'FOREGROUND' THEN 1 END) AS total_samples,
           COUNT(CASE WHEN sample_time >= CAST(SYSDATE - :mins / 1440 AS TIMESTAMP)
                       AND session_type = 'FOREGROUND'
                       AND session_state = 'ON CPU' THEN 1 END)    AS cpu_samples
    FROM   v$active_session_history
) o
"""

# 1) 按 wait_class 汇总：先定大方向（CPU / User I/O / Concurrency / Application ...）
SQL_ASH_WAIT_CLASS = """
SELECT
    CASE WHEN session_state = 'ON CPU' THEN 'CPU' ELSE wait_class END AS wait_class,
    COUNT(*)                                                          AS db_time_sec,
    ROUND(RATIO_TO_REPORT(COUNT(*)) OVER () * 100, 2)                 AS pct
FROM v$active_session_history
WHERE sample_time >= CAST(SYSDATE - :mins / 1440 AS TIMESTAMP)
  AND session_type = 'FOREGROUND'
GROUP BY CASE WHEN session_state = 'ON CPU' THEN 'CPU' ELSE wait_class END
ORDER BY 2 DESC
"""

# 2) Top 等待事件：附累计占比、涉及会话数、贡献最多的 SQL
SQL_ASH_TOP_EVENTS = """
WITH ash AS (
    SELECT CASE WHEN session_state = 'ON CPU' THEN 'CPU + CPU Wait' ELSE event END AS event,
           CASE WHEN session_state = 'ON CPU' THEN 'CPU' ELSE wait_class END      AS wait_class,
           sql_id, session_id, session_serial#
    FROM   v$active_session_history
    WHERE  sample_time >= CAST(SYSDATE - :mins / 1440 AS TIMESTAMP)
    AND    session_type = 'FOREGROUND'
), per_sql AS (
    SELECT event, wait_class, sql_id, COUNT(*) AS cnt
    FROM   ash
    GROUP  BY event, wait_class, sql_id
), agg AS (
    SELECT event, wait_class, SUM(cnt) AS samples,
           MAX(sql_id) KEEP (DENSE_RANK FIRST ORDER BY cnt DESC) AS top_sql_id,
           MAX(cnt)    KEEP (DENSE_RANK FIRST ORDER BY cnt DESC) AS top_sql_sec
    FROM   per_sql
    GROUP  BY event, wait_class
), sess AS (
    SELECT event, wait_class, COUNT(DISTINCT session_id || ',' || session_serial#) AS sessions
    FROM   ash
    GROUP  BY event, wait_class
)
SELECT * FROM (
    SELECT a.event,
           a.wait_class,
           a.samples                                                  AS db_time_sec,
           ROUND(RATIO_TO_REPORT(a.samples) OVER () * 100, 2)         AS pct,
           ROUND(SUM(a.samples) OVER (ORDER BY a.samples DESC, a.event ROWS UNBOUNDED PRECEDING)
                 / SUM(a.samples) OVER () * 100, 2)                   AS pct_cum,
           s.sessions,
           a.top_sql_id,
           a.top_sql_sec
    FROM   agg a
    JOIN   sess s ON s.event = a.event AND s.wait_class = a.wait_class
    ORDER  BY a.samples DESC, a.event
) WHERE ROWNUM <= :row_limit
"""

# 3) Top SQL（按 DB time）：附主要等待事件、执行计划个数、SQL 文本
#    pct_of_sql_time：占「有 sql_id 的样本」比例；pct_of_db_time：占全部前台样本比例
#    sql_text 只对 Top N 取：v$sqlstats 优先，已被挤出共享池时回退 dba_hist_sqltext
SQL_ASH_TOP_SQL = """
WITH ash AS (
    SELECT sql_id, sql_plan_hash_value,
           CASE WHEN session_state = 'ON CPU' THEN 'CPU' ELSE event END AS event
    FROM   v$active_session_history
    WHERE  sample_time >= CAST(SYSDATE - :mins / 1440 AS TIMESTAMP)
    AND    session_type = 'FOREGROUND'
), tot AS (
    SELECT COUNT(*) AS total_samples FROM ash
), ev AS (
    SELECT sql_id, event, COUNT(*) AS cnt
    FROM   ash
    WHERE  sql_id IS NOT NULL
    GROUP  BY sql_id, event
), agg AS (
    SELECT sql_id, SUM(cnt) AS samples,
           MAX(event) KEEP (DENSE_RANK FIRST ORDER BY cnt DESC) AS top_event,
           MAX(cnt)   KEEP (DENSE_RANK FIRST ORDER BY cnt DESC) AS top_event_samples
    FROM   ev
    GROUP  BY sql_id
), pl0 AS (
    SELECT sql_id, sql_plan_hash_value AS phv, COUNT(*) AS cnt
    FROM   ash
    WHERE  sql_id IS NOT NULL
    GROUP  BY sql_id, sql_plan_hash_value
), pl AS (
    SELECT sql_id,
           COUNT(CASE WHEN phv <> 0 THEN 1 END)               AS plan_count,
           MAX(phv) KEEP (DENSE_RANK FIRST ORDER BY cnt DESC) AS top_plan_hash_value
    FROM   pl0
    GROUP  BY sql_id
), ranked AS (
    SELECT * FROM (
        SELECT a.sql_id,
               a.samples                                              AS db_time_sec,
               ROUND(RATIO_TO_REPORT(a.samples) OVER () * 100, 2)     AS pct_of_sql_time,
               ROUND(a.samples * 100 / NULLIF(t.total_samples, 0), 2) AS pct_of_db_time,
               a.top_event,
               ROUND(a.top_event_samples * 100 / a.samples, 1)        AS top_event_pct,
               p.plan_count,
               p.top_plan_hash_value
        FROM   agg a
        JOIN   pl p ON p.sql_id = a.sql_id
        CROSS  JOIN tot t
        ORDER  BY a.samples DESC, a.sql_id
    ) WHERE ROWNUM <= :row_limit
)
SELECT r.*,
       COALESCE(
           (SELECT SUBSTR(s.sql_text, 1, 200) FROM v$sqlstats s
            WHERE s.sql_id = r.sql_id AND ROWNUM = 1),
           (SELECT DBMS_LOB.SUBSTR(h.sql_text, 200, 1) FROM dba_hist_sqltext h
            WHERE h.sql_id = r.sql_id AND ROWNUM = 1)
       ) AS sql_text
FROM ranked r
ORDER BY r.db_time_sec DESC, r.sql_id
"""

# 实际窗口比请求窗口短超过该秒数时，视为 ASH 数据不完整
_ASH_TRUNCATE_TOLERANCE_SEC = 60

# AAS(CPU) / cpu_count，即 CPU 繁忙度。
_AAS_PER_CPU_LOW = 0.7
_AAS_PER_CPU_NORMAL = 1.0
_AAS_PER_CPU_HIGH = 2.0

# 等待分量 >= CPU 分量且绝对值达到该 AAS 时，提示瓶颈不在 CPU（避免空闲库上的噪音提示）
_WAIT_HINT_MIN_AAS = 1.0


def _derive_load(
    total_aas: Optional[float],
    cpu_aas: Optional[float],
    cpu_count: Any,
) -> Dict[str, Any]:
    """
    用 AAS(ON CPU) 与 cpu_count 的比值判定 CPU 繁忙度。

    等待分量不消耗 CPU，不参与 level 判定，仅在其占主导时于 summary 提示去看 wait_class。
    """
    wait_aas = None
    if total_aas is not None and cpu_aas is not None:
        wait_aas = round(total_aas - cpu_aas, 2)

    if cpu_aas is None or not cpu_count:
        return {
            "cpu_count": cpu_count,
            "aas_cpu": cpu_aas,
            "aas_wait": wait_aas,
            "aas_cpu_per_core": None,
            "wait_dominant": None,
            "level": "unknown",
            "summary": "cpu_count 或 ASH 样本不可用，无法判定 CPU 繁忙度",
        }

    # NUMBER 列可能取回 float（如 4.0），归一化便于输出
    cpu_count = int(cpu_count)
    aas_cpu_per_core = round(cpu_aas / cpu_count, 2)
    if aas_cpu_per_core < _AAS_PER_CPU_LOW:
        level, summary = "low", "CPU 仍有明显余量"
    elif aas_cpu_per_core < _AAS_PER_CPU_NORMAL:
        level, summary = "normal", "ON CPU 会话数接近 CPU 核数，繁忙但基本能被 CPU 消化"
    elif aas_cpu_per_core < _AAS_PER_CPU_HIGH:
        level, summary = "high", "ON CPU 会话数超过 CPU 核数，CPU 上存在排队"
    else:
        level, summary = "critical", "ON CPU 会话数远超 CPU 核数，CPU 已过载"
    summary = f"{summary}（aas_cpu={cpu_aas} / cpu_count={cpu_count} = {aas_cpu_per_core}）"

    # total = cpu + wait，故 wait >= cpu 等价于等待占整体 AAS 一半以上
    wait_dominant = bool(wait_aas is not None and wait_aas >= cpu_aas and wait_aas >= _WAIT_HINT_MIN_AAS)
    if wait_dominant:
        summary += (
            f"；但整体 total_aas={total_aas} 中有 {wait_aas} 来自等待而非 CPU，" "瓶颈不在 CPU，请结合 get_ash_wait_class 定位（I/O / 锁 / 并发）"
        )

    return {
        "cpu_count": cpu_count,
        "aas_cpu": cpu_aas,
        "aas_wait": wait_aas,
        "aas_cpu_per_core": aas_cpu_per_core,
        "wait_dominant": wait_dominant,
        "level": level,
        "summary": summary,
    }


# DISPLAY_CURSOR 找不到游标时不返回空集，而是输出一行提示文本
_XPLAN_NOT_FOUND_MARKERS = ("cannot be found", "cannot fetch plan")


def get_sql_plan(
    addr: str,
    sql_id: str,
    child_number: Optional[int] = None,
    plan_format: str = OracleXplanFormat.ALL.value,
) -> dict:
    """
    查询指定 sql_id 的执行计划（DBMS_XPLAN.DISPLAY_CURSOR）。

    依赖共享池：SQL 被 age out 后取不到计划，此时 found=False。
    child_number 为 None 表示输出全部子游标。
    """
    if not sql_id or not sql_id.replace("_", "").isalnum():
        raise DBMMcpUnsafeIdentifierException(msg=f"invalid sql_id: {sql_id}")

    rows = run_query(
        addr,
        SQL_PLAN,
        {
            "sql_id": sql_id,
            "child_number": int(child_number) if child_number is not None else None,
            "plan_format": plan_format,
            "row_limit": ORACLE_XPLAN_MAX_LINES,
        },
    )
    # DBMS_XPLAN 每行一个片段，按行拼接还原带缩进的计划文本
    plan_text = "\n".join(row["output"] for row in rows if row.get("output") is not None)

    lowered = plan_text.lower()
    found = bool(plan_text) and not any(marker in lowered for marker in _XPLAN_NOT_FOUND_MARKERS)

    warnings = []
    if not found:
        warnings.append(f"sql_id={sql_id} 的游标不在共享池中（可能已被 age out），无法获取执行计划")
    if len(rows) >= ORACLE_XPLAN_MAX_LINES:
        warnings.append(f"计划文本已达行数上限（{ORACLE_XPLAN_MAX_LINES} 行）被截断，建议改用 TYPICAL 或 ALL 格式")
    if found and plan_format == OracleXplanFormat.ALLSTATS_LAST.value and "A-Rows" not in plan_text:
        warnings.append(
            "ALLSTATS LAST 未返回实际执行统计（A-Rows/A-Time），"
            "该 SQL 执行时未带 GATHER_PLAN_STATISTICS hint 且 STATISTICS_LEVEL 不为 ALL"
        )

    return {
        "sql_id": sql_id,
        "format": plan_format,
        "found": found,
        "plan_text": plan_text,
        "line_count": len(rows),
        "warnings": warnings,
    }


# ---------- ASH ----------


def _normalize_minutes(minutes: Optional[int]) -> int:
    minutes = int(minutes or ORACLE_ASH_DEFAULT_MINUTES)
    return max(1, min(minutes, ORACLE_ASH_MAX_MINUTES))


def _run_ash(
    addr: str, minutes: int, sql: str, binds: Optional[Dict[str, Any]] = None
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    在同一次 DRS 调用中执行「窗口探测 + ASH 聚合」，并按实际窗口计算 aas。
    返回 (window, rows)。
    """
    if not ORACLE_ENABLE_AWR:
        raise DBMMcpFeatureDisabledException(feature="Oracle ASH (Diagnostics Pack, ORACLE_ENABLE_AWR)")

    window_rows, rows = run_queries(
        addr,
        [(SQL_ASH_WINDOW, {"mins": minutes}), (sql, {**(binds or {}), "mins": minutes})],
    )
    w = window_rows[0] if window_rows else {}
    requested_sec = minutes * 60
    effective_sec = int(w.get("effective_sec") or 0)
    total_db_time = int(w.get("total_db_time_sec") or 0)
    cpu_db_time = int(w.get("cpu_db_time_sec") or 0)
    total_aas = round(total_db_time / effective_sec, 2) if effective_sec > 0 else None
    cpu_aas = round(cpu_db_time / effective_sec, 2) if effective_sec > 0 else None
    window = {
        "requested_minutes": minutes,
        "window_begin": w.get("window_begin"),
        "window_end": w.get("window_end"),
        "oldest_sample_time": w.get("oldest_sample_time"),
        "effective_sec": effective_sec,
        # ASH 循环缓冲区已覆盖窗口前段：结果只代表 effective_sec 内的数据
        "truncated": effective_sec < requested_sec - _ASH_TRUNCATE_TOLERANCE_SEC,
        # 窗口内全部前台会话的 DB time 与整体 AAS（并发规模）
        "total_db_time_sec": total_db_time,
        "total_aas": total_aas,
        # 其中 ON CPU 部分的 DB time，用于与 cpu_count 对比
        "cpu_db_time_sec": cpu_db_time,
        # AAS(CPU) 与 cpu_count 对比得出的 CPU 繁忙度结论
        "load": _derive_load(total_aas, cpu_aas, w.get("cpu_count")),
    }

    # aas（平均活跃会话数）= DB time / 实际窗口秒数
    for row in rows:
        db_time = row.get("db_time_sec") or 0
        row["aas"] = round(db_time / effective_sec, 2) if effective_sec > 0 else None
    return window, rows


def get_ash_wait_class(addr: str, minutes: int = ORACLE_ASH_DEFAULT_MINUTES) -> dict:
    """最近 N 分钟前台会话 DB time 按 wait_class 汇总（ASH）。"""
    minutes = _normalize_minutes(minutes)
    window, rows = _run_ash(addr, minutes, SQL_ASH_WAIT_CLASS)
    return {"window": window, "wait_classes": rows, "count": len(rows)}


def get_ash_top_events(addr: str, minutes: int = ORACLE_ASH_DEFAULT_MINUTES, limit: int = 20) -> dict:
    """最近 N 分钟前台会话 Top 等待事件（ASH）。"""
    minutes = _normalize_minutes(minutes)
    limit = min(int(limit or 20), ORACLE_MAX_ROWS)
    window, rows = _run_ash(addr, minutes, SQL_ASH_TOP_EVENTS, {"row_limit": limit})
    return {"window": window, "events": rows, "count": len(rows)}


def get_ash_top_sql(addr: str, minutes: int = ORACLE_ASH_DEFAULT_MINUTES, limit: int = 15) -> dict:
    """最近 N 分钟前台会话 Top SQL（按 DB time，ASH）。"""
    minutes = _normalize_minutes(minutes)
    limit = min(int(limit or 15), ORACLE_MAX_ROWS)
    window, rows = _run_ash(addr, minutes, SQL_ASH_TOP_SQL, {"row_limit": limit})
    return {"window": window, "top_sql": rows, "count": len(rows)}
