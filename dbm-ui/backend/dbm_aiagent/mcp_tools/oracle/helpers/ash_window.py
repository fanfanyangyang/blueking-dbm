# -*- coding: utf-8 -*-
"""
TencentBlueKing is pleased to support the open source community by making 蓝鲸智云-DB管理系统(BlueKing-BK-DBM) available.
Copyright (C) 2017-2023 THL A29 Limited, a Tencent company. All rights reserved.
Licensed under the MIT License (the "License"); you may not use this file except in compliance with the License.
You may obtain a copy of the License at https://opensource.org/licenses/MIT
Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on
an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the
specific language governing permissions and limitations under the License.

内存 ASH 与历史 ASH 共用的窗口换算与分级。

只输出量化字段与固定阈值分级；阈值集中在本模块，避免两个数据源的分级口径漂移。
"""

from typing import Any, Dict, Optional

from backend.dbm_aiagent.mcp_tools.oracle.constants import ORACLE_ASH_MIN_COVERAGE_PCT

# 实际窗口比请求窗口短超过该秒数时，视为被截断
TRUNCATE_TOLERANCE_SEC = 60

# 请求终点超出数据可用终点该秒数以上时给出提示
FUTURE_TOLERANCE_SEC = 60

# CPU 繁忙度阈值：AAS(ON CPU) / cpu_count
_AAS_PER_CPU_LOW = 0.5
_AAS_PER_CPU_NORMAL = 0.8
_AAS_PER_CPU_HIGH = 1.2

# 活跃度阈值（基于 total_aas）
_IDLE_TOTAL_AAS = 0.1
_IDLE_PEAK_AAS = 1.0
_LIGHT_TOTAL_AAS = 1.0

# 样本数低于该值时，占比（pct）不具统计意义
MIN_SAMPLES_FOR_PCT = 60

_SLIM_WINDOW_KEYS = (
    "actual_begin",
    "actual_end",
    "effective_sec",
    "coverage_pct",
    "coverage_sufficient",
    "truncated",
    "total_db_time_sec",
    "warnings",
)


def to_db_time_sec(samples: Any, sample_interval_sec: int) -> int:
    """样本数 -> DB time 秒数。"""
    return int(samples or 0) * sample_interval_sec


def compute_aas(db_time_sec: Any, effective_sec: int) -> Optional[float]:
    """DB time 秒数 -> AAS（平均活跃会话数）；窗口为空时返回 None。"""
    if not effective_sec or effective_sec <= 0:
        return None
    return round((db_time_sec or 0) / effective_sec, 2)


def compute_coverage(requested_sec: int, effective_sec: int) -> Dict[str, Any]:
    """实际覆盖率；coverage_sufficient=false 表示数据源覆盖不足，应换数据源。"""
    coverage_pct = round(effective_sec * 100 / requested_sec, 1) if requested_sec > 0 else 0.0
    return {
        "coverage_pct": coverage_pct,
        "min_coverage_pct": ORACLE_ASH_MIN_COVERAGE_PCT,
        "coverage_sufficient": coverage_pct >= ORACLE_ASH_MIN_COVERAGE_PCT,
        "truncated": effective_sec < requested_sec - TRUNCATE_TOLERANCE_SEC,
    }


def derive_load(total_aas: Optional[float], cpu_aas: Optional[float], cpu_count: Any) -> Dict[str, Any]:
    """CPU 繁忙度分级。

    AAS = AAS(ON CPU) + AAS(等待)，只有 ON CPU 分量能与 cpu_count 对比，故 level 只由
    aas_cpu_per_core 决定；等待分量以 aas_wait 原样给出。
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
            "level": "unknown",
        }

    cpu_count = int(cpu_count)
    aas_cpu_per_core = round(cpu_aas / cpu_count, 2)
    if aas_cpu_per_core < _AAS_PER_CPU_LOW:
        level = "low"
    elif aas_cpu_per_core < _AAS_PER_CPU_NORMAL:
        level = "normal"
    elif aas_cpu_per_core < _AAS_PER_CPU_HIGH:
        level = "high"
    else:
        level = "critical"

    return {
        "cpu_count": cpu_count,
        "aas_cpu": cpu_aas,
        "aas_wait": wait_aas,
        "aas_cpu_per_core": aas_cpu_per_core,
        "level": level,
    }


def derive_activity(
    total_aas: Optional[float],
    total_samples: int,
    peak_samples: Any,
    peak_label: Optional[str],
    sample_interval_sec: int = 1,
    peak_bucket_sec: int = 60,
    peak_field: str = "peak_minute",
) -> Dict[str, Any]:
    """数据库活跃度分级，与 CPU 繁忙度正交。

    peak_* 描述最忙的一个时间桶；sample_sufficient 按原始 total_samples 判定，不乘 sample_interval_sec。
    """
    peak_aas = round(to_db_time_sec(peak_samples, sample_interval_sec) / peak_bucket_sec, 2) if peak_samples else 0.0
    base = {
        peak_field: peak_label,
        f"{peak_field}_aas": peak_aas,
        "peak_bucket_sec": peak_bucket_sec,
        "sample_sufficient": total_samples >= MIN_SAMPLES_FOR_PCT,
        "min_samples_for_pct": MIN_SAMPLES_FOR_PCT,
    }

    if total_aas is None:
        return {**base, "level": "unknown"}
    if total_aas < _IDLE_TOTAL_AAS and peak_aas < _IDLE_PEAK_AAS:
        level = "idle"
    elif total_aas < _LIGHT_TOTAL_AAS:
        level = "light"
    else:
        level = "active"
    return {**base, "level": level}


def slim_window(window: Dict[str, Any]) -> Dict[str, Any]:
    """精简 window：只保留本次统计区间与可信度，load / activity 由 wait_class 工具单独返回。"""
    slim: Dict[str, Any] = {key: window.get(key) for key in _SLIM_WINDOW_KEYS}
    slim["sample_sufficient"] = window.get("activity", {}).get("sample_sufficient")
    return slim
