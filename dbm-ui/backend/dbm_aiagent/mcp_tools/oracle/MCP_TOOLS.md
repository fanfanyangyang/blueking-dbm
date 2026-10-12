# Oracle MCP Tools

Oracle 数据库相关的 MCP 工具集，供 LLM Agent 调用进行只读查询、健康探活、性能分析与 AWR 报告生成。

- **MCP server 名称**：`oracle-query`（所有 Oracle 工具统一归入该 server）。
- 鉴权维度：**集群**（immute_domain）。
- 鉴权实现：`permission_classes=[McpClusterDetailPermission]` + `mcp_auth_parser=auth_parse_clusters`。
- 元数据来源：`db_meta.Cluster`（`cluster_type` ∈ {`OraclePrimaryStandby`, `OracleSingleNone`}）+ `db_meta.StorageInstance`。
- 工具性质：全部为**只读**（SELECT / PL/SQL 调用只读包函数），均使用绑定变量防止 SQL 注入。
- 行数上限：所有列表接口统一受 `ORACLE_MAX_ROWS`（默认 200）约束，使用 `ROWNUM <= :row_limit` 子查询包装。
- **目标版本**：Oracle 11.2.0.4。

## 通用入参

所有 Oracle MCP 工具共享以下入参：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `cluster_domain` | string | 是 | Oracle 集群的 `immute_domain`，鉴权维度 |
| `addr` | string | 否 | 目标实例 `ip:port`。不填：默认连接 Primary（主从版）/ 唯一实例（单节点版）；填：强制校验属于 `cluster_domain` 对应集群，防越权。 |

## 环境变量

| 变量 | 默认值 | 说明                        |
|---|---|---------------------------|
| `ORACLE_MCP_USER` | `dbm_mcp_ro` | MCP 查询使用的 Oracle 只读账号     |
| `ORACLE_MCP_PASSWORD` | — | 账号密码（临时方案，后续切换至 DBM 密码服务） |
| `ORACLE_ENABLE_AWR` | `false` | AWR 工具开关，默认关闭             |
| `ORACLE_MCP_MAX_ROWS` | `200` | 单次查询返回行数上限                |
| `ORACLE_MCP_MAX_SQL_TEXT_LEN` | `4000` | SQL 文本字段截断长度              |
| `ORACLE_MCP_CONNECT_TIMEOUT` | `10` | 连接超时（秒）                   |
| `ORACLE_MCP_QUERY_TIMEOUT` | `60` | 单次查询超时（秒）                 |
| `ORACLE_MCP_POOL_MIN` / `_MAX` / `_INCREMENT` | `1 / 4 / 1` | 连接池参数                     |

## 工具目录（MCP server: `oracle-query`，共 17 个工具）

所有工具位于同一个 MCP server `oracle-query` 下；下方按能力域分节仅为阅读方便。
统一 `operation_id` 前缀为 `oracle_query_`，例如 `oracle_query_get_instance_info`。

