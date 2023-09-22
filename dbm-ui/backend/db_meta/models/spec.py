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
import json
from collections import defaultdict
from typing import Dict, List

from django.db import models
from django.utils.translation import ugettext_lazy as _

from backend import env
from backend.bk_web.models import AuditedModel
from backend.configuration.constants import SystemSettingsEnum
from backend.configuration.models import SystemSettings
from backend.constants import INT_MAX
from backend.db_meta.enums import ClusterType, MachineType
from backend.ticket.constants import AffinityEnum


class Spec(AuditedModel):
    """
    资源规格
    """

    spec_id = models.AutoField(primary_key=True)
    spec_name = models.CharField(max_length=128, help_text=_("虚拟规格名称"))
    spec_cluster_type = models.CharField(
        max_length=64, choices=ClusterType.get_choices(), help_text=_("集群类型:MySQL、Proxy、Spider")
    )
    spec_machine_type = models.CharField(max_length=64, choices=MachineType.get_choices(), help_text=_("机器规格类型"))
    cpu = models.JSONField(null=True, help_text=_("cpu规格描述:{'min':1,'max':10}"))
    mem = models.JSONField(null=True, help_text=_("mem规格描述:{'min':100,'max':1000}"))
    device_class = models.JSONField(null=True, help_text=_("实际机器机型: ['class1','class2'] "))
    storage_spec = models.JSONField(null=True, help_text=_("存储磁盘需求配置:{'mount_point':'/data','size':500,'type':'ssd'}"))
    desc = models.TextField(help_text=_("资源规格描述"), null=True, blank=True)
    # es专属
    instance_num = models.IntegerField(default=0, help_text=_("实例数(es专属)"))
    # spider，redis集群专属
    qps = models.JSONField(default=dict, help_text=_("qps规格描述:{'min': 1, 'max': 100}"))

    class Meta:
        index_together = [("spec_cluster_type", "spec_machine_type", "spec_name")]

    @property
    def capacity(self):
        """
        根据不同集群类型，计算该规格的容量
        TendbCluster: 如果只有/data数据盘，则容量/2; 如果有/data和/data1数据盘，则按照/data1为准
        TendisPlus, TendisSSD: 一定有两块盘，以/data1为准
        TendisCache: 以内存为准，内存不是范围，是一个准确的值
        默认：磁盘总容量
        """
        mount_point__size: Dict[str, int] = {disk["mount_point"]: disk["size"] for disk in self.storage_spec}
        if self.spec_cluster_type == ClusterType.TenDBCluster:
            return mount_point__size.get("data1") or mount_point__size["/data"] / 2

        if self.spec_cluster_type in [
            ClusterType.TwemproxyTendisSSDInstance,
            ClusterType.TendisPredixyTendisplusCluster,
        ]:
            return mount_point__size["/data1"]

        if self.spec_cluster_type == ClusterType.TendisTwemproxyRedisInstance:
            # 取min, max都一样
            return self.mem["min"]

        return sum(map(lambda x: int(x), mount_point__size.values()))

    def get_apply_params_detail(self, group_mark, count, bk_cloud_id, affinity=AffinityEnum.NONE, location_spec=None):
        # 获取资源申请的detail过程，暂时忽略亲和性和位置参数过滤
        spec_offset = SystemSettings.get_setting_value(SystemSettingsEnum.SPEC_OFFSET)
        # 如果暂不支持城市和亲和性，则忽略
        affinity = affinity if env.RESOURCE_SUPPORT_AFFINITY else AffinityEnum.NONE
        location_spec = location_spec if env.RESOURCE_SUPPORT_AFFINITY else None
        return {
            "group_mark": group_mark,
            "bk_cloud_id": bk_cloud_id,
            "device_class": self.device_class,
            "spec": {
                "cpu": self.cpu,
                # 内存GB-->MB，只偏移左边
                "ram": {
                    "min": max(int(self.mem["min"] * 1024 - spec_offset["mem"]), 0),
                    "max": int(self.mem["max"] * 1024),
                },
            },
            "storage_spec": [
                {
                    "mount_point": storage_spec["mount_point"],
                    # 如果是all，则需要传空
                    "disk_type": "" if storage_spec["type"] == "ALL" else storage_spec["type"],
                    "min": storage_spec["size"] - spec_offset["disk"],
                    "max": INT_MAX,
                }
                for storage_spec in self.storage_spec
            ],
            "count": count,
            "affinity": affinity,
            "location_spec": location_spec,
        }

    def get_backend_group_apply_params_detail(self, bk_cloud_id, backend_group):
        # 专属于后端：如果一组master/slave有特殊要求，则采用backend_group申请
        backend_group_params = [
            self.get_apply_params_detail(
                group_mark=f"backend_group_{group}",
                count=2,
                bk_cloud_id=bk_cloud_id,
                affinity=backend_group.get("affinity", AffinityEnum.NONE),
                location_spec=backend_group.get("location_spec", None),
            )
            for group in range(backend_group["count"])
        ]
        return backend_group_params

    def get_spec_info(self):
        # 获取规格的基本信息
        return {
            "id": self.spec_id,
            "name": self.spec_name,
            "cpu": self.cpu,
            "mem": self.mem,
            "qps": self.qps,
            "device_class": self.device_class,
            "storage_spec": self.storage_spec,
        }

    def compare_to(self, spec: "Spec", compare_flag: bool):
        """比较规格"""
        # 比较存储配置里磁盘的最小值 TODO: TendisCache可能是内存比较
        self_min_config = min([storage.get("size", 0) for storage in self.storage_spec])
        spec_min_config = min([storage.get("size", 0) for storage in spec.storage_spec])

        if compare_flag:
            return self_min_config >= spec_min_config
        else:
            return self_min_config <= spec_min_config

    @classmethod
    def init_spec(cls):
        """初始化系统规格配置"""
        spec_namespace__name: Dict[str, Dict[str, List]] = defaultdict(lambda: defaultdict(list))
        for spec in Spec.objects.all():
            spec_namespace__name[spec.spec_cluster_type][spec.spec_machine_type].append(spec.spec_name)

        with open("backend/db_meta/init/spec_init.json", "r") as f:
            system_spec_init_map = json.loads(f.read())

        to_init_specs: List[Spec] = []
        for spec_cluster_type in system_spec_init_map.keys():
            for spec_machine_type in system_spec_init_map[spec_cluster_type].keys():
                for spec_details in system_spec_init_map[spec_cluster_type][spec_machine_type]:
                    # 排除已经存在的同名规格
                    if spec_details["spec_name"] in spec_namespace__name[spec_cluster_type][spec_machine_type]:
                        continue

                    to_init_specs.append(
                        Spec(**spec_details, spec_machine_type=spec_machine_type, spec_cluster_type=spec_cluster_type)
                    )

        Spec.objects.bulk_create(to_init_specs)

    @classmethod
    def get_choices(cls):
        try:
            spec_choices = [
                (spec.spec_id, f"[{spec.spec_id}]{spec.spec_cluster_type}-{spec.spec_machine_type}-{spec.spec_name}")
                for spec in cls.objects.all()
            ]
        except Exception:  # pylint: disable=broad-except
            # 忽略出现的异常，此时可能因为表未初始化
            spec_choices = []
        return spec_choices


class SnapshotSpec(AuditedModel):
    """
    资源规格快照
    """

    # machine 表在做一个外键关联到快照表
    snapshot_id = models.AutoField(primary_key=True)
    spec_id = models.PositiveIntegerField(null=False)
    spec_name = models.CharField(max_length=128)
    spec_type = models.CharField(max_length=64, default="MySQL")
    cpu = models.JSONField(null=True, help_text=_("cpu规格描述:{'min':1,'max':10}"))
    mem = models.JSONField(null=True, help_text=_("mem规格描述:{'min':100,'max':1000}"))
    device_class = models.JSONField(null=True, help_text=_("实际机器机型: ['class1','class2'] "))
    storage_spec = models.JSONField(null=True)
    desc = models.TextField(default="", help_text=_("资源规格描述"))
