package common

import (
	"gateway/client/napcat"
	"gateway/handler/normalizer"
)

func HandleVideo(message normalizer.IncomingMessage) []napcat.Action {
	// 后续可在这里做视频元信息提取或转发。
	return nil
}
