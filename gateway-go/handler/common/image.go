package common

import (
	"gateway/client/napcat"
	"gateway/handler/normalizer"
)

func HandleImage(message normalizer.IncomingMessage) []napcat.Action {
	// 后续可在这里接入图片下载、OCR 或多模态模型。
	return nil
}
