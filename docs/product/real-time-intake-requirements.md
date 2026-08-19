# NutritionGlass 现状实现与实时饮食记录需求说明

> **目录迁移说明（2026-07-25）**：本文主体记录了整理前的代码路径，用于保留调研证据。当前规范路径为 `apps/user-web`、`apps/supervisor-web`、`apps/rokid-streamer`、`services/recognition`、`tools/camera-link` 和 `ml/training`；旧 `recognition_algorithm` 仓库已完整归档到 `legacy/recognition-algorithm-repository`。新开发请以规范路径为准。

> 项目：基于 Rokid 眼镜的营养监控识别系统  
> 工作区：`F:\adventureX`  
> 文档日期：2026-07-25  
> 文档状态：现状梳理与需求设计稿  
> 目标读者：产品、算法、后端、前端、Android/Rokid、测试及项目负责人

---

## 1. 文档目的

本文档基于当前项目工作区中的代码、页面、数据库模型和既有设计文档，对整个 NutritionGlass 项目进行一次完整梳理，重点回答以下问题：

1. 当前项目由哪些模块组成，各模块分别实现了什么。
2. 当前从 Rokid 眼镜采集画面，到食物识别、克重估算、饮食记录、监管端查看的数据链路实际是怎样的。
3. “食物名称、烹饪方式、克重”目前分别在哪一层生成，是否已经进入正式饮食记录。
4. 当前是否已经能够自动判断“用户确实完成了进食”。
5. 当前是否已经能够把已完成进食的数据实时推送给监管者。
6. 为实现完整需求，需要新增哪些业务状态、数据库表、接口、实时推送机制和监管端页面。
7. 后续开发应该按照什么顺序推进，如何验收。

本文档中的“实时记录”不是指每识别一帧就直接创建一条正式饮食记录，而是指：

> 系统在用餐过程中持续维护食物候选数据；在确认发生了真实进食后，将候选数据转为正式摄入记录，并及时推送给获得授权的监管者。

---

## 2. 核心结论

### 2.1 当前已经具备的能力

当前项目已经拥有较完整的识别算法和业务应用原型，包括：

- Rokid RV101 眼镜视频采集和电脑接收链路。
- 用户注册、登录、健康目标、用户绑定和饮食记录功能。
- 食物名称识别。
- 烹饪方式推断。
- ArUco 标定卡识别。
- 食物面积、体积和克重估算。
- 克重来源、估重等级、误差和置信度计算。
- 多帧食物 Track 跟踪和结果平滑。
- 餐具检测以及餐具与食物接触关系识别。
- `IntakeEvent` 进食事件数据模型。
- 用户手动确认识别结果并写入饮食记录。
- 监管管理端查询用户饮食记录。

### 2.2 当前尚未闭合的关键链路

当前主要链路仍然是：

```text
识别食物
  -> 在用户端展示识别结果
  -> 将结果填入表单
  -> 用户手动点击“添加到我的饮食”
  -> POST /diet/record
  -> 写入 diet_records
  -> 监管端重新查询数据库后看到记录
```

还不是：

```text
持续识别
  -> 多帧跟踪食物
  -> 判断真实进食行为
  -> 自动产生进食完成事件
  -> 自动形成正式摄入记录
  -> 持久化
  -> 实时推送给监管者
  -> 监管端专门区域即时展示
```

### 2.3 本次需求的本质

本次需求并不是单纯增加一个字段或一个监管端列表，而是需要把现有的“算法识别数据”转化为“有业务生命周期的饮食记录”。

建议把下一阶段的建设目标概括为：

> 记录业务化 + 监管实时化。

其中：

- 记录业务化：把 `FoodTrack` 和 `IntakeEvent` 转成可持久化、可确认、可修正、可审计的 `IntakeRecord`。
- 监管实时化：把已授权用户的记录变化通过 WebSocket 或 SSE 推送给监管者，并提供断线补偿和历史查询。

---

## 3. 项目目录与模块说明

当前工作区主要包含以下模块。

### 3.1 用户端健康饮食应用

主要目录：

```text
F:\adventureX\health_diet_app
F:\adventureX\recognition_algorithm\code
F:\adventureX\recognition_algorithm\code\health_diet_app
```

主要职责：

- 用户注册和登录。
- 手机号、邮箱和验证码流程。
- 用户健康信息设置。
- 体重管理、血糖管理、血压管理目标。
- 饮食记录展示。
- 手动添加饮食记录。
- 食物识别入口。
- 用户绑定、共享和授权。
- 用户个人资料和饮食历史。

主要技术：

- Flask。
- Jinja2 模板。
- SQLite。
- 原生 HTML、CSS、JavaScript。

### 3.2 识别算法模块

主要目录：

```text
F:\adventureX\recognition_algorithm\code\demo\backend
```

主要职责：

- 食物识别和实例分割。
- 非食物过滤。
- 食物分类映射。
- 烹饪方式推断。
- ArUco 标定卡检测。
- 克重和体积估算。
- 容器检测。
- 多帧跟踪和结果融合。
- 餐具识别。
- 进食事件构建。
- 营养换算。

主要代码：

```text
backend/services/analyzer.py
backend/services/calibration.py
backend/services/container_detector.py
backend/services/volume_estimator.py
backend/services/session_store.py
backend/services/utensil_tracker.py
backend/services/consumption_tracker.py
backend/services/nutrition.py
backend/models/schemas.py
```

### 3.3 Rokid 眼镜视频链路

主要目录：

```text
F:\adventureX\rokid_camera_link_demo
F:\adventureX\health_diet_app\android
F:\adventureX\recognition_algorithm\code\rokid_glasses_streamer
```

主要职责：

- Rokid AI App 和 CXR-L 授权、连接及控制。
- 启动和停止眼镜端视频推流。
- H.264 视频编码。
- Wi-Fi 视频发送。
- 电脑端视频接收。
- 最新帧抽样。
- 视频接收状态、FPS 和分辨率展示。

### 3.4 监管管理端

主要目录：

```text
F:\adventureX\recognition_algorithm\code\admin_panel
```

主要职责：

- 管理员初始化和登录。
- 用户列表和用户详情。
- 监督绑定关系查看和管理。
- 饮食记录查询和删除。
- 食物资料库管理。
- 操作审计日志。
- 登录尝试记录。

### 3.5 项目文档

已有文档：

```text
recognition_algorithm/docs/Rokid营养监控识别系统-项目文档.md
recognition_algorithm/docs/weight_calibration_requirements.md
recognition_algorithm/docs/weight_calibration_technical_design.md
recognition_algorithm/code/PROJECT.md
recognition_algorithm/code/admin_panel/PROJECT.md
```

这些文档已经描述了算法、标定、客户端和管理端的一部分设计，但并未完整说明“自动进食记录”和“监管者实时展示”之间的业务闭环。

