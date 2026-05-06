# Memory Quality Phase 1 实施规格

> Version: 0.2  
> Language: zh-CN  
> Owner: Brain / Memory Engine  
> Scope: Phase 1 memory quality 与 lifecycle，从“能存”升级到“会变”。  
> Implementation: 首版已落地到 `brain-python/services/memory.py`、`memory_extractor.py`、`database/migrations/000005_memory_lifecycle.*.sql`。  
> Source: `docs/development/TestBot_Cognitive_Agent_Architecture_zh_CN.md` Phase 1。

---

## 1. 目标

Phase 1 的目标是把当前 Memory MVP 做成可执行、可观测、可渐进上线的 lifecycle 系统。

必须完成：

- 为长期记忆补齐 `memory_class`、生命周期字段、质量评分字段。
- 将“新增或更新 active memory”升级为 weak / confirmed / reinforced / stale / contradicted / archived 的状态机。
- 让 extractor upsert、召回、管理命令都理解新状态，默认只把可用记忆交给 AI。
- 提供 Codex / 人类开发者可以并行执行的迁移、服务、命令/API、测试拆分。
- 保持现有 `/memory` 命令、`memory_items` 数据、`memory_runs` 审计记录向后兼容。

成功标准：

- 老数据迁移后仍可搜索、召回、删除。
- 新抽取的记忆默认进入 `weak` 或 `confirmed`，不会把一次性聊天直接当成强长期事实。
- 重复证据会 reinforce 记忆，冲突证据会降低可用性并进入 debug 可见状态。
- 管理员能查看一条记忆为什么存在、为什么被召回、为什么被降级或归档。

当前 API 入口：

- [Memory Lifecycle API](../api/memory-api.md)
- [AI Runtime API](../api/ai-runtime-api.md)
- [Database Schema](../api/database-schema.md)

---

## 2. 非目标

Phase 1 不做：

- 不引入全量 WebUI，只提供后续 WebUI 可复用的服务方法和可选 HTTP surface。
- 不实现完整 embedding rerank。已有 `memory_embeddings` 保留，但 Phase 1 scoring 以结构化字段、关键词和 FTS 为主。
- 不做跨群用户画像合并。`user` 和 `relationship` 仍然绑定 `group_id`。
- 不自动开启 proactive AI。
- 不把所有历史消息批量回填为长期记忆。回填只能通过显式 admin 命令或离线脚本触发。
- 不做复杂自然语言矛盾推理。Phase 1 只做规则型 / LLM 标注型最小闭环。

---

## 3. 当前基线假设

代码基线以当前仓库为准：

- 数据库已有 `database/migrations/000004_memory.up.sql`：
  - `memory_items`
  - `memory_embeddings`
  - `memory_runs`
  - `memory_settings`
- `memory_items` 当前字段包含：
  - `scope`
  - `group_id`
  - `user_id`
  - `target_user_id`
  - `memory_type`
  - `content`
  - `confidence`
  - `importance`
  - `status`，当前允许 `active / archived / deleted`
  - `evidence_message_ids`
  - `metadata`
  - `created_by`
  - `first_seen_at`
  - `last_seen_at`
  - `expires_at`
  - timestamps
- `brain-python/services/memory.py` 当前只召回 `status = 'active'` 的 memory。
- `PostgresMemoryStore.upsert_extracted_memory()` 当前按 scope、IDs、`memory_type`、normalized content 找 active 记忆，匹配则更新 confidence / importance / evidence / metadata。
- `brain-python/services/memory_extractor.py` 当前 extractor 输出字段不含 `memory_class`，只含 `memory_type`。
- `/memory` 当前命令面：
  - `status`
  - `search <keyword>`
  - `user <QQ>`
  - `extract [count]`
  - `forget <id>`
  - `forget-user <QQ>`
  - `forget-group`
  - `enable`
  - `disable`

