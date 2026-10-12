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
from typing import Dict, List, Tuple

from backend.dbm_aiagent.mcp_tools.exceptions import (
    DBMMcpFeatureDisabledException,
    DBMMcpOracleQueryException,
    DBMMcpUnsafeIdentifierException,
)
from backend.dbm_aiagent.mcp_tools.oracle.constants import (
    ORACLE_AWR_MAX_LINES,
    ORACLE_ENABLE_AWR,
    ORACLE_MAX_ROWS,
    ORACLE_SQL_TIME_FORMAT,
)
from backend.dbm_aiagent.mcp_tools.oracle.enums import OracleAwrFormat
from backend.dbm_aiagent.mcp_tools.oracle.helpers.oracle_conn import run_query

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

# 把时间区间 [begin_time, end_time] 解析为快照区间，并一次性取回判定所需的边界信息。
#
# 采用「外扩」策略，保证报告区间覆盖请求区间：
#   begin_snap = end_interval_time <= begin_time 的最大快照
#   end_snap   = end_interval_time >= end_time   的最小快照
SQL_RESOLVE_SNAP_RANGE = """
WITH cur AS (
    SELECT d.dbid AS dbid, i.instance_number AS inst
    FROM v$database d, v$instance i
), snaps AS (
    SELECT s.snap_id, s.end_interval_time, s.startup_time
    FROM dba_hist_snapshot s, cur c
    WHERE s.dbid = c.dbid AND s.instance_number = c.inst
)
SELECT
    (SELECT MAX(snap_id) FROM snaps
      WHERE end_interval_time <= TO_TIMESTAMP(:begin_time, '{time_fmt}'))            AS begin_snap,
    (SELECT MIN(snap_id) FROM snaps
      WHERE end_interval_time >= TO_TIMESTAMP(:end_time, '{time_fmt}'))              AS end_snap,
    (SELECT TO_CHAR(MAX(end_interval_time), '{time_fmt}') FROM snaps
      WHERE end_interval_time <= TO_TIMESTAMP(:begin_time, '{time_fmt}'))            AS actual_begin_time,
    (SELECT TO_CHAR(MIN(end_interval_time), '{time_fmt}') FROM snaps
      WHERE end_interval_time >= TO_TIMESTAMP(:end_time, '{time_fmt}'))              AS actual_end_time,
    (SELECT MIN(snap_id) FROM snaps)                                                 AS oldest_snap,
    (SELECT MAX(snap_id) FROM snaps)                                                 AS newest_snap,
    (SELECT TO_CHAR(MIN(end_interval_time), '{time_fmt}') FROM snaps)                AS oldest_snap_time,
    (SELECT TO_CHAR(MAX(end_interval_time), '{time_fmt}') FROM snaps)                AS newest_snap_time,
    (SELECT COUNT(DISTINCT startup_time) FROM snaps
      WHERE end_interval_time >= TO_TIMESTAMP(:begin_time, '{time_fmt}')
        AND end_interval_time <= TO_TIMESTAMP(:end_time, '{time_fmt}'))              AS startup_count
FROM dual
""".format(
    time_fmt=ORACLE_SQL_TIME_FORMAT
)

# awr_report_text / awr_report_html 作为 pipelined function 调用，
# 返回 awrrpt_{text,html}_type_table，每行是 VARCHAR2，需要在 Python 侧按行拼接。
# 仅支持单机单实例：dbid / instance_number 固定取当前实例（非 RAC 时 instance_number 恒为 1）。
SQL_AWR_REPORT_TMPL = """
SELECT t.output
FROM v$database d, v$instance i,
     TABLE(
         DBMS_WORKLOAD_REPOSITORY.awr_report_{fmt}(
             d.dbid,
             i.instance_number,
             :begin_snap,
             :end_snap,
             0
         )
     ) t
"""


def _ensure_enabled():
    if not ORACLE_ENABLE_AWR:
        raise DBMMcpFeatureDisabledException(feature="Oracle AWR")


def list_awr_snapshots(
    addr: str,
    days: int = 7,
    limit: int = ORACLE_MAX_ROWS,
) -> dict:
    _ensure_enabled()
    limit = min(int(limit or ORACLE_MAX_ROWS), ORACLE_MAX_ROWS)
    rows = run_query(addr, SQL_LIST_AWR_SNAPSHOTS, {"days": int(days), "row_limit": limit})
    return {"snapshots": rows, "count": len(rows), "days": days}


def _render_report(addr: str, begin_snap: int, end_snap: int, report_format: str) -> Tuple[str, bool]:
    """
    调用 awr_report_{text,html} 生成报告并按行拼接。
    返回 (报告内容, 是否因触达 DRS 行数上限而被截断)。
    """
    # report_format 会拼入函数名，必须白名单校验
    if report_format not in OracleAwrFormat.get_values():
        raise DBMMcpUnsafeIdentifierException(msg=f"invalid awr report format: {report_format}")

    rows = run_query(
        addr,
        SQL_AWR_REPORT_TMPL.format(fmt=report_format),
        {"begin_snap": int(begin_snap), "end_snap": int(end_snap)},
    )
    # pipelined function 每行一个片段，用换行拼接还原完整报告
    content = "\n".join(row["output"] for row in rows if row.get("output") is not None)
    return content, len(rows) >= ORACLE_AWR_MAX_LINES


