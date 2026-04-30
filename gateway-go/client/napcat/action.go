package napcat

import (
	"fmt"
	"strconv"
	"strings"
)

type Action struct {
	Action string      `json:"action"`
	Params interface{} `json:"params"`
	Echo   string      `json:"echo,omitempty"`
}

type Response struct {
	Status  string      `json:"status,omitempty"`
	RetCode int         `json:"retcode,omitempty"`
	Data    interface{} `json:"data,omitempty"`
	Message string      `json:"message,omitempty"`
	Wording string      `json:"wording,omitempty"`
	Echo    string      `json:"echo,omitempty"`
}

type SendGroupMessageParams struct {
	GroupID int64       `json:"group_id"`
	Message interface{} `json:"message"`
}

type SendPrivateMessageParams struct {
	UserID  int64       `json:"user_id"`
	Message interface{} `json:"message"`
}

type SendGroupForwardMessageParams struct {
	GroupID  int64                  `json:"group_id"`
	Messages []OneBotMessageSegment `json:"messages"`
	News     []map[string]string    `json:"news,omitempty"`
	Prompt   string                 `json:"prompt,omitempty"`
	Summary  string                 `json:"summary,omitempty"`
	Source   string                 `json:"source,omitempty"`
}

type SendPrivateForwardMessageParams struct {
	UserID   int64                  `json:"user_id"`
	Messages []OneBotMessageSegment `json:"messages"`
	News     []map[string]string    `json:"news,omitempty"`
	Prompt   string                 `json:"prompt,omitempty"`
	Summary  string                 `json:"summary,omitempty"`
	Source   string                 `json:"source,omitempty"`
}

type OneBotMessageSegment struct {
	Type string                 `json:"type"`
	Data map[string]interface{} `json:"data"`
}

type BrainMessageItem struct {
	Type    string                 `json:"type"`
	Text    string                 `json:"text,omitempty"`
	Content string                 `json:"content,omitempty"`
	File    string                 `json:"file,omitempty"`
	URL     string                 `json:"url,omitempty"`
	Path    string                 `json:"path,omitempty"`
	Name    string                 `json:"name,omitempty"`
	Data    map[string]interface{} `json:"data,omitempty"`
}

func NewSendTextAction(messageType string, userID, groupID int64, replyText string) (Action, bool) {
	switch messageType {
	case "group":
		if groupID == 0 {
			return Action{}, false
		}
		return Action{
			Action: "send_group_msg",
			Params: SendGroupMessageParams{
				GroupID: groupID,
				Message: replyText,
			},
		}, true

	case "private":
		if userID == 0 {
			return Action{}, false
		}
		return Action{
			Action: "send_private_msg",
			Params: SendPrivateMessageParams{
				UserID:  userID,
				Message: replyText,
			},
		}, true

	default:
		return Action{}, false
	}
}

func NewTextReplyAction(messageType string, userID, groupID int64, text string) (Action, bool) {
	return NewSendTextAction(messageType, userID, groupID, fmt.Sprintf("收到：%s", text))
}

func NewSendMessageItemsAction(messageType string, userID, groupID int64, items []BrainMessageItem) (Action, bool) {
	segments, ok := BrainMessageItemsToSegments(items)
	if !ok {
		return Action{}, false
	}

	return NewSendRawMessageAction(messageType, userID, groupID, segments)
}

func NewSendRawMessageAction(messageType string, userID, groupID int64, message interface{}) (Action, bool) {
	switch messageType {
	case "group":
		if groupID == 0 {
			return Action{}, false
		}
		return Action{
			Action: "send_group_msg",
			Params: SendGroupMessageParams{
				GroupID: groupID,
				Message: message,
			},
		}, true

	case "private":
		if userID == 0 {
			return Action{}, false
		}
		return Action{
			Action: "send_private_msg",
			Params: SendPrivateMessageParams{
				UserID:  userID,
				Message: message,
			},
		}, true

	default:
		return Action{}, false
	}
}