这些假设用于兼容策略；实现前如代码已变化，以实际代码为准调整字段名，但不改变本文的行为目标。

---

## 4. Schema 与兼容策略

新增迁移建议命名：

```text
database/migrations/000005_memory_lifecycle.up.sql
database/migrations/000005_memory_lifecycle.down.sql
```

### 4.1 新增字段

在 `memory_items` 上新增：

```sql
ALTER TABLE memory_items
    ADD COLUMN memory_class TEXT NOT NULL DEFAULT 'semantic',
    ADD COLUMN lifecycle_status TEXT NOT NULL DEFAULT 'confirmed',
    ADD COLUMN stability DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    ADD COLUMN decay_score DOUBLE PRECISION NOT NULL DEFAULT 1.0,
    ADD COLUMN contradiction_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN source_count INTEGER NOT NULL DEFAULT 1,
    ADD COLUMN last_confirmed_at TIMESTAMPTZ,
    ADD COLUMN archived_at TIMESTAMPTZ,
    ADD COLUMN quality_score DOUBLE PRECISION NOT NULL DEFAULT 0.5;
```

约束建议：

```sql
ALTER TABLE memory_items
    ADD CONSTRAINT memory_items_memory_class_check
        CHECK (memory_class IN ('episodic', 'semantic', 'procedural', 'affective', 'social', 'persona')),
    ADD CONSTRAINT memory_items_lifecycle_status_check
        CHECK (lifecycle_status IN ('weak', 'confirmed', 'reinforced', 'stale', 'contradicted', 'archived')),
    ADD CONSTRAINT memory_items_stability_check CHECK (stability >= 0 AND stability <= 1),
    ADD CONSTRAINT memory_items_decay_score_check CHECK (decay_score >= 0 AND decay_score <= 1),
    ADD CONSTRAINT memory_items_quality_score_check CHECK (quality_score >= 0 AND quality_score <= 1);
```

### 4.2 `status` 与 `lifecycle_status` 关系

保持现有 `status` 字段，不在 Phase 1 移除。

字段含义：

| 字段 | 用途 | 兼容规则 |
| --- | --- | --- |
| `status` | 数据可见性 / 删除状态 | 继续支持 `active / archived / deleted` |
| `lifecycle_status` | 记忆质量和生命周期 | 新逻辑使用 `weak / confirmed / reinforced / stale / contradicted / archived` |

读取规则：

- AI recall 默认只读取：
  - `status = 'active'`
  - `lifecycle_status IN ('confirmed', 'reinforced')`
- admin search 默认显示 active 可用记忆，可通过参数/命令查看 weak、stale、contradicted、archived。
- `status = 'deleted'` 永不召回。
- `status = 'archived'` 和 `lifecycle_status = 'archived'` 都视为归档。

迁移回填：

- 已有 `status = 'active'` 的数据：`lifecycle_status = 'confirmed'`。
- 已有 `status = 'archived'` 的数据：`lifecycle_status = 'archived'`，`archived_at = COALESCE(updated_at, now())`。
- 已有 `status = 'deleted'` 的数据：`lifecycle_status = 'archived'`，保持 deleted 语义。
- `memory_class` 根据 `memory_type` 粗略映射：
  - `fact / topic / summary` -> `semantic`
  - `style / preference` -> `procedural`
  - `relationship` -> `social`
  - `warning` -> `procedural`
- `source_count = jsonb_array_length(evidence_message_ids)`。
- `last_confirmed_at = last_seen_at`。

### 4.3 索引

新增索引：

```sql
CREATE INDEX memory_items_recall_lifecycle_idx
    ON memory_items (
        scope,
        group_id,
        user_id,
        target_user_id,
        lifecycle_status,
        quality_score DESC,
        last_seen_at DESC
    )
    WHERE status = 'active';

CREATE INDEX memory_items_debug_lifecycle_idx
    ON memory_items (lifecycle_status, updated_at DESC)
    WHERE status <> 'deleted';
```

