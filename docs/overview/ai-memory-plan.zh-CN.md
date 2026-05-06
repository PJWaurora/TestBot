# TestBot AI 与记忆整体设计计划

## Summary

TestBot 的 AI 目标不是单纯接一个聊天模型，而是让机器人能在群聊里更像一个长期存在的人：记得上下文、知道每个群和每个人的关系边界、能调用已有插件能力，并且不会因为一时兴起把群刷爆。

当前选择是“先记忆，后智能”。Brain 先负责消息持久化、长期记忆、策略和 AI runtime；业务插件仍然保持外部 HTTP module service。Go Gateway 继续只接 NapCat 和 Brain，不碰数据库、不直接调用插件。

## Current State

已经完成的基础能力：

- Brain 会把 normalized incoming message 和 bot response 写入 Postgres。
- 新增 `000004_memory` migration：
  - `memory_items`
  - `memory_embeddings`
  - `memory_runs`
  - `memory_settings`
- Memory 支持 scope：
  - `global`
  - `group`
  - `user`
  - `relationship`
- Memory 必须带 `evidence_message_ids`，避免永久记忆没有证据。
- `/memory` 和 `/记忆` 管理命令已经可用。
- `Memory Extractor MVP` 已可手动触发：
  - `/memory extract`
  - `/memory extract 100`
  - `/记忆 extract`
- OpenAI-compatible AI runtime 已接入，但默认关闭。
- AI 明确命令触发：
  - `/ai`
  - `/chat`
  - `/聊天`
- Mention trigger 可用，但受 `AI_ENABLED` 和 group policy 限制。
- Reply trigger 默认关闭。
- Proactive AI 暂不直接触发普通消息，等后续有 scheduler/cooldown 后再打开。

## Core Principles

### 1. Memory Is Not Chat History

Chat history 是原始材料，memory 是抽取后的长期事实。

Chat history 用于：

- 最近上下文
- summary
- memory extractor 的证据来源
- debug 和行为回放

Long-term memory 用于：

- 用户偏好
- 群聊习惯
- 用户之间的关系
- 重要事实
- 机器人应该长期记住的互动风格

### 2. Every Long-Term Memory Needs Evidence

长期记忆必须能追溯到消息证据。否则机器人会越来越像在胡说。

Memory item 至少应包含：

- `content`
- `scope`
- `memory_type`
- `confidence`
- `importance`
- `evidence_message_ids`
- `group_id/user_id/target_user_id`

### 3. Group Boundary Is Real

同一个 QQ 在不同群里的身份和关系可能完全不同。

因此：

- `user` memory 必须绑定 `group_id + user_id`。
- `relationship` memory 必须绑定 `group_id + user_id + target_user_id`。
- 普通群管理员只能管理本群 memory。
- 只有 `MEMORY_ADMIN_USER_IDS` 中的全局管理员能跨群删除指定 memory。

### 4. AI Must Be Opt-In

默认行为：

- 普通文本静默。
- deterministic module 优先。
- AI 默认关闭。
- proactive 默认关闭。

这样可以避免成本、刷屏和不可控行为。

## Runtime Architecture

```text
NapCat
  |
  v
Go Gateway
  |
  v
Python Brain
  |-- deterministic router
  |-- remote module services
  |-- memory recall
  |-- OpenAI-compatible AI runtime
  |-- outbox
  |
  v
Postgres
```

关键边界：

- Gateway 不写 DB。
- Gateway 不调用插件。
- Brain 负责策略、路由、memory、AI、outbox。
- 外部模块负责业务能力。
- Renderer/media 是基础设施，不是 Brain module。

## Message Persistence Design

Brain 收到每条 normalized message 后，如果 `DATABASE_URL` 可用，就写入：

- `conversations`
- `message_events_raw`
- `messages`

Brain 产生回复后写入：

- `bot_responses`

原则：

- DB 写失败不影响聊天链路。
- Persistence 是 best-effort。
- Go Gateway 仍然无状态。

## Memory Model

### Scope

`global`：

- 全局事实。
- 需要谨慎使用。
- 一般只由系统或全局管理员写入。

`group`：

- 群规则、群偏好、群里的固定梗。

`user`：

- 某个用户在某个群里的偏好和行为画像。

`relationship`：

- 两个用户在某个群里的关系。
- 也可用于 bot 与用户之间的关系建模。

