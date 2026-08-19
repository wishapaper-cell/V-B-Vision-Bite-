# V&B 用户端项目说明

## 项目概述

V&B 是 NutritionGlass 的用户业务应用：接收手工输入、图片识别或眼镜视频事件，计算食物克重和营养，形成可修正、可追溯、可按授权共享的饮食记录。当前为 Flask + SQLite 的本地原型，同时提供 Android 容器。

## 技术栈

| 模块 | 技术 |
|---|---|
| Web 后端 | Python Flask、服务端 Session、Werkzeug 密码哈希 |
| 页面 | Jinja2、原生 JavaScript、V&B 品牌静态资源 |
| 数据 | SQLite，启动时执行幂等增量迁移 |
| 识别 | `services/recognition` Python 模块，经 `recognition_adapter.py` 适配 |
| Android | 原生 Android 容器，内嵌用户端资源并对接 Rokid 应用 |

## 核心数据

### 用户与关系

`users` 保存手机号/邮箱、密码、角色、昵称、头像、身体指标、健康目标、三类分享码、启用状态、最近活跃时间、医疗史、过敏、饮食偏好、限制、慢病、风险等级、健康备注和每日热量目标。

`user_connections` 保存双向关系、请求者、状态、双方备注，以及饮食、目标和资料三类独立共享权限。旧版 `bound_to` 关系会在迁移时转换为活动连接。

### 饮食与食物

`food_library` 除热量与分类外，包含蛋白质、脂肪、碳水、纤维、矿物质、单位、替代食物和上下架状态。

`diet_records` 保存食物、克重、热量、摄入时间、图片、来源类型、识别候选、宏量营养、餐次和描述。用户修正识别记录时会保留 `original_food_name`、`original_weight_grams` 与 `corrected_at`。

## 主要流程

1. 用户通过手机号或邮箱完成验证码注册并登录。
2. 手工记录直接从食物库计算营养；识别入口接收图片并调用识别服务。
3. 识别结果先展示候选，由用户确认后写入正式饮食记录。
4. 已保存图片可重新分析；用户可修正或删除自己的记录。
5. 眼镜实时会话可通过 `/api/video-intake/import` 将已确认的摄入事件导入用户记录。
6. 共享对象只有在连接有效且对应分享开关开启时才能查看饮食、目标或资料。

## 页面与接口

| 路径 | 用途 |
|---|---|
| `/login`、`/register` | 登录与两阶段注册 |
| `/goal`、`/goal/setup` | 今日目标、身体指标与健康目标 |
| `/diet`、`/diet/record` | 今日/历史饮食与手工记录 |
| `/recognition`、`/api/recognition/analyze` | 图片识别与候选结果 |
| `/api/diet/<id>/recommendations` | 对已保存图片重新分析 |
| `/diet/correct/<id>`、`/diet/delete/<id>` | 记录修正与删除 |
| `/api/video-intake/import` | 导入眼镜会话确认的摄入事件 |
| `/bind`、`/connections/...` | 邀请、接受、共享设置和解绑 |
| `/profile`、`/shared/<id>` | 本人资料和获授权的共享资料 |

## 安全与数据约束

- 非活动用户不能继续使用受保护页面。
- 上传文件有大小、格式和路径限制；饮食图片读取前校验记录所有者或共享权限。
- 饮食记录按用户 ID 隔离，识别结果不会在未确认时自动成为正式摄入。
- 数据库、上传内容、PID 和会话密钥存放在 `.workspace/` 或显式运行目录，不进入源码仓库。

## 启动与下一阶段

规范启动入口为 `scripts/dev/start-user-web.ps1`，默认端口 `5000`。下一阶段包括真实短信/邮件网关、生产数据库与统一 API、连续低延迟眼镜 SDK 评估、正式部署与可观测性。