---

## 4. 当前系统整体架构

### 4.1 当前逻辑架构

```text
┌──────────────────────────────────────────────┐
│ Rokid RV101 眼镜                             │
│ 摄像头采集、H.264 编码、视频推流             │
└─────────────────────┬────────────────────────┘
                      │
                      ▼
┌──────────────────────────────────────────────┐
│ 手机控制层 / 电脑视频接收服务                │
│ Rokid 授权、启动推流、接收视频、提取最新帧   │
└─────────────────────┬────────────────────────┘
                      │
                      ▼
┌──────────────────────────────────────────────┐
│ 识别算法层                                   │
│ FoodAnalyzer                                 │
│ CalibrationService                          │
│ SessionStore                                 │
│ UtensilTracker                               │
│ ConsumptionTracker                          │
│ NutritionEngine                             │
└─────────────────────┬────────────────────────┘
                      │ FoodTrack / IntakeEvent
                      ▼
┌──────────────────────────────────────────────┐
│ 用户端 Flask 应用                            │
│ 识别结果展示、用户确认、饮食记录写入         │
└─────────────────────┬────────────────────────┘
                      │ SQLite
                      ▼
┌──────────────────────────────────────────────┐
│ 用户数据库                                   │
│ users / food_library / diet_records          │
└─────────────────────┬────────────────────────┘
                      │ 查询
                      ▼
┌──────────────────────────────────────────────┐
│ 监管管理端                                   │
│ dashboard / users / bindings / diets / audit │
└──────────────────────────────────────────────┘
```

### 4.2 当前技术栈

| 层级 | 当前技术 | 说明 |
|---|---|---|
| 眼镜端 | Android、Rokid SDK、CXR-L | 采集和控制眼镜视频 |
| 视频传输 | H.264、UDP/HTTP 相关链路 | 当前存在眼镜推流和电脑接收 Demo |
| 用户业务端 | Flask、Jinja2、SQLite | 注册、绑定、饮食和识别页面 |
| 算法端 | Python、OpenCV、Ultralytics/YOLO | 食物、餐具、标定和克重估算 |
| 数据模型 | Pydantic | `FoodTrack`、`IntakeEvent`、`SessionState` 等 |
| 监管端 | Flask、Jinja2、SQLite | 管理员和饮食记录管理 |
| 实时通信 | 原算法设计中包含 WebSocket | 尚未与业务监管端闭环 |

---

## 5. 当前用户端业务实现

### 5.1 用户与身份

当前用户模型包含：

- 手机号。
- 邮箱。
- 密码。
- 昵称。
- 头像。
- 身高、体重、年龄、性别。
- 健康目标。
- 绑定码和分享码。
- 用户关系和共享权限。

代码中同时存在两种关系模型：

1. 旧模型：`supervisor`、`supervisee` 和 `bound_to`。
2. 新模型：`user_connections` 双向连接和 `share_diet`、`share_goal`、`share_profile` 权限。

对于本次监管需求，建议采用更细粒度的共享关系模型，而不是仅依赖角色字段。

### 5.2 饮食记录

当前正式饮食记录写入接口：

```text
POST /diet/record
```

当前接收的主要表单字段：

```text
food_name
weight_grams
intake_time
```

当前业务逻辑：

1. 校验食物名称和克重。
2. 从 `food_library` 查找食物。
3. 根据每 100g 热量和克重计算总热量。
4. 写入 `diet_records`。
5. 返回“已记录”提示。

当前写入 SQL 的逻辑形式为：

```sql
INSERT INTO diet_records (
    user_id,
    food_name,
    weight_grams,
    calories,
    intake_time
) VALUES (?, ?, ?, ?, ?)
```

### 5.3 当前 `diet_records` 数据结构

当前主要字段：

| 字段 | 类型/含义 | 当前是否满足新需求 |
|---|---|---|
| `id` | 记录 ID | 满足 |
| `user_id` | 用户 ID | 满足 |
| `food_name` | 食物名称 | 满足基础需求 |
| `weight_grams` | 克重 | 满足基础需求 |
| `calories` | 热量 | 满足 |
| `intake_time` | 摄入时间 | 满足 |
| `created_at` | 创建时间 | 满足 |
| `cooking_method` | 烹饪方式 | 当前没有 |
| `meal_session_id` | 用餐会话 | 当前没有 |
| `track_id` | 食物 Track | 当前没有 |
| `status` | 候选/进行中/已确认等状态 | 当前没有 |
| `source` | 手工/识别/算法确认 | 当前没有 |
| `confidence` | 综合置信度 | 当前没有 |
| `weight_source` | 标定/容器/视觉估算 | 当前没有 |
| `weight_error_g` | 克重误差 | 当前没有 |
| `raw_recognition` | 原始识别数据 | 当前没有 |
| `confirmed_at` | 完成确认时间 | 当前没有 |

### 5.4 当前识别页面行为

当前识别页面能够：

- 连接 Rokid 眼镜。
- 检查和安装眼镜端推流程序。
- 启动和停止视频流。
- 显示眼镜和电脑接收端状态。
- 显示实际 FPS 和视频分辨率。
- 从电脑选择图片进行调试。
- 调用识别接口。
- 展示多个识别结果。
- 展示食物名称、估算克重、热量和置信度。
- 把识别结果填入饮食表单。

但是识别结果不会直接生成正式记录，而是调用类似以下逻辑：

```javascript
quickFood(food.record_food_name, food.estimated_weight_g)
```

随后仍需要用户点击：

```text
添加到我的饮食
```

因此当前属于“识别辅助填写”，不是“自动实时记录”。

---

## 6. 当前识别算法实现

### 6.1 食物识别

核心类：

```text
FoodAnalyzer
```

主要位置：

```text
recognition_algorithm/code/demo/backend/services/analyzer.py
```

主要职责：

- 解码 JPEG/Base64 图片。
- 调用 YOLO 模型进行食物实例分割。
- 在模型不可用时使用 OpenCV Fallback。
- 过滤人、键盘、桌面、包装、餐具等非食物区域。
- 将模型标签映射到食物资料。
- 计算检测框、掩膜、多边形、面积比例和置信度。
- 推断烹饪方式。
- 估算体积和重量。
- 计算营养数据。

### 6.2 食物识别输出

`FoodTrack` 已经包含大量本次需求需要的数据，例如：

