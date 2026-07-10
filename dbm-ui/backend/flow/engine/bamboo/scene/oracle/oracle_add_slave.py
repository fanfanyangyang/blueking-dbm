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
import copy
import logging
import os
from dataclasses import asdict
from typing import Dict, Optional

from django.utils.translation import gettext as _

from backend.configuration.constants import DBType
from backend.db_meta.enums import ClusterEntryRole, InstanceRole
from backend.db_meta.enums.cluster_type import ClusterType
from backend.db_meta.models import Cluster
from backend.flow.consts import DBA_ORACLE_USER, DBA_ROOT_USER, DEPENDENCIES_PLUGINS, ManagerDefaultPort
from backend.flow.engine.bamboo.scene.common.builder import Builder, SubBuilder
from backend.flow.engine.bamboo.scene.common.get_file_list import GetFileList
from backend.flow.plugins.components.collections.common.install_nodeman_plugin import (
    InstallNodemanPluginServiceComponent,
)
from backend.flow.plugins.components.collections.common.pause import PauseComponent
from backend.flow.plugins.components.collections.common.sa_idle_check import CheckMachineIdleComponent
from backend.flow.plugins.components.collections.mysql.dns_manage import MySQLDnsManageComponent
from backend.flow.plugins.components.collections.oracle.exec_actuator_script import (
    ExecuteOracleActuatorScriptComponent,
)
from backend.flow.plugins.components.collections.oracle.oracle_db_meta import OracleDBMetaComponent
from backend.flow.plugins.components.collections.oracle.trans_flies import TransFileComponent
from backend.flow.plugins.components.collections.oracle.upload_file import UploadFileServiceComponent
from backend.flow.utils.common_act_dataclass import InitCheckKwargs, InstallNodemanPluginKwargs
from backend.flow.utils.mysql.mysql_act_dataclass import UpdateDnsRecordKwargs
from backend.flow.utils.oracle.oracle_act_dataclass import DownloadMediaKwargs, UploadFile
from backend.flow.utils.oracle.oracle_act_payload import OracleActPayload
from backend.flow.utils.oracle.oracle_context_dataclass import AddSlaveContext, OracleActKwargs
from backend.flow.utils.oracle.oracle_db_meta import OracleDBMeta

logger = logging.getLogger("flow")

BKREPO_ORACLE_PATH = "oracle/files"


