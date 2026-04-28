package group

import (
	"gateway/client/napcat"
	"gateway/handler/normalizer"
)

func HandleReply(message normalizer.IncomingMessage) []napcat.Action {
	// 后续可在这里读取被回复消息上下文。
	return nil
}