```json
{
  "track_id": "food_1",
  "name": "炒制鸡胸肉",
  "category": "蛋白质",
  "profile_key": "chicken",
  "cooking_method": "stir_fried",
  "cooking_method_name": "炒制",
  "cooking_confidence": 0.78,
  "estimated_weight_g": 138.5,
  "weight_error_g": 32.4,
  "weight_confidence": 0.76,
  "weight_source": "aruco_calibrated",
  "weight_estimation_level": "calibrated",
  "reference_detected": true,
  "scale_confidence": 0.81,
  "visible_frames": 12,
  "sample_count": 12,
  "stable_seconds": 8.4,
  "convergence": 0.72,
  "consumption_state": "observing",
  "remaining_ratio": 0.82,
  "nutrition": {
    "calories_kcal": 317.6,
    "protein_g": 28.0,
    "carbs_g": 0,
    "fat_g": 12.5,
    "fiber_g": 0,
    "sodium_mg": 280.4
  }
}
```

结论：算法层已经可以提供“名称、烹饪方式、克重”这三个核心字段，也能提供置信度、来源和误差。

真正缺少的是把这些字段可靠地转成业务记录。

### 6.3 烹饪方式识别

当前烹饪方式主要通过区域视觉特征推断，例如：

- 颜色。
- 油亮度。
- 焦化边缘。
- 表面纹理。
- 食物类别先验。

已有烹饪方式包括：

| 代码/类别 | 中文名称 | 典型营养修正 |
|---|---|---|
| 原味/少油 | 少油、原味 | 不额外增加或少量增加 |
| boiled | 水煮 | 低额外油脂 |
| steamed | 清蒸 | 低额外油脂 |
| stir_fried | 炒制 | 增加热量、脂肪和钠 |
| pan_fried | 煎制 | 增加热量和脂肪 |
| deep_fried | 炸制 | 显著增加热量和脂肪 |
| braised | 红烧/卤制 | 增加钠和部分热量 |
| grilled | 烤制 | 适量增加热量 |
| baked | 烘焙 | 根据食物资料进行修正 |
| unknown | 未识别 | 当前无法确定 |

产品层需要明确：

- `unknown` 是否允许自动生成正式记录。
- 混合菜是否只保存主烹饪方式。
- 人工修正后是否重新计算营养。
- 是否保留原始算法判断和修正后的业务判断。

建议：

```text
raw_cooking_method       保存原始算法结果
cooking_method           保存最终业务结果
cooking_method_source    algorithm / user / supervisor
cooking_confidence       保存算法置信度
```

### 6.4 克重估算

当前重量来源类型包括：

```text
aruco_calibrated
container_model
visual_fallback
unknown
```

估重等级包括：

```text
calibrated
approximate
rough
unsupported
```

其中：

- `calibrated`：检测到标定卡，场景适合估重。
- `approximate`：存在标定信息，但容器、遮挡或食物形状复杂。
- `rough`：没有可靠标定，仅依靠视觉比例粗估。
- `unsupported`：透明容器、液体、严重遮挡等情况下不应输出可信重量。

业务记录不能只保存一个 `weight_grams`，还应该保存：

```text
estimated_weight_g
weight_error_g
weight_confidence
weight_source
weight_estimation_level
reference_detected
scale_confidence
```

监管端应该明确展示“估算”属性，避免把视觉估重展示成电子秤称重结果。

---

## 7. 多帧跟踪和会话状态

### 7.1 `SessionStore`

`SessionStore` 负责在连续帧之间保持食物身份，主要机制包括：

- 根据检测框 IoU 进行匹配。
- 根据中心点距离进行匹配。
- 根据食物类别一致性进行匹配。
- 对重量、体积、检测框和置信度进行 EMA 平滑。
- 过滤短暂出现的碎片检测。
- 维护可见帧数和稳定时间。
- 计算识别收敛度。
- 在短暂丢失时保留 Track。
- 长时间丢失后清理 Track。
- 限制同时维护的食物 Track 数量。

### 7.2 多帧跟踪对实时记录的重要性

如果不使用 Track，而是每帧直接写数据库，会出现：

- 同一个苹果每秒生成多条饮食记录。
- 克重不断波动，产生多条不同重量记录。
- 食物被短暂遮挡后重新出现，被当作新食物。
- 同一个食物名称在模型轻微变化时产生多个业务对象。

因此建议使用以下幂等键：

```text
meal_session_id + track_id
```

对于一次食物 Track 中的多次入口事件，可以增加：

```text
intake_episode_id
```

最终幂等维度建议为：

```text
meal_session_id + track_id + intake_episode_id
```

---

## 8. 当前进食事件模型

### 8.1 `IntakeEvent`

当前数据模型已经定义以下进食状态：

```text
utensil_detected
utensil_contact_food
food_lifted
moving_to_mouth
intake_confirmed
returned_to_plate
uncertain
```

事件字段包括：

```text
event_id
state
utensil_type
source_track_id
source_profile_key
source_confidence
estimated_bite_weight_g
bite_weight_error_g
bite_area_cm2
bite_volume_ml
weight_source
reference_detected
scale_confidence
trajectory_confidence
intake_confidence
started_at_ms
confirmed_at_ms
```

### 8.2 当前 `ConsumptionTracker` 实现范围

当前 `ConsumptionTracker` 能够根据：

- 餐具是否与某个食物 Track 接触。
- 餐具携带食物的图像面积。
- 食物类别和密度。
- 标定卡信息。
- 餐具识别置信度。

构建进食事件并估算单口重量。

但是当前代码中构建出的事件主要停留在算法会话对象中，尚未完成以下业务动作：

- 写入用户数据库。
- 与 `diet_records` 建立关联。
- 根据 `intake_confirmed` 自动生成正式记录。
- 触发用户端提示。
- 触发监管者端推送。
- 在失败后补偿重试。
- 在用户修正后保留审计记录。

### 8.3 “识别到食物”不能等同于“已经进食”

这是本需求最重要的业务边界。

以下场景不能直接记为已摄入：

- 用户只是看到了桌上的食物。
- 餐具接触食物但没有送入口中。
- 食物被夹起后又放回盘中。
- 用户拿起包装查看但没有吃。
- 同桌其他人的食物进入画面。
- 识别模型短暂误识别。
- 饮料或汤被遮挡，系统无法确定摄入量。

因此必须引入候选记录和正式记录之间的状态转换。

---

## 9. 当前监管端实现

### 9.1 已有页面

当前 `admin_panel` 已有：

- `/dashboard`：总体统计。
- `/users`：用户列表。
- `/users/<id>`：用户详情。
- `/bindings`：绑定关系。
- `/diets`：饮食记录列表。
- `/foods`：食物库管理。
- `/audit`：审计日志。

### 9.2 当前饮食记录页面

当前饮食页面展示：

| 字段 | 当前支持 |
|---|---|
| 用户昵称 | 支持 |
| 手机号 | 支持 |
| 食物名称 | 支持 |
| 克重 | 支持 |
| 热量 | 支持 |
| 摄入时间 | 支持 |
| 删除操作 | 支持 |
| 烹饪方式 | 不支持 |
| 识别状态 | 不支持 |
| 估重来源 | 不支持 |
| 识别置信度 | 不支持 |
| 用餐会话 | 不支持 |
| 实时推送 | 不支持 |
| 原始值和修正值 | 不支持 |

