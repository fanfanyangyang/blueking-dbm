/*
 * TencentBlueKing is pleased to support the open source community by making 蓝鲸智云-DB管理系统(BlueKing-BK-DBM) available.
 *
 * Copyright (C) 2017-2023 THL A29 Limited, a Tencent company. All rights reserved.
 *
 * Licensed under the MIT License (the "License"); you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at https://opensource.org/licenses/MIT
 *
 * Unless required by applicable law or agreed to in writing, software distributed under the License is distributed
 * on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for
 * the specific language governing permissions and limitations under the License.
 */
import dayjs from 'dayjs';

import { TicketTypes } from '@common/const';

import { utcDisplayTime } from '@utils';

import type {
  DumperInstallDetails,
  MysqlAuthorizationDetails,
  MySQLChecksumDetails,
  MySQLCloneDetails,
  MySQLDetails,
  MySQLFlashback,
  MySQLFullBackupDetails,
  MySQLHATruncateDetails,
  MySQLImportSQLFileDetails,
  MySQLInstanceCloneDetails,
  MySQLMasterFailDetails,
  MySQLMasterSlaveDetails,
  MySQLMigrateDetails,
  MysqlOpenAreaDetails,
  MySQLOperationDetails,
  MySQLProxyAddDetails,
  MySQLProxySwitchDetails,
  MySQLRenameDetails,
  MySQLRestoreLocalSlaveDetails,
  MySQLRestoreSlaveDetails,
  MySQLRollbackDetails,
  MySQLSlaveDetails,
  MySQLTableBackupDetails,
} from './details/mysql';
import type {
  RedisAddSlaveDetails,
  RedisCLBDetails,
  RedisClusterShardUpdateDetails,
  RedisClusterTypeUpdateDetails,
  RedisDataCheckAndRepairDetails,
  RedisDataCopyDetails,
  RedisDataStructrueDetails,
  RedisDBReplaceDetails,
  RedisDetails,
  RedisKeysDetails,
  RedisMasterSlaveSwitchDetails,
  RedisProxyScaleDownDetails,
  RedisProxyScaleUpDetails,
  RedisRollbackDataCopyDetails,
  RedisScaleUpDownDetails,
  RedisStructureDeleteDetails,
} from './details/redis';

/**
 * 单据状态类型
 */
export enum StatusTypes {
  ALL = '全部',
  PENDING = '审批中',
  RUNNING = '进行中',
  SUCCEEDED = '已完成',
  FAILED = '已失败',
  TERMINATED = '已终止',
  REVOKED = '已撤销',
}

export type StatusTypeKeys = keyof typeof StatusTypes;

/**
 * 状态 theme 映射
 */
const tagTheme = {
  PENDING: 'warning',
  RUNNING: 'info',
  SUCCEEDED: 'success',
  FAILED: 'danger',
  REVOKED: 'danger',
  TERMINATED: 'danger',
  ALL: undefined,
};

export type TicketDetails = RedisAddSlaveDetails & RedisCLBDetails & RedisScaleUpDownDetails & RedisClusterShardUpdateDetails & RedisClusterTypeUpdateDetails
  & RedisDataCheckAndRepairDetails & RedisDataCopyDetails & RedisDataStructrueDetails & RedisDBReplaceDetails & RedisDetails & RedisMasterSlaveSwitchDetails
  & RedisKeysDetails & RedisProxyScaleDownDetails & RedisProxyScaleUpDetails & RedisRollbackDataCopyDetails & RedisStructureDeleteDetails & MysqlAuthorizationDetails
  & MySQLImportSQLFileDetails & MySQLChecksumDetails & MySQLCloneDetails & MySQLInstanceCloneDetails & MySQLOperationDetails & MySQLDetails
  & DumperInstallDetails & MySQLFlashback & MySQLFullBackupDetails & MySQLHATruncateDetails & MySQLMasterFailDetails & MySQLMasterSlaveDetails
  & MySQLMigrateDetails & MysqlOpenAreaDetails & MySQLProxyAddDetails & MySQLProxySwitchDetails & MySQLRenameDetails & MySQLRestoreLocalSlaveDetails
  & MySQLRestoreSlaveDetails & MySQLRollbackDetails & MySQLSlaveDetails & MySQLTableBackupDetails

export default class Ticket<T = TicketDetails> {
  bk_biz_id: number;
  bk_biz_name: string;
  cost_time: number;
  create_at: string;
  creator: string;
  db_app_abbr: string;
  details: T;
  group: string;
  id: number;
  ignore_duplication: boolean;
  is_reviewed: boolean;
  remark: string;
  status: StatusTypeKeys;
  status_display: string;
  ticket_type: TicketTypes;
  ticket_type_display: string;
  update_at: string;
  updater: string;
  related_object?: {
    title: string;
    objects: string[];
  };

  constructor(payload = {} as Ticket<T>) {
    this.bk_biz_id = payload.bk_biz_id;
    this.bk_biz_name = payload.bk_biz_name;
    this.cost_time = payload.cost_time;
    this.create_at = payload.create_at;
    this.creator = payload.creator;
    this.db_app_abbr = payload.db_app_abbr;
    this.details = payload.details;
    this.group = payload.group;
    this.id = payload.id;
    this.ignore_duplication = payload.ignore_duplication;
    this.is_reviewed = payload.is_reviewed;
    this.remark = payload.remark;
    this.status = payload.status;
    this.status_display = payload.status_display;
    this.ticket_type = payload.ticket_type;
    this.ticket_type_display = payload.ticket_type_display;
    this.update_at = payload.update_at;
    this.updater = payload.updater;
    this.related_object = payload.related_object;
  }

  // 获取状态对应文案
  get tagTheme() {
    return tagTheme[this.status] as BKTagTheme;
  }

  get statusText() {
    return StatusTypes[this.status];
  }

  get formatCreateAt() {
    return dayjs(this.create_at).format('YYYY-MM-DD');
  }

  get createAtDisplay() {
    return utcDisplayTime(this.create_at);
  }
}