保留现有索引，避免影响已有命令。

---

## 5. Memory Lifecycle

Phase 1 状态机：

```text
weak
  |
  | enough evidence / admin confirm
  v
confirmed
  |
  | repeated evidence
  v
reinforced
  |
  | low decay / old without evidence
  v
stale

confirmed / reinforced
  |
  | contradiction evidence
  v
contradicted

any non-deleted
  |
  | admin archive / expiry / hard retirement rule
  v
archived
```

状态定义：

| lifecycle_status | 含义 | 是否默认召回 |
| --- | --- | --- |
| `weak` | 单次或低置信候选，证据存在但还不够稳定 | 否 |
| `confirmed` | 可用长期记忆，有足够 confidence / importance / evidence | 是 |
| `reinforced` | 多次被证据强化，优先级更高 | 是 |
| `stale` | 可能过期，仍可 debug 查看 | 否 |
| `contradicted` | 被新证据冲突，等待人工或后续合并 | 否 |
| `archived` | 已归档，不参与正常使用 | 否 |

### 5.1 初始状态规则

Extractor 写入新 memory 时：

- `confidence >= 0.78` 且 `importance >= 0.55` 且 evidence 数量 >= 2：`confirmed`
- `memory_type = warning` 且 `confidence >= 0.7`：`confirmed`
- 其他合格候选：`weak`

人工创建或 admin confirm：

- 默认 `confirmed`
- 可显式指定 `weak` 或 `archived`

### 5.2 强化规则

匹配到已有 memory 且 evidence 有新增时：

- 合并 evidence。
- `source_count = evidence_message_ids` 去重后的数量。
- `last_seen_at = now()`。
- `last_confirmed_at = now()`。
- `confidence = clamp(max(old_confidence, new_confidence) + 0.03, 0, 1)`，最多每次 +0.03。
- `importance = max(old_importance, new_importance)`。
- `stability = clamp(old_stability + 0.05, 0, 1)`。
- `decay_score = 1.0`。
- `contradiction_count` 不变。

状态迁移：

- `weak` 满足 confirmed 阈值后 -> `confirmed`。
- `confirmed` 且 `source_count >= 3` 或 `stability >= 0.75` -> `reinforced`。
- `stale` 被新证据确认后 -> `confirmed`。
- `contradicted` 不自动恢复，除非新证据与当前 content 强匹配且 admin 或后续实现显式确认。

### 5.3 衰减规则

Phase 1 用后台命令或管理命令触发，不要求常驻 scheduler。

建议命令：

```text
/memory lifecycle decay [days]
```

规则：

- 默认扫描 `status = 'active'` 且 `lifecycle_status IN ('weak', 'confirmed', 'reinforced')`。
- `age_days = now() - last_seen_at`。
- 对 `episodic / topic / summary` 衰减更快，对 `procedural / persona / warning` 衰减更慢。

MVP 公式：

```text
decay_score = max(0, 1 - age_days / half_life_days)
```

建议 half-life：

| memory_class | half_life_days |
| --- | --- |
| `episodic` | 30 |
| `semantic` | 180 |
| `procedural` | 365 |
| `affective` | 180 |
| `social` | 120 |
| `persona` | 730 |

迁移到 stale：

- `weak` 超过 14 天无强化 -> `archived`
- `confirmed` 且 `decay_score < 0.25` -> `stale`
- `reinforced` 且 `decay_score < 0.15` -> `stale`

### 5.4 冲突规则

Phase 1 支持两类冲突：

1. 规则型冲突：
   - 同 scope / IDs / class / type 下出现标准化 content 完全不同，但 key entity 相同。
   - 示例：同一用户偏好从“喜欢长解释”变成“不要写长解释”。
2. Extractor 标注型冲突：
   - extractor 输出 `metadata.conflicts_with_memory_id` 或未来字段 `conflicts_with`。

