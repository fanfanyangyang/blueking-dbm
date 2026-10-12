# Oracle MCP Tools

Oracle 数据库相关的 MCP 工具集，供 LLM Agent 调用进行只读查询、健康探活、性能分析与 AWR 报告生成。

- **MCP server 名称**：`oracle-query`（所有 Oracle 工具统一归入该 server）。
- 鉴权维度：**实例所属集群**（`bk_cloud_id` + `address`）。
- 鉴权实现：`permission_classes=[McpClusterDetailPermission]` + `mcp_auth_parser=auth_parse_instances`。
- 元数据来源：`db_meta.Machine` + `db_meta.Cluster`（`cluster_type` ∈ {`OraclePrimaryStandby`, `OracleSingleNone`}）+ `db_meta.StorageInstance`。
- 工具性质：全部为**只读**（SELECT / PL/SQL 调用只读包函数），均使用绑定变量防止 SQL 注入。
- 行数上限：所有列表接口统一受 `ORACLE_MAX_ROWS`（默认 200）约束，使用 `ROWNUM <= :row_limit` 子查询包装。
- **目标版本**：Oracle 11.2.0.4。

## 通用入参

所有 Oracle MCP 工具共享以下入参：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `bk_cloud_id` | integer | 是 | 实例所在云区域 ID |
| `address` | string | 是 | 目标实例 `ip:port`，鉴权维度；连接前会校验实例存在且属于 Oracle 集群。 |

## 环境变量

查询通过 DRS 的 `/v2/oracle/rpc` 接口执行（go-ora 纯 Go 驱动，无需 Oracle Instant Client，兼容 11.2.0.4）。

DBM（dbm-ui）侧：

| 变量 | 默认值 | 说明                        |
|---|---|---------------------------|
| `ORACLE_SERVICE_NAME` | `CFDB` | 连接使用的 service_name |
| `ORACLE_ENABLE_AWR` | `false` | AWR 工具开关，默认关闭             |
| `ORACLE_MCP_MAX_ROWS` | `200` | 单次查询返回行数上限                |
| `ORACLE_MCP_CONNECT_TIMEOUT` | `5` | DRS 建连超时（秒）                   |
| `ORACLE_MCP_QUERY_TIMEOUT` | `60` | 单条查询超时（秒）                 |
| `ORACLE_DRS_READ_USER` | `mcp_readonly` | 部署 DRS 时注入的 Oracle 只读账号 |
| `ORACLE_DRS_READ_PASSWORD` | — | 部署 DRS 时注入的 Oracle 只读账号密码 |

DRS 侧（由部署模板根据上面两个变量生成）：`ORACLE_READ_USER` / `ORACLE_READ_PASSWORD`。

## 工具目录（MCP server: `oracle-query`，共 15 个工具）

所有工具位于同一个 MCP server `oracle-query` 下；下方按能力域分节仅为阅读方便。
统一 `operation_id` 前缀为 `oracle_query_`，例如 `oracle_query_check_instance_status`。

