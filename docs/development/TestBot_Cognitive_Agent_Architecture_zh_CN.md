# TestBot 认知型群聊 Agent 架构设计

> Version: 0.2  
> Language: zh-CN  
> Purpose: 给 Codex / 开发模型 / 人类开发者阅读的工程架构设计文档  
> Goal: 构建一个拥有长期记忆、群边界、用户关系、稳定风格、低频主动参与能力，并预留 WebUI 管理 API 的群聊 Agent。

---

## 当前状态 vs 未来目标

本文档描述的是 TestBot 的认知型 Agent 架构愿景与演进目标，不代表当前代码库已经完整实现了这些能力。

后续开发模型和人类开发者阅读本文时，应将其中的 Memory Engine、Recall Engine、Decision Engine、关系图、主动参与、WebUI API 等内容理解为目标架构，而不是默认存在的运行时行为。具体实现状态必须以当前代码、测试、部署配置和运行日志为准。

当前阶段的工程重心应放在：

- 明确消息、用户、群、记忆、证据、权限等核心数据边界
- 提升长期记忆的质量、证据链、合并策略和生命周期管理
- 保持 AI 触发策略保守、可控、可观测
- 为未来 WebUI、关系图、主动参与和评估系统预留清晰接口

未来目标是逐步把 TestBot 演进成长期存在于群聊中的认知型 Agent，但任何未落地能力都不应被当成已完成依赖。

---

## 实施策略

不要一次性实现本文档里的全部内容。该架构应按阶段推进，每个阶段都要有可运行代码、可回滚边界、测试覆盖和行为观测，再进入下一阶段。

Phase 1 的优先级是 memory quality / lifecycle：先把长期记忆的抽取、证据、置信度、重要性、去重、合并、过期、归档、纠错和权限边界做好。只有记忆系统足够可靠，后续召回、人格稳定、关系建模和主动参与才有意义。

Phase 1 不应急于实现：

- proactive AI / 低频主动参与
- entity graph / relationship graph 的完整图谱能力
- full WebUI / 完整管理后台
- 自动化高风险行为决策

这些能力应该排在记忆质量和生命周期稳定之后，再按 Hybrid Recall、Conversation State、Prompt Compiler、WebUI API Foundation、Tool Calling、Evaluation、Proactive AI 等阶段逐步落地。

未来 agent 执行任务时，应优先选择最小可验证切片：先补数据模型、权限、测试和可观测性，再扩展行为能力。本文档保留完整愿景，但实施时必须避免把愿景误读成一次性需求清单。

---

## 1. 项目目标

TestBot 的目标不是做一个简单的 LLM 聊天机器人，而是做一个长期存在于群聊中的认知型 Agent。

它应该具备：

- 长期记忆
- 群边界意识
- 用户关系建模
- 稳定人格与回复风格
- 低频主动参与能力
- 工具调用能力
- 可追踪、可评估、可调优的行为系统
- 面向未来 WebUI 的管理 API

最终目标：

> 让 TestBot 更像一个长期存在于群里的成员，而不是一个每次从零开始的 AI 助手。

---

## 2. 核心原则

### 2.1 记忆不是聊天记录

聊天记录是原始材料。

长期记忆是从聊天记录中抽取、合并、确认后的稳定信息。

聊天记录用于：

- 最近上下文
- 行为回放
- Debug
- 记忆抽取
- 对话总结

长期记忆用于：

- 用户偏好
- 群聊习惯
- 用户关系
- 群内固定梗
- 行为边界
- 长期风格控制

机器人不能把每一句话都当成永久记忆。

---

### 2.2 每条长期记忆必须有证据

所有长期记忆必须能追溯到原始消息。

每条 memory 至少应包含：

```json
{
  "content": "该用户更喜欢简短的技术解释。",
  "scope": "user",
  "memory_class": "procedural",
  "memory_type": "style",
  "confidence": 0.82,
  "importance": 0.7,
  "evidence_message_ids": ["msg_001", "msg_014"],
  "group_id": "group_123",
  "user_id": "user_456"
}
```

没有证据的内容不能进入长期记忆。

---

### 2.3 群边界是真实存在的

同一个用户在不同群里的身份、语气和关系可能完全不同。

因此：

```text
user memory = group_id + user_id
relationship memory = group_id + user_id + target_user_id
```

不能默认把某个用户在一个群里的行为泛化到所有群。

---

### 2.4 AI 默认保守，主动参与最后再开

默认策略：

- 普通文本不触发 AI
- deterministic command 优先
- `/ai`、`/chat`、`/聊天` 显式触发
- mention trigger 受群策略限制
- reply trigger 默认关闭
- proactive AI 默认关闭

主动参与必须等以下能力完善后再开启：

- cooldown
- daily quota
- quiet hours
- opportunity scoring
- recent bot reply suppression
- sensitive topic avoidance

---

## 3. 总体架构

```text
NapCat
  |
  v
Go Gateway
  |
  v
Python Brain
  |
  |-- Ingestion Service
  |-- State Engine
  |-- Memory Engine
  |-- Recall Engine
  |-- Decision Engine
  |-- Prompt Compiler
  |-- LLM Runtime
  |-- Tool Calling Runtime
  |-- Evaluation Engine
  |-- WebUI API Layer
  |-- Outbox
  |
  v
Postgres / pgvector / Redis
```