处理：

- 不直接覆盖旧 content。
- 将旧 memory `contradiction_count += 1`。
- 将旧 memory `lifecycle_status = 'contradicted'`，除非它是 `reinforced` 且新候选 confidence 低于旧 confidence 0.15 以上。
- 新候选进入 `weak` 或 `confirmed`。
- `metadata.contradiction_events` 追加：

```json
{
  "at": "2026-05-06T12:00:00Z",
  "candidate_content": "...",
  "evidence_message_ids": [123],
  "reason": "extractor_conflict"
}
```

---

## 6. Scoring MVP

Phase 1 引入 `quality_score` 和 recall-time `memory_score`。

### 6.1 `quality_score`

写入或 lifecycle 更新时持久化：

```text
quality_score =
    confidence * 0.35
  + importance * 0.25
  + stability * 0.15
  + min(source_count, 5) / 5 * 0.15
  + decay_score * 0.10
  - min(contradiction_count, 3) * 0.10
```

结果 clamp 到 `0..1`。

用途：

- admin 排序。
- recall 候选排序的一部分。
- rollout 观测。

### 6.2 `memory_score`

召回时临时计算，不必 Phase 1 入库：

```text
memory_score =
    keyword_match * 0.30
  + entity_relevance * 0.20
  + scope_relevance * 0.15
  + quality_score * 0.25
  + recency_weight * 0.10
```

MVP 定义：

- `keyword_match`：当前 `_keywords(text)` 与 content 命中比例。
- `entity_relevance`：请求中的 `group_id / user_id` 与 memory IDs 匹配程度。
- `scope_relevance`：
  - exact user / relationship = 1.0
  - group = 0.75
  - global = 0.4
- `recency_weight`：`last_seen_at` 30 天内 1.0，180 天外 0.2，中间线性。

召回默认：

- 最多先取 50 条候选。
- 排除 `weak / stale / contradicted / archived`。
- 按 `memory_score DESC, quality_score DESC, last_seen_at DESC` 取 `DEFAULT_MEMORY_LIMIT`。

---

## 7. Merge / Update 规则

### 7.1 匹配键

候选与已有 memory 的匹配键：

```text
scope
group_id
user_id
target_user_id
memory_class
memory_type
normalized_content
```

兼容期：

- 如果旧数据没有 `memory_class`，迁移必须先补齐。
- `normalized_content` 继续可放在 `metadata.normalized_content`。

### 7.2 可合并

满足以下条件合并：

- scope 与 IDs 完全一致。
- `memory_class` 与 `memory_type` 一致。
- normalized content 完全一致，或 canonical key 一致且语义不是否定关系。

更新字段：

- evidence 去重追加。
- confidence / importance / stability 按强化规则更新。
- metadata 保留旧 keys，追加 `last_extractor_version`、`merge_events`。

### 7.3 不可合并

以下情况不合并：

- scope 或 group/user 边界不同。
- relationship 的 `user_id` / `target_user_id` 方向不同，除非 memory_type 明确是对称关系。
- content 明显否定旧 content。
- 新候选 evidence 为空或 evidence 不属于本次输入消息。

### 7.4 更新现有记忆内容

内容改写只允许两种入口：

- admin patch / confirm。
- extractor 返回明确的 `update_of_memory_id`，且新证据覆盖旧证据。

普通重复抽取不改写 content，只强化旧 memory。

---

## 8. Admin / Debug Surface

Phase 1 先做命令和 store/service 方法；HTTP API 可随后复用同一服务层。

### 8.1 命令

保留现有命令，新增：

```text
/memory show <id>
/memory search <keyword> [--status weak|confirmed|reinforced|stale|contradicted|archived|all]
/memory lifecycle status
/memory lifecycle confirm <id>
/memory lifecycle archive <id>
/memory lifecycle stale <id>
/memory lifecycle decay [days]
/memory debug recall <text>
```

