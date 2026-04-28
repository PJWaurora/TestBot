package common

import (
	"log"

	"gateway/client/napcat"
	"gateway/handler/normalizer"
)

func HandleText(message normalizer.IncomingMessage) []napcat.Action {
	log.Printf("文本消息未命中命令，静默处理: user_id=%d group_id=%d text=%q", message.UserID, message.GroupID, message.Text)
	return nil
}
