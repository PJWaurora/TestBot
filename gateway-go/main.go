package main

import (
	handler "gateway/handler"
	"log"
	"net/http"

	"github.com/gorilla/websocket"
)

var upgrader = websocket.Upgrader{
	CheckOrigin: func(r *http.Request) bool {
		return true
	},
}

// 1. 定义任务通道（设置缓冲区为 1000，防止偶发拥堵）
var jobQueue = make(chan []byte, 1000)

// 2. 定义工人函数
func worker(int) {
	for msg := range jobQueue {
		// 所有的业务逻辑都在这里运行
		handler.Dispatch(msg)
	}
}

func main() {

	workerCount := 10
	for i := 1; i <= workerCount; i++ {
		go worker(i)
	}

	http.HandleFunc("/ws", func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			//log.Println("Upgrade error:", err)
			return
		}
		defer conn.Close()

		for {
			_, message, err := conn.ReadMessage()
			if err != nil {
				//log.Println("Read error:", err)
				break
			}

			//log.Println("收到消息:", string(message))
			jobQueue <- message
		}

	})
	//log.Println("WebSocket服务器已启动，等待连接...")
	log.Fatal(http.ListenAndServe(":808", nil))
}