func NewSendForwardMessageAction(messageType string, userID, groupID int64, items []BrainMessageItem) (Action, bool) {
	segments, options, ok := BrainMessageItemsToForwardSegments(items)
	if !ok || len(segments) == 0 {
		return Action{}, false
	}

	switch messageType {
	case "group":
		if groupID == 0 {
			return Action{}, false
		}
		return Action{
			Action: "send_group_forward_msg",
			Params: SendGroupForwardMessageParams{
				GroupID:  groupID,
				Messages: segments,
				News:     options.News,
				Prompt:   options.Prompt,
				Summary:  options.Summary,
				Source:   options.Source,
			},
		}, true

	case "private":
		if userID == 0 {
			return Action{}, false
		}
		return Action{
			Action: "send_private_forward_msg",
			Params: SendPrivateForwardMessageParams{
				UserID:   userID,
				Messages: segments,
				News:     options.News,
				Prompt:   options.Prompt,
				Summary:  options.Summary,
				Source:   options.Source,
			},
		}, true

	default:
		return Action{}, false
	}
}

type ForwardOptions struct {
	News    []map[string]string
	Prompt  string
	Summary string
	Source  string
}

func BrainMessageItemsToSegments(items []BrainMessageItem) ([]OneBotMessageSegment, bool) {
	if len(items) == 0 {
		return nil, false
	}

	segments := make([]OneBotMessageSegment, 0, len(items))
	for _, item := range items {
		segment, ok := item.toSegment()
		if !ok {
			return nil, false
		}
		segments = append(segments, segment)
	}
	return segments, len(segments) > 0
}

func BrainMessageItemsToForwardSegments(items []BrainMessageItem) ([]OneBotMessageSegment, ForwardOptions, bool) {
	if len(items) == 0 {
		return nil, ForwardOptions{}, false
	}

	var options ForwardOptions
	if len(items) == 1 && itemType(items[0]) == "forward" {
		options = forwardOptionsFromItem(items[0])
		nodes := nodeItemsFromForwardItem(items[0])
		if len(nodes) == 0 {
			return nil, options, false
		}
		items = nodes
	}

	segments := make([]OneBotMessageSegment, 0, len(items))
	for _, item := range items {
		if itemType(item) != "node" {
			return nil, options, false
		}
		segment, ok := item.toNodeSegment()
		if !ok {
			return nil, options, false
		}
		segments = append(segments, segment)
	}
	return segments, options, len(segments) > 0
}

func BrainMessageItemsToCQString(items []BrainMessageItem) (string, bool) {
	var builder strings.Builder

	for _, item := range items {
		itemType := strings.ToLower(strings.TrimSpace(item.Type))
		switch itemType {
		case "text":
			builder.WriteString(cqEscapeText(item.textValue()))
		case "image", "video":
			file := item.fileValue()
			if file == "" {
				return "", false
			}
			builder.WriteString("[CQ:")
			builder.WriteString(itemType)
			builder.WriteString(",file=")
			builder.WriteString(cqEscapeParam(file))
			builder.WriteString("]")
		case "file":
			file := item.fileValue()
			if file == "" {
				return "", false
			}
			builder.WriteString("[CQ:file,file=")
			builder.WriteString(cqEscapeParam(file))
			if name := item.nameValue(); name != "" {
				builder.WriteString(",name=")
				builder.WriteString(cqEscapeParam(name))
			}
			builder.WriteString("]")
		default:
			return "", false
		}
	}

	message := builder.String()
	return message, message != ""
}

func (item BrainMessageItem) toSegment() (OneBotMessageSegment, bool) {
	switch itemType(item) {
	case "text":
		text := item.textValue()
		if text == "" {
			return OneBotMessageSegment{}, false
		}
		return OneBotMessageSegment{Type: "text", Data: map[string]interface{}{"text": text}}, true

	case "image":
		return item.fileSegment("image", "name", "thumb", "summary", "sub_type", "cache", "proxy", "timeout")

	case "video":
		return item.fileSegment("video", "name", "cover", "thumb")

	case "record", "audio":
		return item.fileSegment("record", "name", "magic", "cache", "proxy", "timeout")

	case "file":
		return item.fileSegment("file", "name", "folder")

	case "reply":
		id := item.stringValue("id", "message_id")
		if id == "" {
			return OneBotMessageSegment{}, false
		}
		data := map[string]interface{}{"id": id}
		if seq := item.value("seq", "message_seq"); seq != nil {
			data["seq"] = seq
		}
		return OneBotMessageSegment{Type: "reply", Data: data}, true

	case "at":
		qq := item.stringValue("qq", "user_id")
		if qq == "" {
			return OneBotMessageSegment{}, false
		}
		return OneBotMessageSegment{Type: "at", Data: map[string]interface{}{"qq": qq}}, true

	case "face":
		id := item.value("id")
		if id == nil {
			return OneBotMessageSegment{}, false
		}
		return OneBotMessageSegment{Type: "face", Data: map[string]interface{}{"id": id}}, true

	case "json", "xml", "markdown":
		data := item.stringValue("data", "content", "text")
		if data == "" {
			return OneBotMessageSegment{}, false
		}
		return OneBotMessageSegment{Type: itemType(item), Data: map[string]interface{}{"data": data}}, true

	case "dice", "rps":
		return OneBotMessageSegment{Type: itemType(item), Data: copyMap(item.Data)}, true

	case "music", "contact", "poke", "mface":
		data := copyMap(item.Data)
		if len(data) == 0 {
			return OneBotMessageSegment{}, false
		}
		return OneBotMessageSegment{Type: itemType(item), Data: data}, true

	case "node":
		return item.toNodeSegment()

	default:
		return OneBotMessageSegment{}, false
	}
}

