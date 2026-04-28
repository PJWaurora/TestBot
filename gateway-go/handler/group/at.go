package group

import (
	"gateway/client/napcat"
	"gateway/handler/normalizer"
)

func HandleAt(message normalizer.IncomingMessage) []napcat.Action {
	// 后续可在这里判断是否 @ 到机器人账号。
	return nil
}
