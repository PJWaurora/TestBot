package common

import (
	"log"

	"gateway/handler/normalizer"
)

func HandleImage(message normalizer.IncomingMessage) {
	log.Printf("处理图片事件: user_id=%d group_id=%d images=%+v", message.UserID, message.GroupID, message.Images)
	// 后续可在这里接入图片下载、OCR 或多模态模型。
}
