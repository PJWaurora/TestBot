# AI 模块使用指南

> 当前状态：AI 模块已接入 Brain `/chat` 路由，但默认关闭。  
> 维护建议：以后改 AI 触发、prompt、memory recall、tool calling 或上游模型配置时，同步更新本文。

## 1. AI 模块是什么

TestBot 的 AI 模块不是独立 HTTP 服务，也没有单独的 `/ai` HTTP route。它是 Brain 的一个路由阶段，代码入口在：

```text
brain-python/services/ai_runtime.py
```

外部消息仍然走统一链路：

```text
QQ / NapCat
  -> Gateway
  -> Brain POST /chat
  -> memory 管理命令
  -> deterministic modules
  -> remote module services
  -> fake echo planner
  -> AI runtime
  -> no_route
```

所以 AI 只在前面的确定性命令和模块都没有处理时才会被尝试。天气、Pixiv、Bilibili、TSPerson、memory 管理命令等仍然优先于 AI。

## 2. 最小启用配置

在 `brain-python/.env` 中配置：

```env
AI_ENABLED=true
AI_BASE_URL=https://your-openai-compatible-endpoint
AI_API_KEY=your-api-key
AI_MODEL=your-model-name
```

`AI_BASE_URL` 支持三种写法：

| 配置值 | Brain 最终请求 |
| --- | --- |
| `https://llm.example` | `https://llm.example/v1/chat/completions` |
| `https://llm.example/v1` | `https://llm.example/v1/chat/completions` |
| `https://llm.example/v1/chat/completions` | 原样使用 |

如果 `AI_API_KEY` 为空，Brain 不发送 `Authorization` header，适合本地无鉴权兼容服务。

## 3. 常用环境变量

| 变量 | 默认值 | 作用 |
| --- | --- | --- |
| `AI_ENABLED` | `false` | 是否启用 AI runtime。 |
| `AI_BASE_URL` | 空 | OpenAI-compatible 服务地址。 |
| `AI_API_KEY` | 空 | 上游 API key。为空时不发送鉴权 header。 |
| `AI_MODEL` | 空 | 上游模型名。 |
| `AI_TIMEOUT` | `20` | 上游请求超时时间，单位秒。 |
| `AI_TEMPERATURE` | `0.7` | 模型采样温度。 |
| `AI_MAX_TOKENS` | `800` | 单次回复最大 token 数。 |
| `AI_SYSTEM_PROMPT` | 内置中文 prompt | 覆盖默认角色 prompt。Brain 会额外追加安全 prompt。 |
| `AI_COMMAND_ALIASES` | `ai,chat,聊天` | 用户命令别名，支持逗号、分号或空白分隔。 |
| `AI_GROUP_ALLOWLIST` | 空 | 非空时，只允许这些群使用 AI。 |
| `AI_GROUP_BLOCKLIST` | 空 | 禁止这些群使用 AI，优先级高于 allowlist。 |
| `AI_MENTION_TRIGGER_ENABLED` | `true` | 是否允许 @bot 触发 AI。 |
| `AI_REPLY_TRIGGER_ENABLED` | `false` | 是否允许回复 bot 消息触发 AI。 |
| `AI_PROACTIVE_ENABLED` | `false` | 当前没有 proactive scheduler，只是预留配置。 |

## 4. 用户如何触发 AI

### 4.1 命令触发

默认支持：

```text
/ai 你记得我喜欢什么吗？
/chat 帮我总结一下刚才讨论的内容
/聊天 今天适合做什么？
```

命令前缀由共享命令解析器处理，通常支持 `/` 和 `.`。命令触发时，Brain 会去掉命令名，只把参数发送给模型：

```text
/ai 你记得我喜欢什么吗？
```

发送给模型的 user message 是：

```text
你记得我喜欢什么吗？
```

如果命令没有参数，例如：

```text
/ai
```

Brain 会使用：

```text
继续。
```

### 4.2 @bot 触发

当 `AI_MENTION_TRIGGER_ENABLED=true` 且 Gateway 传入的 `ChatRequest.self_id` 出现在 `at_user_ids` 中时，AI 会被触发。

示例输入：

```json
{
  "self_id": "42",
  "text": "帮我总结一下刚才说了什么",
  "message_type": "group",
  "group_id": "613689332",
  "user_id": "854271190",
  "at_user_ids": ["42"]
}
```

