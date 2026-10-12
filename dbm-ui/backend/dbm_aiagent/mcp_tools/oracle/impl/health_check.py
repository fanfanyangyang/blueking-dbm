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

from backend.dbm_aiagent.mcp_tools.oracle.constants import ORACLE_MAX_ROWS
from backend.dbm_aiagent.mcp_tools.oracle.helpers.oracle_conn import fetch_dicts, oracle_cursor

# 近 N 小时的告警日志错误（v$diag_alert_ext）
SQL_ALERT_LOG_ERRORS = """
SELECT * FROM (
    SELECT
        originating_timestamp AS ts,
        message_level,
        message_type,
        message_group,
        host_id,
        process_id,
        SUBSTR(message_text, 1, 2000) AS message_text
    FROM v$diag_alert_ext
    WHERE originating_timestamp > SYSTIMESTAMP - :hours / 24
      AND message_level <= 8          -- 1=critical, 2=severe, 8=info（取 <=8 覆盖告警）
    ORDER BY originating_timestamp DESC
) WHERE ROWNUM <= :row_limit
"""


def get_alert_log_errors(
    immute_domain: str,
    addr: Optional[str] = None,
    hours: int = 24,
    limit: int = ORACLE_MAX_ROWS,
) -> dict:
    limit = min(int(limit or ORACLE_MAX_ROWS), ORACLE_MAX_ROWS)
    with oracle_cursor(immute_domain, addr) as cur:
        cur.execute(SQL_ALERT_LOG_ERRORS, {"hours": int(hours), "row_limit": limit})
        rows = fetch_dicts(cur)
    return {"errors": rows, "count": len(rows), "hours": hours}
