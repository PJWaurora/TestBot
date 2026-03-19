package common

import (
	"gateway/handler/models"
	"log"
)

func HandleText(event models.BaseTextEvent) {
	log.Println("处理文本消息:", event)
	// 这里你可以添加处理文本消息的逻辑
}
