package main

import (
	"fmt"
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

func main() {
	http.HandleFunc("/ws", func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			log.Println("Upgrade error:", err)
			return
		}
		defer conn.Close()

		for {
			_, message, err := conn.ReadMessage()
			if err != nil {
				log.Println("Read error:", err)
				break
			}

			go handler.Dispatch(message)
		}

	})
	fmt.Println("WebSocket服务器已启动，等待连接...")
	log.Fatal(http.ListenAndServe(":0808", nil))
}