命令行为：

- `show`：显示 content、scope、class/type、confidence、importance、stability、decay、quality、status、lifecycle_status、evidence IDs。
- `lifecycle status`：按 lifecycle_status 聚合计数。
- `confirm`：将 weak/stale/contradicted 改为 confirmed，设置 `last_confirmed_at = now()`，记录 admin 操作。
- `archive`：设置 `status = 'archived'`、`lifecycle_status = 'archived'`、`archived_at = now()`。
- `stale`：人工降级为 stale。
- `decay`：执行衰减扫描，返回 scanned / stale / archived 数量。
- `debug recall`：不调用 LLM，只输出候选记忆及每条 score breakdown。

### 8.2 HTTP API 建议

如果同期要补 HTTP surface，保持小而稳定：

```http
GET /api/memories?group_id=&user_id=&query=&status=&lifecycle_status=&limit=
GET /api/memories/{id}
PATCH /api/memories/{id}
POST /api/memories/{id}/confirm
POST /api/memories/{id}/archive
POST /api/memories/lifecycle/decay
POST /api/memories/debug/recall
```

权限：

- 复用 `/memory` 的 admin 判断。
- 群管理员只能管理本群 memory。
- `MEMORY_ADMIN_USER_IDS` 可管理 global / 跨群 debug。

---

## 9. 实现拆分

可由 subagents / Codex 并行推进，但每个分支都只碰自己的边界。

### 9.1 Database Agent

负责：

- 新增 `000005_memory_lifecycle` up/down migration。
- 更新 `docs/api/database-schema.md`，如果该任务被单独授权。
- 验证迁移在已有 `000004_memory` 后可运行。

验收：

- 新字段有默认值，旧数据不需要手工修复。
- down migration 能移除新增约束、索引、字段。

### 9.2 Store / Lifecycle Agent

负责：

- 扩展 `MemoryRecord`。
- 新增 lifecycle helper：
  - `class_for_type(memory_type)`
  - `initial_lifecycle_status(item)`
  - `compute_quality_score(record)`
  - `reinforce_memory(existing, item)`
  - `apply_decay(now)`
- 更新 `upsert_extracted_memory()`。
- 更新 delete/archive 语义，避免继续写 `deleted` 以外的新不可见状态到 `status`。

验收：

- 老调用方仍能使用 `memory_to_dict()`。
- 现有测试通过。

### 9.3 Recall / Scoring Agent

负责：

- 实现候选拉取与 `memory_score`。
- `recall_context()` 默认只返回 confirmed/reinforced。
- `debug recall` 返回 score breakdown。

验收：

- weak / contradicted 不进入 AI prompt。
- 同一用户同一群的 user memory 排名高于 group/global memory。

### 9.4 Extractor Agent

负责：

- prompt 增加 `memory_class` 输出要求。
- validator 支持 `memory_class`，缺省按 `memory_type` 映射。
- 可选支持 `conflicts_with_memory_id` metadata。

验收：

- 旧模型未输出 `memory_class` 时仍可写入。
- 输出非法 class 时跳过或回退，不污染数据库。

### 9.5 Command / API Agent

负责：

- 新增命令。
- 命令输出保持群聊可读，不刷屏。
- HTTP API 如被授权则使用同一 store/service 方法。

验收：

- 非 admin 仍在 store lookup 前拒绝。
- 群聊命令不会跨群展示私有记忆。

---

## 10. 测试计划

### 10.1 Migration

- 空库从 `000001` 到 `000005` 成功。
- 只含 `000004` 老 memory 的库运行 `000005` 后：
  - active -> confirmed
  - archived/deleted -> archived lifecycle
  - `source_count` 与 evidence 数量一致
  - `memory_class` 按映射填充

### 10.2 Unit Tests

新增或扩展 `brain-python/tests/test_memory_core.py`：