def _build_result(
    begin_snap: int,
    end_snap: int,
    report_format: str,
    content: str,
    truncated: bool,
    warnings: List[str],
) -> dict:
    if truncated:
        hint = f"报告行数已触达 DRS 上限（{ORACLE_AWR_MAX_LINES} 行），内容被截断，建议缩小快照区间"
        if report_format == OracleAwrFormat.HTML.value:
            hint += "，或改用 text 格式（体积约为 html 的 1/4）"
        warnings = warnings + [hint]
    return {
        "begin_snap": begin_snap,
        "end_snap": end_snap,
        "format": report_format,
        "report": content,
        "report_size": len(content),
        "truncated": truncated,
        "warnings": warnings,
    }


def generate_awr_report(
    addr: str,
    begin_snap: int,
    end_snap: int,
    report_format: str = OracleAwrFormat.TEXT.value,
) -> dict:
    """
    生成指定快照区间 [begin_snap, end_snap] 的 AWR 报告。
    报告固定针对当前实例（v$database.dbid, v$instance.instance_number）。
    """
    _ensure_enabled()
    content, truncated = _render_report(addr, begin_snap, end_snap, report_format)
    return _build_result(begin_snap, end_snap, report_format, content, truncated, [])


def _resolve_snap_range(addr: str, begin_time: str, end_time: str) -> Tuple[int, int, Dict[str, str], List[str]]:
    """
    把时间区间解析为快照区间（外扩，保证覆盖请求区间）。
    返回 (begin_snap, end_snap, 实际区间时间, warnings)。
    """
    rows = run_query(addr, SQL_RESOLVE_SNAP_RANGE, {"begin_time": begin_time, "end_time": end_time})
    r = rows[0] if rows else {}

    if r.get("oldest_snap") is None:
        raise DBMMcpOracleQueryException(msg="AWR 仓库中没有任何快照，请确认 AWR 采集已启用")

    warnings: List[str] = []
    begin_snap = r.get("begin_snap")
    end_snap = r.get("end_snap")
    actual_begin_time = r.get("actual_begin_time")
    actual_end_time = r.get("actual_end_time")

    # 请求起点早于最早快照：无法外扩，直接失败（报告区间会缺失前半段）
    if begin_snap is None:
        raise DBMMcpOracleQueryException(
            msg=(
                f"begin_time={begin_time} 早于最早可用快照（snap_id={r.get('oldest_snap')}, "
                f"{r.get('oldest_snap_time')}），已超出 AWR 保留期"
            )
        )

    # 请求终点晚于最新快照（例如刚发生的问题还未生成快照）：回退到最新快照
    if end_snap is None:
        end_snap = r.get("newest_snap")
        actual_end_time = r.get("newest_snap_time")
        warnings.append(
            f"end_time={end_time} 晚于最新快照，已回退至 snap_id={end_snap}（{actual_end_time}）；" "该时刻之后的活动尚未进入 AWR，如需分析请改用 ASH 工具"
        )

    # 回退后可能与 begin_snap 重合：请求区间内还没有形成完整的快照间隔。
    # 未回退时由 end_time > begin_time 可保证 begin_snap < end_snap，走不到这里。
    if end_snap <= begin_snap:
        raise DBMMcpOracleQueryException(
            msg=(
                f"[{begin_time}, {end_time}] 区间内尚无完整的快照间隔"
                f"（最新快照 snap_id={end_snap}, {actual_end_time}）。"
                "AWR 报告需要区间两端各有一个快照，请等待下一次快照生成，"
                "或改用 ASH 工具分析最近时段"
            )
        )

    if (r.get("startup_count") or 0) > 1:
        warnings.append("请求区间内实例发生过重启，累计统计量已被重置，报告中的增量数据不可信")

    actual = {"actual_begin_time": actual_begin_time, "actual_end_time": actual_end_time}
    return int(begin_snap), int(end_snap), actual, warnings


def generate_awr_report_by_time(
    addr: str,
    begin_time: str,
    end_time: str,
    report_format: str = OracleAwrFormat.TEXT.value,
) -> dict:
    """
    按时间区间生成 AWR 报告：先把 [begin_time, end_time] 解析为快照区间，再生成报告。

    时间为数据库服务器本地时间（格式 YYYY-MM-DD HH:MM:SS），不做时区换算。
    快照按「外扩」策略选取，因此实际报告区间可能宽于请求区间，由出参 actual_* 回显。

    分两次查询：快照解析很廉价，而报告生成开销大且参数不匹配时不报错（只产出空报告），
    因此先解析并校验，再决定是否生成。
    """
    _ensure_enabled()

    begin_snap, end_snap, actual, warnings = _resolve_snap_range(addr, begin_time, end_time)
    content, truncated = _render_report(addr, begin_snap, end_snap, report_format)

    result = _build_result(begin_snap, end_snap, report_format, content, truncated, warnings)
    result.update(
        {
            "requested_begin_time": begin_time,
            "requested_end_time": end_time,
            **actual,
        }
    )
    return result