---

## 4. 模块职责

### 4.1 Go Gateway

Go Gateway 保持轻量和无状态。

职责：

- 接收 NapCat 事件
- 标准化消息结构
- 转发到 Brain
- 接收 Brain outbox
- 调用 NapCat 发送消息

Gateway 不负责：

- 写数据库
- 记忆逻辑
- AI 调用
- 插件调用
- 群策略判断
- WebUI 管理逻辑

Gateway 应该尽可能无状态。

---

### 4.2 Python Brain

Brain 是整个系统的认知核心。

职责：

- 消息持久化
- 短期上下文管理
- 群状态建模
- 记忆抽取
- 记忆合并
- 记忆生命周期管理
- 用户关系建模
- 记忆召回
- 回复决策
- Prompt 编译
- LLM 调用
- Tool Calling
- 回复评估
- WebUI API
- Outbox 投递

Brain 不是 LLM wrapper。

Brain 是 Agent Runtime。

---

## 5. 认知处理流水线

理想处理流程：

```text
Incoming Message
  |
  v
Normalize & Persist
  |
  v
Update Conversation State
  |
  v
Extract Memory Signals
  |
  v
Update Entity / Relationship Graph
  |
  v
Decide Whether To Respond
  |
  v
Recall Relevant Memory
  |
  v
Rerank & Compress Context
  |
  v
Compile Prompt Strategy
  |
  v
Generate Response / Call Tools
  |
  v
Post-Check Response
  |
  v
Send Response
  |
  v
Evaluate Response Outcome
  |
  v
Update Future Policy
```

不要只做：

```text
message -> recall -> prompt -> response
```

这个流程太线性，不足以支撑长期群聊 Agent。

---

## 6. Memory System

### 6.1 Memory Class

不要只用扁平的 memory_type。

建议将记忆分成以下 memory_class：

```text
episodic
semantic
procedural
affective
social
persona
```

#### episodic memory

事件记忆。

例子：

- 用户 A 昨天问过 Clash REST API。
- 群里上周讨论过 AI 安全 presentation。
- bot 曾经在某次主动回复中被指出太长。

用途：

- 回忆具体事件
- 对话连续性
- 复盘和行为回放

---

#### semantic memory

稳定事实。

例子：

- 用户 A 正在做 QQ bot 项目。
- 这个群经常讨论编程和部署。
- 该群使用 NapCat 接入 QQ。

用途：

- 背景事实
- 长期上下文

---

#### procedural memory

行为规则 / 习惯记忆。

例子：

- 对这个用户回答技术问题时优先给命令。
- 这个群不喜欢长篇 proactive 回复。
- 被问到部署问题时，先确认运行环境。

用途：

- 控制行为
- 控制回复风格
- 减少重复犯错

---

#### affective memory

情绪 / 语气相关记忆。

例子：

- 用户 A 喜欢轻微吐槽式幽默。
- 用户 B 不喜欢被直接纠正。
- 这个群在深夜聊天时风格更随意。

用途：

- 情绪调节
- 社交语气判断
- 避免冒犯

---

#### social memory

群体关系记忆。

例子：

- 用户 A 和用户 B 经常互相开玩笑。
- 用户 C 经常帮别人解决技术问题。
- 用户 D 不喜欢被频繁 cue。

用途：

- 用户关系建模
- 群动态理解
- 避免误判冲突和玩笑

---

#### persona memory

bot 自身人格设定。

例子：

- bot 应该像低频群友，而不是客服。
- bot 不应在普通聊天里过度解释。
- bot 可以轻微幽默，但不能刷屏。

用途：

- 人格稳定
- 长期风格控制

---

### 6.2 Memory Scope

每条记忆必须有 scope。

支持：

```text
global
group
user
relationship
```

#### global

全局事实或全局规则。

谨慎使用。

例子：

```text
bot 不允许把一个群的私有记忆泄漏到另一个群。
```

#### group

某个群内有效。

例子：

```text
这个群喜欢简短随意的回复。
```

#### user

某个用户在某个群内有效。

例子：

```text
在这个群里，用户 A 更喜欢技术回答带具体命令。
```

#### relationship

某个群内两个用户之间，或 bot 与用户之间的关系。

例子：

```text
在这个群里，用户 A 经常用吐槽语气和 bot 互动。
```

---

### 6.3 Memory Table

建议表结构：

```sql
CREATE TABLE memory_items (
    id UUID PRIMARY KEY,

    scope TEXT NOT NULL,
    memory_class TEXT NOT NULL,
    memory_type TEXT NOT NULL,

    group_id TEXT,
    user_id TEXT,
    target_user_id TEXT,

    content TEXT NOT NULL,

    confidence FLOAT NOT NULL DEFAULT 0.5,
    importance FLOAT NOT NULL DEFAULT 0.5,
    stability FLOAT NOT NULL DEFAULT 0.5,

    first_seen_at TIMESTAMP NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMP NOT NULL DEFAULT NOW(),
    last_confirmed_at TIMESTAMP,

    valid_until TIMESTAMP,

    decay_score FLOAT NOT NULL DEFAULT 1.0,
    contradiction_count INT NOT NULL DEFAULT 0,
    source_count INT NOT NULL DEFAULT 1,

    status TEXT NOT NULL DEFAULT 'active',
    evidence_message_ids TEXT[] NOT NULL,

    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
```