@bot 触发会保留完整文本作为 user message。

### 4.3 回复触发

默认关闭。开启：

```env
AI_REPLY_TRIGGER_ENABLED=true
```

当消息带有 `reply_to_message_id` 时，AI 才会被尝试。建议只在需要更强连续对话体验时开启，否则群聊中普通回复容易误触发。

## 5. Brain 返回什么

AI 成功时返回普通 `BrainResponse`：

```json
{
  "handled": true,
  "should_reply": true,
  "reply": "你之前提过喜欢南京天气和 Pixiv。",
  "messages": [
    {
      "type": "text",
      "text": "你之前提过喜欢南京天气和 Pixiv。"
    }
  ],
  "metadata": {
    "module": "ai",
    "model": "test-model",
    "trigger": "command",
    "memory_count": 1,
    "recent_message_count": 1,
    "prompt_version": "ai-memory-v1"
  }
}
```

Gateway 只需要按普通 Brain 回复处理 `messages`，不需要知道这是 AI 回复。

## 6. 上游请求格式

Brain 调用 OpenAI-compatible chat completions：

```http
POST <AI_BASE_URL>/v1/chat/completions
Content-Type: application/json
Authorization: Bearer <AI_API_KEY>
```

请求体结构：

```json
{
  "model": "test-model",
  "messages": [
    {
      "role": "system",
      "content": "<AI_SYSTEM_PROMPT + Brain 内置安全 prompt>"
    },
    {
      "role": "user",
      "content": "<当前群/用户信息、近期聊天、长期记忆组成的非指令上下文>"
    },
    {
      "role": "user",
      "content": "用户实际问题"
    }
  ],
  "temperature": 0.7,
  "max_tokens": 800
}
```

Brain 支持解析这些上游返回：

```json
{"choices":[{"message":{"content":"hello"}}]}
```

```json
{"choices":[{"message":{"content":[{"type":"text","text":"hello"}]}}]}
```

```json
{"choices":[{"text":"hello"}]}
```

## 7. AI 如何使用 memory

AI runtime 在请求模型前调用：

```text
memory_service.recall_context(request, user_text)
```

返回的 context 可能包含：

| 字段 | 含义 |
| --- | --- |
| `recent_messages` | 当前会话附近的近期聊天。Brain 最多放入最新 20 条。 |
| `memories` | 长期记忆片段。Brain 会按 memory service 的 recall 结果放入 prompt。 |

这些内容会被放进第二个 `user` message，并明确标记为“非指令上下文”。也就是说，memory 和近期聊天只能作为事实参考，不应该覆盖 system prompt。

当前长期记忆默认只召回可靠生命周期状态：

```text
status = active
lifecycle_status IN (confirmed, reinforced)
```

`weak`、`stale`、`contradicted`、`archived` 默认不进入 AI prompt。它们仍然可以被管理员 search/debug。

如果 Phase 2 vector recall 已启用，memory service 会把 keyword、FTS、embedding candidates 合并后 rerank。AI runtime 本身不直接调用 embedding endpoint，只消费 memory service 返回的最终 context。

## 7.1 AI 如何使用 conversation state

Phase 3 启用后，Brain 会从 `conversation_states` 读取当前会话的短期状态，并把它放进同一个“非指令上下文”。

状态可能包含：

| 字段 | 含义 |
| --- | --- |
| `conversation_velocity` | 当前聊天速度：`quiet`、`normal`、`active`、`burst`。 |
| `active_topics` | 最近消息中的轻量话题关键词。 |
| `current_speaker_ids` | 最近参与发言的人。 |
| `bot_reply_count_1h` | 最近 1 小时 bot 回复次数。 |
| `bot_reply_count_24h` | 最近 24 小时 bot 回复次数。 |
| `should_avoid_long_reply` | 是否建议 AI 优先短回复。 |

如果 state 不存在或读取失败，AI 会继续回复，只是不带这段短期状态。

## 8. 常见配置组合

### 8.1 只允许命令触发

```env
AI_ENABLED=true
AI_MENTION_TRIGGER_ENABLED=false
AI_REPLY_TRIGGER_ENABLED=false
AI_COMMAND_ALIASES=ai,chat,聊天
```

适合早期测试。用户必须显式输入 `/ai`、`/chat` 或 `/聊天`。

### 8.2 指定群启用

```env
AI_ENABLED=true
AI_GROUP_ALLOWLIST=613689332,123456789
```

