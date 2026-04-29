package handler

import (
	"context"
	"encoding/json"
	"log"
	"os"
	"strconv"
	"strings"
	"time"

	"gateway/client/brain"
	"gateway/client/napcat"
	"gateway/handler/common"
	"gateway/handler/group"
	"gateway/handler/models"
	"gateway/handler/normalizer"
)

const defaultBrainRequestTimeout = 20 * time.Second

type BaseEvent = models.BaseEvent
type BaseVideoEvent = models.BaseVideoEvent
type BaseTextEvent = models.BaseTextEvent
type BaseImageEvent = models.BaseImageEvent
type BaseJsonEvent = models.BaseJsonEvent
type BaseReplyEvent = models.BaseReplyEvent
type BaseAtEvent = models.BaseAtEvent

func GetEventType(event BaseEvent) string {
	return normalizer.NormalizeEvent(event).PrimaryType()
}

func Dispatch(data []byte) []napcat.Action {
	if ignore, err := ignoreBeforeNormalize(data); err == nil && ignore {
		return nil
	}

	message, err := normalizer.NormalizeBytes(data)
	if err != nil {
		log.Printf("解析基础事件失败 (Failed to unmarshal base event): %v", err)
		return nil
	}

	if message.PostType != "message" {
		return nil
	}
	if message.MessageType != "group" && message.MessageType != "private" {
		return nil
	}
	if message.SelfID != 0 && message.UserID == message.SelfID {
		return nil
	}

	eventType := message.PrimaryType()
	if actions, handled := DispatchBrain(message); handled {
		return actions
	}

	switch eventType {
	case "text":
		return common.HandleText(message)

	case "image":
		return common.HandleImage(message)

	case "json":
		return common.HandleJson(message)

	case "video":
		return common.HandleVideo(message)

	case "reply":
		return group.HandleReply(message)
	case "at":
		return group.HandleAt(message)

	default:
		return nil
	}

	return nil
}

type dispatchEnvelope struct {
	PostType    string `json:"post_type"`
	MessageType string `json:"message_type"`
	SelfID      int64  `json:"self_id"`
	UserID      int64  `json:"user_id"`
}

func ignoreBeforeNormalize(data []byte) (bool, error) {
	var envelope dispatchEnvelope
	if err := json.Unmarshal(data, &envelope); err != nil {
		return false, err
	}
	if envelope.PostType != "message" {
		return true, nil
	}
	if envelope.MessageType != "group" && envelope.MessageType != "private" {
		return true, nil
	}
	if envelope.SelfID != 0 && envelope.UserID == envelope.SelfID {
		return true, nil
	}
	return false, nil
}

func DispatchBrain(message normalizer.IncomingMessage) ([]napcat.Action, bool) {
	baseURL := strings.TrimSpace(os.Getenv("BRAIN_BASE_URL"))
	if baseURL == "" {
		return nil, false
	}

	timeout := brainRequestTimeout()
	client, err := brain.NewClient(baseURL, brain.WithTimeout(timeout))
	if err != nil {
		log.Printf("Brain client 配置错误，跳过回复: %v", err)
		return nil, true
	}

	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()

	response, err := client.PostMessage(ctx, message)
	if err != nil {
		log.Printf("Brain 请求失败，跳过回复: %v", err)
		return nil, true
	}
	if response == nil || !response.Handled {
		return nil, true
	}
	if !response.ShouldReply {
		return nil, true
	}

	actions := BrainResponseActions(message, response)
	if len(actions) == 0 {
		log.Printf("Brain 已处理但未生成可发送 action")
		return nil, true
	}
	log.Printf(
		"Brain 触发回复: type=%s message_type=%s user_id=%d group_id=%d actions=%d messages=%d reply_len=%d",
		message.PrimaryType(),
		message.MessageType,
		message.UserID,
		message.GroupID,
		len(actions),
		len(response.Messages),
		len(response.Reply),
	)
	return actions, true
}

func brainRequestTimeout() time.Duration {
	raw := strings.TrimSpace(os.Getenv("GATEWAY_BRAIN_TIMEOUT_SECONDS"))
	if raw == "" {
		return defaultBrainRequestTimeout
	}

	seconds, err := strconv.ParseFloat(raw, 64)
	if err != nil || seconds <= 0 {
		log.Printf("GATEWAY_BRAIN_TIMEOUT_SECONDS=%q 无效，使用默认 %s", raw, defaultBrainRequestTimeout)
		return defaultBrainRequestTimeout
	}
	return time.Duration(seconds * float64(time.Second))
}

func BrainResponseActions(message normalizer.IncomingMessage, response *brain.Response) []napcat.Action {
	if response == nil {
		return nil
	}

	if len(response.Messages) > 0 {
		actions := brainMessagesToNapcatActions(message, response.Messages)
		if len(actions) == 0 {
			return nil
		}
		return actions
	}

	if response.Reply == "" {
		return nil
	}
	action, ok := napcat.NewSendTextAction(message.MessageType, message.UserID, message.GroupID, response.Reply)
	if !ok {
		return nil
	}
	return []napcat.Action{action}
}

func brainMessagesToNapcatItems(messages []brain.Message) []napcat.BrainMessageItem {
	if len(messages) == 0 {
		return nil
	}

	items := make([]napcat.BrainMessageItem, 0, len(messages))
	for _, message := range messages {
		items = append(items, napcat.BrainMessageItem{
			Type:    message.Type,
			Text:    message.Text,
			Content: message.Content,
			File:    message.File,
			URL:     message.URL,
			Path:    message.Path,
			Name:    message.Name,
			Data:    message.Data,
		})
	}
	return items
}

func brainMessagesToNapcatActions(message normalizer.IncomingMessage, messages []brain.Message) []napcat.Action {
	if len(messages) == 0 {
		return nil
	}

	actions := make([]napcat.Action, 0, len(messages))
	for _, item := range brainMessagesToNapcatItems(messages) {
		action, ok := napcat.NewSendMessageItemsAction(
			message.MessageType,
			message.UserID,
			message.GroupID,
			[]napcat.BrainMessageItem{item},
		)
		if !ok {
			return nil
		}
		actions = append(actions, action)
	}
	return actions
}

func OutboxAction(item brain.OutboxItem) (napcat.Action, bool) {
	userID, ok := parseOutboxID(item.UserID)
	if !ok && item.MessageType == "private" {
		return napcat.Action{}, false
	}
	groupID, ok := parseOutboxID(item.GroupID)
	if !ok && item.MessageType == "group" {
		return napcat.Action{}, false
	}

	return napcat.NewSendMessageItemsAction(
		item.MessageType,
		userID,
		groupID,
		brainMessagesToNapcatItems(item.Messages),
	)
}

func parseOutboxID(value string) (int64, bool) {
	text := strings.TrimSpace(value)
	if text == "" {
		return 0, false
	}
	id, err := strconv.ParseInt(text, 10, 64)
	if err != nil || id == 0 {
		return 0, false
	}
	return id, true
}