---

### 6.4 Memory Lifecycle

记忆不能只新增和召回。

它应该有生命周期：

```text
candidate signal
  |
  v
weak memory
  |
  v
confirmed memory
  |
  v
reinforced memory
  |
  v
stale / contradicted / archived memory
```

必要操作：

- reinforcement
- decay
- contradiction detection
- merge
- retirement
- evidence update
- confidence adjustment
- importance adjustment

---

### 6.5 Memory Score

召回时不应该只看 embedding similarity。

建议综合打分：

```text
memory_score =
    semantic_similarity
  + keyword_match
  + entity_relevance
  + relationship_relevance
  + recency_weight
  + importance_weight
  + confidence_weight
  + source_count_weight
  - contradiction_penalty
  - decay_penalty
```

---

## 7. Entity and Relationship Graph

自然语言 memory 不足以支撑高质量社交行为。

需要结构化关系图。

### 7.1 memory_entities

```sql
CREATE TABLE memory_entities (
    entity_id UUID PRIMARY KEY,
    group_id TEXT,
    entity_type TEXT NOT NULL,
    qq_id TEXT,
    display_name TEXT,
    aliases TEXT[],
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
```

entity_type：

```text
user
group
topic
bot
plugin
external_resource
```

---

### 7.2 memory_edges

```sql
CREATE TABLE memory_edges (
    edge_id UUID PRIMARY KEY,

    group_id TEXT NOT NULL,

    source_entity_id UUID NOT NULL,
    target_entity_id UUID NOT NULL,

    relation_type TEXT NOT NULL,

    strength FLOAT NOT NULL DEFAULT 0.5,
    confidence FLOAT NOT NULL DEFAULT 0.5,

    evidence_message_ids TEXT[] NOT NULL,

    first_seen_at TIMESTAMP NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMP NOT NULL DEFAULT NOW(),

    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
```

relation_type 示例：

```text
often_jokes_with
often_helps
often_argues_with
same_interest
dislikes_topic
prefers_short_reply
uses_nickname_for
trusts
avoids
frequently_mentions
often_asks_technical_questions
```

---

## 8. Conversation State Engine

长期记忆不够，还需要当前群状态。

### 8.1 目的

Conversation State Engine 用于追踪：

- 当前话题
- 当前群气氛
- 聊天速度
- 当前发言人集合
- bot 是否刚说过话
- 是否适合长回复
- 群里是在认真讨论还是玩梗

---

### 8.2 conversation_states

```sql
CREATE TABLE conversation_states (
    group_id TEXT PRIMARY KEY,

    active_topics TEXT[],
    mood TEXT,
    conversation_velocity TEXT,

    current_speaker_ids TEXT[],

    last_bot_reply_at TIMESTAMP,
    bot_reply_count_1h INT NOT NULL DEFAULT 0,
    bot_reply_count_24h INT NOT NULL DEFAULT 0,

    should_avoid_long_reply BOOLEAN NOT NULL DEFAULT FALSE,

    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
```

---

### 8.3 Example

```json
{
  "group_id": "group_123",
  "active_topics": ["AI Agent", "长期记忆", "WebUI"],
  "mood": "technical_casual",
  "conversation_velocity": "medium",
  "current_speaker_ids": ["user_456"],
  "last_bot_reply_at": "2026-05-06T12:00:00Z",
  "bot_reply_count_1h": 1,
  "bot_reply_count_24h": 8,
  "should_avoid_long_reply": false
}
```

---

## 9. Recall Engine

### 9.1 多阶段召回

强召回系统不应该只用 keyword 或 vector。

推荐流程：

```text
Stage 1: Candidate Generation
  - keyword search
  - vector search
  - entity graph search
  - relationship search
  - temporal search
  - recent conversation search

Stage 2: Reranking
  - semantic relevance
  - entity relevance
  - confidence
  - importance
  - recency
  - relationship match
  - contradiction penalty

Stage 3: Deduplication
  - remove repeated memories
  - merge overlapping memories
  - prefer more recent confirmed memories

Stage 4: Compression
  - compress low-priority memories
  - preserve high-priority memories verbatim
  - fit prompt budget

Stage 5: Prompt Placement
  - place critical memories near the user message
  - keep background summaries short
```

---

### 9.2 Recall Output

```json
{
  "high_priority_memories": [
    {
      "id": "mem_001",
      "content": "用户更喜欢简短技术回答。",
      "reason": "直接影响回复风格。"
    }
  ],
  "relationship_context": [
    {
      "id": "edge_002",
      "content": "用户经常和 bot 用轻微吐槽语气互动。"
    }
  ],
  "group_context": [
    {
      "id": "mem_010",
      "content": "这个群偏好低频 bot 参与。"
    }
  ],
  "compressed_background": "该群主要讨论编程、bot、AI、部署。"
}
```

---

## 10. Decision Engine

Decision Engine 决定 bot 是否应该回复。

LLM 不应该负责所有 reply / no-reply 决策。

### 10.1 Trigger Types

```text
command
mention
reply
proactive
tool_request
admin_command
```

---

### 10.2 Opportunity Scoring

proactive 参与需要打分：

