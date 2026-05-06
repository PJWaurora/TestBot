# Gateway API

This document describes the Go Gateway wire contracts as implemented in
`gateway-go/`. The gateway is intentionally thin: it accepts NapCat WebSocket
events, normalizes message events, asks Brain what to do, and writes NapCat
actions back on the same WebSocket connection.

## Runtime Contract

| Variable | Default | Description |
| --- | --- | --- |
| `GATEWAY_LISTEN_ADDR` | `:808` | HTTP listen address for the WebSocket server. |
| `GATEWAY_WS_PATH` | `/ws` | WebSocket path that NapCat connects to. |
| `BRAIN_BASE_URL` | empty | Enables synchronous Brain `/chat` calls and the Brain outbox poller. If it includes a path, `/chat` and `/outbox/*` are joined under that path. |
| `GATEWAY_BRAIN_TIMEOUT_SECONDS` | `20` | Timeout for synchronous Brain `/chat` requests. Invalid or non-positive values fall back to 20 seconds. |
| `OUTBOX_TOKEN` | empty | Enables authenticated outbox polling when `BRAIN_BASE_URL` is also set. Sent as `Authorization: Bearer <token>`. |

Internal gateway constants:

| Setting | Value | Description |
| --- | --- | --- |
| Worker count | `10` | Number of goroutines dispatching inbound WebSocket messages. |
| Global inbound queue | `1000` | Buffered jobs shared by all sessions. |
| Per-session outbound queue | `100` | Buffered NapCat actions waiting to be written to one WebSocket. |
| WebSocket write deadline | `10s` | Deadline for each `WriteJSON` call. |
| Outbox poll interval | `3s` | Poll cadence while a NapCat WebSocket session is connected. |
| Outbox pull limit | `10` | Items requested per outbox pull. |
| Outbox lease | `30s` | Lease duration requested from Brain. |
| Outbox send timeout | `5s` | Maximum time to enqueue an outbox action for WebSocket writing. |

## WebSocket Endpoint

```text
GET ws://<gateway-host>:808/ws
```

The path and port are configurable through `GATEWAY_WS_PATH` and
`GATEWAY_LISTEN_ADDR`. The upgrader currently accepts any origin and does not
perform gateway-side authentication.

NapCat sends JSON frames containing OneBot/NapCat events. The gateway writes
JSON frames containing NapCat actions. It does not send an application-level
ack for inbound events. NapCat action responses that arrive back on the socket
are ignored because they are not `post_type=message` events.

## Inbound Event Filtering

The gateway processes only message events:

- `post_type` must be `message`.
- `message_type` must be `group` or `private`.
- If `self_id` is non-zero, events where `user_id == self_id` are ignored to
  avoid replying to the bot's own messages.

Malformed JSON, unsupported post types, unsupported message types, self
messages, and non-message action responses are dropped without a WebSocket
reply.

## Inbound Event Shape

The gateway accepts the standard NapCat message shape. Important fields are:

| Field | Type | Description |
| --- | --- | --- |
| `self_id` | number | Bot account ID. Used for self-message filtering. |
| `post_type` | string | Must be `message` to be processed. |
| `message_type` | string | `group` or `private`. |
| `sub_type` | string | Preserved and forwarded to Brain. |
| `message_id` | number | Preserved and forwarded to Brain as a string. |
| `user_id` | number | Sender QQ ID. Also used as the private reply target. |
| `group_id` | number | Group ID for group messages. |
| `group_name` | string | Group display name, when present. |
| `target_id` | number | Preserved for private events, when present. |
| `sender` | object | `user_id`, `nickname`, `card`, and `role`. |
| `message` | array or string | Segment array, or a plain string that is normalized into one text segment. |

Example group text event:

```json
{
  "self_id": 42,
  "post_type": "message",
  "message_type": "group",
  "sub_type": "normal",
  "message_id": 9007199254740993,
  "user_id": 10001,
  "group_id": 20001,
  "group_name": "Test Group",
  "sender": {
    "user_id": 10001,
    "nickname": "Alice",
    "card": "Alice",
    "role": "member"
  },
  "message": [
    {
      "type": "text",
      "data": {
        "text": "hello"
      }
    }
  ]
}
```

## Segment Normalization

The gateway converts NapCat message segments into a normalized Brain envelope.
Large IDs are decoded with `json.Number` and sent to Brain as strings to avoid
JSON number precision loss in downstream runtimes.

| Segment type | Normalized fields |
| --- | --- |
| `text` | Appends `data.text` to `text_segments`; `text` is all text segments joined with no separator. |
| `image` | Appends `{url, file, summary, sub_type, file_size}` to `images`. |
| `json` | Appends `{raw, parsed}` to `json_messages`; `parsed` is set only when `data.data` is valid JSON object text. |
| `video` | Appends `{url, file}` to `videos`. |
| `at` | Appends numeric `data.qq` to `at_user_ids`; `qq="all"` sets `at_all=true`. |
| `reply` | Sets `reply_to_message_id` from `data.id`. |
| Other | Appends the segment type to `unknown_types`. |

