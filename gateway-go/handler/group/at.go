package group

import (
	"log"

	"gateway/handler/normalizer"
)

func HandleAt(message normalizer.IncomingMessage) {
	log.Printf("处理@事件: user_id=%d group_id=%d at=%v text=%q", message.UserID, message.GroupID, message.AtUserIDs, message.Text)
	// 后续可在这里判断是否 @ 到机器人账号。
}
