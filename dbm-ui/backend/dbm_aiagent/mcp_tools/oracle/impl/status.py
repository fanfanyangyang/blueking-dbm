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
import time
from typing import Optional

from backend.dbm_aiagent.mcp_tools.exceptions import DBMMcpOracleConnectionException
from backend.dbm_aiagent.mcp_tools.oracle.helpers.oracle_conn import fetch_dicts, oracle_cursor

logger = logging.getLogger("root")

# 一次性拉取实例+DB+会话计数的综合状态
SQL_INSTANCE_STATE = """
SELECT
    i.instance_name,
    i.host_name,
    i.version,
    i.startup_time,
    i.status                   AS instance_status,
    i.database_status,
    i.instance_role,
    i.logins,
    i.archiver,
    i.active_state,
    i.blocked,
    d.name                     AS db_name,
    d.database_role,
    d.open_mode,
    d.protection_mode,
    d.protection_level,
    d.switchover_status,
    d.flashback_on,
    d.log_mode
FROM v$instance i, v$database d
"""

SQL_SESSION_COUNTS = """
SELECT
    COUNT(*)                                                    AS total_sessions,
    SUM(CASE WHEN status = 'ACTIVE' THEN 1 ELSE 0 END)          AS active_sessions,
    SUM(CASE WHEN blocking_session IS NOT NULL THEN 1 ELSE 0 END) AS blocked_sessions,
    SUM(CASE WHEN type = 'USER' THEN 1 ELSE 0 END)              AS user_sessions
FROM v$session
"""

# sessions 上限（初始化参数）
SQL_SESSION_LIMIT = """
SELECT TO_NUMBER(value) AS session_limit
FROM v$parameter
WHERE name = 'sessions'
"""

# 评估结论：根据状态字段汇总 health 等级
_HEALTHY_INSTANCE_STATUS = {"OPEN"}
_HEALTHY_DB_STATUS = {"ACTIVE"}


def _derive_health(state: dict, session_usage_pct: float) -> dict:
    """根据各状态字段汇总出一个简单的 health 等级和原因列表。"""
    reasons = []
    level = "healthy"

    inst_status = (state.get("instance_status") or "").upper()
    db_status = (state.get("database_status") or "").upper()
    logins = (state.get("logins") or "").upper()
    archiver = (state.get("archiver") or "").upper()
    blocked = (state.get("blocked") or "").upper()

    if inst_status not in _HEALTHY_INSTANCE_STATUS:
        level = "critical"
        reasons.append(f"instance_status={inst_status}")
    if db_status not in _HEALTHY_DB_STATUS:
        level = "critical"
        reasons.append(f"database_status={db_status}")
    if archiver == "FAILED":
        level = "critical"
        reasons.append("archiver=FAILED")
    if blocked == "YES":
        level = "critical"
        reasons.append("instance blocked")

    if level == "healthy":
        if logins == "RESTRICTED":
            level = "warning"
            reasons.append("logins=RESTRICTED")
        if session_usage_pct >= 90:
            level = "warning" if level == "healthy" else level
            reasons.append(f"session usage {session_usage_pct:.1f}% >= 90%")

    return {"level": level, "reasons": reasons}


def check_instance_status(immute_domain: str, addr: Optional[str] = None) -> dict:
    """
    综合探活 Oracle 实例：
    - 连接是否可用
    - v$instance / v$database 关键字段
    - 会话数 + 会话上限使用率
    - DG 场景的 database_role / switchover_status
    - 本次探活耗时
    - 聚合出 healthy / warning / critical 结论
    """
    start_ts = time.monotonic()

    try:
        with oracle_cursor(immute_domain, addr) as cur:
            cur.execute(SQL_INSTANCE_STATE)
            state_rows = fetch_dicts(cur, limit=1)
            cur.execute(SQL_SESSION_COUNTS)
            sess_rows = fetch_dicts(cur, limit=1)
            cur.execute(SQL_SESSION_LIMIT)
            limit_rows = fetch_dicts(cur, limit=1)
    except DBMMcpOracleConnectionException as e:
        latency_ms = int((time.monotonic() - start_ts) * 1000)
        return {
            "reachable": False,
            "latency_ms": latency_ms,
            "health": {"level": "critical", "reasons": [f"connect failed: {e.message}"]},
            "state": {},
            "sessions": {},
        }

    latency_ms = int((time.monotonic() - start_ts) * 1000)
    state = state_rows[0] if state_rows else {}
    sess = sess_rows[0] if sess_rows else {}
    session_limit = (limit_rows[0].get("session_limit") if limit_rows else 0) or 0

    total_sessions = sess.get("total_sessions") or 0
    session_usage_pct = (total_sessions / session_limit * 100) if session_limit else 0.0
    sess["session_limit"] = session_limit
    sess["session_usage_pct"] = round(session_usage_pct, 2)

    health = _derive_health(state, session_usage_pct)

    return {
        "reachable": True,
        "latency_ms": latency_ms,
        "health": health,
        "state": state,
        "sessions": sess,
    }