Primary type precedence is:

```text
reply -> at -> text -> image -> json -> video -> first unknown type -> meta_or_other
```

## Brain `/chat` Request

When `BRAIN_BASE_URL` is set, every processed message is posted to Brain:

```text
POST <BRAIN_BASE_URL>/chat
Accept: application/json
Content-Type: application/json
```

There is no gateway environment variable for changing the `/chat` endpoint.
Set `BRAIN_BASE_URL` with a path if Brain is mounted under a prefix, for
example `http://brain-python:8000/api` posts to `/api/chat`.

Request body:

| Field | Type | Description |
| --- | --- | --- |
| `self_id` | string | Bot account ID, omitted when zero. |
| `post_type` | string | Usually `message`. |
| `message_type` | string | `group` or `private`. |
| `sub_type` | string | NapCat subtype. |
| `primary_type` | string | Gateway computed primary type. |
| `message_id` | string | Incoming message ID. |
| `user_id` | string | Sender QQ ID. |
| `group_id` | string | Group ID for group messages. |
| `group_name` | string | Group display name. |
| `target_id` | string | Private target ID, when present. |
| `sender` | object | Sender object with string `user_id`. |
| `text` | string | Joined text segments. |
| `text_segments` | array | Individual text segment values. |
| `images` | array | Normalized image objects. |
| `json_messages` | array | Normalized JSON card objects. |
| `videos` | array | Normalized video objects. |
| `at_user_ids` | array | Mentioned user IDs as strings. |
| `at_all` | boolean | Whether the message contains `@all`. |
| `reply_to_message_id` | string | Replied-to message ID. |
| `unknown_types` | array | Unsupported segment types seen in the message. |
| `segments` | array | Original segment list with known ID-like data keys converted to strings. |

Example:

```json
{
  "self_id": "42",
  "post_type": "message",
  "message_type": "group",
  "sub_type": "normal",
  "primary_type": "text",
  "message_id": "9007199254740993",
  "user_id": "10001",
  "group_id": "20001",
  "group_name": "Test Group",
  "sender": {
    "user_id": "10001",
    "nickname": "Alice",
    "card": "Alice",
    "role": "member"
  },
  "text": "hello",
  "text_segments": ["hello"],
  "segments": [
    {
      "type": "text",
      "data": {
        "text": "hello"
      }
    }
  ]
}
```

## Brain `/chat` Response

Expected response body:

| Field | Type | Description |
| --- | --- | --- |
| `handled` | boolean | Whether Brain considered the request. If false, gateway sends no reply and does not fall back to local handlers. |
| `should_reply` | boolean | If false, gateway sends no reply. |
| `messages` | array | Preferred reply payload. When non-empty, this takes priority over `reply`. |
| `reply` | string | Legacy plain text reply used only when `messages` is empty. |
| `tool_calls` | array | Decoded for logging/compatibility, not sent to NapCat by the gateway. |
| `job_id` | string | Optional Brain job identifier for logs. |
| `metadata` | object | Optional Brain metadata for logs. |

If `BRAIN_BASE_URL` is set, Brain owns routing. Brain errors, non-2xx responses,
timeouts, `handled=false`, `should_reply=false`, or unconvertible response
messages all result in no NapCat action.

If `BRAIN_BASE_URL` is not set, the gateway falls through to local handlers.
The current local handlers for text, image, JSON, video, reply, and at messages
are placeholders and return no actions.

## Brain Message Items

`messages` entries use this shape:

| Field | Type | Description |
| --- | --- | --- |
| `type` | string | Message item type. |
| `text` | string | Text content. |
| `content` | string | Text/content fallback. |
| `file` | string | File or URL value for media/file segments. |
| `url` | string | Media URL fallback. |
| `path` | string | Local path fallback. |
| `name` | string | Optional filename or display name. |
| `data` | object | Type-specific fields. |

Supported item types for synchronous Brain responses:

| Item type | NapCat segment/action behavior |
| --- | --- |
| `text` | Text segment. Uses `text`, then `content`, then `data.text`/`data.content`. |
| `image` | Image segment. Uses `file`, then `url`, then `path`; copies selected image options from `data`. |
| `video` | Video segment. Uses `file`, then `url`, then `path`; copies selected video options from `data`. |
| `record` or `audio` | Record segment. Uses `file`, then `url`, then `path`. |
| `file` | File segment. Uses `file`, then `url`, then `path`. |
| `reply` | Reply segment. Requires `data.id` or `data.message_id`; optional `data.seq`/`data.message_seq`. |
| `at` | At segment. Requires `data.qq` or `data.user_id`. |
| `face` | Face segment. Requires `data.id`. |
| `json`, `xml`, `markdown` | Structured segment. Uses `data.data`, `data.content`, or `data.text`. |
| `dice`, `rps` | Segment with copied `data`. |
| `music`, `contact`, `poke`, `mface` | Segment with non-empty copied `data`. |
| `node` | Forward node segment. See forward messages below. |
| `forward` | Forward message wrapper. See forward messages below. |