```text
speak_score =
    mention_score
  + relevance_score
  + expertise_score
  + relationship_score
  + humor_opportunity_score
  + silence_duration_bonus
  - interruption_penalty
  - recent_bot_reply_penalty
  - sensitive_topic_penalty
  - low_confidence_penalty
  - daily_quota_penalty
```

---

### 10.3 Reply Decision

建议阈值：

```text
score < 0.30
  -> do not reply

0.30 <= score < 0.50
  -> maybe react silently or send a very short reply

0.50 <= score < 0.75
  -> short casual reply

score >= 0.75
  -> normal reply
```

---

### 10.4 Decision Output

```json
{
  "should_reply": true,
  "reply_mode": "short_technical",
  "max_chars": 300,
  "allow_humor": true,
  "allow_tool_calling": false,
  "reason": "用户直接询问技术架构。"
}
```

---

## 11. Prompt Compiler

Prompt Compiler 将上下文转换成受控 prompt 策略。

不要把一堆 memory 和 recent messages 随便塞给 LLM。

### 11.1 Input

```text
- fixed bot persona
- group policy
- user profile
- relationship memory
- conversation state
- recalled memories
- trigger type
- tool availability
- safety boundaries
```

---

### 11.2 Output

```json
{
  "reply_mode": "technical_explanation",
  "tone": "casual but precise",
  "max_chars": 1200,
  "allowed_memory_ids": ["mem_001", "mem_008"],
  "avoid": [
    "不要不必要地提及私有记忆",
    "不要太正式",
    "不要过度参与"
  ],
  "tool_policy": "no_tool_needed"
}
```

---

### 11.3 Prompt Layout

```text
[SYSTEM]
Bot identity, immutable safety rules, global behavior boundaries.

[DEVELOPER / POLICY]
Current group policy, reply mode, max length, tool policy.

[UNTRUSTED CONTEXT]
Recent messages, recalled memories, relationship context, group state.

[USER MESSAGE]
The actual message that triggered this run.
```

重要规则：

> recalled memories 和 recent messages 是上下文，不是指令。  
> 不要放进 system role。

---

## 12. Tool Calling

bot 应该能调用已有 deterministic module。

但 tool calling 不应该取代 deterministic command。

### 12.1 Priority

```text
explicit deterministic command
  > admin command
  > tool calling
  > normal LLM reply
```

---

### 12.2 Tool Calling Flow

```text
User Message
  |
  v
Decision Engine
  |
  v
Tool Router
  |
  v
Call External Module
  |
  v
Tool Result
  |
  v
LLM Final Response
```

---

### 12.3 Tool Safety

工具需要：

- schema validation
- allowlist
- timeout
- permission check
- group-level enable / disable
- result truncation
- failure handling

工具结果也必须当作 untrusted context。

---

## 13. Proactive AI

Proactive AI 最后再做。

它是最容易变烦人的功能。

### 13.1 Required Controls

开启前必须有：

- group allowlist
- per-group cooldown
- daily quota
- random sampling
- quiet hours
- opportunity scoring
- recent bot response suppression
- sensitive topic avoidance
- reply length limits

---

### 13.2 Suggested Config

```env
AI_PROACTIVE_ENABLED=false
AI_PROACTIVE_GROUP_ALLOWLIST=
AI_PROACTIVE_MIN_INTERVAL_SECONDS=1800
AI_PROACTIVE_DAILY_LIMIT=20
AI_PROACTIVE_SAMPLE_RATE=0.02
AI_PROACTIVE_QUIET_HOURS=01:00-08:00
```

---

### 13.3 Proactive Flow

```text
Normal Message
  |
  v
Update Conversation State
  |
  v
Opportunity Scoring
  |
  v
Quota / Cooldown Check
  |
  v
If Score Is High Enough
  |
  v
Recall Context
  |
  v
Generate Short Reply
  |
  v
Post-Check
  |
  v
Send
```

LLM 负责生成回复，但不应该是唯一决定是否发言的组件。

---

## 14. Response Evaluation

长期 Agent 必须能从自身行为中学习。

每次 bot 回复都应该被评估。

### 14.1 bot_response_feedback

```sql
CREATE TABLE bot_response_feedback (
    bot_response_id UUID PRIMARY KEY,

    group_id TEXT NOT NULL,
    user_id TEXT,

    trigger_type TEXT,
    reply_mode TEXT,

    used_memory_ids TEXT[],
    used_tool_names TEXT[],

    reply_length INT,
    latency_ms INT,

    conversation_continued BOOLEAN,
    positive_signal BOOLEAN,
    negative_signal BOOLEAN,

    possible_memory_error BOOLEAN,
    possible_tone_error BOOLEAN,
    possible_spam BOOLEAN,

    evaluator_score FLOAT,

    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
```

---

### 14.2 Evaluation Signals

positive:

- 用户继续对话
- 用户感谢 bot
- 用户正面回应
- bot 的回答之后被引用

negative:

- 用户无视 bot
- 用户说 bot 烦
- 用户纠正记忆
- bot 连续刷屏
- bot 语气错误
- bot 泄漏了无关群上下文

---

### 14.3 Evaluator Job

周期性 evaluator 可以分析最近 bot 回复，并生成 procedural memory。

例子：

```json
{
  "memory_class": "procedural",
  "memory_type": "style",
  "scope": "group",
  "content": "在这个群里，proactive 回复应控制在 80 字以内，除非用户明确要求详细解释。",
  "confidence": 0.78,
  "importance": 0.8
}
```

