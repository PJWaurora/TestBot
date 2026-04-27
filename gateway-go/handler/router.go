package handler

import (
	"context"
	"log"
	"os"
	"strings"
	"time"

	"gateway/client/brain"
	"gateway/client/napcat"
	"gateway/handler/common"
	"gateway/handler/group"
	"gateway/handler/models"
	"gateway/handler/normalizer"
)

const brainRequestTimeout = 5 * time.Second

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
	message, err := normalizer.NormalizeBytes(data)
	if err != nil {
		log.Printf("解析基础事件失败 (Failed to unmarshal base event): %v", err)
		return nil
	}

	if message.PostType == "meta_event" {
		return nil
	}

	eventType := message.PrimaryType()
	log.Printf(
		"路由分发中... type=%s message_type=%s user_id=%d group_id=%d text=%q",
		eventType,
		message.MessageType,
		message.UserID,
		message.GroupID,
		message.Text,
	)

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
		log.Println("未知事件类型:", eventType)
	}

	return nil
}

func DispatchBrain(message normalizer.IncomingMessage) ([]napcat.Action, bool) {
	baseURL := strings.TrimSpace(os.Getenv("BRAIN_BASE_URL"))
	if baseURL == "" {
		return nil, false
	}

	client, err := brain.NewClient(baseURL, brain.WithTimeout(brainRequestTimeout))
	if err != nil {
		log.Printf("Brain client 配置错误，跳过回复: %v", err)
		return nil, true
	}

	ctx, cancel := context.WithTimeout(context.Background(), brainRequestTimeout)
	defer cancel()

	response, err := client.PostMessage(ctx, message)
	if err != nil {
		log.Printf("Brain 请求失败，跳过回复: %v", err)
		return nil, true
	}
	if response == nil || !response.Handled {
		return nil, false
	}
	if !response.ShouldReply {
		return nil, true
	}

	actions := BrainResponseActions(message, response)
	if len(actions) == 0 {
		log.Printf("Brain 已处理但未生成可发送 action")
	}
	return actions, true
}

func BrainResponseActions(message normalizer.IncomingMessage, response *brain.Response) []napcat.Action {
	if response == nil {
		return nil
	}

	if len(response.Messages) > 0 {
		action, ok := napcat.NewSendMessageItemsAction(
			message.MessageType,
			message.UserID,
			message.GroupID,
			brainMessagesToNapcatItems(response.Messages),
		)
		if !ok {
			return nil
		}
		return []napcat.Action{action}
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
