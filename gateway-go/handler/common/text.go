package common

import (
	"log"

	"gateway/client/napcat"
	"gateway/handler/normalizer"
)

func HandleText(message normalizer.IncomingMessage) []napcat.Action {
	log.Printf("处理文本消息: user_id=%d group_id=%d text=%q", message.UserID, message.GroupID, message.Text)

	action, ok := napcat.NewTextReplyAction(message.MessageType, message.UserID, message.GroupID, message.Text)
	if !ok {
		log.Printf("无法生成文本回复 action: message_type=%q user_id=%d group_id=%d", message.MessageType, message.UserID, message.GroupID)
		return nil
	}

	return []napcat.Action{action}
}
