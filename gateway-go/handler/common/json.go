package common

import (
	//"fmt"
	"gateway/handler/models"
	"log"
)

func HandleJson(event models.BaseJsonEvent) {
	log.Println("处理JSON事件:", event)
	// 这里你可以添加处理JSON事件的逻辑
}