- `upsert_extracted_memory` 新 memory 初始为 weak / confirmed。
- 重复 evidence 强化 existing memory。
- source_count、stability、quality_score 更新正确。
- weak 不被 recall。
- confirmed/reinforced 可 recall。
- contradicted / archived / deleted 不被 recall。
- delete/forget 保持向后兼容。
- `/memory lifecycle status` 聚合正确。
- `/memory debug recall` 输出 score breakdown。

新增或扩展 `brain-python/tests/test_memory_extractor.py`：

- extractor 接受合法 `memory_class`。
- extractor 缺省 class 时按 type 映射。
- 非法 class 被拒绝或回退到安全默认值。
- conflict metadata 被保留。

### 10.3 Integration

- 用本地 Postgres 跑 migration + pytest。
- 手动流程：
  - `/memory extract 100`
  - `/memory lifecycle status`
  - `/memory show <id>`
  - `/memory debug recall <text>`
  - `/memory lifecycle archive <id>`

### 10.4 Regression

必须保护：

- `MEMORY_ENABLED=false` 时 recall 不访问 store。
- 未配置 `DATABASE_URL` 时命令返回现有错误。
- group disabled 时 extract / recall 行为不变。
- 非管理员无权操作。

---

## 11. Rollout 计划

### Step 1: Schema only

- 合入 migration。
- 不改变 recall 行为。
- 部署后检查 `memory_items` 计数与 lifecycle 聚合。

### Step 2: Write path

- extractor/upsert 开始写 `memory_class`、`lifecycle_status`、quality 字段。
- 新 memory 可进入 weak，但 recall 暂时仍兼容 active confirmed 老数据。

### Step 3: Read path

- recall 默认改为 confirmed/reinforced。
- 提供环境开关：

```text
MEMORY_RECALL_LIFECYCLE_FILTER_ENABLED=true
```

- 如出现召回过少，可临时关闭开关。

### Step 4: Admin/debug

- 上线 `show`、`lifecycle status`、`debug recall`。
- 让人工可以解释为什么记忆没被召回。

### Step 5: Decay

- 手动执行 decay。
- 观察 stale/archived 数量。
- 稳定后再考虑定时任务。

---

## 12. 风险与缓解

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| 过滤 weak 后 recall 变少 | AI 看起来“失忆” | rollout Step 3 使用环境开关，debug recall 可见被过滤原因 |
| migration 默认值错误 | 老 memory 丢失可用性 | active 老数据统一 confirmed，部署前跑迁移测试 |
| lifecycle 与 status 混乱 | 删除/归档语义不一致 | `status` 只管可见性，`lifecycle_status` 只管质量；删除仍以 `status='deleted'` 为准 |
| extractor 输出质量低 | weak 堆积或错误 confirmed | 初始状态阈值保守，warning 以外需要高 confidence 或多 evidence |
| contradiction 误判 | 正确记忆被降级 | Phase 1 不自动覆盖 content，contradicted 可人工 confirm |
| admin 输出刷屏 | 群内体验变差 | show/search 限制条数，debug recall 只返回 top N |
| 多 subagents 改同一文件冲突 | 合并成本高 | 按 Database / Store / Recall / Extractor / Command 拆边界，小步 PR |

---

## 13. 最小完成清单

- [x] `000005_memory_lifecycle` migration。
- [x] `MemoryRecord` 和 row mapping 支持新字段。
- [x] extractor validator 支持或回退 `memory_class`。
- [x] upsert 支持 weak/confirmed/reinforced、contradicted 和 quality_score。
- [x] recall 默认只返回 confirmed/reinforced。
- [x] `/memory lifecycle status`。
- [x] `/memory show <id>`。
- [x] `/memory debug recall <text>`。
- [x] 单元测试覆盖生命周期、召回过滤、命令权限。
- [x] rollout 开关 `MEMORY_RECALL_LIFECYCLE_FILTER_ENABLED`。
