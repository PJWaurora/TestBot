# Cognitive Agent 分阶段设计

> Language: zh-CN  
> Purpose: 把认知型 Agent 愿景拆成可推进阶段。  
> Status: Phase 1 已完成首版实现；Phase 2-8 是阶段级设计，进入实现前再展开成工程规格。

---

## 总原则

不要把认知型 Agent 一次性做完。每个阶段都必须满足：

- 有明确上游依赖。
- 有非目标，避免 scope 膨胀。
- 能独立上线或通过 feature flag 关闭。
- 有测试和观测口径。
- 不破坏 deterministic command 和外部 module service 的优先级。

阶段顺序：

```text
Phase 1  Memory Quality / Lifecycle
Phase 2  Hybrid Recall
Phase 3  Conversation State
Phase 4  Prompt Compiler
Phase 5  WebUI API Foundation
Phase 6  Tool Calling
Phase 7  Response Evaluation
Phase 8  Proactive AI
```

当前详细规格与 API：

- [Memory Quality Phase 1](memory-quality-phase1.zh-CN.md)
- [Memory Lifecycle API](../api/memory-api.md)

架构愿景：

- [TestBot 认知型群聊 Agent 架构设计](TestBot_Cognitive_Agent_Architecture_zh_CN.md)

---

## Phase 1: Memory Quality / Lifecycle

目标：

> 让 memory 从“能存”升级为“会变”。

状态：

- 首版实现已落地。
- 后续应围绕真实群聊数据调参、补充 contradiction 自动合并策略，再进入 Phase 2。

核心内容：

- `memory_class`
- lifecycle status
- quality score
- weak / confirmed / reinforced / stale / contradicted / archived
- merge / update / contradiction rules
- admin/debug commands
- rollout and tests

完成后应该得到：

- AI 默认只召回 `confirmed / reinforced` memory。
- 管理员能看出一条 memory 为什么存在、为什么被召回、为什么被降级。
- 错误或过期 memory 有归档、降级、contradicted、debug 路径。

---

## Phase 2: Hybrid Recall

目标：

> 让 bot 在正确时间召回正确记忆。

依赖：

- Phase 1 的 lifecycle 和 quality score。
- 现有 message persistence。
- 现有 `memory_embeddings` 表或新的 embedding migration。

核心设计：

```text
Candidate Generation
  -> keyword / FTS
  -> vector similarity
  -> scope and entity matching
  -> recent conversation
  -> relationship hints

Rerank
  -> relevance
  -> quality_score
  -> scope relevance
  -> recency
  -> confidence / importance

Compress
  -> remove duplicates
  -> keep high-priority memory verbatim
  -> summarize low-priority background
```

非目标：

- 不做完整 entity graph。
- 不做主动发言。
- 不让 LLM 决定原始 recall 权限。

最小实现：

- 增加 embedding 写入任务。
- 给 `memory_embeddings` 增加向量索引。
- `recall_context()` 同时取 keyword 和 vector 候选。
- 统一计算 `memory_score`。
- `debug recall` 输出每条候选的 score breakdown。

验收：

- 同一问题能召回语义相近但关键词不同的 memory。
- 当前群/当前用户 memory 排名高于 global/group 泛化 memory。
- `weak / stale / contradicted / archived` 不进入 AI prompt。
- recall 失败时 AI 仍能继续，只是没有 memory context。

---

## Phase 3: Conversation State

目标：

> 让 bot 理解当前群的短期状态，而不是只看单条消息。

依赖：

- Message persistence。
- Phase 1/2 的 memory/recent context 稳定。

核心状态：

```text
group_id
active_topics
mood
conversation_velocity
current_speaker_ids
last_bot_reply_at
bot_reply_count_1h
bot_reply_count_24h
should_avoid_long_reply
updated_at
```

非目标：

- 不做 proactive AI。
- 不做复杂情绪识别模型。
- 不把短期 state 当长期 memory。

最小实现：

- 在 Brain 中新增 conversation state service。
- 每条消息更新轻量 state：
  - 最近 topic keywords
  - 最近发言人集合
  - 消息速度
  - bot 最近是否回复
- AI prompt context 中加入只读 state summary。

验收：

- AI 能知道当前群聊速度和最近 topic。
- 长回复策略能根据 `should_avoid_long_reply` 收敛。
- state 过期后会自然清空或刷新。

---

## Phase 4: Prompt Compiler

目标：

> 让 AI 行为由结构化策略编译，而不是 raw prompt stuffing。

依赖：

- Phase 1 lifecycle。
- Phase 2 recall scoring。
- Phase 3 conversation state。
- 当前 AI Runtime API。

输入：

```text
trigger type
group policy
conversation state
user/profile memory
relationship memory
recalled memories
tool availability
safety boundaries
```

输出：

```json
{
  "reply_mode": "short_technical",
  "tone": "casual_precise",
  "max_chars": 500,
  "memory_ids": [1, 8, 13],
  "tool_policy": "no_tool_needed",
  "avoid": ["不要暴露记忆来源", "不要跨群引用"]
}
```

非目标：

- 不让 LLM 自己选择安全边界。
- 不引入多轮 tool calling。
- 不改 Gateway 协议。

