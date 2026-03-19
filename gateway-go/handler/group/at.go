package group

import (
	"gateway/handler/models"
	"log"
)

func HandleAt(event models.BaseAtEvent) {
	log.Println("处理@事件:", event)
	// 这里你可以添加处理@事件的逻辑
}
