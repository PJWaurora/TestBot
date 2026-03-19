package common

import (
	"gateway/handler/models"
	"log"
)

func HandleImage(event models.BaseImageEvent) {
	log.Println("处理图片事件:", event)
	// 这里你可以添加处理图片事件的逻辑
}
