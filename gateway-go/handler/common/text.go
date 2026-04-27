package common

import (
	"log"

	"gateway/handler/normalizer"
)

func HandleText(message normalizer.IncomingMessage) {
	log.Printf("处理文本消息: user_id=%d group_id=%d text=%q", message.UserID, message.GroupID, message.Text)
	// 后续可在这里转发给 Python Brain，或先实现规则回复。
}