### 9.3 当前监管端不是业务监督者实时端

现有 `admin_panel` 更接近系统管理员后台，主要负责：

- 管理所有用户。
- 管理食物库。
- 处理错误记录。
- 查看全局统计。
- 查看审计日志。

业务监督者通常只能看到自己绑定和获授权的用户。

因此需要明确区分：

| 身份 | 数据范围 | 主要目的 |
|---|---|---|
| 系统管理员 | 全部用户和全部记录 | 运维、审计、纠错、食物库管理 |
| 业务监管者 | 已绑定并授权的用户 | 实时监管、饮食干预、提醒和跟踪 |
| 被监管用户 | 自己的数据 | 查看、确认和修正 |

可以共用后端事件服务，但不应共用完全相同的权限逻辑。

---

## 10. 当前工程一致性问题

### 10.1 多份应用代码

当前存在多份相似的 Flask 应用：

```text
health_diet_app/app.py
recognition_algorithm/code/app.py
recognition_algorithm/code/health_diet_app/app.py
```

这些版本在以下方面存在差异：

- 用户角色模型。
- 绑定关系模型。
- 共享权限。
- 识别页面位置。
- 数据库默认路径。
- Android 内嵌资源引用。

如果继续同时修改多个版本，会造成：

- 功能只在某一个版本中生效。
- APK 内运行的版本和电脑 Web 版本不同。
- 管理端读取到不同的数据。
- 测试环境无法确认当前基线。

### 10.2 数据库路径不一致

监管端默认配置：

```python
USER_DB_PATH = .../recognition_algorithm/code/v2/health.db
```

当前工作区实际检查结果：

```text
recognition_algorithm/code/v2/health.db       不存在
recognition_algorithm/code/health.db          不存在
health_diet_app/health.db                      存在
```

这意味着如果不设置环境变量，监管端可能无法读取实际用户端数据库。

必须在开发实时推送前先统一：

```text
HEALTH_DB_PATH
USER_APP_DB_PATH
ADMIN_DB_PATH
```

并在服务启动时进行自检。

### 10.3 建议的工程基线

建议确定唯一主业务目录，例如：

```text
recognition_algorithm/code/app.py
recognition_algorithm/code/database.py
recognition_algorithm/code/templates/
recognition_algorithm/code/static/
recognition_algorithm/code/demo/backend/
recognition_algorithm/code/admin_panel/
```

或者将用户应用重新归一到：

```text
health_diet_app/
```

无论选择哪一个，都需要：

1. 明确唯一源码目录。
2. Android 打包只复制该目录资源。
3. 管理端和用户端使用同一个数据库配置。
4. 删除或标记其他目录为归档副本。
5. README 中只保留一套启动方式。

---

## 11. 新需求的业务目标

### 11.1 总体目标

系统需要在一次用餐过程中，实时维护识别到的食物信息，包括：

- 食物名称。
- 烹饪方式。
- 克重。

当系统判断用户完成某次进食，或者用户主动确认后：

1. 将数据保存为正式摄入记录。
2. 计算并保存营养数据快照。
3. 将记录推送给获得授权的监管者。
4. 在监管者端专门的实时区域展示。
5. 支持后续查看、修正和审计。

### 11.2 需求范围

本需求至少包含：

- 用餐会话。
- 实时识别状态。
- 食物候选记录。
- 进食事件。
- 正式摄入记录。
- 用户确认和修正。
- 监管者实时推送。
- 监管者专门展示区域。
- 历史记录。
- 权限控制。
- 断线补偿。
- 审计日志。

### 11.3 不建议在第一阶段强制实现的内容

以下内容可以作为后续版本：

- 保存完整原始用餐视频。
- 自动生成医学诊断。
- 自动替代医生或营养师决策。
- 对所有汤、粥、液体给出高精度克重。
- 多人同桌情况下完全自动区分食物归属。
- 复杂混合菜的所有原料级识别。

---

## 12. 建议业务概念

### 12.1 MealSession

表示一次完整用餐会话。

建议字段：

```text
id
user_id
status
started_at
ended_at
device_type
device_id
app_version
stream_id
created_at
updated_at
```

建议状态：

```text
created
connecting
streaming
paused
finishing
completed
cancelled
error
```

### 12.2 FoodTrack

算法层在连续帧中维护的食物对象。

特点：

- 会持续更新。
- 重量会随多帧融合变化。
- 名称和烹饪方式可能发生修正。
- 不一定代表已经发生摄入。

### 12.3 IntakeEvent

算法观察到的一次进食动作或疑似进食动作。

例如：

```text
餐具接触食物
食物被夹起
食物向嘴部移动
进食完成
食物被放回
无法判断
```

### 12.4 IntakeRecord

对用户和监管者具有业务意义的正式记录。

它应该具有：

- 明确的所有者。
- 明确的用餐会话。
- 明确的状态。
- 名称、烹饪方式和克重。
- 数据来源。
- 置信度和估重等级。
- 原始值和最终值。
- 创建、确认和修正时间。
- 可追溯的事件证据。

---

## 13. 建议记录状态机

### 13.1 状态定义

```text
candidate
in_progress
pending_confirmation
confirmed
rejected
edited
cancelled
```

### 13.2 状态说明

| 状态 | 含义 | 是否计入摄入统计 | 是否推送监管者 |
|---|---|---:|---:|
| `candidate` | 稳定识别到食物，但没有足够证据证明已经吃下 | 否 | 可选，仅显示识别中 |
| `in_progress` | 检测到餐具接触、携带或进食轨迹 | 否 | 是，可显示进行中 |
| `pending_confirmation` | 疑似已进食，但置信度不足或会话结束未结算 | 否或单独统计 | 是 |
| `confirmed` | 算法高置信确认或用户主动确认 | 是 | 是，重点推送 |
| `rejected` | 用户或监管者确认是误识别 | 否 | 是，更新原事件 |
| `edited` | 原记录被人工修正 | 是，使用修正后数据 | 是，更新原事件 |
| `cancelled` | 会话取消或候选失效 | 否 | 通常不展示 |

### 13.3 推荐转换路径

```text
candidate
  ├─> in_progress
  │     ├─> confirmed
  │     ├─> pending_confirmation
  │     └─> rejected
  ├─> pending_confirmation
  ├─> rejected
  └─> cancelled

confirmed
  ├─> edited
  └─> rejected
```

### 13.4 自动确认条件建议

第一版不要只依赖单一条件，建议组合：

- 食物 Track 已稳定存在一定时间。
- 检测到餐具与该食物 Track 接触。
- 餐具携带食物面积大于阈值。
- 轨迹朝嘴部方向移动。
- 食物未被检测为返回盘中。
- `intake_confidence` 达到阈值。
- 同一事件未被处理过。

