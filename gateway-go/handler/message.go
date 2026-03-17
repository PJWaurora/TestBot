package handler

import "fmt"

func handleMessage(event interface{}) {
	fmt.Println("处理消息事件:", event)
	// 这里你可以添加处理消息事件的逻辑
}