---

## 15. Logging and Observability

为了优化行为，每次 AI run 都必须可追踪。

### 15.1 prompt_runs

```sql
CREATE TABLE prompt_runs (
    run_id UUID PRIMARY KEY,

    message_id TEXT,
    group_id TEXT,
    user_id TEXT,

    model TEXT,
    prompt_hash TEXT,

    trigger_type TEXT,
    reply_mode TEXT,

    memory_ids TEXT[],
    tool_names TEXT[],

    decision_score FLOAT,
    output_text TEXT,

    latency_ms INT,
    cost_estimate FLOAT,

    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
```

---

### 15.2 Why

没有 prompt run logs，就无法知道：

- bot 为什么回复
- 使用了哪些记忆
- 为什么用这个语气
- 哪个 prompt version 更好
- 换模型有没有改善
- proactive 是否烦人

---

## 16. WebUI API Design

### 16.1 为什么需要 WebUI API

如果 TestBot 只是玩具，可以只靠群命令。

但如果目标是长期优化效果，就必须有 WebUI。

WebUI 用于：

- 查看记忆
- 搜索记忆
- 删除错误记忆
- 调整群策略
- 查看用户画像
- 查看关系图
- 查看 AI 回复日志
- 查看 prompt run
- 查看 proactive 触发原因
- 管理模型配置
- 管理工具权限
- 观察效果评估
- Debug 为什么 bot 会这样回复

WebUI 不是装饰，是长期调参和修正行为的核心。

---

### 16.2 WebUI API 原则

WebUI API 应该满足：

- 只管理 Brain，不直接操作 Gateway
- 所有写操作需要权限控制
- 所有高风险操作需要审计日志
- API 返回结构化 JSON
- Memory、Prompt、Policy、Tool、Log 都要可视化
- WebUI 不直接修改数据库，应通过 Brain API 调用
- WebUI 操作应与群内 `/memory` 命令共享同一套权限逻辑

---

### 16.3 API Modules

建议预留：

```text
/api/auth
/api/dashboard
/api/groups
/api/users
/api/memories
/api/entities
/api/relationships
/api/conversation-states
/api/policies
/api/prompts
/api/models
/api/tools
/api/runs
/api/evaluations
/api/outbox
/api/admin
```

---

## 17. Auth API

### 17.1 当前登录用户

```http
GET /api/auth/me
```

Response:

```json
{
  "user_id": "admin_001",
  "name": "Admin",
  "role": "global_admin",
  "permissions": [
    "memory.read",
    "memory.write",
    "policy.write",
    "prompt.write"
  ]
}
```

---

### 17.2 权限模型

```text
global_admin
group_admin
viewer
```

global_admin:

- 管理所有群
- 管理所有 memory
- 管理全局 prompt
- 管理模型配置
- 管理工具权限
- 查看审计日志

group_admin:

- 管理自己有权限的群
- 管理本群 memory
- 管理本群 policy
- 管理本群 proactive 设置

viewer:

- 只能查看
- 不能修改

---

## 18. Dashboard API

### 18.1 系统概览

```http
GET /api/dashboard/overview
```

Response:

```json
{
  "groups_total": 12,
  "messages_24h": 5321,
  "bot_responses_24h": 82,
  "ai_runs_24h": 76,
  "tool_calls_24h": 19,
  "memory_items_total": 10423,
  "active_memory_items": 9210,
  "proactive_replies_24h": 5,
  "average_latency_ms": 1320,
  "estimated_cost_24h": 1.42
}
```

---

### 18.2 最近活动

```http
GET /api/dashboard/recent-activity
```

Response:

```json
{
  "items": [
    {
      "type": "ai_reply",
      "group_id": "group_123",
      "user_id": "user_456",
      "summary": "Bot answered an architecture question.",
      "created_at": "2026-05-06T12:00:00Z"
    }
  ]
}
```

---

## 19. Group API

### 19.1 群列表

```http
GET /api/groups
```

Response:

```json
{
  "groups": [
    {
      "group_id": "group_123",
      "name": "测试群",
      "ai_enabled": true,
      "memory_enabled": true,
      "proactive_enabled": false,
      "message_count_24h": 1203,
      "bot_reply_count_24h": 15
    }
  ]
}
```

---

### 19.2 群详情

```http
GET /api/groups/{group_id}
```

Response:

```json
{
  "group_id": "group_123",
  "name": "测试群",
  "settings": {
    "ai_enabled": true,
    "memory_enabled": true,
    "mention_trigger_enabled": true,
    "reply_trigger_enabled": false,
    "proactive_enabled": false
  },
  "stats": {
    "messages_total": 230001,
    "memory_items": 892,
    "bot_responses": 3021
  }
}
```

---

## 20. Memory API

### 20.1 搜索记忆

```http
GET /api/memories?group_id=group_123&query=技术解释&scope=user&status=active
```

Response:

```json
{
  "items": [
    {
      "id": "mem_001",
      "scope": "user",
      "memory_class": "procedural",
      "memory_type": "style",
      "content": "该用户更喜欢简短的技术解释。",
      "confidence": 0.82,
      "importance": 0.7,
      "status": "active",
      "group_id": "group_123",
      "user_id": "user_456",
      "evidence_message_ids": ["msg_001", "msg_014"],
      "created_at": "2026-05-06T12:00:00Z",
      "updated_at": "2026-05-06T12:30:00Z"
    }
  ],
  "total": 1
}
```

