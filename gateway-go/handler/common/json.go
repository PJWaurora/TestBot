package common

import (
	"log"

	"gateway/handler/normalizer"
)

func HandleJson(message normalizer.IncomingMessage) {
	log.Printf("处理JSON事件: user_id=%d group_id=%d json_count=%d", message.UserID, message.GroupID, len(message.JSONMessages))
	// 后续可在这里提取小程序卡片、分享链接等结构化信息。
}
