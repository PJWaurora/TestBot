package main

import (
	"gateway/client/napcat"
	handler "gateway/handler"
	"log"
	"net/http"
	"os"
	"sync"
	"time"

	"github.com/gorilla/websocket"
)

var upgrader = websocket.Upgrader{
	CheckOrigin: func(r *http.Request) bool {
		return true
	},
}

const writeWait = 10 * time.Second

func getenv(key, fallback string) string {
	value := os.Getenv(key)
	if value == "" {
		return fallback
	}
	return value
}

type job struct {
	data      []byte
	sendQueue chan<- napcat.Action
	done      <-chan struct{}
}

// 1. 定义任务通道（设置缓冲区为 1000，防止偶发拥堵）
var jobQueue = make(chan job, 1000)

// 2. 定义工人函数
func worker(int) {
	for msg := range jobQueue {
		// 所有的业务逻辑都在这里运行
		for _, action := range handler.Dispatch(msg.data) {
			select {
			case <-msg.done:
				log.Printf("连接已关闭，丢弃 NapCat action: %s", action.Action)
				continue
			default:
			}

			select {
			case msg.sendQueue <- action:
			case <-msg.done:
				log.Printf("连接已关闭，丢弃 NapCat action: %s", action.Action)
			}
		}
	}
}

func writeLoop(conn *websocket.Conn, sendQueue <-chan napcat.Action, done <-chan struct{}, closeSession func()) {
	defer closeSession()

	for {
		select {
		case action, ok := <-sendQueue:
			if !ok {
				return
			}
			if err := conn.SetWriteDeadline(time.Now().Add(writeWait)); err != nil {
				log.Printf("设置 WebSocket 写超时失败: %v", err)
				return
			}
			if err := conn.WriteJSON(action); err != nil {
				log.Printf("写入 NapCat action 失败: %v", err)
				return
			}
		case <-done:
			return
		}
	}
}

func main() {
	listenAddr := getenv("GATEWAY_LISTEN_ADDR", ":808")
	wsPath := getenv("GATEWAY_WS_PATH", "/ws")

	workerCount := 10
	for i := 1; i <= workerCount; i++ {
		go worker(i)
	}

	mux := http.NewServeMux()
	mux.HandleFunc(wsPath, func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			//log.Println("Upgrade error:", err)
			return
		}
		defer conn.Close()
		sendQueue := make(chan napcat.Action, 100)
		done := make(chan struct{})
		var closeOnce sync.Once
		closeSession := func() {
			closeOnce.Do(func() {
				close(done)
				_ = conn.Close()
			})
		}
		go writeLoop(conn, sendQueue, done, closeSession)
		defer closeSession()

		for {
			_, message, err := conn.ReadMessage()
			if err != nil {
				//log.Println("Read error:", err)
				break
			}

			//log.Println("收到消息:", string(message))
			select {
			case jobQueue <- job{
				data:      message,
				sendQueue: sendQueue,
				done:      done,
			}:
			case <-done:
				return
			}
		}

	})
	log.Printf("WebSocket服务器已启动，监听 %s%s", listenAddr, wsPath)
	log.Fatal(http.ListenAndServe(listenAddr, mux))
}