---

### 20.2 查看单条记忆

```http
GET /api/memories/{memory_id}
```

Response:

```json
{
  "id": "mem_001",
  "content": "该用户更喜欢简短的技术解释。",
  "scope": "user",
  "memory_class": "procedural",
  "memory_type": "style",
  "confidence": 0.82,
  "importance": 0.7,
  "stability": 0.75,
  "decay_score": 0.94,
  "status": "active",
  "evidence_messages": [
    {
      "message_id": "msg_001",
      "sender_name": "User A",
      "content": "你别写那么长，直接告诉我命令。",
      "created_at": "2026-05-05T20:00:00Z"
    }
  ]
}
```

---

### 20.3 创建记忆

```http
POST /api/memories
```

Request:

```json
{
  "scope": "group",
  "memory_class": "procedural",
  "memory_type": "style",
  "content": "这个群更喜欢短句吐槽风格。",
  "confidence": 0.9,
  "importance": 0.8,
  "group_id": "group_123",
  "evidence_message_ids": ["msg_001", "msg_002"]
}
```

---

### 20.4 更新记忆

```http
PATCH /api/memories/{memory_id}
```

Request:

```json
{
  "content": "这个群更喜欢简短、轻微吐槽的回复风格。",
  "confidence": 0.92,
  "importance": 0.85
}
```

---

### 20.5 归档记忆

```http
DELETE /api/memories/{memory_id}
```

建议 soft delete。

实际更新：

```json
{
  "status": "archived"
}
```

---

### 20.6 触发记忆抽取

```http
POST /api/memories/extract
```

Request:

```json
{
  "group_id": "group_123",
  "limit": 100
}
```

Response:

```json
{
  "run_id": "memory_run_001",
  "status": "queued"
}
```

---

## 21. Entity / Relationship API

### 21.1 查询实体

```http
GET /api/entities?group_id=group_123&type=user
```

Response:

```json
{
  "items": [
    {
      "entity_id": "entity_001",
      "entity_type": "user",
      "qq_id": "123456",
      "display_name": "PJW",
      "aliases": ["pjw", "群主"]
    }
  ]
}
```

---

### 21.2 查询关系图

```http
GET /api/relationships?group_id=group_123&user_id=user_456
```

Response:

```json
{
  "edges": [
    {
      "source_user_id": "user_456",
      "target_user_id": "bot",
      "relation_type": "often_asks_technical_questions",
      "strength": 0.81,
      "confidence": 0.76,
      "evidence_message_ids": ["msg_001", "msg_013"]
    }
  ]
}
```

---

## 22. Conversation State API

### 22.1 查看群当前状态

```http
GET /api/conversation-states/{group_id}
```

Response:

```json
{
  "group_id": "group_123",
  "active_topics": ["AI Agent", "长期记忆", "WebUI"],
  "mood": "technical_casual",
  "conversation_velocity": "medium",
  "current_speaker_ids": ["user_456"],
  "last_bot_reply_at": "2026-05-06T12:00:00Z",
  "bot_reply_count_1h": 1,
  "bot_reply_count_24h": 8,
  "should_avoid_long_reply": false
}
```

---

## 23. Policy API

### 23.1 查看群策略

```http
GET /api/policies/groups/{group_id}
```

Response:

```json
{
  "group_id": "group_123",
  "ai_enabled": true,
  "memory_enabled": true,
  "mention_trigger_enabled": true,
  "reply_trigger_enabled": false,
  "proactive_enabled": false,
  "max_reply_chars": 800,
  "style": "casual_technical",
  "quiet_hours": "01:00-08:00",
  "daily_proactive_limit": 5
}
```

---

### 23.2 更新群策略

```http
PATCH /api/policies/groups/{group_id}
```

Request:

```json
{
  "proactive_enabled": true,
  "daily_proactive_limit": 3,
  "max_reply_chars": 300,
  "style": "short_casual"
}
```

---

## 24. Prompt / Run API

### 24.1 Prompt 列表

```http
GET /api/prompts
```

Response:

```json
{
  "items": [
    {
      "id": "prompt_default_chat",
      "name": "Default Chat Prompt",
      "version": 3,
      "enabled": true,
      "updated_at": "2026-05-06T12:00:00Z"
    }
  ]
}
```

---

### 24.2 查看 Prompt Run

```http
GET /api/runs/{run_id}
```

Response:

```json
{
  "run_id": "run_001",
  "group_id": "group_123",
  "user_id": "user_456",
  "trigger_type": "mention",
  "model": "gpt-xxx",
  "reply_mode": "technical_explanation",
  "decision_score": 0.91,
  "used_memory_ids": ["mem_001", "mem_008"],
  "used_tool_names": [],
  "input_summary": "User asked about agent architecture.",
  "output_text": "建议你预留 WebUI API...",
  "latency_ms": 1420,
  "created_at": "2026-05-06T12:00:00Z"
}
```

---

## 25. Model Config API

### 25.1 查看模型配置

```http
GET /api/models
```

Response:

