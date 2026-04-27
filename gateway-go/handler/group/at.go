package group

import (
	"log"

	"gateway/client/napcat"
	"gateway/handler/normalizer"
)

func HandleAt(message normalizer.IncomingMessage) []napcat.Action {
	log.Printf("处理@事件: user_id=%d group_id=%d at=%v at_all=%t text=%q", message.UserID, message.GroupID, message.AtUserIDs, message.AtAll, message.Text)
	// 后续可在这里判断是否 @ 到机器人账号。
	return nil
}