| 能力域 | 工具数 | 用途 |
|---|---|---|
| [状态探活](#1-状态探活) | 2 | 快速健康探活、告警日志 |
| [会话与活动](#2-会话与活动) | 3 | 活跃会话、阻塞链、长查询 |
| [性能分析](#3-性能分析) | 4 | 执行计划、ASH 最近 N 分钟分析（ASH 需开启） |
| [容量](#4-容量) | 3 | 表空间、Undo、SGA/PGA |
| [AWR 报告](#5-awr-报告开关控制) | 3 | AWR 快照、按快照/按时间生成报告（需开启） |

> 不提供通用的 `v$parameter` 初始化参数查询工具。ASH 判定所需的 `cpu_count`
> 直接在窗口查询中以标量子查询取回（见 `impl/performance.py: SQL_ASH_WINDOW`）；
> 实例关键状态所需的 `sessions` 上限见 `impl/status.py: SQL_SESSION_LIMIT`。

---

## 1. 状态探活

### 1.1 `oracle_query_check_instance_status`

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

### 1.2 `oracle_query_get_alert_log_errors`

查询近 N 分钟的 Oracle 告警日志错误（`v$diag_alert_ext`，`message_level <= 8`）。

- **入参**：

| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `minutes` | int | 否 | 120 | 回溯分钟数（1-4320） |
| `limit` | int | 否 | `ORACLE_MAX_ROWS` | 返回行数上限 |

- **数据源**：`v$diag_alert_ext`
- **出参**：`{"errors": [...], "count": N, "minutes": 120}`
- **关键列**：`ts`, `message_level`, `message_type`, `message_group`, `message_text`（截断到 2000）

---

## 2. 会话与活动

### 2.1 `oracle_query_get_active_sessions`

查询活跃用户会话（`v$session.status='ACTIVE'` 且 `wait_class != 'Idle'`）。

- **入参**：

| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `limit` | int | 否 | `ORACLE_MAX_ROWS` | 返回行数上限 |

- **出参**：`{"sessions": [...], "count": N}`
- **关键列**：`sid`, `serial_num`, `username`, `sql_id`, `event`, `wait_class`, `seconds_in_wait`, `blocking_session`, `last_call_et`

### 2.2 `oracle_query_get_blocking_sessions`

查询阻塞链（blocker → waiter），按 `waiter.seconds_in_wait` 降序。

- **入参**：同上 `limit`
- **出参**：`{"blocking_chains": [...], "count": N}`
- **关键列**：`blocker_sid`, `blocker_user`, `blocker_sql_id`, `waiter_sid`, `waiter_user`, `waiter_sql_id`, `waiter_event`, `waiter_seconds_in_wait`

### 2.3 `oracle_query_get_long_running_queries`

查询长时间运行的 SQL（`v$session.last_call_et >= min_seconds`）。

- **入参**：

| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `min_seconds` | int | 否 | 60 | 最小运行时长（秒） |
| `limit` | int | 否 | `ORACLE_MAX_ROWS` | 返回行数上限 |

- **出参**：`{"queries": [...], "count": N}`
- **关键列**：`sid`, `username`, `sql_id`, `seconds_running`, `event`, `sql_text`

---

## 3. 性能分析

> 不提供基于 `v$sqlstats` / `v$system_event` 累计值（实例启动或 SQL 进入共享池以来）的 Top 列表：
> 累计排名长期被高频 SQL / 常见事件占据，不能反映当前问题。最近时间段的分析使用下方 ASH 工具。

### 3.1 `oracle_query_get_sql_plan`

查询指定 `sql_id` 的执行计划（`DBMS_XPLAN.DISPLAY_CURSOR`）。

返回 Oracle 官方格式化文本：带缩进的执行树、Predicate Information（谓词推入哪一步）、
Note 段（自适应计划、基数反馈等）。相比 `v$sql_plan` 的扁平结构化行（需调用方按 `parent_id` 自行重建树形），
可读性与信息量都显著更高。

- **入参**：

| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `sql_id` | string | 是 | — | SQL ID。白名单校验（字母/数字/下划线） |
| `child_number` | int | 否 | null | 子游标号；**不传则输出全部子游标** |
| `format` | string | 否 | `ALL` | 见下表 |

> `child_number` 显式传 `NULL` 才是输出全部子游标——`DISPLAY_CURSOR` 该参数的默认值是 `0`（仅第一个），
> 不显式传会使行为静默变窄。

#### `format` 取值

| 取值 | 说明 |
|---|---|
| `ALL` | **默认**。含 Query Block Name / Object Alias、Predicate Information、Column Projection。不依赖执行时统计，任何环境可用 |
| `TYPICAL` | Oracle 默认格式，信息少于 `ALL` |
| `ALLSTATS LAST` | 含 `A-Rows` / `A-Time` / `Buffers` 等**实际执行统计**，可与 `E-Rows` 对比判断基数估算偏差 |
| `ADVANCED` | `ALL` 再加 Outline Data，输出可达数百行 |

> **`ALLSTATS LAST` 的前提**：SQL 执行时带 `/*+ GATHER_PLAN_STATISTICS */` hint，或 `STATISTICS_LEVEL = ALL`
> （默认为 `TYPICAL`，生产库通常不开）。两者都不满足时**不会报错**，只会退化为无实际统计的计划并附 Note，
> 此时 `warnings` 中会给出提示。因此默认用 `ALL` 而非 `ALLSTATS LAST`。
>
> `format` 以绑定变量传入（非字符串拼接），但仍用枚举约束取值：`DBMS_XPLAN` 会静默忽略无法识别的格式关键字，
> 拼写错误不报错而是降级输出。

- **出参**：
```json
{
  "sql_id": "a1b2c3d4e5f6g",
  "format": "ALL",
  "found": true,
  "plan_text": "Plan hash value: 1234567890\n\n| Id | Operation | ...",
  "line_count": 42,
  "warnings": []
}
```

- **`found` 字段**：`DISPLAY_CURSOR` 依赖共享池。SQL 被 age out 后，它**不返回空集**，
  而是输出一行提示文本（如 `cannot be found`）。此时 `found=false` 并在 `warnings` 中说明。
- **行数上限**：`ORACLE_XPLAN_MAX_LINES`（1000 行），独立于 `ORACLE_MAX_ROWS`（200）设置，
  避免计划被中途截断；触达上限时在 `warnings` 中提示。

> **只读账号权限要求**：`DISPLAY_CURSOR` 内部访问 `V$SQL_PLAN_STATISTICS_ALL`、`V$SQL`、`V$SQL_PLAN`。
> 若只读账号仅被授予 `V$SQL_PLAN`（旧实现的需要），调用会直接报权限错误，需补授权。

### 3.2–3.4 ASH 最近 N 分钟分析（开关控制）

基于 `v$active_session_history`，统计最近 N 分钟前台会话的 DB time（1 个样本 ≈ 1 秒）。
ASH 与 AWR 同属 Diagnostics Pack，共用 `ORACLE_ENABLE_AWR` 开关，未开启时返回「功能未启用」。

建议下钻顺序：`get_ash_wait_class`（定方向）→ `get_ash_top_events`（定事件）→ `get_ash_top_sql`（定 SQL）→ `get_sql_plan`。

- **公共入参**：

| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `minutes` | int | 否 | 30 | 最近多少分钟，1–180 |
| `limit` | int | 否 | 20 / 15 | 仅 top_events / top_sql，返回条数 |

- **公共出参 `window`**：`requested_minutes`, `window_begin`, `window_end`, `oldest_sample_time`, `effective_sec`, `truncated`, `total_db_time_sec`, `total_aas`, `cpu_db_time_sec`, `load`。
  内存 ASH 是循环缓冲区，`truncated=true` 表示窗口前段已被覆盖，结果只代表 `effective_sec` 内的数据；`aas` 按 `effective_sec` 计算。
  `total_db_time_sec` / `total_aas` 为窗口内全部前台会话的 DB time 与整体 AAS，`cpu_db_time_sec` 为其中 `session_state='ON CPU'` 的部分，均不受 `limit` 截断影响。

#### `window.load`：CPU 繁忙度判定

`AAS = AAS(ON CPU) + AAS(等待)`，两个分量的参照物不同，**只有 ON CPU 部分能与 `cpu_count` 对比**：
`cpu_count` 是真正能并行跑的上限，而等待中的会话（I/O / 锁 / 并发）并不消耗 CPU。
因此 `level` 只由 `aas_cpu / cpu_count` 决定，`total_aas` 仅作为整体并发规模的参照。
`cpu_count` 随窗口查询一并取回（`v$parameter` 标量子查询），不增加 DRS 往返。

| 字段 | 说明 |
|---|---|
| `cpu_count` | 实例 `cpu_count` 初始化参数；取不到或非正数时为 `null` |
| `aas_cpu` | `ON CPU` 部分的 AAS |
| `aas_wait` | `total_aas - aas_cpu`，等待部分的 AAS |
| `aas_cpu_per_core` | `aas_cpu / cpu_count`，即 CPU 繁忙度 |
| `wait_dominant` | 等待分量是否占主导（`aas_wait >= aas_cpu` 且 `aas_wait >= 1`） |
| `level` | `low` / `normal` / `high` / `critical` / `unknown` |
| `summary` | 中文结论，含换算过程；`wait_dominant` 时追加「瓶颈不在 CPU」提示 |

判定阈值（经验值）：

| `aas_cpu_per_core` | `level` | 含义 |
|---|---|---|
| < 0.7 | `low` | CPU 仍有明显余量（< 0.5 可视为很空闲） |
| 0.7 – 1.0 | `normal` | ON CPU 会话数接近 CPU 核数，繁忙但基本能被 CPU 消化 |
| 1.0 – 2.0 | `high` | ON CPU 会话数超过 CPU 核数，CPU 上存在排队 |
| ≥ 2.0 | `critical` | 远超 CPU 核数，CPU 已过载 |

阈值取在 1.0 以下而非正好 1.0：`cpu_count` 是逻辑 CPU（含超线程），实际并行能力约为标称值的 0.6–0.7 倍；此外 `cpu_count` 可能被 instance caging / Resource Manager 改写，此时它反映配额而非物理核数。
`cpu_count` 或 ASH 样本不可用时 `level=unknown`。

实际判定是二维的，`level` 低并不代表没有问题：

| `aas_cpu_per_core` | `total_aas` | 结论 |
|---|---|---|
| 低 | 低 | 整体负载不高 |
| 低 | **高** | 并发高但不烧 CPU，瓶颈在等待（I/O / 锁 / 并发），**必须看 `wait_class`**（此时 `wait_dominant=true`） |
| 高 | 高 | 真正的 CPU 瓶颈 |

- **统一口径**：`session_state = 'ON CPU'` 的样本，event 记为 `CPU + CPU Wait`，wait_class 记为 `CPU`。

| 工具 | 出参列表字段 | 关键列 |
|---|---|---|
| `oracle_query_get_ash_wait_class` | `wait_classes` | `wait_class`, `db_time_sec`, `aas`, `pct` |
| `oracle_query_get_ash_top_events` | `events` | `event`, `wait_class`, `db_time_sec`, `aas`, `pct`, `pct_cum`, `sessions`, `top_sql_id`, `top_sql_sec` |
| `oracle_query_get_ash_top_sql` | `top_sql` | `sql_id`, `db_time_sec`, `aas`, `pct_of_sql_time`, `pct_of_db_time`, `top_event`, `top_event_pct`, `plan_count`, `top_plan_hash_value`, `sql_text` |

`get_ash_top_sql` 说明：`pct_of_sql_time` 为占「有 sql_id 的样本」比例，`pct_of_db_time` 为占全部前台样本比例；`plan_count > 1` 表示窗口内同一 SQL 使用了多个执行计划；`sql_text` 优先取 `v$sqlstats`，已被挤出共享池时回退 `dba_hist_sqltext`。

---

## 4. 容量

### 4.1 `oracle_query_get_tablespace_usage`

表空间使用率，按已用占比降序。

- **入参**：`limit`
- **数据源**：`dba_data_files` + `dba_free_space`
- **出参**：`{"tablespaces": [...], "count": N}`
- **关键列**：`tablespace_name`, `total_mb`, `used_mb`, `free_mb`, `used_pct`, `max_mb`, `autoextensible`

### 4.2 `oracle_query_get_undo_usage`

Undo 表空间使用情况（按 `ACTIVE` / `UNEXPIRED` / `EXPIRED` 分组）。

- **入参**：仅通用入参
- **数据源**：`dba_undo_extents`
- **出参**：`{"undo_extents": [...]}`

### 4.3 `oracle_query_get_sga_pga_usage`

SGA / PGA 内存使用情况。

- **入参**：仅通用入参
- **数据源**：`v$sga`, `v$pgastat`
- **出参**：`{"sga": [...], "pga": [...]}`

---

## 5. AWR 报告（开关控制）

> **开关**：`ORACLE_ENABLE_AWR` 环境变量，默认 `false`。未启用时所有 AWR 工具抛 `DBMMcpFeatureDisabledException`。

> ### ⚠️ 报告类工具的调用方式
> `generate_awr_report` / `generate_awr_report_by_time` 返回**完整报告**，体积通常 200KB–2MB。
> MCP 工具的返回值会直接进入模型上下文，因此这两个工具**必须由 skill 的脚本 / CLI 调用**，
> 由脚本裁剪出所需段落后再交给模型，**禁止模型直接 tool call**。
>
> 职责划分：MCP 只负责取回完整原始报告（不做有损裁剪，因为「哪些段落重要」属于分析逻辑）；
> 裁剪规则放在 skill 侧，便于随时调整。

### 5.1 `oracle_query_list_awr_snapshots`

列出最近 N 天的 AWR 快照（`dba_hist_snapshot`）。

- **入参**：

| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `days` | int | 否 | 7 | 回溯天数（1-90） |
| `limit` | int | 否 | `ORACLE_MAX_ROWS` | 返回行数上限 |

- **出参**：`{"snapshots": [...], "count": N, "days": 7}`
- **关键列**：`snap_id`, `dbid`, `instance_number`, `begin_interval_time`, `end_interval_time`

### 5.2 `oracle_query_generate_awr_report`

生成指定快照区间 `[begin_snap, end_snap]` 的 AWR 报告（`dbms_workload_repository.awr_report_text/html`）。

- **入参**：

| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `begin_snap` | int | 是 | — | 起始快照 ID |
| `end_snap` | int | 是 | — | 结束快照 ID（必须 > begin_snap） |
| `format` | string | 否 | `text` | `text` 供 LLM 分析 / `html` 供人工查看 |

- **出参**：
```json
{
  "begin_snap": 1000,
  "end_snap": 1001,
  "format": "text",
  "report": "WORKLOAD REPOSITORY report for ...",
  "report_size": 132480,
  "truncated": false,
  "warnings": []
}
```
- 报告固定针对**当前实例**：`dbid` / `instance_number` 直接取自 `v$database` / `v$instance`，不支持指定，也不在出参中回显。

### 5.3 `oracle_query_generate_awr_report_by_time`

按**时间区间**生成 AWR 报告：自动把 `[begin_time, end_time]` 解析为快照区间，免去先查 `snap_id` 的步骤。
告警时间、用户反馈的故障时段通常是时间点而非 `snap_id`，这个入口更贴近实际用法。

- **入参**：

| 字段 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `begin_time` | string | 是 | — | `YYYY-MM-DD HH:MM:SS` |
| `end_time` | string | 是 | — | `YYYY-MM-DD HH:MM:SS`，须晚于 `begin_time` |
| `format` | string | 否 | `text` | 同上 |

- **时区**：`dba_hist_snapshot.end_interval_time` 是**不带时区**的 `TIMESTAMP`，记录数据库服务器本地时间。
  因此入参按**服务器本地时间**解释，不做任何时区换算（故未使用 DRF `DateTimeField`，避免 `USE_TZ=True` 下被转成 UTC 产生整体偏移）。
- **跨度上限**：24 小时（`ORACLE_AWR_MAX_SPAN_HOURS`）。跨度过大时各项统计被平均稀释，失去诊断价值。

#### 快照选择策略：外扩

| 边界 | 取法 |
|---|---|
| `begin_snap` | `end_interval_time <= begin_time` 中 `snap_id` 最大者 |
| `end_snap` | `end_interval_time >= end_time` 中 `snap_id` 最小者 |

即报告区间 ⊇ 请求区间。相比「内缩」，外扩保证请求时段被完整覆盖，且窗口短于快照间隔（默认 1 小时）时仍可工作。
由 `end_time > begin_time` 可推出 `begin_snap < end_snap` 必然成立。

由于实际区间可能宽于请求，出参回显 `actual_begin_time` / `actual_end_time`（这是推导结果，调用方无法自行得知）。

- **出参**：在 5.2 的字段之外追加：

```json
{
  "requested_begin_time": "2026-11-13 10:00:00",
  "requested_end_time":   "2026-11-13 11:00:00",
  "actual_begin_time":    "2026-11-13 09:00:00",
  "actual_end_time":      "2026-11-13 11:00:00"
}
```

#### 边界情况

| 情况 | 处理 |
|---|---|
| 仓库内无任何快照 | 报错（AWR 未采集或刚建库） |
| `begin_time` 早于最早快照 | 报错并给出最早快照 `snap_id` 与时刻（超出保留期，默认 8 天） |
| `end_time` 晚于最新快照 | 回退到最新快照 + `warnings`，并提示改用 ASH 分析该时刻之后的活动 |
| 回退后区间内仍无完整快照间隔 | 报错并提示等待下一次快照或改用 ASH（刚发生的问题常见） |
| 区间内实例重启过 | `warnings` 提示累计统计量已重置、增量不可信（按 `COUNT(DISTINCT startup_time)` 判定） |

#### 为何分两次查询

快照解析很廉价，而报告生成开销大（秒级）。更关键的是：**快照参数不匹配时 `awr_report_*` 不报错，只返回一份空报告**，
表现为「调用成功但 `report_size` 很小」，极难诊断。因此先解析并校验，再决定是否生成。

> **`truncated` 字段**：报告由 pipelined function 按行返回，不受 `ORACLE_MAX_ROWS` 约束，但受 DRS 侧 10 万行上限约束。
> 触达上限时内容会被**静默截断**，此时 `truncated=true` 并在 `warnings` 中给出提示。

---

## 安全与质量约束（全局生效）

1. **鉴权**：所有工具走 `McpClusterDetailPermission`，由 `auth_parse_instances` 将 `address` 映射到实例所属的 `cluster_id`，走 IAM 集群级权限校验。
2. **实例越权防护**：由 `bk_cloud_id` + `address` 定位机器和存储实例，并校验其属于 Oracle 集群，拒绝连接任意实例。
3. **SQL 注入防护**：用户输入在 Python 侧渲染为转义后的 SQL 字面量（仅支持 None/数字/字符串）；动态列名 / 标识符（`sort_by`、`sql_id`、`names`）通过枚举白名单或字符白名单校验。
4. **结果上限**：列表接口统一受 `ORACLE_MAX_ROWS` 约束；按行返回文本的接口另设独立上限（`ORACLE_XPLAN_MAX_LINES` 1000 行、`ORACLE_AWR_MAX_LINES` 10 万行）；DRS 侧另有 10 万行 / 64MB 上限。
5. **连接方式**：一次工具调用的多条 SQL 合并为一次 DRS 请求，在同一连接上顺序执行；DRS 每次请求独立建连，用完即关。
6. **只读**：DRS 只放行 `SELECT` / `WITH`（拒绝 `FOR UPDATE`），连接账号为 DRS 侧配置的只读账号，应仅授予只读权限。
7. **AWR 开关**：`ORACLE_ENABLE_AWR` 控制，便于按要求禁用。
