package common

import (
	"log"

	"gateway/client/napcat"
	"gateway/handler/normalizer"
)

func HandleVideo(message normalizer.IncomingMessage) []napcat.Action {
	log.Printf("处理视频事件: user_id=%d group_id=%d videos=%+v", message.UserID, message.GroupID, message.Videos)
	// 后续可在这里做视频元信息提取或转发。
	return nil
}
