# Conversation State Phase 3 实施规格

> Version: 0.1  
> Status: Phase 3 first implementation landed  
> Owner: Brain / AI Runtime  
> Scope: 让 AI 使用短期会话状态，而不是只看单条消息和长期 memory。

## 目标

Phase 3 把 Brain 的短期群聊状态落成可测试、可降级、可维护的工程模块。

首版只解决三件事：

- [x] 每条持久化消息后更新轻量 conversation state。
- [x] 每次 bot 回复后更新最近回复时间和回复计数。
- [x] AI prompt 中加入只读 state summary，指导模型理解当前群聊速度、话题和回复长度策略。

## 非目标

- 不做 proactive AI。
- 不引入复杂情绪识别模型。
- 不把短期 state 写入长期 memory。
- 不做 prompt compiler；Phase 4 再把 state、memory、tool policy 编译为结构化 prompt plan。

## 数据模型

新增 migration：

```text
database/migrations/000007_conversation_state.up.sql
database/migrations/000007_conversation_state.down.sql
```

核心表：

```text
conversation_states
  conversation_id BIGINT PRIMARY KEY REFERENCES conversations(id)
  active_topics JSONB
  mood TEXT
  conversation_velocity TEXT
  current_speaker_ids JSONB
  last_bot_reply_at TIMESTAMPTZ
  bot_reply_count_1h INTEGER
  bot_reply_count_24h INTEGER
  should_avoid_long_reply BOOLEAN
  metadata JSONB
  updated_at TIMESTAMPTZ
```

`conversation_id` 复用现有 `conversations` 表，因此 group/private conversation 都能支持。

## Runtime 位置

Phase 3 不修改主路由优先级。

```text
Brain POST /chat
  -> safe_persist_incoming()
       -> conversation_state.update_from_message()
  -> routing / modules / AI
  -> safe_persist_response()
       -> conversation_state.update_from_bot_response()
```

AI runtime 在构造 prompt 前读取：

```text
conversation_state.read_for_request(request)
```

读取失败必须降级为空 state，不影响 AI 回复。

## 状态派生规则

首版使用确定性规则，避免引入新的 LLM 调用：

| 字段 | 首版规则 |
| --- | --- |
| `active_topics` | 从最近消息文本抽取 bounded keyword，去停用词，按频次排序。 |
| `current_speaker_ids` | 最近窗口内去重 speaker id，限制数量。 |
| `conversation_velocity` | 最近 10 分钟消息数分桶：`quiet`、`normal`、`active`、`burst`。 |
| `mood` | 默认 `neutral`。 |
| `bot_reply_count_1h` | 最近 1 小时 bot response 数。 |
| `bot_reply_count_24h` | 最近 24 小时 bot response 数。 |
| `should_avoid_long_reply` | 高速群聊、多发言人、或 bot 刚回复过时为 true。 |

## AI Prompt 集成

Conversation state 放入现有 non-instruction context：

```text
当前群聊状态：
- velocity: active
- active_topics: pixiv, 天气
- current_speaker_count: 4
- bot_reply_count_1h: 3
- should_avoid_long_reply: true
- reply_guidance: 当前群聊较快，优先短回复。
```

这些内容仍然是 `user` role 的引用上下文，不是 system instruction。system prompt 继续负责安全边界。

## 失败策略

| 失败点 | 行为 |
| --- | --- |
| `DATABASE_URL` 为空 | 不更新、不读取 state。 |
| migration 未跑 | 记录 warning，聊天继续。 |
| state 更新失败 | 持久化 wrapper 吞掉异常，聊天继续。 |
| state 读取失败 | AI prompt 不带 state，AI 继续。 |

## 首版落地文件

```text
brain-python/services/conversation_state.py
brain-python/services/persistence.py
brain-python/services/ai_runtime.py
brain-python/tests/test_conversation_state.py
brain-python/tests/test_ai_runtime.py
database/migrations/000007_conversation_state.up.sql
database/migrations/000007_conversation_state.down.sql
```

## 验收

- [x] `/chat` 后 `conversation_states` 能生成或更新当前 conversation 的 state。
- [x] AI prompt 包含当前群聊状态。
- [x] 高速消息或多发言人时 `should_avoid_long_reply=true`。
- [x] 缺失数据库或缺失 state table 不影响 Brain 回复。
- [x] 单元测试覆盖 state 派生、prompt 集成和 fail-soft 行为。

## 后续

- Phase 4 Prompt Compiler 应消费 conversation state，而不是继续在 AI runtime 中拼接策略。
- 如果后续加入 WebUI，可以暴露只读 state 查看 API。
- 如果后续加入 proactive AI，必须基于 state 增加 quota/cooldown，不能只看最近消息。
