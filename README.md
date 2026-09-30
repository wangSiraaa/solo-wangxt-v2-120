# 地震定位教学实验台

一个明确限定为课堂教学的全栈示例：从少量台站的波形到时恢复候选事件位置，并展示为什么不能只报一个“精确坐标”。

- 前端：Vue 3、Plotly.js
- 后端：FastAPI、ObsPy、SciPy、NumPy
- 数据库：PostgreSQL、PostGIS、SQLAlchemy、GeoAlchemy2
- 示例：启动时生成已知源位置的合成 MiniSEED 波形、合成到时、离群到时、缺测拾取、台站几乎共线和台站不足案例

> **不是地震预警系统。** 本项目不接入真实台网，不做实时延迟评估，也不产生可用于应急响应的结果。

## 1. 明确采用的简化模型

模型版本固定为 `homogeneous-halfspace-v1`：

- 局部笛卡尔坐标系，单位 km；不使用经纬度定位。
- 所有台站和震源位于同一简化速度模型中。
- P 波速度：`6.0 km/s`
- S 波速度：`3.5 km/s`
- 走时：`三维欧氏距离 / 所选震相速度`
- 默认固定深度：`8 km`；也可加入自由深度候选观察深度—发震时刻权衡。
- 忽略速度分层、横向非均匀性、台站校正、高程校正、椭球和真实地壳结构。
- **每次定位只使用 P 或只使用 S，不混用 P/S 到时。**

## 2. 内置教学案例

| 案例 ID | 目的 |
|---|---|
| `controlled-known` | 5 个方位覆盖良好的台站，已知合成源可揭示 |
| `outlier-manual-demo` | ST02 的 P 到时晚 3.2 s，ST04 缺测 P；包含人工修订集 |
| `near-collinear` | 5 个台站近似沿一条线布设，几何病态 |
| `too-few-stations` | 只有 2 个台站，明确返回不可定位 |

启动时后端用 ObsPy 写出 MiniSEED；波形接口再用 ObsPy 读回并降采样发送给 Plotly。

## 3. 一键启动

```bash
docker compose up --build
```

- 前端：<http://localhost:5173>
- API 文档：<http://localhost:8000/docs>

首次启动会自动：

1. 创建 PostGIS 扩展和表；
2. 生成合成波形；
3. 插入案例、台站、原始拾取和预置人工修订；
4. 将 PostGIS 的 `POINTZ` 坐标显式标记为 SRID 0 的局部 km 坐标。

## 4. 本地开发

后端：

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest

# 需要一个可访问的 PostGIS 数据库
export DATABASE_URL='postgresql+psycopg://seismo:seismo@localhost:5432/seismo_teaching'
uvicorn app.main:app --reload
```

前端：

```bash
cd frontend
npm install
npm run dev
```

## 5. API 摘要

- `GET /api/model`：速度模型、假设和模型版本。
- `GET /api/scenarios`：案例列表。
- `GET /api/scenarios/{id}?reveal_truth=false`：台站、拾取集和可选已知源。
- `GET /api/scenarios/{id}/waveforms?phase=P&pick_set_id=...`：ObsPy 解析后的波形与单震相拾取。
- `POST /api/scenarios/{id}/revisions`：从现有拾取集复制为新的人工修订版本，原始数据不覆盖。
- `POST /api/scenarios/{id}/locate`：运行 SciPy 定位，保存完整结果记录。
- `GET /api/scenarios/{id}/runs`：历史重算记录。
- `GET /api/runs/{id}`：候选解、残差、几何覆盖和版本绑定。

定位请求示例：

```json
{
  "pick_set_id": 1,
  "phase": "P",
  "fixed_depth_km": 8.0,
  "outlier_threshold_s": 1.5,
  "include_free_depth": true
}
```

## 6. 候选解和残差如何呈现

每次定位最多保留三个候选，便于比较：

1. 稳健拟合、固定深度（Soft L1 loss）；
2. 普通最小二乘、固定深度；
3. 稳健拟合、自由深度（可选）。

系统展示：

- 候选 `(x, y, z)` 和相对发震时刻；
- 使用拾取数、剔除/不可用数、RMS 和最大绝对残差；
- 每台站的观测到时、预测到时和 `observed - predicted`；
- 缺测、离群、人工修订状态；
- 方位空挡、条件数、Jacobian 秩和线性化 1σ 椭圆；
- 良好/一般/差的几何覆盖评级。

选择规则是教学用的透明排序：优先较少被剔除拾取，再比较 RMS。它不是业务自动编目结论。

## 7. 原始拾取、人工修订与版本绑定

- `pick_sets.kind = raw/manual`，人工集通过 `parent_set_id` 指向被复制的基础集。
- 修订总是创建新版本，不更新原始行。
- 每次 `location_runs` 都保存：
  - `model_version`
  - `data_version`
  - `picks_version`
  - 固定深度和离群阈值
  - 由完整输入生成的 `input_hash`
- 即使输入哈希相同，也会生成一条新的运行记录，方便课堂反复重算和追溯。

## 8. 不可定位规则

- 固定深度：少于 3 个同一震相有效到时，不给候选坐标。
- 自由深度：少于 4 个同一震相到时，不给自由深度候选。
- 只有 2 个台站时不给出候选坐标，界面显示“不可定位”。
- 近似共线案例默认固定深度时可能保留数值候选，用于比较候选漂移和残差；同时给出强几何警告、条件数/方位空挡和大不确定度，不把结果描述成唯一精确位置。自由深度解若不能通过秩检查则不输出坐标。

## 9. 数据与几何约定

PostGIS 几何用于明确保存和审计局部 3D 坐标：

- 震源：`POINT Z (x y depth)`
- 台站：`POINT Z (x y -elevation)`
- SRID 0：表示本地笛卡尔 km 坐标系，而不是经纬度。

这避免了把教学坐标误解释为 WGS84 地理坐标。