```json
{
  "chat_model": {
    "provider": "openai_compatible",
    "base_url": "https://api.example.com/v1",
    "model": "gpt-xxx",
    "temperature": 0.7,
    "max_tokens": 800
  },
  "memory_extractor_model": {
    "provider": "openai_compatible",
    "model": "gpt-xxx-mini",
    "temperature": 0.2
  },
  "embedding_model": {
    "provider": "openai_compatible",
    "model": "text-embedding-xxx",
    "dimensions": 1536
  }
}
```

---

### 25.2 更新聊天模型配置

```http
PATCH /api/models/chat
```

Request:

```json
{
  "model": "gpt-xxx",
  "temperature": 0.65,
  "max_tokens": 1200
}
```

---

## 26. Tool API

### 26.1 查看可用工具

```http
GET /api/tools
```

Response:

```json
{
  "tools": [
    {
      "name": "weather",
      "enabled": true,
      "description": "查询天气",
      "groups_enabled": ["group_123"]
    },
    {
      "name": "pixiv_ranking",
      "enabled": false,
      "description": "查询 Pixiv 排行"
    }
  ]
}
```

---

### 26.2 更新工具权限

```http
PATCH /api/tools/{tool_name}
```

Request:

```json
{
  "enabled": true,
  "groups_enabled": ["group_123", "group_456"]
}
```

---

## 27. Evaluation API

### 27.1 查看回复评估

```http
GET /api/evaluations?group_id=group_123
```

Response:

```json
{
  "items": [
    {
      "bot_response_id": "resp_001",
      "reply_mode": "technical_explanation",
      "evaluator_score": 0.86,
      "possible_memory_error": false,
      "possible_tone_error": false,
      "possible_spam": false,
      "conversation_continued": true
    }
  ]
}
```

---

### 27.2 手动反馈回复质量

```http
POST /api/evaluations/{bot_response_id}/feedback
```

Request:

```json
{
  "rating": "good",
  "tags": ["useful", "good_tone"],
  "comment": "这次回答长度合适，记忆使用正确。"
}
```

---

## 28. Outbox API

### 28.1 查看待发送消息

```http
GET /api/outbox?status=pending
```

Response:

```json
{
  "items": [
    {
      "id": "outbox_001",
      "group_id": "group_123",
      "content": "已完成 memory extract。",
      "status": "pending",
      "created_at": "2026-05-06T12:00:00Z"
    }
  ]
}
```

---

### 28.2 取消待发送消息

```http
POST /api/outbox/{outbox_id}/cancel
```

---

## 29. Admin API

### 29.1 系统健康检查

```http
GET /api/admin/health
```

Response:

```json
{
  "status": "ok",
  "database": "ok",
  "llm_runtime": "ok",
  "embedding_runtime": "ok",
  "outbox": "ok"
}
```

---

### 29.2 审计日志

```http
GET /api/admin/audit-logs
```

Response:

```json
{
  "items": [
    {
      "actor_id": "admin_001",
      "action": "memory.archive",
      "target_id": "mem_001",
      "group_id": "group_123",
      "created_at": "2026-05-06T12:00:00Z"
    }
  ]
}
```

---

## 30. 推荐 WebUI 页面

未来 WebUI 可以包含：

```text
Dashboard
  系统概览、消息量、AI 调用量、成本、延迟

Groups
  群列表、群策略、AI 开关、proactive 设置

Memories
  记忆搜索、查看证据、编辑、归档、重新抽取

Users
  用户画像、偏好、关系、常见话题

Relationship Graph
  用户关系图、bot 与用户关系、群内互动模式

Conversation State
  当前话题、群气氛、bot 参与频率

Prompt Runs
  每次 AI 调用的上下文、记忆、输出、耗时

Evaluations
  回复质量、风格错误、记忆错误、刷屏风险

Tools
  工具列表、群权限、调用日志

Settings
  模型配置、Embedding 配置、Extractor 配置

Audit Logs
  管理员操作记录
```

---

## 31. WebUI 技术建议

### 31.1 后端

推荐：

```text
FastAPI
Pydantic
Postgres
pgvector
Redis
SQLAlchemy / asyncpg
```

原因：

- 类型清晰
- 自动生成 OpenAPI
- WebUI 对接方便
- 适合管理后台 API
- Python Brain 内部集成方便

---

### 31.2 前端

可选：

```text
Next.js
React
Vue
SvelteKit
```

推荐：

```text
Next.js / React
```

适合：

- Dashboard
- 表格
- 搜索
- 图谱
- 日志查看
- Prompt 调试

---

### 31.3 API 文档

Brain API 应自动生成：

```text
/openapi.json
/docs
/redoc
```

这样 WebUI、Codex、第三方工具都能直接接入。

---

## 32. WebUI 安全要求

WebUI 不能裸奔。

至少需要：

```text
登录认证
管理员权限
群权限隔离
CSRF / CORS 控制
写操作审计日志
敏感字段脱敏
API Token 管理
危险操作二次确认
```

敏感内容：

- AI API Key
- 用户 QQ 号
- 群消息原文
- 长期记忆
- Prompt Run 原始上下文
- Tool 调用结果

---

## 33. Offline Evaluation

如果目标是“最佳效果”，不能只靠感觉调 prompt。

需要离线评估集。

### 33.1 Test Case

每个测试样本包含：

```text
- recent messages
- group_id
- user_id
- current memory snapshot
- expected reply/no-reply decision
- expected tone
- relevant memory ids
- unacceptable behaviors
```