只有 allowlist 里的群可以触发 AI。

### 8.3 禁止某些群

```env
AI_ENABLED=true
AI_GROUP_BLOCKLIST=111111111,222222222
```

blocklist 优先级高于 allowlist。

### 8.4 开启 memory + embedding recall

基础 memory：

```env
MEMORY_ENABLED=true
DATABASE_URL=postgres://testbot:password@localhost:5432/testbot?sslmode=disable
MEMORY_RECALL_LIFECYCLE_FILTER_ENABLED=true
```

embedding 写入与向量召回：

```env
MEMORY_EMBEDDING_ENABLED=true
MEMORY_EMBEDDING_BASE_URL=https://your-openai-compatible-endpoint
MEMORY_EMBEDDING_API_KEY=your-api-key
MEMORY_EMBEDDING_MODEL=your-embedding-model
MEMORY_EMBEDDING_DIMENSIONS=1536
MEMORY_VECTOR_RECALL_ENABLED=true
```

初始化或补齐 embedding：

```text
/memory embedding status
/memory embedding index 100
```

## 9. 错误行为

| 场景 | 命令触发 | @bot / reply 触发 |
| --- | --- | --- |
| `AI_ENABLED=false` | 回复 `AI 当前未启用。` | 静默跳过 AI |
| 当前群被策略拒绝 | 回复 `AI 未在当前群启用。` | 静默跳过 AI |
| 缺少 `AI_BASE_URL` 或 `AI_MODEL` | 回复配置缺失信息 | 静默跳过 AI，并写 warning log |
| 上游请求失败 | 回复 `AI 暂时不可用。` | 静默跳过 AI |
| 上游空回复 | `handled=true`，但 `should_reply=false` | 同左 |
| memory recall 失败 | AI 继续，只是不带 memory context | 同左 |

这种设计让显式命令有可见错误，隐式触发不会在群里刷错误消息。

## 10. 调试方式

### 10.1 看 Brain 日志

Brain 会记录路由阶段和结果：

```text
Brain 路由结果: stage=ai handled=true should_reply=true module=ai ...
```

如果没有进入 AI，先检查日志中是否已经被 memory、deterministic module、remote module 或 fake planner 处理。

### 10.2 检查配置

最常见问题：

```text
AI_ENABLED=false
AI_BASE_URL 为空
AI_MODEL 为空
AI_GROUP_ALLOWLIST 不包含当前 group_id
AI_GROUP_BLOCKLIST 包含当前 group_id
```

### 10.3 检查 memory recall

```text
/memory debug recall 用户的问题
/memory embedding status
```

如果 debug recall 有结果但 AI 回复没体现，优先检查：

- memory 是否处于 `confirmed` 或 `reinforced`。
- `MEMORY_RECALL_LIFECYCLE_FILTER_ENABLED` 是否符合预期。
- prompt 中 memory 数量是否被 `MEMORY_RECALL_FINAL_LIMIT` 限制。
- 上游模型是否遵守上下文。

## 11. 修改 AI 模块时要同步更新哪里

| 改动类型 | 需要更新 |
| --- | --- |
| 新增/删除 AI env | 本文第 3 节、`brain-python/.env.example`、[AI Runtime API](ai-runtime-api.md)。 |
| 改触发规则 | 本文第 4 节、[AI Runtime API](ai-runtime-api.md)、相关测试。 |
| 改上游 payload | 本文第 6 节、[AI Runtime API](ai-runtime-api.md)、`brain-python/tests/test_ai_runtime.py`。 |
| 改 memory prompt 行为 | 本文第 7 节、[Memory Lifecycle API](memory-api.md)、相关 memory tests。 |
| 接入 AI tool calling | 本文新增 tool calling 章节、[Brain API](brain-api.md)、[Module Service API](module-service-api.md)。 |
| 改错误行为 | 本文第 9 节、[AI Runtime API](ai-runtime-api.md)、测试断言。 |

## 12. 相关文档

- [AI Runtime API](ai-runtime-api.md)
- [Brain API](brain-api.md)
- [Memory Lifecycle API](memory-api.md)
- [Database Schema](database-schema.md)
- [Hybrid Recall Phase 2 实施规格](../development/hybrid-recall-phase2.zh-CN.md)
- [AI 与记忆整体设计计划](../overview/ai-memory-plan.zh-CN.md)
