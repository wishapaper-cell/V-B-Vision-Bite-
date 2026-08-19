# Changelog

所有重要变更记录在此文件。版本发布建议遵循 Semantic Versioning。

## Unreleased

### Changed

- 整合桌面 `管理端.zip` 的新版监管管理端，加入管理员邀请审批、用户健康风险、饮食复核、食谱、反馈、导出、备份和系统审计能力。
- 整合桌面 `v2.zip` 的新版用户端、Android 品牌资源和识别服务，加入饮食图片、重新分析、可追溯修正、宏量营养、视频摄入导入和 V&B 品牌资源。
- 识别服务增加 FastAPI 会话入口与 PyAV UDP MPEG-TS 接收器，并继续保留项目 50×50 mm 参考物和兼容 ArUco 标定流程。
- 将仓库整理为 `apps/`、`services/`、`ml/`、`tools/`、`docs/`、`scripts/`、`artifacts/`、`legacy/` 和 `.workspace/` 分层结构。
- 用户数据库和运行文件默认迁移到 `.workspace/`。
- 统一用户端、监管端、识别服务和 Rokid 后端的路径配置。
- 增加开发、测试、架构、运行和协作规范文档。

### Compatibility

- 根目录 `start_rokid_backend.ps1` 继续保留，并转发到新的规范脚本。
- 迁移前的 `recognition_algorithm` 嵌套仓库完整保存在 `legacy/recognition-algorithm-repository/`。
