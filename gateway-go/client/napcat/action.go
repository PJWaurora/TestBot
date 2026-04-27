package napcat

import (
	"fmt"
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
	GroupID int64  `json:"group_id"`
	Message string `json:"message"`
}

type SendPrivateMessageParams struct {
	UserID  int64  `json:"user_id"`
	Message string `json:"message"`
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
	message, ok := BrainMessageItemsToCQString(items)
	if !ok {
		return Action{}, false
	}

	return NewSendTextAction(messageType, userID, groupID, message)
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