### Memory Type

当前类型：

- `preference`
- `fact`
- `style`
- `relationship`
- `topic`
- `summary`
- `warning`

后续可以扩展，但不要太早加太多类型。类型太细会让 extractor 变得不稳定。

## Memory Recall

v1 recall 使用：

- recent messages
- keyword memory search

后续加入：

- embedding recall
- rerank
- per-user relationship recall
- time decay
- importance weighting

Recall 输出进入 AI prompt 时必须当作“不可信引用数据”，不能作为 system instruction。现在 AI runtime 已经把 memory/recent chat 放在 user role context 中，并加入安全规则。

## AI Runtime

### Trigger

当前支持：

- `/ai <text>`
- `/chat <text>`
- `/聊天 <text>`
- mention bot

默认关闭：

- reply trigger
- proactive trigger

原因：

- QQ reply 不一定是回复 bot。
- proactive 如果没有冷却和采样，会变成每条消息都调用 LLM。

### Config

`brain-python/.env`：

```env
AI_ENABLED=false
AI_BASE_URL=
AI_API_KEY=
AI_MODEL=
AI_TIMEOUT=20
AI_TEMPERATURE=0.7
AI_MAX_TOKENS=800
AI_SYSTEM_PROMPT=
AI_COMMAND_ALIASES=ai,chat,聊天
AI_GROUP_ALLOWLIST=
AI_GROUP_BLOCKLIST=
AI_MENTION_TRIGGER_ENABLED=true
AI_REPLY_TRIGGER_ENABLED=false
AI_PROACTIVE_ENABLED=false
AI_PROACTIVE_GROUP_ALLOWLIST=
```

推荐第一阶段：

```env
AI_ENABLED=true
AI_GROUP_ALLOWLIST=测试群号
AI_REPLY_TRIGGER_ENABLED=false
AI_PROACTIVE_ENABLED=false
```

Memory extractor 配置：

```env
MEMORY_EXTRACTOR_ENABLED=false
MEMORY_EXTRACTOR_BASE_URL=
MEMORY_EXTRACTOR_API_KEY=
MEMORY_EXTRACTOR_MODEL=
MEMORY_EXTRACTOR_TIMEOUT=30
MEMORY_EXTRACTOR_BATCH_SIZE=80
MEMORY_EXTRACTOR_MAX_CANDIDATES=12
```

`MEMORY_EXTRACTOR_BASE_URL/API_KEY/MODEL` 为空时会回退到 `AI_BASE_URL/API_KEY/MODEL`。建议只在测试群先开启，并通过手动 `/memory extract` 验证质量。

## Prompt Design

Prompt 分三层：

1. Fixed system prompt
2. Untrusted context block
3. User message

System prompt 只放机器人身份、风格和安全规则。

Untrusted context block 放：

- 当前 message metadata
- sender name
- recent messages
- recalled long-term memories

User message 放真实触发文本。

上下文必须：

- delimiter 包裹
- 截断
- 明确标注非指令
- 不放入 system role

## Memory Admin Commands

```text
/memory status
/memory search <keyword>
/memory user <QQ>
/memory extract [数量]
/memory forget <id>
/memory forget-user <QQ>
/memory forget-group
/memory enable
/memory disable
```

权限：

- NapCat sender role 是 `owner/admin` 可管理本群。
- `MEMORY_ADMIN_USER_IDS` 是全局管理员。

删除策略：

- soft delete。
- 群管理员只删本群。
- 全局管理员可按 id 删除。

抽取策略：

- `/memory extract` 只在当前群执行。
- 命令会先立即回复“已开始”，实际 LLM 抽取在后台 worker 中执行。
- 完成、无消息或失败结果通过 Brain outbox 异步发回群里。
- 默认读取最近 `MEMORY_EXTRACTOR_BATCH_SIZE` 条文本消息。
- 显式数量允许 `10-200`，例如 `/memory extract 100`。
- 当前群 `/memory disable` 后不会抽取。
- 每条长期 memory 必须带本批消息中的 `evidence_message_ids`。
- MVP 拒绝 `global` scope，只写 `group/user/relationship`。
- 相同 scope/type/user/target/content 的 active memory 会 merge/update，不会无限新增。

## Next Implementation Batches

### Batch 1: Memory Extractor MVP

