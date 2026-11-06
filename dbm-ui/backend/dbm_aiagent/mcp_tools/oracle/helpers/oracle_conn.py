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
import os
import threading
from contextlib import contextmanager
from typing import Optional

from backend.db_meta.enums import ClusterType
from backend.db_meta.models import Cluster, StorageInstance
from backend.dbm_aiagent.mcp_tools.exceptions import DBMMcpInstanceNotFoundException, DBMMcpOracleConnectionException
from backend.dbm_aiagent.mcp_tools.oracle.constants import (
    ORACLE_CONNECT_TIMEOUT,
    ORACLE_MCP_USER,
    ORACLE_POOL_INCREMENT,
    ORACLE_POOL_MAX,
    ORACLE_POOL_MIN,
    ORACLE_QUERY_TIMEOUT,
    ORACLE_SERVICE_NAME,
)

logger = logging.getLogger("root")

ORACLE_CLUSTER_TYPES = (ClusterType.OraclePrimaryStandby, ClusterType.OracleSingleNone)

# 连接池缓存：key = f"{ip}:{port}/{service_name}" → oracledb.ConnectionPool
_POOLS: dict = {}
_POOLS_LOCK = threading.Lock()


# ---------- db_meta 定位 ----------


def resolve_instance(addr: str) -> StorageInstance:
    """按 addr（ip:port）解析 Oracle 存储实例；未命中或命中多个实例（跨云区域同地址）时报错。"""
    if ":" not in addr:
        raise DBMMcpInstanceNotFoundException(msg=f"addr must be ip:port, got: {addr}")
    ip, port_str = addr.rsplit(":", 1)
    try:
        port = int(port_str)
    except ValueError:
        raise DBMMcpInstanceNotFoundException(msg=f"invalid port in addr: {addr}")

    instances = list(
        StorageInstance.objects.filter(machine__ip=ip, port=port, cluster__cluster_type__in=ORACLE_CLUSTER_TYPES)
        .select_related("machine")
        .distinct()[:2]
    )
    if not instances:
        raise DBMMcpInstanceNotFoundException(msg=f"oracle instance not found: {addr}")
    if len(instances) > 1:
        raise DBMMcpInstanceNotFoundException(msg=f"addr {addr} matches multiple oracle instances")
    return instances[0]


# ---------- 密码/认证策略（可替换） ----------


def _get_password(cluster: Cluster, instance: StorageInstance) -> str:
    """
    获取 ORACLE_MCP_USER 的密码。
    """
    pwd = os.getenv("ORACLE_MCP_PASSWORD")
    if not pwd:
        raise DBMMcpOracleConnectionException(msg="ORACLE_MCP_PASSWORD env is not set (temporary auth strategy)")
    return pwd


# ---------- 连接池 ----------


def _get_pool(ip: str, port: int, service_name: str, password: str):
    """按 (ip, port, service_name) 维度维护连接池。"""
    import oracledb

    key = f"{ip}:{port}/{service_name}"
    with _POOLS_LOCK:
        pool = _POOLS.get(key)
        if pool is not None:
            return pool

        dsn = oracledb.makedsn(ip, port, service_name=service_name)
        try:
            pool = oracledb.create_pool(
                user=ORACLE_MCP_USER,
                password=password,
                dsn=dsn,
                min=ORACLE_POOL_MIN,
                max=ORACLE_POOL_MAX,
                increment=ORACLE_POOL_INCREMENT,
                getmode=oracledb.POOL_GETMODE_WAIT,
                wait_timeout=ORACLE_CONNECT_TIMEOUT * 1000,
            )
        except Exception as e:  # pragma: no cover
            logger.exception("create oracle pool failed: %s", key)
            raise DBMMcpOracleConnectionException(msg=f"create pool failed for {key}: {e}")

        _POOLS[key] = pool
        return pool


@contextmanager
def oracle_cursor(addr: str):
    """
    以 context manager 方式提供 Oracle cursor。
    使用示例：
        with oracle_cursor(addr) as cur:
            cur.execute("select 1 from dual")
            rows = cur.fetchall()
    """
    instance = resolve_instance(addr)
    cluster = instance.cluster.filter(cluster_type__in=ORACLE_CLUSTER_TYPES).first()
    password = _get_password(cluster, instance)

    pool = _get_pool(instance.machine.ip, instance.port, ORACLE_SERVICE_NAME, password)
    conn = None
    try:
        conn = pool.acquire()
        conn.call_timeout = ORACLE_QUERY_TIMEOUT * 1000  # 毫秒
        cur = conn.cursor()
        try:
            yield cur
        finally:
            try:
                cur.close()
            except Exception:  # pylint: disable=broad-except
                pass
    except DBMMcpOracleConnectionException:
        raise
    except Exception as e:
        logger.exception("oracle query failed: %s", addr)
        raise DBMMcpOracleConnectionException(msg=str(e))
    finally:
        if conn is not None:
            try:
                pool.release(conn)
            except Exception:  # pylint: disable=broad-except
                pass


def fetch_dicts(cur, limit: Optional[int] = None) -> list:
    """把 cursor 结果转成 [{col: value, ...}, ...]，列名小写。"""
    if cur.description is None:
        return []
    cols = [d[0].lower() for d in cur.description]
    rows = cur.fetchmany(limit) if limit else cur.fetchall()
    return [dict(zip(cols, r)) for r in rows]
