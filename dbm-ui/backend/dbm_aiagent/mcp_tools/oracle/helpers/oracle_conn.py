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
from backend.db_meta.enums.instance_role import InstanceRole
from backend.db_meta.models import Cluster, StorageInstance
from backend.dbm_aiagent.mcp_tools.exceptions import (
    DBMMcpClusterNotFoundException,
    DBMMcpInstanceNotFoundException,
    DBMMcpOracleConnectionException,
)
from backend.dbm_aiagent.mcp_tools.oracle.constants import (
    ORACLE_CONNECT_TIMEOUT,
    ORACLE_MCP_USER,
    ORACLE_POOL_INCREMENT,
    ORACLE_POOL_MAX,
    ORACLE_POOL_MIN,
    ORACLE_QUERY_TIMEOUT,
)

logger = logging.getLogger("root")

ORACLE_CLUSTER_TYPES = (ClusterType.OraclePrimaryStandby, ClusterType.OracleSingleNone)

# 连接池缓存：key = f"{ip}:{port}/{service_name}" → oracledb.ConnectionPool
_POOLS: dict = {}
_POOLS_LOCK = threading.Lock()


# ---------- db_meta 定位 ----------


def get_oracle_cluster(immute_domain: str) -> Cluster:
    """根据 immute_domain 定位 Oracle 集群（校验 cluster_type）。"""
    try:
        return Cluster.objects.get(immute_domain=immute_domain, cluster_type__in=ORACLE_CLUSTER_TYPES)
    except Cluster.DoesNotExist:
        raise DBMMcpClusterNotFoundException(msg=f"oracle cluster not found: {immute_domain}")


def _primary_storage(cluster: Cluster) -> StorageInstance:
    """取集群内的 Primary 实例（主从版）；单节点版唯一实例。"""
    qs = StorageInstance.objects.filter(cluster=cluster)
    primary = qs.filter(instance_role=InstanceRole.PRIMARY.value).first()
    if primary:
        return primary
    # 单节点版没有 Primary/Standby 区分，返回第一个
    first = qs.first()
    if not first:
        raise DBMMcpInstanceNotFoundException(msg=f"no storage instance for cluster: {cluster.immute_domain}")
    return first


def resolve_instance(immute_domain: str, addr: Optional[str] = None) -> StorageInstance:
    """
    解析目标实例：
    - 未传 addr：返回 Primary（主从版）/ 唯一实例（单节点版）
    - 传入 addr（ip:port）：必须属于该集群，否则报错（防止越权连接任意实例）
    """
    cluster = get_oracle_cluster(immute_domain)
    if not addr:
        return _primary_storage(cluster)

    if ":" not in addr:
        raise DBMMcpInstanceNotFoundException(msg=f"addr must be ip:port, got: {addr}")
    ip, port_str = addr.rsplit(":", 1)
    try:
        port = int(port_str)
    except ValueError:
        raise DBMMcpInstanceNotFoundException(msg=f"invalid port in addr: {addr}")

    inst = StorageInstance.objects.filter(cluster=cluster, machine__ip=ip, port=port).select_related("machine").first()
    if not inst:
        raise DBMMcpInstanceNotFoundException(msg=f"addr {addr} does not belong to cluster {immute_domain}")
    return inst


def resolve_service_name(cluster: Cluster, instance: StorageInstance) -> str:
    """
    解析 Oracle service_name。
    优先取 instance 的 db_module 配置；没有则用 immute_domain 作为 fallback。
    具体字段名随 DBM 侧 Oracle meta 落地情况可能微调。
    """
    return cluster.name or cluster.immute_domain


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
def oracle_cursor(immute_domain: str, addr: Optional[str] = None):
    """
    以 context manager 方式提供 Oracle cursor。
    使用示例：
        with oracle_cursor(immute_domain, addr) as cur:
            cur.execute("select 1 from dual")
            rows = cur.fetchall()
    """
    cluster = get_oracle_cluster(immute_domain)
    instance = resolve_instance(immute_domain, addr) if addr else _primary_storage(cluster)
    service_name = resolve_service_name(cluster, instance)
    password = _get_password(cluster, instance)

    pool = _get_pool(instance.machine.ip, instance.port, service_name, password)
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
        logger.exception("oracle query failed: %s / %s", immute_domain, addr)
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
