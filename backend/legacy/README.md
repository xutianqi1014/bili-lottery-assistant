# 历史受控写入工具

source_like_plan、source_like_execution、source_like_write_test 保存旧的独立来源点赞计划与单目标授权流程。
主应用使用 backend/use_cases/source_like_automation.py，不加载这条历史执行链。

原 backend.use_cases 模块保留公开名称的兼容导出；旧计划字段、检查点和确认词不变。
保留测试覆盖以防意外扩大授权，不将离线测试标记为线上写入验证。