建议配置：

```text
AUTO_CONFIRM_THRESHOLD=0.75
PENDING_CONFIRM_THRESHOLD=0.45
```

实际阈值需要通过真实 Rokid 视频验证，不应直接写死在产品需求中。

---

## 14. 建议数据库设计

### 14.1 方案选择

有两种方案。

#### 方案 A：直接扩展 `diet_records`

优点：

- 改动较小。
- 现有页面可以继续使用。
- 统计查询容易兼容。

缺点：

- 一个表同时承担候选、事件、正式记录和历史修正，容易越来越复杂。
- 不适合保存多次状态变化和多次单口事件。

#### 方案 B：新增用餐和摄入表，保留 `diet_records` 作为兼容视图

优点：

- 业务边界清晰。
- 可以完整支持状态机和事件追踪。
- 便于实时推送、重试和审计。

缺点：

- 初期开发量更大。
- 需要迁移现有查询。

推荐使用方案 B。

### 14.2 `meal_sessions`

建议结构：

```sql
CREATE TABLE meal_sessions (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    status TEXT NOT NULL,
    started_at TIMESTAMP NOT NULL,
    ended_at TIMESTAMP,
    device_type TEXT,
    device_id TEXT,
    app_version TEXT,
    stream_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 14.3 `intake_records`

建议结构：

```sql
CREATE TABLE intake_records (
    id TEXT PRIMARY KEY,
    meal_session_id TEXT NOT NULL REFERENCES meal_sessions(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    track_id TEXT,
    intake_episode_id TEXT,

    status TEXT NOT NULL,

    food_profile_key TEXT,
    raw_food_name TEXT,
    food_name TEXT NOT NULL,
    food_name_source TEXT NOT NULL DEFAULT 'algorithm',

    raw_cooking_method TEXT,
    cooking_method TEXT,
    cooking_method_name TEXT,
    cooking_method_source TEXT NOT NULL DEFAULT 'algorithm',
    cooking_confidence REAL DEFAULT 0,

    raw_weight_g REAL,
    weight_grams REAL,
    weight_error_g REAL,
    weight_confidence REAL DEFAULT 0,
    weight_source TEXT,
    weight_estimation_level TEXT,

    recognition_confidence REAL DEFAULT 0,
    intake_confidence REAL DEFAULT 0,

    calories REAL DEFAULT 0,
    protein_g REAL DEFAULT 0,
    carbs_g REAL DEFAULT 0,
    fat_g REAL DEFAULT 0,
    fiber_g REAL DEFAULT 0,
    sodium_mg REAL DEFAULT 0,
    nutrition_snapshot_json TEXT,

    intake_time TIMESTAMP,
    confirmed_at TIMESTAMP,
    confirmed_by INTEGER REFERENCES users(id),
    confirmation_source TEXT,

    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(meal_session_id, track_id, intake_episode_id)
);
```

### 14.4 `intake_events`

```sql
CREATE TABLE intake_events (
    id TEXT PRIMARY KEY,
    meal_session_id TEXT NOT NULL REFERENCES meal_sessions(id),
    intake_record_id TEXT REFERENCES intake_records(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    event_type TEXT NOT NULL,
    event_state TEXT NOT NULL,
    source_track_id TEXT,
    utensil_type TEXT,
    estimated_bite_weight_g REAL DEFAULT 0,
    bite_weight_error_g REAL DEFAULT 0,
    trajectory_confidence REAL DEFAULT 0,
    intake_confidence REAL DEFAULT 0,
    occurred_at TIMESTAMP NOT NULL,
    payload_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 14.5 `record_audit_logs`

```sql
CREATE TABLE record_audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    intake_record_id TEXT NOT NULL REFERENCES intake_records(id),
    actor_user_id INTEGER REFERENCES users(id),
    actor_type TEXT NOT NULL,
    action TEXT NOT NULL,
    before_json TEXT,
    after_json TEXT,
    reason TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 14.6 `push_events`

如果需要保证推送可靠性，建议使用 Outbox 表：

```sql
CREATE TABLE push_events (
    id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    aggregate_version INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    retry_count INTEGER NOT NULL DEFAULT 0,
    next_retry_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sent_at TIMESTAMP
);
```

数据库事务中同时写入 `intake_records` 和 `push_events`，后台推送任务再读取 Outbox，可以避免“记录已写入但推送事件丢失”。

---

## 15. 建议接口设计

### 15.1 创建用餐会话

```http
POST /api/meals
```

请求：

```json
{
  "device": {
    "platform": "android",
    "model": "Rokid RV101",
    "app_version": "1.2.0"
  }
}
```

响应：

```json
{
  "ok": true,
  "meal_session_id": "meal_01J...",
  "status": "created",
  "started_at": "2026-07-25T12:30:00+08:00"
}
```

用户 ID 必须从登录态或访问令牌中获取，不能信任客户端直接上传的用户 ID。

### 15.2 上传帧或提交识别状态

```http
POST /api/meals/{meal_session_id}/frames
```

请求可沿用当前 `FrameUpload`：

```json
{
  "frame_id": "frame_000123",
  "image": "data:image/jpeg;base64,...",
  "width": 1280,
  "height": 720,
  "timestamp_ms": 1784953800000,
  "device_motion": {}
}
```

响应：

```json
{
  "ok": true,
  "meal_session_id": "meal_01J...",
  "frame_id": "frame_000123",
  "foods": [],
  "intake_events": [],
  "records": [],
  "quality": {},
  "guidance": "请保持食物和标定卡完整可见"
}
```

### 15.3 查询当前会话状态

```http
GET /api/meals/{meal_session_id}/state
```

返回：

- 当前会话状态。
- 食物 Track。
- 进食事件。
- 当前候选记录。
- 已确认记录。
- 画面质量。
- 标定状态。
- 指导信息。

### 15.4 结束用餐

```http
POST /api/meals/{meal_session_id}/finish
```

结束时需要：

1. 停止接收新帧。
2. 等待正在处理的最新帧完成。
3. 结算所有 Track。
4. 把高置信度事件转为 `confirmed`。
5. 把低置信度事件转为 `pending_confirmation`。
6. 取消无意义候选。
7. 生成用餐汇总。
8. 触发最终推送。

### 15.5 用户确认或修正记录

```http
POST /api/intake-records/{record_id}/confirm
```

请求：

```json
{
  "action": "confirm",
  "food_name": "鸡胸肉",
  "cooking_method": "stir_fried",
  "weight_grams": 138.5,
  "reason": "用户确认"
}
```

支持动作：

```text
confirm
edit
reject
restore
```

### 15.6 监管者增量查询

```http
GET /api/supervisor/intake-records?since=...&cursor=...&status=confirmed
```

用途：

- 首次加载。
- WebSocket 断线补偿。
- 页面刷新。
- 历史分页。

### 15.7 监管者实时连接

```text
WS /ws/supervisor/intake
```

建议事件类型：

```text
meal.started
meal.updated
meal.completed
intake.candidate_created
intake.in_progress
intake.pending_confirmation
intake.confirmed
intake.edited
intake.rejected
system.heartbeat
system.resync_required
```

---

## 16. 实时推送事件格式

建议统一使用：

```json
{
  "event_id": "evt_01J...",
  "event_type": "intake.confirmed",
  "occurred_at": "2026-07-25T12:35:21.123+08:00",
  "aggregate_id": "intake_01J...",
  "aggregate_version": 3,
  "meal_session_id": "meal_01J...",
  "user": {
    "id": 12,
    "nickname": "测试用户",
    "avatar_url": "/uploads/avatars/..."
  },
  "record": {
    "id": "intake_01J...",
    "status": "confirmed",
    "food_name": "鸡胸肉",
    "cooking_method": "stir_fried",
    "cooking_method_name": "炒制",
    "weight_grams": 138.5,
    "weight_error_g": 32.4,
    "weight_source": "aruco_calibrated",
    "weight_estimation_level": "calibrated",
    "recognition_confidence": 0.86,
    "intake_confidence": 0.79,
    "intake_time": "2026-07-25T12:35:20+08:00"
  }
}
```

### 16.1 幂等要求

监管端必须保存或维护：

```text
event_id
aggregate_id
aggregate_version
```

处理规则：

- 相同 `event_id` 只处理一次。
- 相同记录只接受更高的 `aggregate_version`。
- 版本缺失时触发增量同步。
- 断线重连时携带 `last_event_id` 或时间游标。

### 16.2 心跳和重连

建议：

- 服务端每 20～30 秒发送心跳。
- 客户端超过 60 秒未收到消息时重连。
- 使用指数退避。
- 重连成功后调用增量接口补偿。
- 页面明确显示“实时连接正常、正在重连、数据可能延迟”等状态。

---

## 17. 监管者端专门展示区域

### 17.1 页面入口

建议新增一级入口：

```text
实时进食
```

如果保留现有管理端导航，建议结构为：

```text
首页概览
实时进食
用户管理
绑定关系
饮食记录
食物资料
审计日志
```

业务监督者端可以使用：

```text
我的监管对象
实时进食
待确认
历史记录
异常提醒
```

### 17.2 实时进食首页

建议包含以下模块。

#### A. 实时状态条

展示：

- 当前在线被监管用户数。
- 当前活跃用餐数。
- 今日已确认摄入事件数。
- 待确认记录数。
- 最近一条事件时间。
- 实时连接状态。

#### B. 活跃用餐卡片

每个正在用餐的用户显示：

- 用户头像和昵称。
- 用餐开始时间。
- 会话持续时间。
- 眼镜连接状态。
- 视频接收状态。
- 标定卡状态。
- 当前识别食物数。
- 已确认摄入重量。
- 待确认事件数。

#### C. 实时事件流

每条事件显示：

- 用户。
- 食物名称。
- 烹饪方式。
- 克重。
- 发生时间。
- 记录状态。
- 识别置信度。
- 进食置信度。
- 估重来源。
- 是否有标定卡。

#### D. 待确认区域

重点展示：

- 低进食置信度。
- 烹饪方式未知。
- 克重不支持。
- 标定卡缺失。
- 食物名称无法映射食物库。
- 同一 Track 发生冲突。

允许监管者：

- 确认。
- 修改。
- 驳回。
- 添加备注。

前提是产品明确允许监管者代替用户确认。

#### E. 异常提醒

可能的提醒：

- 视频断流。
- 识别服务不可用。
- 标定卡长时间不可见。
- 光线不足。
- 图像模糊。
- 克重估算为 `unsupported`。
- 待确认记录超时。
- 推送积压。

### 17.3 用餐详情页

建议展示：

```text
用户信息
用餐开始/结束时间
设备和视频状态
画面质量趋势
标定卡状态
食物 Track 列表
进食事件时间线
正式摄入记录
营养汇总
修正和审计记录
```

### 17.4 历史记录页

筛选条件：

- 用户。
- 日期范围。
- 食物名称。
- 烹饪方式。
- 状态。
- 克重来源。
- 估重等级。
- 置信度范围。
- 是否人工修正。

列表字段：

```text
用户
食物名称
烹饪方式
克重
热量
摄入时间
记录来源
估重等级
状态
修正标记
```

---

## 18. 用户端交互建议

### 18.1 用餐开始

```text
进入食物识别页面
  -> 连接眼镜
  -> 检查视频流
  -> 点击“开始用餐”
  -> 创建 MealSession
  -> 持续识别和显示候选数据
```

### 18.2 用餐进行中

用户端可以显示：

- 当前识别到的食物。
- 烹饪方式。
- 当前估算克重。
- 估重等级。
- 标定卡状态。
- 已确认摄入事件。
- 待确认事件。

避免每一帧弹窗确认，以免严重打断用餐。

### 18.3 用餐结束

结束时建议弹出汇总：

```text
已自动确认 3 项
待确认 1 项
无法估重 1 项
```

用户可以：

- 一键确认高置信度结果。
- 修改名称。
- 修改烹饪方式。
- 修改克重。
- 驳回误识别。
- 稍后处理待确认记录。

### 18.4 自动记录策略建议

建议提供配置：

```text
严格模式：所有记录都要用户确认
平衡模式：高置信度自动确认，低置信度待确认
自动模式：符合阈值的记录自动确认并推送
```

第一版建议默认使用“平衡模式”。

---

## 19. 权限与隐私设计

### 19.1 数据查看权限

监管者查看某用户数据必须同时满足：

1. 双方存在有效绑定关系。
2. 关系状态为 `active`。
3. 被监管用户开启饮食共享。
4. 关系未过期或未解除。
5. 实时连接令牌属于当前监管者。

不能只依赖客户端传入的用户 ID。

### 19.2 数据修改权限

建议规则：

| 操作者 | 可确认 | 可修改 | 可删除/驳回 | 是否保留审计 |
|---|---:|---:|---:|---:|
| 记录所有者 | 是 | 是 | 是 | 是 |
| 业务监管者 | 取决于授权 | 取决于授权 | 取决于授权 | 是 |
| 系统管理员 | 可纠错 | 可纠错 | 可纠错 | 是 |
| 未授权用户 | 否 | 否 | 否 | 不适用 |

### 19.3 视频和关键帧隐私

建议第一版：

- 默认不永久保存完整视频。
- 只保存必要的结构化识别数据。
- 如需复核，可保存低频关键帧或局部食物截图。
- 关键帧设置过期时间。
- 明确告知用户数据用途。
- 提供删除机制。

---

## 20. 异常和降级策略

### 20.1 识别服务不可用

处理：

- 用户端显示明确错误。
- 用餐会话不立即丢弃。
- 允许暂存关键帧或转为手工记录。
- 恢复后可选择重试尚未处理的帧。

### 20.2 标定卡缺失

处理：

- 名称和烹饪方式仍可识别。
- 克重标记为 `rough`。
- 监管端显示“视觉粗估”。
- 不得标记为精确称重。

### 20.3 克重不支持

处理：

- `weight_estimation_level=unsupported`。
- 记录可以进入 `pending_confirmation`。
- 用户手动输入克重后再确认。

### 20.4 网络断开

处理：

- 客户端维护本地待同步队列。
- 每条请求包含幂等键。
- 恢复网络后按顺序补传。
- 服务端重复接收不重复写入。

### 20.5 监管端断线

处理：

- 数据库记录不受影响。
- 推送事件进入 Outbox。
- 监管端重连后用游标补偿。
- UI 明确显示连接状态。

### 20.6 食物映射失败

处理：

- 保存原始模型标签。
- 使用 `unknown_food` 或候选名称。
- 不强制映射到已有食物库。
- 进入待确认。
- 用户确认后可补充食物库映射。

### 20.7 重复事件

处理：

- 使用会话、Track 和 Episode 组合键。
- 事件使用唯一 `event_id`。
- 记录使用版本号。
- 重复消息只更新更高版本。

---

## 21. 营养计算策略

### 21.1 保存营养快照

当前食物库会变化，烹饪方式修正规则也可能变化。

正式记录生成时应保存营养快照：

```json
{
  "calories_kcal": 317.6,
  "protein_g": 28.0,
  "carbs_g": 0,
  "fat_g": 12.5,
  "fiber_g": 0,
  "sodium_mg": 280.4,
  "food_library_version": "2026-07-25",
  "calculation_version": "nutrition-v1"
}
```

否则食物库更新后，历史记录的营养数据可能被重新计算成不同结果。

### 21.2 修正记录后的重新计算

如果用户修改：

- 食物名称。
- 烹饪方式。
- 克重。

应重新计算营养快照，同时保留修改前后的值。

---

## 22. 非功能需求

### 22.1 实时性

建议目标：

| 动作 | 目标延迟 |
|---|---:|
| 最新帧进入识别结果 | 2 秒以内 |
| Track 状态更新到用户端 | 2 秒以内 |
| `confirmed` 写入数据库 | 1 秒以内 |
| 正式记录推送监管者 | 3 秒以内 |
| 监管端断线补偿 | 重连后 5 秒内开始同步 |

实际延迟目标应根据硬件和部署环境调整。

### 22.2 一致性

- 同一事件不能重复生成正式记录。
- 推送失败不能影响数据库提交。
- 数据库提交失败不能发送成功事件。
- 用户修正后必须增加版本号。
- 监管端不能使用旧版本覆盖新版本。

### 22.3 可解释性

每条记录必须能回答：

- 识别到了什么。
- 为什么判断是这种烹饪方式。
- 克重来自哪种估算方式。
- 误差和置信度是多少。
- 为什么判断已经吃下。
- 是否被人工修改。
- 谁修改了。

### 22.4 可观测性

建议监控：

- 视频连接数。
- 当前活跃用餐数。
- 帧接收速率。
- 帧分析速率。
- 识别失败率。
- Track 数量。
- IntakeEvent 产生速率。
- 自动确认率。
- 人工驳回率。
- 数据库写入失败率。
- 推送积压数量。
- WebSocket 在线连接数。
- 断线重连次数。

---

## 23. 推荐开发顺序

### P0：统一工程基线

必须先完成：

1. 确定唯一用户端源码。
2. 确定唯一数据库路径。
3. 修正监管端 `USER_DB_PATH`。
4. 明确 Android APK 使用哪一份 Web/Python 资源。
5. 为所有服务增加启动自检。
6. 更新 README。

交付结果：

- 用户端和监管端读取同一个用户数据库。
- 可以清楚说明开发、测试和 APK 分别运行哪一份代码。

### P1：扩展数据模型

开发内容：

- 新增 `meal_sessions`。
- 新增 `intake_records`。
- 新增 `intake_events`。
- 新增审计和 Outbox 表。
- 编写 SQLite 迁移。
- 保持现有 `diet_records` 查询兼容。

### P2：打通算法到业务记录

开发内容：

- 给识别请求增加 `meal_session_id`。
- 将 `FoodTrack` 映射为候选 `IntakeRecord`。
- 将 `IntakeEvent` 写入数据库。
- 实现状态转换。
- 实现幂等。
- 实现会话结束结算。

### P3：改造用户端

开发内容：

- 开始、暂停和结束用餐。
- 实时显示候选和已确认记录。
- 用餐结束汇总。
- 待确认列表。
- 修改和驳回。
- 显示估重等级和置信度。

### P4：实时推送服务

开发内容：

- WebSocket 或 SSE。
- 事件格式。
- 权限验证。
- Outbox 消费。
- 心跳。
- 重连。
- 增量补偿接口。

### P5：监管者专门区域

开发内容：

- 实时状态条。
- 活跃用餐卡片。
- 实时事件流。
- 待确认区域。
- 用餐详情。
- 历史查询。
- 审计查看。

### P6：真实场景验证

至少测试：

- 单一食物。
- 多种食物同时出现。
- 同一食物多次进食。
- 使用筷子、勺子、叉子和手。
- 食物夹起后放回。
- 无标定卡。
- 标定卡倾斜和遮挡。
- 视频模糊。
- 网络断开。
- 服务重启。
- 监管端断线。
- 多监管者同时在线。
- 解除绑定后的权限回收。

---

## 24. 验收标准

### 24.1 用餐会话

- 用户开始用餐后生成唯一 `meal_session_id`。
- 同一用户不能意外创建多个无关联的活动会话。
- 会话可以暂停、恢复和结束。
- 服务重启后已完成会话仍可查询。

### 24.2 食物识别记录

- 识别结果包含食物名称、烹饪方式和克重。
- 同一 Track 不会因连续帧生成大量重复记录。
- Track 更新时只更新对应候选记录。
- 原始识别结果得到保留。

### 24.3 进食完成

- 仅食物出现在画面中时不计为已摄入。
- 餐具接触后放回食物时不生成 `confirmed`。
- 满足自动确认条件后生成正式记录。
- 低置信度事件进入待确认。
- 同一事件重复上报不会生成重复记录。

### 24.4 数据字段

正式记录至少包含：

```text
user_id
meal_session_id
food_name
cooking_method
weight_grams
status
intake_time
source
confidence
```

同时建议包含：

```text
track_id
intake_episode_id
weight_source
weight_estimation_level
weight_error_g
raw_food_name
raw_cooking_method
nutrition_snapshot_json
version
```

### 24.5 实时推送

- 记录确认后 3 秒内出现在在线监管者端。
- 未授权监管者收不到事件。
- WebSocket 重复消息不会产生重复 UI 项。
- 监管端断线后可以补齐离线期间的数据。
- 编辑或驳回会更新原记录，而不是新增一条无关联记录。

### 24.6 监管端

- 有独立“实时进食”入口。
- 可以看到活跃用餐用户。
- 可以看到名称、烹饪方式、克重、时间和状态。
- 可以区分精确标定、近似估算、视觉粗估和不支持。
- 可以进入用餐详情。
- 可以按用户、日期和状态筛选。
- 可以查看修改审计。

### 24.7 权限

- 未绑定用户不可互相查看数据。
- 未开启饮食共享时监管者不可查看。
- 解除绑定后实时连接不再收到新事件。
- 服务端不信任客户端传入的用户身份。
- 管理员和业务监管者权限范围明确区分。

---

## 25. 测试用例建议

### 用例 1：食物只出现在画面中

预期：

- 创建 `candidate`。
- 不创建 `confirmed`。
- 不计入摄入汇总。

### 用例 2：餐具接触后放回

预期：

- 状态可以进入 `in_progress`。
- 出现 `returned_to_plate`。
- 不创建正式摄入记录或将候选驳回。

### 用例 3：高置信度进食完成

预期：

- 创建 `intake_confirmed`。
- 生成一条 `confirmed` 记录。
- 保存名称、烹饪方式和克重。
- 监管者实时收到推送。

### 用例 4：烹饪方式未知

预期：

- 名称和克重仍可保存。
- 烹饪方式为 `unknown`。
- 根据产品策略进入 `pending_confirmation` 或低置信度确认。

### 用例 5：无标定卡

预期：

- 克重来源为 `visual_fallback`。
- 估重等级为 `rough`。
- 用户和监管者端均显示“粗估”。

### 用例 6：网络中断后重传

预期：

- 客户端进入待同步队列。
- 网络恢复后补传。
- 不生成重复记录。

### 用例 7：监管端断线

预期：

- 数据正常落库。
- 监管端重连后通过增量接口补齐。
- 已处理事件不重复显示。

### 用例 8：用户修改克重

预期：

- 原始估算克重得到保留。
- 最终克重更新。
- 营养快照重新计算。
- 版本号增加。
- 监管者收到 `intake.edited`。
- 审计日志记录修改前后数据。

### 用例 9：解绑用户

预期：

- 解绑后监管者无法查询新记录。
- 当前实时连接中的相关订阅被取消。
- 历史数据是否继续可见按照产品权限策略执行。

---

## 26. 需要产品确认的问题

开发前需要明确：

1. 正式记录的粒度是每一口、每一道食物，还是每餐汇总。
2. 是否需要同时保留“单口事件”和“食物总摄入”两层数据。
3. 高置信度记录是否允许完全自动确认。
4. `unknown` 烹饪方式是否允许成为正式记录。
5. 监管者是否有权代替用户确认和修改。
6. 监管者是独立角色，还是所有建立共享关系的用户都可以成为监管者。
7. 管理员是否需要看到所有实时进食事件。
8. 是否保存关键帧，保存多久。
9. 是否需要实时告警，例如高热量、高钠或异常进食频率。
10. 是否需要在多个设备之间同步用餐会话。
11. 用餐会话未正常结束时如何结算。
12. 同桌多人或共享餐盘如何处理归属。

本文建议的默认答案：

- 保存单口事件，但监管主视图按食物汇总。
- 默认使用平衡模式，高置信度自动确认，低置信度待确认。
- `unknown` 可以保存，但必须明显标记。
- 用户拥有最终确认权；监管者修改需要额外授权。
- 默认不保存完整视频，只保存结构化数据和必要关键帧。

---

## 27. 关键代码索引

| 文件 | 作用 |
|---|---|
| `recognition_algorithm/code/app.py` | 用户端主应用、饮食、识别和共享关系 |
| `recognition_algorithm/code/database.py` | 用户数据库和迁移 |
| `recognition_algorithm/code/recognition_adapter.py` | 算法结果到用户端 JSON 的适配 |
| `recognition_algorithm/code/templates/recognition.html` | Rokid 识别页面和识别结果确认 |
| `recognition_algorithm/code/templates/diet.html` | 饮食记录页面 |
| `recognition_algorithm/code/demo/backend/models/schemas.py` | `FoodTrack`、`IntakeEvent`、`SessionState` |
| `recognition_algorithm/code/demo/backend/services/analyzer.py` | 食物识别、烹饪方式和克重估算 |
| `recognition_algorithm/code/demo/backend/services/calibration.py` | ArUco 标定 |
| `recognition_algorithm/code/demo/backend/services/volume_estimator.py` | 体积和单口重量估算 |
| `recognition_algorithm/code/demo/backend/services/session_store.py` | 多帧 Track 和会话融合 |
| `recognition_algorithm/code/demo/backend/services/utensil_tracker.py` | 餐具跟踪 |
| `recognition_algorithm/code/demo/backend/services/consumption_tracker.py` | 进食事件构建 |
| `recognition_algorithm/code/demo/backend/services/nutrition.py` | 食物资料和营养换算 |
| `recognition_algorithm/code/admin_panel/app.py` | 管理端路由和业务 |
| `recognition_algorithm/code/admin_panel/admin_database.py` | 管理端和用户数据库连接 |
| `recognition_algorithm/code/admin_panel/templates/diets.html` | 当前管理端饮食列表 |
| `recognition_algorithm/docs/Rokid营养监控识别系统-项目文档.md` | 项目原有总体设计 |
| `recognition_algorithm/docs/weight_calibration_requirements.md` | 标定与克重需求 |
| `recognition_algorithm/docs/weight_calibration_technical_design.md` | 标定技术设计 |

---

## 28. 最终建议

当前项目不需要重新从零设计识别算法。已有算法输出已经覆盖本次最核心的三个字段：

```text
名称
烹饪方式
克重
```

下一步开发重点应该从“继续增加识别页面”转移到：

1. 统一应用和数据库基线。
2. 建立用餐会话。
3. 建立候选、进行中、待确认和已确认状态。
4. 把 `FoodTrack`、`IntakeEvent` 映射为业务 `IntakeRecord`。
5. 将烹饪方式、估重来源、误差和置信度写入数据库。
6. 建立可靠的实时推送和断线补偿。
7. 在监管者端建设专门的实时进食区域。
8. 保留用户确认、纠错和审计能力。

一句话总结：

> 项目已经具备“识别数据生产能力”，现在需要完成“记录业务化和监管实时化”，将算法产生的 FoodTrack 与 IntakeEvent 转化为有状态、可持久化、可授权推送、可追踪和可纠错的正式饮食记录。
