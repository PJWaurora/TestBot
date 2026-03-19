package common

import (
	"gateway/handler/models"
	"log"
)

func HandleVideo(event models.BaseVideoEvent) {
	log.Println("处理视频事件:", event)
	// 这里你可以添加处理视频事件的逻辑
}