最小实现：

- 新增 `PromptPlan` 数据结构。
- 新增 `compile_prompt_plan(request, recall, state)`。
- AI runtime 从 plan 生成 OpenAI-compatible payload。
- 记录 `prompt_version` 和 plan metadata。

验收：

- prompt 中 trusted instruction 和 untrusted context 明确分离。
- max length、tone、memory subset 可测试。
- 同一输入能稳定生成相同策略结构。

---

## Phase 5: WebUI API Foundation

目标：

> 先提供小而稳定的 Brain 管理 API，供未来 WebUI 使用。

依赖：

- Phase 1 admin/debug service。
- Brain 权限模型明确。

优先 API：

```text
/api/auth/me
/api/memories
/api/memories/{id}
/api/memories/{id}/confirm
/api/memories/{id}/archive
/api/memories/debug/recall
/api/groups/{group_id}/policy
/api/prompt-runs
```

非目标：

- 不做完整前端。
- 不做 OAuth 或复杂账户系统。
- 不直接暴露数据库写入。

最小实现：

- Brain 新增 `/api/*` router。
- 只支持 token/admin 方式。
- 写操作复用 `/memory` 命令背后的 service。
- 写操作记录 audit log。

验收：

- WebUI API 能查看/确认/归档 memory。
- 群管理员只能管理本群数据。
- 全局 admin 才能跨群 debug。
- OpenAPI docs 可读。

---

## Phase 6: Tool Calling

目标：

> 让自然语言 AI 能安全调用已有 deterministic module tool。

依赖：

- 当前 `/tools` 和 `/tools/call` 已可聚合远程模块工具。
- Phase 4 Prompt Compiler。
- 明确 group policy。

优先级规则：

```text
explicit deterministic command
  > memory/admin command
  > AI tool calling
  > normal AI reply
```

非目标：

- 不让 AI 绕过模块权限。
- 不让 tool calling 替代明确命令。
- 不支持无限循环工具调用。

最小实现：

- 给 AI runtime 注入可用 tool schema。
- 只允许 allowlisted tools。
- 单次 AI run 最多一次 tool call。
- tool result 作为 untrusted context 放回最终回答。

验收：

- AI 可以通过自然语言查询天气、Pixiv ranking 等允许工具。
- 被 group policy 禁止的工具不会出现在 AI tool list。
- tool 超时或失败时 AI 给出可读 fallback。

---

## Phase 7: Response Evaluation

目标：

> 让 bot 能从自己的行为中变好。

依赖：

- Phase 4 PromptPlan。
- AI run logging。
- Memory lifecycle 可接收 procedural memory。

数据：

```text
prompt_runs
bot_response_feedback
used_memory_ids
used_tool_names
trigger_type
reply_mode
latency_ms
positive_signal
negative_signal
possible_spam
possible_tone_error
```

非目标：

- 不自动大规模改 persona。
- 不把每个评价都立刻写成长期 memory。
- 不用 evaluator 决定实时回复。

最小实现：

- 每次 AI 回复写 prompt run。
- 从后续消息中提取轻量反馈信号。
- 管理员可查看最近 AI run。
- evaluator 只提出候选 procedural memory，不自动确认。

验收：

- 能追踪一次 AI 回复用了哪些 memory 和 prompt plan。
- 能标记“太长 / 烦 / 记忆错 / 有帮助”。
- 负反馈不会直接污染长期 memory。

---

## Phase 8: Proactive AI

目标：

> 让 bot 低频、克制、可控地参与群聊。

依赖：

- Phase 1-7。
- 特别依赖 conversation state、prompt compiler、evaluation、quota/cooldown。

必要控制：

```text
group allowlist
per-group cooldown
daily quota
quiet hours
random sampling
opportunity scoring
recent bot response suppression
sensitive topic avoidance
max reply length
kill switch
```

非目标：

- 默认不开。
- 不在所有群里自动上线。
- 不让 LLM 单独决定是否发言。

最小实现：

- 只允许测试群。
- 只在高分 opportunity 下触发。
- 每群每天极低 quota。
- 所有 proactive run 写 prompt/evaluation log。
- 一键 disable。

验收：

- 普通群默认完全无 proactive。
- 测试群 proactive 不刷屏。
- negative feedback 会降低后续触发概率。
- quiet hours 和 cooldown 强制生效。

---

## 推荐推进顺序

短期：

1. 实现 Phase 1 schema + lifecycle helper。
2. 实现 Phase 1 recall filtering + debug recall。
3. 实现 Phase 1 admin commands。

中期：

1. Phase 2 Hybrid Recall。
2. Phase 4 Prompt Compiler。
3. Phase 5 最小 WebUI API。

后期：

1. Phase 3 Conversation State。
2. Phase 6 Tool Calling。
3. Phase 7 Response Evaluation。
4. Phase 8 Proactive AI。

注意：Phase 3 和 Phase 4 的顺序可以根据实际体验交换。如果 AI 回复已经开始受 prompt stuffing 影响，应先做 Prompt Compiler；如果 bot 经常误判群状态，应先做 Conversation State。