| 能力域 | 工具数 | 用途 |
|---|---|---|
| [基础信息](#1-基础信息) | 3 | 实例概览、版本、参数 |
| [状态探活](#2-状态探活) | 1 | 快速健康探活 |
| [会话与活动](#3-会话与活动) | 3 | 活跃会话、阻塞链、长查询 |
| [性能分析](#4-性能分析) | 4 | Top SQL、等待事件、执行计划 |
| [容量](#5-容量) | 3 | 表空间、Undo、SGA/PGA |
| [健康检查](#6-健康检查) | 1 | 告警日志 |
| [AWR 报告](#7-awr-报告开关控制) | 2 | AWR 快照与报告（需开启） |

---

## 1. 基础信息

### 1.1 `oracle_query_get_instance_info`

查询 Oracle 实例概览（v$instance + v$database），用于了解版本、角色、启动时间、归档模式、保护模式等。

- **入参**：仅通用入参
- **数据源**：`v$instance`, `v$database`
- **出参**：
```json
{
  "instance": {
    "instance_name": "orcl1",
    "host_name": "oracle01",
    "version": "11.2.0.4.0",
    "startup_time": "2026-09-01T03:00:00",
    "status": "OPEN",
    "database_status": "ACTIVE",
    "instance_role": "PRIMARY_INSTANCE",
    "thread_num": 1,
    "archiver": "STARTED",
    "logins": "ALLOWED"
  },
  "database": {
    "db_name": "ORCL",
    "db_unique_name": "orcl_pri",
    "database_role": "PRIMARY",
    "open_mode": "READ WRITE",
    "log_mode": "ARCHIVELOG",
    "flashback_on": "YES",
    "protection_mode": "MAXIMUM PERFORMANCE",
    "dbid": 1234567890,
    "created": "2024-01-01T00:00:00"
  }
}
```

### 1.2 `oracle_query_get_db_version`

查询 Oracle 版本信息（v$version banner）。11.2 返回多行（Database / PL/SQL / CORE / TNS / NLSRTL）。

- **入参**：仅通用入参
- **数据源**：`v$version`
- **出参**：
```json
{"banners": ["Oracle Database 11g Enterprise Edition Release 11.2.0.4.0 - Production"]}
```

### 1.3 `oracle_query_get_db_parameters`

查询 Oracle 初始化参数（v$parameter）。

- **入参**：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `names` | string[] | 否 | 参数名列表。为空则返回全部（按 `ORACLE_MAX_ROWS` 截断）；非空则精确匹配。参数名使用白名单校验（字母/数字/下划线）+ 绑定变量，防注入。 |

- **数据源**：`v$parameter`
- **出参**：
```json
{
  "parameters": [
    {"name": "sga_target", "value": "8G", "display_value": "8G", "isdefault": "FALSE", ...}
  ],
  "truncated": false
}
```

---

## 2. 状态探活

### 2.1 `oracle_query_check_instance_status`

Oracle 实例综合**健康探活**。一次调用完成：连通性检查、关键状态读取、会话上限使用率估算、DG 状态读取、本次探活耗时测量，并输出 `healthy / warning / critical` 等级与原因。

- **入参**：仅通用入参
- **数据源**：`v$instance`, `v$database`, `v$session`, `v$parameter`
- **判定规则**：
  - `critical`：实例非 `OPEN` / 数据库非 `ACTIVE` / `archiver=FAILED` / 实例 `blocked`
  - `warning`：`logins=RESTRICTED` 或 session 使用率 ≥ 90%
  - 其它视为 `healthy`
- **出参**：
```json
{
  "reachable": true,
  "latency_ms": 32,
  "health": {
    "level": "warning",
    "reasons": ["logins=RESTRICTED"]
  },
  "state": {
    "instance_name": "orcl1",
    "instance_status": "OPEN",
    "database_status": "ACTIVE",
    "database_role": "PRIMARY",
    "open_mode": "READ WRITE",
    "protection_mode": "MAXIMUM PERFORMANCE",
    "switchover_status": "TO STANDBY",
    "archiver": "STARTED",
    "logins": "RESTRICTED",
    "blocked": "FALSE"
  },
  "sessions": {
    "total_sessions": 180,
    "active_sessions": 12,
    "blocked_sessions": 0,
    "user_sessions": 150,
    "session_limit": 500,
    "session_usage_pct": 36.0
  }
}
```

- **典型 LLM 使用场景**：
  - 用户问"这个库现在怎么样" → 一次调用拿到可读结论
  - 排障前的第一步快速 triage，决定下一步要调性能/会话/容量工具里的哪一个

---

## 3. 会话与活动

### 3.1 `oracle_query_get_active_sessions`

查询活跃用户会话（`v$session.status='ACTIVE'` 且 `wait_class != 'Idle'`）。

- **入参**：

| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `limit` | int | 否 | `ORACLE_MAX_ROWS` | 返回行数上限 |

- **出参**：`{"sessions": [...], "count": N}`
- **关键列**：`sid`, `serial_num`, `username`, `sql_id`, `event`, `wait_class`, `seconds_in_wait`, `blocking_session`, `last_call_et`

### 3.2 `oracle_query_get_blocking_sessions`

查询阻塞链（blocker → waiter），按 `waiter.seconds_in_wait` 降序。

- **入参**：同上 `limit`
- **出参**：`{"blocking_chains": [...], "count": N}`
- **关键列**：`blocker_sid`, `blocker_user`, `blocker_sql_id`, `waiter_sid`, `waiter_user`, `waiter_sql_id`, `waiter_event`, `waiter_seconds_in_wait`

### 3.3 `oracle_query_get_long_running_queries`

查询长时间运行的 SQL（`v$session.last_call_et >= min_seconds`）。

- **入参**：

| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `min_seconds` | int | 否 | 60 | 最小运行时长（秒） |
| `limit` | int | 否 | `ORACLE_MAX_ROWS` | 返回行数上限 |

- **出参**：`{"queries": [...], "count": N}`
- **关键列**：`sid`, `username`, `sql_id`, `seconds_running`, `event`, `sql_text`（截断到 `ORACLE_MAX_SQL_TEXT_LEN`）

---

## 4. 性能分析

### 4.1 `oracle_query_get_top_sql_by_cpu`

Top SQL（默认按 CPU 时间排序）。

- **入参**：

| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `sort_by` | enum | 否 | `cpu_time` | 可选：`elapsed_time` / `cpu_time` / `buffer_gets` / `disk_reads` / `executions`。白名单映射列名，防注入。 |
| `limit` | int | 否 | `ORACLE_MAX_ROWS` | 返回行数上限 |

- **数据源**：`v$sqlstats`
- **出参**：`{"sort_by": "cpu_time", "top_sql": [...], "count": N}`
- **关键列**：`sql_id`, `executions`, `elapsed_sec`, `cpu_sec`, `buffer_gets`, `disk_reads`, `avg_elapsed_ms`, `sql_text`

### 4.2 `oracle_query_get_top_sql_by_io`

Top SQL by IO（按 `disk_reads + direct_writes` 排序）。

- **入参**：`limit`
- **出参**：`{"top_sql": [...], "count": N}`
- **关键列**：`sql_id`, `disk_reads`, `direct_writes`, `physical_read_bytes`, `physical_write_bytes`

### 4.3 `oracle_query_get_wait_events`

Top 等待事件（`v$system_event`，剔除 Idle 类）。

- **入参**：`limit`
- **出参**：`{"events": [...], "count": N}`
- **关键列**：`event`, `wait_class`, `total_waits`, `time_waited_micro`, `avg_wait_cs`

### 4.4 `oracle_query_get_sql_plan`

查询指定 `sql_id` 的执行计划（`v$sql_plan`）。

- **入参**：

| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `sql_id` | string | 是 | — | SQL ID。白名单校验（字母/数字/下划线）。 |
| `child_number` | int | 否 | null | 子游标号，用于精确定位。 |

- **出参**：`{"sql_id": "...", "plan_steps": [...], "count": N}`
- **关键列**：`plan_hash_value`, `step_id`, `parent_id`, `operation`, `options`, `object_name`, `cost`, `cardinality`, `access_predicates`, `filter_predicates`

---

## 5. 容量

### 5.1 `oracle_query_get_tablespace_usage`

表空间使用率，按已用占比降序。

- **入参**：`limit`
- **数据源**：`dba_data_files` + `dba_free_space`
- **出参**：`{"tablespaces": [...], "count": N}`
- **关键列**：`tablespace_name`, `total_mb`, `used_mb`, `free_mb`, `used_pct`, `max_mb`, `autoextensible`

### 5.2 `oracle_query_get_undo_usage`

Undo 表空间使用情况（按 `ACTIVE` / `UNEXPIRED` / `EXPIRED` 分组）。

- **入参**：仅通用入参
- **数据源**：`dba_undo_extents`
- **出参**：`{"undo_extents": [...]}`

### 5.3 `oracle_query_get_sga_pga_usage`

SGA / PGA 内存使用情况。

- **入参**：仅通用入参
- **数据源**：`v$sga`, `v$pgastat`
- **出参**：`{"sga": [...], "pga": [...]}`

---

## 6. 健康检查

### 6.1 `oracle_query_get_alert_log_errors`

查询近 N 小时的 Oracle 告警日志错误（`v$diag_alert_ext`）。

- **入参**：

| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `hours` | int | 否 | 24 | 回溯小时数（1-720） |
| `limit` | int | 否 | `ORACLE_MAX_ROWS` | 返回行数上限 |

- **出参**：`{"errors": [...], "count": N, "hours": 24}`
- **关键列**：`ts`, `message_level`, `message_type`, `message_group`, `message_text`（截断到 2000）

---

## 7. AWR 报告（开关控制）

> **开关**：`ORACLE_ENABLE_AWR` 环境变量，默认 `false`。未启用时所有 AWR 工具抛 `DBMMcpFeatureDisabledException`。

### 7.1 `oracle_query_list_awr_snapshots`

列出最近 N 天的 AWR 快照（`dba_hist_snapshot`）。

- **入参**：

| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `days` | int | 否 | 7 | 回溯天数（1-90） |
| `limit` | int | 否 | `ORACLE_MAX_ROWS` | 返回行数上限 |

- **出参**：`{"snapshots": [...], "count": N, "days": 7}`
- **关键列**：`snap_id`, `dbid`, `instance_number`, `begin_interval_time`, `end_interval_time`

### 7.2 `oracle_query_generate_awr_report`

生成指定快照区间 `[begin_snap, end_snap]` 的 AWR HTML 报告（`dbms_workload_repository.awr_report_html`）。

- **入参**：

| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `begin_snap` | int | 是 | — | 起始快照 ID |
| `end_snap` | int | 是 | — | 结束快照 ID（必须 > begin_snap） |
| `dbid` | int | 否 | 当前实例 dbid | 可跨实例指定 |
| `inst_num` | int | 否 | 当前实例号 | 可跨实例指定 |

- **出参**：
```json
{
  "dbid": 1234567890,
  "instance_number": 1,
  "begin_snap": 1000,
  "end_snap": 1001,
  "report_html": "<html>...</html>",
  "report_size": 523148
}
```

---

## 安全与质量约束（全局生效）

1. **鉴权**：所有工具走 `McpClusterDetailPermission`，由 `auth_parse_clusters` 将 `cluster_domain` 映射到 `cluster_id`，走 IAM 集群级权限校验。
2. **实例越权防护**：传入 `addr` 时强制校验属于 `cluster_domain` 对应集群，拒绝连接任意实例。
3. **SQL 注入防护**：所有用户输入通过 Oracle 绑定变量传入；动态列名 / 标识符（`sort_by`、`sql_id`、`names`）通过枚举白名单或字符白名单校验。
4. **结果上限**：所有列表接口统一受 `ORACLE_MAX_ROWS` 约束，SQL 文本字段截断到 `ORACLE_MAX_SQL_TEXT_LEN`。
5. **连接复用**：按 `(ip, port, service_name)` 维度维护 `oracledb.ConnectionPool`，不每次 open/close。
6. **只读账号**：所有工具通过 `ORACLE_MCP_USER`（默认 `dbm_mcp_ro`）登录。
7. **AWR 开关**：`ORACLE_ENABLE_AWR` 控制，便于按要求禁用。
