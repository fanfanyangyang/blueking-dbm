package atomoracle

import (
	"dbm-services/oracle/db-tools/dbactuator/pkg/jobruntime"
	"encoding/json"
	"fmt"

	"github.com/go-playground/validator/v10"
)

// ShutdownServiceParams 执行脚本初始化参数
type ShutdownServiceParams struct {
}

// ShutdownService 执行脚本原子任务   oracle用户执行
type ShutdownService struct {
	BaseJob
	Params                    *ShutdownServiceParams
	ShutdownServiceRunTimeCtx `json:"-"`
}

// ShutdownServiceRunTimeCtx 运行时上下文
type ShutdownServiceRunTimeCtx struct {
}

// NewShutdownService new
func NewShutdownService() jobruntime.JobRunner {
	return &ShutdownService{}
}

// Init 初始化
func (e *ShutdownService) Init(runtime *jobruntime.JobGenericRuntime) error {
	e.Runtime = runtime
	err := json.Unmarshal([]byte(e.Runtime.PayloadDecoded), &e.Params)
	if err != nil {
		e.Runtime.Logger.Error(
			"get parameters of ShutdownService fail by json.Unmarshal, error:%s", err)
		return fmt.Errorf("get parameters of ShutdownService fail by json.Unmarshal, error:%s", err)
	}
	if err = e.checkParams(); err != nil {
		return err
	}
	e.Runtime.Logger.Info("init successfully")
	return nil
}

// checkParams 校验参数
func (e *ShutdownService) checkParams() error {
	// 校验配置参数
	e.Runtime.Logger.Info("start to validate parameters")
	validate := validator.New()
	e.Runtime.Logger.Info("start to validate parameters of ShutdownService")
	if err := validate.Struct(e.Params); err != nil {
		e.Runtime.Logger.Error("validate parameters of ShutdownService fail, error:%s", err)
		return fmt.Errorf("validate parameters of ShutdownService fail, error:%s", err)
	}
	e.Runtime.Logger.Info("validate parameters successfully")
	return nil
}

// Name 名字
func (e *ShutdownService) Name() string {
	return "shutdown-service"
}

// Run 执行函数
func (e *ShutdownService) Run() error {
	e.Runtime.Logger.Info("start to shutdown listener")
	err := ShutdownListener()
	if err != nil {
		e.Runtime.Logger.Error("shutdown listener fail: %s", err)
		return err
	}
	e.Runtime.Logger.Info("shutdown listener success")

	e.Runtime.Logger.Info("start to shutdown instance")
	err = ShutdownInstance(true)
	if err != nil {
		e.Runtime.Logger.Error("shutdown instance fail: %s", err)
		return err
	}
	e.Runtime.Logger.Info("shutdown instance success")
	return nil
}