---

### 33.2 Metrics

推荐指标：

```text
reply_decision_accuracy
memory_precision
memory_recall
tone_consistency
cross_group_leak_rate
unwanted_proactive_rate
average_reply_length
tool_call_accuracy
relationship_usage_accuracy
user_engagement_after_reply
```

---

## 34. 推荐实现路线

### Phase 1: Memory Lifecycle

目标：

> 让 memory 从“能存”升级为“会变”。

任务：

- 添加 memory_class
- 添加 memory lifecycle 字段
- 添加 status
- contradiction detection
- reinforcement
- decay
- admin inspection

优先级：

```text
P0
```

---

### Phase 2: Hybrid Recall

目标：

> 让 bot 能在正确时间召回正确记忆。

任务：

- keyword recall
- vector recall
- entity recall
- relationship recall
- recency recall
- reranking
- deduplication
- compression

优先级：

```text
P0
```

---

### Phase 3: Conversation State

目标：

> 让 bot 理解当前群气氛。

任务：

- active topic detection
- mood detection
- conversation velocity
- speaker cluster
- bot participation tracking
- long-reply avoidance

优先级：

```text
P1
```

---

### Phase 4: Prompt Compiler

目标：

> 让 bot 行为更稳定，而不是依赖 raw prompt stuffing。

任务：

- compile reply strategy
- enforce max length
- choose tone
- choose memory subset
- choose tool policy
- separate trusted instruction from untrusted context

优先级：

```text
P1
```

---

### Phase 5: WebUI API Foundation

目标：

> 先预留 WebUI API，避免后期重构地狱。

任务：

- FastAPI router structure
- auth middleware
- permission model
- memory API
- group policy API
- prompt run API
- audit log API
- OpenAPI docs

优先级：

```text
P1
```

---

### Phase 6: Tool Calling

目标：

> 让自然语言能调用已有 deterministic modules。

任务：

- define tool schemas
- expose module capabilities
- implement tool router
- implement tool calling loop
- validate tool results
- add permission controls

优先级：

```text
P1
```

---

### Phase 7: Response Evaluation

目标：

> 让 bot 能从自身行为中变好。

任务：

- log every AI run
- detect positive / negative signals
- evaluate memory usage
- evaluate tone
- evaluate proactive annoyance
- generate procedural memory from evaluations

优先级：

```text
P2
```

---

### Phase 8: Proactive AI

目标：

> 让 bot 像低频群友一样参与。

任务：

- cooldown
- quota
- quiet hours
- opportunity scoring
- proactive allowlist
- short reply mode
- sensitive topic avoidance
- post-check before sending

优先级：

```text
P3
```

不要在 Phase 1-7 稳定之前开启 proactive AI。

---

## 35. Risk List

### 35.1 Prompt Injection

来源：

- recent messages
- stored memories
- tool outputs
- group chat content

缓解：

- 用户内容不放 system role
- 使用 delimiter
- 标记 untrusted context
- validate tool calls
- truncate tool output
- 固定安全规则单独放置

---

### 35.2 Cross-Group Leakage

风险：

bot 在一个群使用另一个群的记忆。

缓解：

- user memory 绑定 group_id + user_id
- relationship memory 绑定 group_id + user_id + target_user_id
- recall SQL 强制 scope rules
- 记录 used_memory_ids
- 评估 cross_group_leak_rate

---

### 35.3 Bad Memories

风险：

bot 把玩笑、临时情绪、错误事实写入长期记忆。

缓解：

- evidence required
- weak memory signals
- 重要 memory 需要重复确认
- contradiction detection
- admin forget
- memory status: active / stale / contradicted / archived

---

### 35.4 Spam

风险：

bot 变烦。

缓解：

- proactive 默认关闭
- cooldown
- daily quota
- quiet hours
- opportunity scoring
- recent bot reply penalty
- short proactive reply mode

---

### 35.5 Personality Drift

风险：

bot 风格漂移。

缓解：

- persona memory
- group procedural memory
- prompt compiler
- response evaluation
- offline test cases
- prompt run logging

---

## 36. 最终形态

最终系统应该是：

```text
bot 看得见每条消息，
但不会回复每条消息。

bot 会记住有用的长期事实，
但不会把每句话当成永久记忆。

bot 知道群边界，
不会跨群泄漏记忆。

bot 理解用户关系，
但不会过度使用私有信息。

bot 有稳定风格，
但会适应当前群气氛。

bot 可以调用工具，
但 deterministic command 仍然可靠。

bot 可以主动参与，
但只在机会足够强时低频参与。

bot 会评估自己的行为，
并逐渐改善未来策略。
```

---

## 37. 总结

TestBot 的核心不是：

```text
LLM + chat history = intelligent bot
```

而是：

```text
LLM
+ long-term memory
+ memory lifecycle
+ group boundary
+ relationship graph
+ conversation state
+ decision engine
+ prompt compiler
+ tool calling
+ response evaluation
+ WebUI admin API
= long-term social agent
```

最高优先级：

```text
1. Memory lifecycle
2. Hybrid recall and reranking
3. Conversation state
4. Prompt compiler
5. WebUI API foundation
6. Opportunity scoring
7. Response evaluation
8. Proactive AI
```

最终目标不是做一个普通聊天机器人。

而是做一个长期存在于群聊中的认知型 Agent。
