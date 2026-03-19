package group

import (
	"gateway/handler/models"
	"log"
)

func HandleReply(event models.BaseReplyEvent) {
	log.Println("处理回复事件:", event)
	// 这里你可以添加处理回复事件的逻辑
}
