package handler

import (
	"encoding/json"
	"gateway/handler/common"
	"gateway/handler/group"
	"gateway/handler/models"
	"log"
)

type BaseEvent = models.BaseEvent
type BaseVideoEvent = models.BaseVideoEvent
type BaseTextEvent = models.BaseTextEvent
type BaseImageEvent = models.BaseImageEvent
type BaseJsonEvent = models.BaseJsonEvent
type BaseReplyEvent = models.BaseReplyEvent
type BaseAtEvent = models.BaseAtEvent

func GetEventType(event BaseEvent) string {
	// 1. 先判断是否有消息段
	if len(event.Message) == 0 {
		// 如果没有消息内容，可能是心跳或系统通知
		return "meta_or_other"
	}
	// 2. 只有长度 > 0 时才安全访问 [0]
	return event.Message[0].Type
}

// 确保首字母大写！
func Dispatch(data []byte) {
	var temp BaseEvent
	if err := json.Unmarshal(data, &temp); err != nil {
		log.Printf("解析基础事件失败 (Failed to unmarshal base event): %v", err)
		return
	}

	if temp.PostType == "meta_event" {
		// 如果你连日志都不想看，直接 return
		// 如果想保留一个简单的记录，可以写 log.Println("收到心跳，已忽略")
		return
	}

	eventType := GetEventType(temp)
	log.Println("路由分发中...", eventType)

	switch eventType {
	case "text":
		var textEvent BaseTextEvent
		if err := json.Unmarshal(data, &textEvent); err != nil {
			log.Printf("解析文本事件失败 (Failed to unmarshal text event): %v", err)
			return
		}
		common.HandleText(textEvent)

	case "image":
		var imageEvent BaseImageEvent
		if err := json.Unmarshal(data, &imageEvent); err != nil {
			log.Printf("解析图片事件失败 (Failed to unmarshal image event): %v", err)
			return
		}
		common.HandleImage(imageEvent)

	case "json":
		var jsonEvent BaseJsonEvent
		if err := json.Unmarshal(data, &jsonEvent); err != nil {
			log.Printf("解析JSON事件失败 (Failed to unmarshal json event): %v", err)
			return
		}
		common.HandleJson(jsonEvent)

	case "video":
		var videoEvent BaseVideoEvent
		if err := json.Unmarshal(data, &videoEvent); err != nil {
			log.Printf("解析视频事件失败 (Failed to unmarshal video event): %v", err)
			return
		}
		common.HandleVideo(videoEvent)

	case "reply":
		var replyEvent BaseReplyEvent
		if err := json.Unmarshal(data, &replyEvent); err != nil {
			log.Printf("解析回复事件失败 (Failed to unmarshal reply event): %v", err)
			return
		}
		group.HandleReply(replyEvent)
	case "at":
		var atEvent BaseAtEvent
		if err := json.Unmarshal(data, &atEvent); err != nil {
			log.Printf("解析@事件失败 (Failed to unmarshal at event): %v", err)
			return
		}
		group.HandleAt(atEvent)

	default:
		log.Println("未知事件类型:", eventType)
	}

}
