package common

import (
	"gateway/client/napcat"
	"gateway/handler/normalizer"
)

func HandleJson(message normalizer.IncomingMessage) []napcat.Action {
	// 后续可在这里提取小程序卡片、分享链接等结构化信息。
	return nil
}
