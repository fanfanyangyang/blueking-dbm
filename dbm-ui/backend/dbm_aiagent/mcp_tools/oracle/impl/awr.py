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

from backend.dbm_aiagent.mcp_tools.exceptions import DBMMcpFeatureDisabledException
from backend.dbm_aiagent.mcp_tools.oracle.constants import ORACLE_ENABLE_AWR, ORACLE_MAX_ROWS
from backend.dbm_aiagent.mcp_tools.oracle.helpers.oracle_conn import fetch_dicts, oracle_cursor

# 目标版本：Oracle 11.2.0.4
#   - DBMS_WORKLOAD_REPOSITORY.awr_report_html 作为 pipelined function 调用：
#     通过 SELECT output FROM TABLE(...) 逐行读取拼接

# 列出最近 N 天的 AWR 快照
SQL_LIST_AWR_SNAPSHOTS = """
SELECT * FROM (
    SELECT
        s.snap_id,
        s.dbid,
        s.instance_number,
        s.begin_interval_time,
        s.end_interval_time,
        s.snap_level,
        s.flush_elapsed
    FROM dba_hist_snapshot s
    WHERE s.end_interval_time > SYSTIMESTAMP - NUMTODSINTERVAL(:days, 'DAY')
    ORDER BY s.snap_id DESC
) WHERE ROWNUM <= :row_limit
"""

# awr_report_html 作为 pipelined function 调用，返回 awrrpt_html_type_table
# 每行是 VARCHAR2(500)，需要在 Python 侧按行拼接
SQL_AWR_REPORT = """
SELECT output
FROM TABLE(
    DBMS_WORKLOAD_REPOSITORY.awr_report_html(
        :dbid,
        :inst_num,
        :begin_snap,
        :end_snap,
        0
    )
)
"""


def _ensure_enabled():
    if not ORACLE_ENABLE_AWR:
        raise DBMMcpFeatureDisabledException(feature="Oracle AWR")


def list_awr_snapshots(
    immute_domain: str,
    addr: Optional[str] = None,
    days: int = 7,
    limit: int = ORACLE_MAX_ROWS,
) -> dict:
    _ensure_enabled()
    limit = min(int(limit or ORACLE_MAX_ROWS), ORACLE_MAX_ROWS)
    with oracle_cursor(immute_domain, addr) as cur:
        cur.execute(SQL_LIST_AWR_SNAPSHOTS, {"days": int(days), "row_limit": limit})
        rows = fetch_dicts(cur)
    return {"snapshots": rows, "count": len(rows), "days": days}


def generate_awr_report(
    immute_domain: str,
    begin_snap: int,
    end_snap: int,
    addr: Optional[str] = None,
    dbid: Optional[int] = None,
    inst_num: Optional[int] = None,
) -> dict:
    """
    生成指定快照区间的 AWR HTML 报告。
    从 pipelined function 按行读取并拼接完整 HTML。
    dbid/inst_num 未传则取当前实例默认值（v$database.dbid, v$instance.instance_number）。
    """
    _ensure_enabled()

    with oracle_cursor(immute_domain, addr) as cur:
        if dbid is None:
            cur.execute("SELECT dbid FROM v$database")
            dbid = cur.fetchone()[0]
        if inst_num is None:
            cur.execute("SELECT instance_number FROM v$instance")
            inst_num = cur.fetchone()[0]

        cur.execute(
            SQL_AWR_REPORT,
            {
                "dbid": int(dbid),
                "inst_num": int(inst_num),
                "begin_snap": int(begin_snap),
                "end_snap": int(end_snap),
            },
        )
        # pipelined function 每行是 VARCHAR2(500)，用换行拼接还原完整 HTML
        parts = []
        for row in cur:
            line = row[0]
            if line is not None:
                parts.append(line)
        report_html = "\n".join(parts)

    return {
        "dbid": dbid,
        "instance_number": inst_num,
        "begin_snap": begin_snap,
        "end_snap": end_snap,
        "report_html": report_html,
        "report_size": len(report_html),
    }