func (item BrainMessageItem) fileSegment(segmentType string, keys ...string) (OneBotMessageSegment, bool) {
	file := item.fileValue()
	if file == "" {
		return OneBotMessageSegment{}, false
	}

	data := copyKeys(item.Data, keys...)
	data["file"] = file
	if item.Name != "" {
		data["name"] = item.Name
	}
	return OneBotMessageSegment{Type: segmentType, Data: data}, true
}

func (item BrainMessageItem) toNodeSegment() (OneBotMessageSegment, bool) {
	data := copyMap(item.Data)
	if id := item.stringValue("id"); id != "" {
		data["id"] = id
		return OneBotMessageSegment{Type: "node", Data: data}, true
	}

	content := nodeContent(item)
	if content == nil {
		return OneBotMessageSegment{}, false
	}
	data["content"] = content

	if userID := item.value("user_id", "uin"); userID != nil {
		data["user_id"] = userID
	} else if _, ok := data["user_id"]; !ok {
		data["user_id"] = int64(0)
	}
	if nickname := item.stringValue("nickname", "name"); nickname != "" {
		data["nickname"] = nickname
	} else if _, ok := data["nickname"]; !ok {
		data["nickname"] = "TestBot"
	}
	return OneBotMessageSegment{Type: "node", Data: data}, true
}

func (item BrainMessageItem) textValue() string {
	if item.Text != "" {
		return item.Text
	}
	if item.Content != "" {
		return item.Content
	}
	return item.stringValue("text", "content")
}

func (item BrainMessageItem) fileValue() string {
	if item.File != "" {
		return item.File
	}
	if item.URL != "" {
		return item.URL
	}
	if item.Path != "" {
		return item.Path
	}
	return item.stringValue("file", "url", "path")
}

func (item BrainMessageItem) nameValue() string {
	if item.Name != "" {
		return item.Name
	}
	return item.stringValue("name")
}

func itemType(item BrainMessageItem) string {
	return strings.ToLower(strings.TrimSpace(item.Type))
}

func (item BrainMessageItem) value(keys ...string) interface{} {
	if item.Data == nil {
		return nil
	}

	for _, key := range keys {
		value, ok := item.Data[key]
		if ok && value != nil {
			return value
		}
	}
	return nil
}

func (item BrainMessageItem) stringValue(keys ...string) string {
	if item.Data == nil {
		return ""
	}

	for _, key := range keys {
		value, ok := item.Data[key]
		if !ok || value == nil {
			continue
		}
		if text := fmt.Sprint(value); text != "" {
			return text
		}
	}

	return ""
}

func copyKeys(in map[string]interface{}, keys ...string) map[string]interface{} {
	out := make(map[string]interface{})
	if len(in) == 0 {
		return out
	}
	for _, key := range keys {
		if value, ok := in[key]; ok && value != nil {
			out[key] = value
		}
	}
	return out
}

func copyMap(in map[string]interface{}) map[string]interface{} {
	if len(in) == 0 {
		return nil
	}

	out := make(map[string]interface{}, len(in))
	for key, value := range in {
		out[key] = value
	}
	return out
}

func nodeContent(item BrainMessageItem) interface{} {
	if messages := brainItemsFromValue(item.value("messages")); len(messages) > 0 {
		if segments, ok := BrainMessageItemsToSegments(messages); ok {
			return segments
		}
	}
	if content := item.value("content", "message"); content != nil {
		return content
	}
	text := item.textValue()
	if text != "" {
		segments, ok := BrainMessageItemsToSegments([]BrainMessageItem{{Type: "text", Text: text}})
		if ok {
			return segments
		}
	}
	return nil
}

