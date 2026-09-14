package atomoracle

import (
	"dbm-services/oracle/db-tools/dbactuator/pkg/common"
	"dbm-services/oracle/db-tools/dbactuator/pkg/consts"
	"dbm-services/oracle/db-tools/dbactuator/pkg/jobruntime"
	"dbm-services/oracle/db-tools/dbactuator/pkg/util"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"github.com/go-playground/validator/v10"
)

// ShutdownParams 执行脚本初始化参数
type ShutdownParams struct {
}

// Shutdown 执行脚本原子任务   oracle用户执行
type Shutdown struct {
	BaseJob
	Params             *ShutdownParams
	ShutdownRunTimeCtx `json:"-"`
}

// ShutdownRunTimeCtx 运行时上下文
type ShutdownRunTimeCtx struct {
}

// NewShutdown new
func NewShutdown() jobruntime.JobRunner {
	return &Shutdown{}
}

// Init 初始化
func (e *Shutdown) Init(runtime *jobruntime.JobGenericRuntime) error {
	e.Runtime = runtime
	err := json.Unmarshal([]byte(e.Runtime.PayloadDecoded), &e.Params)
	if err != nil {
		e.Runtime.Logger.Error(
			"get parameters of Shutdown fail by json.Unmarshal, error:%s", err)
		return fmt.Errorf("get parameters of Shutdown fail by json.Unmarshal, error:%s", err)
	}
	if err = e.checkParams(); err != nil {
		return err
	}
	e.Runtime.Logger.Info("init successfully")
	return nil
}

// checkParams 校验参数
func (e *Shutdown) checkParams() error {
	// 校验配置参数
	e.Runtime.Logger.Info("start to validate parameters")
	validate := validator.New()
	e.Runtime.Logger.Info("start to validate parameters of Shutdown")
	if err := validate.Struct(e.Params); err != nil {
		e.Runtime.Logger.Error("validate parameters of Shutdown fail, error:%s", err)
		return fmt.Errorf("validate parameters of Shutdown fail, error:%s", err)
	}
	e.Runtime.Logger.Info("validate parameters successfully")
	return nil
}

// Name 名字
func (e *Shutdown) Name() string {
	return "shutdown"
}

// Run 执行函数
func (e *Shutdown) Run() error {
	e.Runtime.Logger.Info("start to shutdown listener")
	err := ShutdownListener()
	if err != nil {
		e.Runtime.Logger.Info("shutdown listener fail, skipped: %v", err)
	}
	isRunning, err := CheckListenerStatus()
	if err != nil {
		e.Runtime.Logger.Error("check listener status fail: %s", err)
		return err
	} else if isRunning {
		e.Runtime.Logger.Info("listener is running")
		return fmt.Errorf("listener is running, please check and shutdown listener manually")
	}
	e.Runtime.Logger.Info("shutdown listener success")

	e.Runtime.Logger.Info("start to shutdown instance")
	err = ShutdownInstance(false)
	if err != nil {
		e.Runtime.Logger.Error("shutdown instance fail: %s", err)
		return err
	}
	e.Runtime.Logger.Info("shutdown instance success")
	return nil

}

// ShutdownInstance 关闭实例
func ShutdownInstance(force bool) error {
	db, err := common.OpenOracleAsSysdba()
	if err != nil {
		return err
	}
	defer db.Close()
	shutdownSQL := consts.ShutdownImmediate
	err = common.ExecuteOracle(db, shutdownSQL)
	if err == nil {
		return nil
	}
	if !force {
		return fmt.Errorf("failed to execute shutdown command: %s error: %v", shutdownSQL, err)
	}
	shutdownSQL = consts.ShutdownAbort
	err = common.ExecuteOracle(db, shutdownSQL)
	if err != nil {
		return fmt.Errorf("failed to execute shutdown command: %s error: %v", shutdownSQL, err)
	}
	return nil
}

// ShutdownListener 关闭监听
func ShutdownListener() error {
	var errors error
	cmd := []string{`lsnrctl stop`, `lsnrctl stop LISTENER1`}
	for _, c := range cmd {
		_, err := util.RunBashCmd(c, "", nil, 30*time.Second)
		if err != nil {
			errors = fmt.Errorf("%v \n failed to execute command: %s error: %v", err, c, err)
			continue
		}
	}
	return errors
}

// CheckListenerStatus 检查监听状态
func CheckListenerStatus() (bool, error) {
	isRunning := false
	cmd := []string{`lsnrctl status`, `lsnrctl status LISTENER1`}
	for _, c := range cmd {
		_, err := util.RunBashCmd(c, "", nil, 30*time.Second)
		if err != nil {
			if strings.Contains(err.Error(), "No listener") {
				continue
			} else {
				return isRunning, fmt.Errorf("failed to execute command: %s error: %v", c, err)
			}
		}
		isRunning = true
	}
	return isRunning, nil
}