class OracleAddSlaveFlow(object):
    """
    Oracle[添加从库/重建从库]单据的流程引擎

    资源池模式(ip_source=resource_pool):
    {
        "uid": "2022111212001000",
        "root_id": 123,
        "created_by": "admin",
        "bk_biz_id": 9991001,
        "ticket_type": "ORACLE_ADD_SLAVE",
        "infos": [
            {
                "cluster_id": 2,
                "old_node": {"ip": "1.1.1.1", "bk_cloud_id": 0},
                "replace_flag": False,
                "resource_spec": {"oracle": {"spec_id": 1, "count": 1}}
            }
        ],
        "ip_source": "resource_pool"
    }
    """

    def __init__(self, root_id: str, data: Optional[Dict]):
        """
        传入参数
        @param root_id : 任务流程定义的root_id
        @param data : 单据传递过来的参数列表，是dict格式
        """

        self.root_id = root_id
        self.data = data

    def oracle_add_slave_flow(self):
        """
        oracle [添加从库/重建从库]流程
        """

        oracle_pipeline = Builder(root_id=self.root_id, data=self.data)
        sub_pipelines = []
        for info in self.data["infos"]:
            sub_data = copy.deepcopy(self.data)
            sub_data.pop("infos")
            sub_pipeline = SubBuilder(root_id=self.root_id, data={**info, **sub_data})
            cluster = Cluster.objects.get(id=info["cluster_id"])
            bk_cloud_id = cluster.bk_cloud_id
            cluster_master = cluster.storageinstance_set.get(instance_role=InstanceRole.PRIMARY.value).machine.ip
            old_node = info["old_node"]["ip"]
            new_slave = info["new_slave"]["ip"]

            sub_pipeline.add_act(
                act_name=_("空闲检查[{}]".format(new_slave)),
                act_component_code=CheckMachineIdleComponent.code,
                kwargs=asdict(InitCheckKwargs(ips=[new_slave], bk_cloud_id=bk_cloud_id)),
            )

            acts_list = []
            for plugin_name in DEPENDENCIES_PLUGINS:
                acts_list.append(
                    {
                        "act_name": _("安装[{}]插件".format(plugin_name)),
                        "act_component_code": InstallNodemanPluginServiceComponent.code,
                        "kwargs": asdict(
                            InstallNodemanPluginKwargs(
                                ips=[new_slave], plugin_name=plugin_name, bk_cloud_id=bk_cloud_id
                            )
                        ),
                    }
                )
            sub_pipeline.add_parallel_acts(acts_list=acts_list)

            sub_pipeline.add_act(
                act_name=_("旧实例下发actuator"),
                act_component_code=TransFileComponent.code,
                kwargs=asdict(
                    DownloadMediaKwargs(
                        bk_cloud_id=bk_cloud_id,
                        exec_ip=[old_node, cluster_master],
                        file_list=GetFileList(db_type=DBType.Oracle).get_db_actuator_package(),
                    )
                ),
            )

            sub_pipeline.add_act(
                act_name=_("新备库下发actuator以及oracle介质"),
                act_component_code=TransFileComponent.code,
                kwargs=asdict(
                    DownloadMediaKwargs(
                        bk_cloud_id=bk_cloud_id,
                        exec_ip=new_slave,
                        file_list=GetFileList(db_type=DBType.Oracle).oracle_install_package(
                            self.data["db_version"], self.data["patch_list"]
                        ),
                    )
                ),
            )

            sub_pipeline.add_act(
                act_name=_("获取集群配置"),
                act_component_code=ExecuteOracleActuatorScriptComponent.code,
                kwargs=asdict(
                    OracleActKwargs(
                        exec_ip=old_node,
                        bk_cloud_id=bk_cloud_id,
                        run_as_system_user=DBA_ORACLE_USER,
                        get_oracle_payload_func=OracleActPayload.get_config_payload.__name__,
                    )
                ),
                write_payload_var=AddSlaveContext.get_configs_var_name(),
            )

            sub_pipeline.add_act(
                act_name=_("获取参数文件"),
                act_component_code=ExecuteOracleActuatorScriptComponent.code,
                kwargs=asdict(
                    OracleActKwargs(
                        exec_ip=old_node,
                        bk_cloud_id=bk_cloud_id,
                        run_as_system_user=DBA_ORACLE_USER,
                        get_oracle_payload_func=OracleActPayload.get_pfile_payload.__name__,
                    )
                ),
                write_payload_var=AddSlaveContext.get_pfile_var_name(),
            )

            sub_pipeline.add_act(
                act_name=_("获取密码文件"),
                act_component_code=ExecuteOracleActuatorScriptComponent.code,
                kwargs=asdict(
                    OracleActKwargs(
                        exec_ip=old_node,
                        bk_cloud_id=bk_cloud_id,
                        run_as_system_user=DBA_ORACLE_USER,
                        get_oracle_payload_func=OracleActPayload.get_password_file_payload.__name__,
                    )
                ),
                write_payload_var=AddSlaveContext.get_orapw_var_name(),
            )

            pfile = _("{}.pfile.ora".format(self.data["uid"]))
            orapw = _("{}.orapw.ora".format(self.data["uid"]))
            sub_pipeline.add_act(
                act_name=_("上传参数文件"),
                act_component_code=UploadFileServiceComponent.code,
                kwargs=asdict(
                    UploadFile(
                        path=os.path.join(BKREPO_ORACLE_PATH, pfile),
                        content_var=AddSlaveContext.get_pfile_var_name(),
                    )
                ),
            )

            sub_pipeline.add_act(
                act_name=_("上传密码文件"),
                act_component_code=UploadFileServiceComponent.code,
                kwargs=asdict(
                    UploadFile(
                        path=os.path.join(BKREPO_ORACLE_PATH, orapw),
                        content_var=AddSlaveContext.get_orapw_var_name(),
                        encoding="base64",
                    )
                ),
            )

            sub_pipeline.add_act(
                act_name=_("下发参数与密码文件"),
                act_component_code=TransFileComponent.code,
                kwargs=asdict(
                    DownloadMediaKwargs(
                        bk_cloud_id=bk_cloud_id,
                        exec_ip=new_slave,
                        file_list=GetFileList(db_type=DBType.Oracle).oracle_file(
                            path=BKREPO_ORACLE_PATH, filelist=[pfile, orapw]
                        ),
                    )
                ),
            )

            sub_pipeline.add_act(
                act_name=_("获取软链接配置"),
                act_component_code=ExecuteOracleActuatorScriptComponent.code,
                kwargs=asdict(
                    OracleActKwargs(
                        exec_ip=old_node,
                        bk_cloud_id=bk_cloud_id,
                        get_oracle_payload_func=OracleActPayload.get_symbolic_link_payload.__name__,
                    )
                ),
                write_payload_var=AddSlaveContext.get_path_var_name(),
            )

            sub_pipeline.add_act(
                act_name=_("系统配置初始化"),
                act_component_code=ExecuteOracleActuatorScriptComponent.code,
                kwargs=asdict(
                    OracleActKwargs(
                        exec_ip=new_slave,
                        bk_cloud_id=bk_cloud_id,
                        run_as_system_user=DBA_ROOT_USER,
                        get_oracle_payload_func=OracleActPayload.get_sysinit_payload.__name__,
                    )
                ),
            )

            sub_pipeline.add_act(
                act_name=_("部署Oracle软件"),
                act_component_code=ExecuteOracleActuatorScriptComponent.code,
                kwargs=asdict(
                    OracleActKwargs(
                        exec_ip=new_slave,
                        bk_cloud_id=bk_cloud_id,
                        get_oracle_payload_func=OracleActPayload.get_install_trans_payload.__name__,
                    )
                ),
            )

            sub_pipeline.add_act(
                act_name=_("部署Oracle实例"),
                act_component_code=ExecuteOracleActuatorScriptComponent.code,
                kwargs=asdict(
                    OracleActKwargs(
                        exec_ip=new_slave,
                        bk_cloud_id=bk_cloud_id,
                        get_oracle_payload_func=OracleActPayload.get_install_instance_trans_payload.__name__,
                    )
                ),
            )

            sub_pipeline.add_act(
                act_name=_("配置DataGuard"),
                act_component_code=ExecuteOracleActuatorScriptComponent.code,
                kwargs=asdict(
                    OracleActKwargs(
                        exec_ip=old_node,
                        bk_cloud_id=bk_cloud_id,
                        run_as_system_user=DBA_ORACLE_USER,
                        get_oracle_payload_func=OracleActPayload.get_config_data_guard_via_statistic_payload.__name__,
                    )
                ),
            )

            sub_pipeline.add_act(
                act_name=_("RMAN在线复制搭建备库"),
                act_component_code=ExecuteOracleActuatorScriptComponent.code,
                kwargs=asdict(
                    OracleActKwargs(
                        exec_ip=new_slave,
                        bk_cloud_id=bk_cloud_id,
                        run_as_system_user=DBA_ORACLE_USER,
                        get_oracle_payload_func=OracleActPayload.get_rman_duplicate_payload.__name__,
                    )
                ),
            )

            sub_pipeline.add_act(
                act_name=_("切换日志"),
                act_component_code=ExecuteOracleActuatorScriptComponent.code,
                kwargs=asdict(
                    OracleActKwargs(
                        exec_ip=cluster_master,
                        bk_cloud_id=bk_cloud_id,
                        run_as_system_user=DBA_ORACLE_USER,
                        get_oracle_payload_func=OracleActPayload.get_switch_log_payload.__name__,
                    )
                ),
            )

            sub_pipeline.add_act(
                act_name=_("检查同步状态"),
                act_component_code=ExecuteOracleActuatorScriptComponent.code,
                kwargs=asdict(
                    OracleActKwargs(
                        exec_ip=new_slave,
                        bk_cloud_id=bk_cloud_id,
                        run_as_system_user=DBA_ORACLE_USER,
                        get_oracle_payload_func=OracleActPayload.get_check_sync_status_payload.__name__,
                    )
                ),
            )

            sub_pipeline.add_act(
                act_name=_("实时应用日志"),
                act_component_code=ExecuteOracleActuatorScriptComponent.code,
                kwargs=asdict(
                    OracleActKwargs(
                        exec_ip=new_slave,
                        bk_cloud_id=bk_cloud_id,
                        run_as_system_user=DBA_ORACLE_USER,
                        get_oracle_payload_func=OracleActPayload.get_real_time_apply_payload.__name__,
                    )
                ),
            )

            sub_pipeline.add_act(
                act_name=_("切换日志"),
                act_component_code=ExecuteOracleActuatorScriptComponent.code,
                kwargs=asdict(
                    OracleActKwargs(
                        exec_ip=cluster_master,
                        bk_cloud_id=bk_cloud_id,
                        run_as_system_user=DBA_ORACLE_USER,
                        get_oracle_payload_func=OracleActPayload.get_switch_log_payload.__name__,
                    )
                ),
            )

            sub_pipeline.add_act(
                act_name=_("检查同步状态"),
                act_component_code=ExecuteOracleActuatorScriptComponent.code,
                kwargs=asdict(
                    OracleActKwargs(
                        exec_ip=new_slave,
                        bk_cloud_id=bk_cloud_id,
                        run_as_system_user=DBA_ORACLE_USER,
                        get_oracle_payload_func=OracleActPayload.get_check_sync_status_payload.__name__,
                    )
                ),
            )

            sub_pipeline.add_act(
                act_name=_("启动动态监听"),
                act_component_code=ExecuteOracleActuatorScriptComponent.code,
                kwargs=asdict(
                    OracleActKwargs(
                        exec_ip=new_slave,
                        bk_cloud_id=bk_cloud_id,
                        run_as_system_user=DBA_ORACLE_USER,
                        get_oracle_payload_func=OracleActPayload.get_start_listener_payload.__name__,
                    )
                ),
            )

            # 仅 oracle 单节点版集群需要校验旧实例是否为真实主节点
            if cluster.cluster_type == ClusterType.OracleSingleNone.value:
                sub_pipeline.add_act(
                    act_name=_("旧实例是否为真实主节点"),
                    act_component_code=ExecuteOracleActuatorScriptComponent.code,
                    kwargs=asdict(
                        OracleActKwargs(
                            exec_ip=old_node,
                            bk_cloud_id=bk_cloud_id,
                            run_as_system_user=DBA_ORACLE_USER,
                            get_oracle_payload_func=OracleActPayload.get_real_master_payload.__name__,
                        )
                    ),
                )

            sub_pipeline.add_act(
                act_name=_("写入元数据-新增机器"),
                act_component_code=OracleDBMetaComponent.code,
                kwargs={
                    "meta_func_name": OracleDBMeta.new_machine.__name__,
                    "bk_cloud_id": bk_cloud_id,
                    "bk_biz_id": int(self.data["bk_biz_id"]),
                    "new_ip": new_slave,
                    "resource_spec": info["resource_spec"],
                    "created_by": self.data["created_by"],
                    "cluster_type": cluster.cluster_type,
                },
            )

            if info["replace_flag"]:

                sub_pipeline.add_act(act_name=_("人工确认"), act_component_code=PauseComponent.code, kwargs={})

                sub_pipeline.add_act(
                    act_name=_("切换日志"),
                    act_component_code=ExecuteOracleActuatorScriptComponent.code,
                    kwargs=asdict(
                        OracleActKwargs(
                            exec_ip=cluster_master,
                            bk_cloud_id=bk_cloud_id,
                            run_as_system_user=DBA_ORACLE_USER,
                            get_oracle_payload_func=OracleActPayload.get_switch_log_payload.__name__,
                        )
                    ),
                )

                sub_pipeline.add_act(
                    act_name=_("检查同步状态"),
                    act_component_code=ExecuteOracleActuatorScriptComponent.code,
                    kwargs=asdict(
                        OracleActKwargs(
                            exec_ip=new_slave,
                            bk_cloud_id=bk_cloud_id,
                            run_as_system_user=DBA_ORACLE_USER,
                            get_oracle_payload_func=OracleActPayload.get_check_sync_status_payload.__name__,
                        )
                    ),
                )

                if cluster.cluster_type == ClusterType.OraclePrimaryStandby.value:
                    sub_pipeline.add_act(
                        act_name=_("写入元数据-替换备库实例"),
                        act_component_code=OracleDBMetaComponent.code,
                        kwargs={
                            "meta_func_name": OracleDBMeta.replace_instance.__name__,
                            "cluster_id": info["cluster_id"],
                            "bk_biz_id": int(self.data["bk_biz_id"]),
                            "new_instance_ip": new_slave,
                            "new_instance_port": ManagerDefaultPort.ORACLE_PORT.value,
                            "old_instance_ip": info["old_node"]["ip"],
                            "old_instance_port": ManagerDefaultPort.ORACLE_PORT.value,
                        },
                    )
                    dns = cluster.clusterentry_set.get(role=ClusterEntryRole.SLAVE_ENTRY).entry
                elif cluster.cluster_type == ClusterType.OracleSingleNone.value:
                    sub_pipeline.add_act(
                        act_name=_("写入元数据-替换单节点实例"),
                        act_component_code=OracleDBMetaComponent.code,
                        kwargs={
                            "meta_func_name": OracleDBMeta.replace_single_instance.__name__,
                            "cluster_id": info["cluster_id"],
                            "bk_biz_id": int(self.data["bk_biz_id"]),
                            "new_ip": new_slave,
                            "new_port": ManagerDefaultPort.ORACLE_PORT.value,
                        },
                    )
                    dns = cluster.clusterentry_set.get(role=ClusterEntryRole.MASTER_ENTRY).entry
                else:
                    raise Exception(
                        _("不支持的集群类型: {}, 仅支持 OraclePrimaryStandby / OracleSingleNone").format(cluster.cluster_type)
                    )

                sub_pipeline.add_act(
                    act_name=_("[{}]替换域名映射".format(dns)),
                    act_component_code=MySQLDnsManageComponent.code,
                    kwargs=asdict(
                        UpdateDnsRecordKwargs(
                            bk_cloud_id=cluster.bk_cloud_id,
                            old_instance=_("{}#{}".format(old_node, ManagerDefaultPort.ORACLE_PORT.value)),
                            new_instance=_("{}#{}".format(new_slave, ManagerDefaultPort.ORACLE_PORT.value)),
                            update_domain_name=dns,
                        ),
                    ),
                )

                sub_pipeline.add_act(act_name=_("人工确认"), act_component_code=PauseComponent.code, kwargs={})
                sub_pipeline.add_act(
                    act_name=_("关闭实例与监听"),
                    act_component_code=ExecuteOracleActuatorScriptComponent.code,
                    kwargs=asdict(
                        OracleActKwargs(
                            exec_ip=old_node,
                            bk_cloud_id=bk_cloud_id,
                            run_as_system_user=DBA_ORACLE_USER,
                            get_oracle_payload_func=OracleActPayload.get_shutdown_payload.__name__,
                        )
                    ),
                )

            sub_pipelines.append(
                sub_pipeline.build_sub_process(sub_name=_("集群[{}][添加从库/重建从库]").format(cluster.immute_domain))
            )

        oracle_pipeline.add_parallel_sub_pipeline(sub_flow_list=sub_pipelines)
        logger.info(_("构建Oracle[添加从库/重建从库]流程成功"))
        oracle_pipeline.run_pipeline(init_trans_data_class=AddSlaveContext())
