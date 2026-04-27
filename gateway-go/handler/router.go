package handler

import (
	"log"

	"gateway/client/napcat"
	"gateway/handler/common"
	"gateway/handler/group"
	"gateway/handler/models"
	"gateway/handler/normalizer"
)

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
