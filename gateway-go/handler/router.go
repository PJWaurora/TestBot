package handler

import (
	"fmt"
)

func getEventType(event interface{}) string {
	// 这里你可以根据事件的结构体类型来判断事件类型
	// 例如，如果事件是一个包含 "type" 字段的 JSON 对象，你可以这样做：
	if eventMap, ok := event.(map[string]interface{}); ok {
		if eventType, exists := eventMap["type"].(string); exists {
			return eventType
		}
	}
	return "unknown"
}

// 确保首字母大写！
func Dispatch(event interface{}) {
	eventType := getEventType(event)
	fmt.Println("路由分发中...", eventType)
	// 你的逻辑
	switch eventType {
	case "message":
		handleMessage(event)
	case "image":
		handleImage(event)
	default:
		fmt.Println("未知事件类型:", eventType)
	}
}
