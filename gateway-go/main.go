package main

import (
	"context"
	brainclient "gateway/client/brain"
	"gateway/client/napcat"
	handler "gateway/handler"
	"log"
	"net/http"
	"os"
	"strings"
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
const gatewayBrainRequestTimeout = 20 * time.Second
const outboxPollInterval = 3 * time.Second
const outboxLeaseSeconds = 30
const outboxPullLimit = 10
const outboxSendTimeout = 5 * time.Second

func getenv(key, fallback string) string {
	value := os.Getenv(key)
	if value == "" {
		return fallback
	}
	return value
}

type job struct {
	data      []byte
	sendQueue chan<- outboundAction
	done      <-chan struct{}
}

type outboundAction struct {
	action napcat.Action
	onSent func(error)
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
			case msg.sendQueue <- outboundAction{action: action}:
			case <-msg.done:
				log.Printf("连接已关闭，丢弃 NapCat action: %s", action.Action)
			}
		}
	}
}

func writeLoop(conn *websocket.Conn, sendQueue <-chan outboundAction, done <-chan struct{}, closeSession func()) {
	defer closeSession()

	for {
		select {
		case outbound, ok := <-sendQueue:
			if !ok {
				return
			}
			if err := conn.SetWriteDeadline(time.Now().Add(writeWait)); err != nil {
				log.Printf("设置 WebSocket 写超时失败: %v", err)
				notifySent(outbound, err)
				return
			}
			if err := conn.WriteJSON(outbound.action); err != nil {
				log.Printf("写入 NapCat action 失败: %v", err)
				notifySent(outbound, err)
				return
			}
			notifySent(outbound, nil)
		case <-done:
			return
		}
	}
}

func notifySent(outbound outboundAction, err error) {
	if outbound.onSent != nil {
		outbound.onSent(err)
	}
}

func startOutboxPoller(sendQueue chan<- outboundAction, done <-chan struct{}) {
	baseURL := strings.TrimSpace(os.Getenv("BRAIN_BASE_URL"))
	token := strings.TrimSpace(os.Getenv("OUTBOX_TOKEN"))
	if baseURL == "" || token == "" {
		return
	}

	client, err := brainclient.NewClient(
		baseURL,
		brainclient.WithTimeout(gatewayBrainRequestTimeout),
		brainclient.WithOutboxToken(token),
	)
	if err != nil {
		log.Printf("Outbox poller 配置错误: %v", err)
		return
	}

	go func() {
		pollOutboxOnce(client, sendQueue, done)

		ticker := time.NewTicker(outboxPollInterval)
		defer ticker.Stop()
		for {
			select {
			case <-ticker.C:
				pollOutboxOnce(client, sendQueue, done)
			case <-done:
				return
			}
		}
	}()
}

func pollOutboxOnce(client *brainclient.Client, sendQueue chan<- outboundAction, done <-chan struct{}) {
	ctx, cancel := context.WithTimeout(context.Background(), gatewayBrainRequestTimeout)
	items, err := client.PullOutbox(ctx, outboxPullLimit, outboxLeaseSeconds)
	cancel()
	if err != nil {
		select {
		case <-done:
			return
		default:
		}
		log.Printf("Outbox 拉取失败: %v", err)
		return
	}

	for _, item := range items {
		if processOutboxItem(client, sendQueue, done, item) {
			continue
		}
		select {
		case <-done:
			return
		default:
		}
	}
}

func processOutboxItem(
	client *brainclient.Client,
	sendQueue chan<- outboundAction,
	done <-chan struct{},
	item brainclient.OutboxItem,
) bool {
	action, ok := handler.OutboxAction(item)
	if !ok {
		failOutboxItem(client, item.ID, "unsupported_or_invalid_outbox_item")
		return true
	}

	writeResult := make(chan error, 1)
	outbound := outboundAction{
		action: action,
		onSent: func(err error) {
			writeResult <- err
		},
	}

	select {
	case sendQueue <- outbound:
	case <-time.After(outboxSendTimeout):
		failOutboxItem(client, item.ID, "gateway_send_queue_timeout")
		return true
	case <-done:
		failOutboxItem(client, item.ID, "gateway_connection_closed")
		return false
	}

	select {
	case err := <-writeResult:
		if err != nil {
			failOutboxItem(client, item.ID, "gateway_write_failed")
			return true
		}
		ackOutboxItem(client, item.ID)
		return true
	case <-done:
		failOutboxItem(client, item.ID, "gateway_connection_closed")
		return false
	}
}

func ackOutboxItem(client *brainclient.Client, itemID int64) {
	ctx, cancel := context.WithTimeout(context.Background(), gatewayBrainRequestTimeout)
	defer cancel()
	if err := client.AckOutbox(ctx, itemID); err != nil {
		log.Printf("Outbox ack 失败 item_id=%d: %v", itemID, err)
	}
}

func failOutboxItem(client *brainclient.Client, itemID int64, reason string) {
	ctx, cancel := context.WithTimeout(context.Background(), gatewayBrainRequestTimeout)
	defer cancel()
	if err := client.FailOutbox(ctx, itemID, reason); err != nil {
		log.Printf("Outbox fail 失败 item_id=%d reason=%s: %v", itemID, reason, err)
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
		sendQueue := make(chan outboundAction, 100)
		done := make(chan struct{})
		var closeOnce sync.Once
		closeSession := func() {
			closeOnce.Do(func() {
				close(done)
				_ = conn.Close()
			})
		}
		go writeLoop(conn, sendQueue, done, closeSession)
		startOutboxPoller(sendQueue, done)
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