## NapCat Actions Emitted

For normal Brain `messages`, the gateway sends one NapCat action per item:

```json
{
  "action": "send_group_msg",
  "params": {
    "group_id": 20001,
    "message": [
      {
        "type": "text",
        "data": {
          "text": "hello"
        }
      }
    ]
  }
}
```

Private messages use `send_private_msg`:

```json
{
  "action": "send_private_msg",
  "params": {
    "user_id": 10001,
    "message": [
      {
        "type": "image",
        "data": {
          "file": "https://example.test/card.png"
        }
      }
    ]
  }
}
```

Legacy `reply` responses are sent as a plain string instead of segment arrays:

```json
{
  "action": "send_group_msg",
  "params": {
    "group_id": 20001,
    "message": "plain text reply"
  }
}
```

## Forward Messages

The gateway emits a forward action when either of these is true:

- Brain returns exactly one item with `type="forward"`.
- Brain returns one or more items and every item has `type="node"`.

Group forward action:

```json
{
  "action": "send_group_forward_msg",
  "params": {
    "group_id": 20001,
    "messages": [
      {
        "type": "node",
        "data": {
          "user_id": 10001,
          "nickname": "Alice",
          "content": [
            {
              "type": "text",
              "data": {
                "text": "hello"
              }
            }
          ]
        }
      }
    ],
    "prompt": "optional prompt",
    "summary": "optional summary",
    "source": "optional source"
  }
}
```

Private forward action uses `send_private_forward_msg` with `user_id`.

A `forward` item may carry nodes in `data.nodes`, `data.messages`, or
`data.content`. It may also carry `data.news`, `data.prompt`, `data.summary`,
and `data.source`, which are copied to the forward action.

A `node` item can be either:

- A reference node with `data.id`.
- A content node with nested `data.messages`, `data.content`, `data.message`,
  or item text. Missing `user_id` defaults to `0`; missing `nickname` defaults
  to `TestBot`.

## Brain Outbox Polling

The outbox endpoints are exposed by Brain, not by the gateway. The gateway is
the consumer that pulls items and delivers them to NapCat.

The poller starts only when both `BRAIN_BASE_URL` and `OUTBOX_TOKEN` are set,
and only while a NapCat WebSocket session is connected. It polls once
immediately after connection, then every 3 seconds.

### Pull

```text
POST <BRAIN_BASE_URL>/outbox/pull
Authorization: Bearer <OUTBOX_TOKEN>
Accept: application/json
Content-Type: application/json
```

Request:

```json
{
  "limit": 10,
  "lease_seconds": 30
}
```

Response:

```json
{
  "items": [
    {
      "id": 7,
      "message_type": "group",
      "group_id": "20001",
      "messages": [
        {
          "type": "text",
          "text": "queued"
        }
      ],
      "status": "processing",
      "attempts": 0,
      "max_attempts": 5
    }
  ]
}
```

Outbox target rules:

- `message_type="group"` requires a non-zero numeric `group_id`.
- `message_type="private"` requires a non-zero numeric `user_id`.
- The gateway converts all `messages` in one outbox item into one
  `send_group_msg` or `send_private_msg` action with a multi-segment message.

Brain's current outbox validation accepts only `text`, `image`, and `video`
message items, although the gateway converter can handle more item types.

### Ack

After the action is written successfully to the NapCat WebSocket:

```text
POST <BRAIN_BASE_URL>/outbox/{id}/ack
Authorization: Bearer <OUTBOX_TOKEN>
Content-Type: application/json
```

Request body:

```json
{}
```

### Fail

If the item cannot be converted, queued, or written:

```text
POST <BRAIN_BASE_URL>/outbox/{id}/fail
Authorization: Bearer <OUTBOX_TOKEN>
Content-Type: application/json
```

Request body:

```json
{
  "error": "gateway_write_failed"
}
```

Gateway failure reasons:

| Error | Meaning |
| --- | --- |
| `unsupported_or_invalid_outbox_item` | Target IDs or messages could not be converted to a NapCat action. |
| `gateway_send_queue_timeout` | The per-session outbound queue did not accept the action within 5 seconds. |
| `gateway_connection_closed` | The NapCat WebSocket session closed before delivery completed. |
| `gateway_write_failed` | Writing the action JSON to the WebSocket failed. |

## Operational Notes

- Gateway state is per WebSocket session and in-memory only.
- The gateway does not write to the database and does not call module services
  directly.
- All routing, policy, persistence, memory, AI, module calls, and outbox storage
  belong to Brain.
- Media URLs in image/video/file messages must be reachable from the NapCat
  runtime, because NapCat performs the actual fetch/send operation.
- A successful gateway write means the action was accepted by the WebSocket,
  not that QQ definitely delivered the message.

## Local Development

Run the gateway:

```bash
cd gateway-go
go run .
```

Connect NapCat to:

```text
ws://127.0.0.1:808/ws
```

Run gateway tests:

```bash
cd gateway-go
go test ./...
```