状态：已完成手动触发 MVP。

已实现：

- `/memory extract [数量]` 管理命令。
- 按当前 group 分批读取最近 messages。
- 调 OpenAI-compatible model 产出候选 memory。
- 要求每条候选 memory 包含 evidence message ids。
- 写入 `memory_runs` 和 `memory_items`。
- 对相似 memory 做 merge/update，而不是无限新增。

尚未实现：

- 后台 scheduler。
- embedding 写入。
- 跨批次智能 rerank。

测试场景：

- 没有 evidence 的候选 memory 被拒绝。
- 同一事实重复出现时更新 confidence/last_seen。
- blocked/disabled group 不抽取。

### Batch 2: Embedding Recall

目标：让 recall 不只靠关键词。

任务：

- 配置 embedding model。
- 新增 memory embedding 写入。
- recall 时 keyword + vector hybrid。
- 对结果做简单 rerank。

配置：

```env
EMBEDDING_ENABLED=false
EMBEDDING_MODEL=
EMBEDDING_BASE_URL=
EMBEDDING_API_KEY=
EMBEDDING_DIMENSIONS=1536
```

注意：当前 DB 是 `vector(1536)`，如果换维度需要新 migration。

### Batch 3: Persona And Relationship Model

目标：让机器人更像长期存在于群里。

任务：

- bot persona prompt 配置化。
- per-group style memory。
- per-user relationship memory。
- reply style 根据群和用户调整。

示例：

- 某群喜欢短句吐槽。
- 某用户不喜欢被长篇解释。
- 某用户经常问 Pixiv 排行。

### Batch 4: Tool Calling

目标：AI 能调用已有 command/module 能力。

任务：

- `/tools` 聚合远程 module tools。
- AI runtime 支持 tool calling loop。
- tool result 进入二次 LLM response。
- deterministic 命令仍然优先。

原则：

- 明确命令不走 AI。
- 自然语言可以让 AI 调 tool。
- 敏感模块需要额外 gating。

### Batch 5: Proactive AI

目标：低频、像真人一样偶尔参与。

上线前必须具备：

- group allowlist
- per-group cooldown
- daily quota
- random sampling
- quiet hours
- recent bot response suppression
- topic relevance scoring

初始建议：

```env
AI_PROACTIVE_ENABLED=false
AI_PROACTIVE_GROUP_ALLOWLIST=
AI_PROACTIVE_MIN_INTERVAL_SECONDS=1800
AI_PROACTIVE_DAILY_LIMIT=20
AI_PROACTIVE_SAMPLE_RATE=0.02
```

不要让 proactive 直接绑定每条普通消息，这是刷屏和烧钱按钮。

### Batch 6: Retention And Privacy

目标：控制数据生命周期。

任务：

- raw messages 30 天清理 job。
- bot responses 同步清理。
- long-term memory 永久保留，除非 admin forget。
- 导出某群 memory。
- 查询某用户 memory。
- 审计删除记录。

## Risk List

### Prompt Injection

来源：

- recent messages
- stored memory
- module output

控制：

- 不可信上下文不用 system role。
- delimiter。
- 明确安全规则。
- 截断。
- tool calling 需要白名单和 schema validation。

### Cross-Group Leakage

控制：

- user/relationship memory 必须绑定 group。
- recall SQL 必须按 scope 区分。
- 管理命令按 group 限制。

### Spam And Cost

控制：

- AI 默认关闭。
- allowlist。
- proactive 需要 cooldown/quota。
- failures 不重试群回复。

### Bad Memories

控制：

- evidence required。
- confidence/importance。
- admin forget。
- extractor 输出 JSON schema validation。
- merge rather than append。

## Recommended Immediate Next Step

`Memory Extractor MVP` 已完成，下一步优先做 `AI Tool Calling` 或 `Embedding Recall`，不要急着做 proactive。

原因：

- AI Tool Calling 能把自然语言接到现有 Weather/Bilibili/TS/Pixiv 能力。
- Embedding Recall 能让已抽取 memory 不只靠关键词召回。
- proactive 仍然需要 cooldown/quota/quiet hours，否则容易刷屏和烧钱。

建议分 PR：

1. AI tool calling loop
2. Embedding recall
3. Background extractor scheduler
4. Persona/relationship prompt tuning
5. Proactive AI