func forwardOptionsFromItem(item BrainMessageItem) ForwardOptions {
	return ForwardOptions{
		News:    newsFromValue(item.value("news")),
		Prompt:  item.stringValue("prompt"),
		Summary: item.stringValue("summary"),
		Source:  item.stringValue("source"),
	}
}

func nodeItemsFromForwardItem(item BrainMessageItem) []BrainMessageItem {
	for _, key := range []string{"nodes", "messages", "content"} {
		if items := brainItemsFromValue(item.value(key)); len(items) > 0 {
			return items
		}
	}
	return nil
}

func brainItemsFromValue(value interface{}) []BrainMessageItem {
	switch typed := value.(type) {
	case []BrainMessageItem:
		return typed
	case []interface{}:
		items := make([]BrainMessageItem, 0, len(typed))
		for _, entry := range typed {
			item, ok := brainItemFromValue(entry)
			if !ok {
				return nil
			}
			items = append(items, item)
		}
		return items
	case []map[string]interface{}:
		items := make([]BrainMessageItem, 0, len(typed))
		for _, entry := range typed {
			items = append(items, brainItemFromMap(entry))
		}
		return items
	default:
		return nil
	}
}

func brainItemFromValue(value interface{}) (BrainMessageItem, bool) {
	switch typed := value.(type) {
	case BrainMessageItem:
		return typed, true
	case map[string]interface{}:
		return brainItemFromMap(typed), true
	default:
		return BrainMessageItem{}, false
	}
}

func brainItemFromMap(data map[string]interface{}) BrainMessageItem {
	item := BrainMessageItem{
		Type:    stringFromAny(data["type"]),
		Text:    stringFromAny(data["text"]),
		Content: stringFromAny(data["content"]),
		File:    stringFromAny(data["file"]),
		URL:     stringFromAny(data["url"]),
		Path:    stringFromAny(data["path"]),
		Name:    stringFromAny(data["name"]),
		Data:    copyMapFromAny(data["data"]),
	}
	for key, value := range data {
		switch key {
		case "type", "text", "content", "file", "url", "path", "name", "data":
			continue
		default:
			if item.Data == nil {
				item.Data = make(map[string]interface{})
			}
			item.Data[key] = value
		}
	}
	return item
}

func copyMapFromAny(value interface{}) map[string]interface{} {
	switch typed := value.(type) {
	case map[string]interface{}:
		return copyMap(typed)
	default:
		return nil
	}
}

func stringFromAny(value interface{}) string {
	switch typed := value.(type) {
	case string:
		return typed
	case fmt.Stringer:
		return typed.String()
	case float64:
		if typed == float64(int64(typed)) {
			return strconv.FormatInt(int64(typed), 10)
		}
		return strconv.FormatFloat(typed, 'f', -1, 64)
	case float32:
		return strconv.FormatFloat(float64(typed), 'f', -1, 32)
	case int:
		return strconv.Itoa(typed)
	case int64:
		return strconv.FormatInt(typed, 10)
	case int32:
		return strconv.FormatInt(int64(typed), 10)
	case nil:
		return ""
	default:
		return fmt.Sprint(value)
	}
}

func newsFromValue(value interface{}) []map[string]string {
	switch typed := value.(type) {
	case []map[string]string:
		return typed
	case []interface{}:
		news := make([]map[string]string, 0, len(typed))
		for _, entry := range typed {
			entryMap, ok := entry.(map[string]interface{})
			if !ok {
				continue
			}
			item := make(map[string]string)
			for key, value := range entryMap {
				if text := stringFromAny(value); text != "" {
					item[key] = text
				}
			}
			if len(item) > 0 {
				news = append(news, item)
			}
		}
		return news
	default:
		return nil
	}
}

func cqEscapeText(text string) string {
	replacer := strings.NewReplacer(
		"&", "&amp;",
		"[", "&#91;",
		"]", "&#93;",
	)
	return replacer.Replace(text)
}

func cqEscapeParam(value string) string {
	replacer := strings.NewReplacer(
		"&", "&amp;",
		"[", "&#91;",
		"]", "&#93;",
		",", "&#44;",
	)
	return replacer.Replace(value)
}
