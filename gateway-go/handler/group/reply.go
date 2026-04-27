package group

import (
	"log"

	"gateway/client/napcat"
	"gateway/handler/normalizer"
)

func HandleReply(message normalizer.IncomingMessage) []napcat.Action {
	log.Printf("处理回复事件: user_id=%d group_id=%d reply_to=%d text=%q", message.UserID, message.GroupID, message.ReplyToMessageID, message.Text)
	// 后续可在这里读取被回复消息上下文。
	return nil
}
