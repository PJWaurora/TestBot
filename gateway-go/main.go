package main

import (
	"context"
	"encoding/json"
	"fmt"
	"gateway/client/brain"
	"gateway/client/napcat"
	handler "gateway/handler"
	"log"
	"net/http"
	"os"
	"strconv"
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
const defaultOutboxPollInterval = 5 * time.Second
const defaultOutboxPollLimit = 10
const outboxRequestTimeout = 5 * time.Second
const defaultOutboxActionTimeout = 30 * time.Second

func getenv(key, fallback string) string {
	value := os.Getenv(key)
	if value == "" {
		return fallback
	}
	return value
}

type job struct {
	data      []byte
	sendQueue chan<- queuedAction
	done      <-chan struct{}
}

type queuedAction struct {
	action      napcat.Action
	writeResult chan<- error
}

type pendingNapcatActions struct {
	mu      sync.Mutex
	next    uint64
	pending map[string]chan napcat.Response
}

func newPendingNapcatActions() *pendingNapcatActions {
	return &pendingNapcatActions{pending: make(map[string]chan napcat.Response)}
}

func (actions *pendingNapcatActions) register(itemID int64) (string, <-chan napcat.Response) {
	actions.mu.Lock()
	defer actions.mu.Unlock()

	actions.next++
	echo := fmt.Sprintf("outbox:%d:%d", itemID, actions.next)
	result := make(chan napcat.Response, 1)
	actions.pending[echo] = result
	return echo, result
}

func (actions *pendingNapcatActions) complete(response napcat.Response) bool {
	if response.Echo == "" {
		return false
	}

	actions.mu.Lock()
	result, ok := actions.pending[response.Echo]
	if ok {
		delete(actions.pending, response.Echo)
	}
	actions.mu.Unlock()
	if !ok {
		return false
	}

	result <- response
	return true
}

func (actions *pendingNapcatActions) unregister(echo string) {
	actions.mu.Lock()
	delete(actions.pending, echo)
	actions.mu.Unlock()
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
			case msg.sendQueue <- queuedAction{action: action}:
			case <-msg.done:
				log.Printf("连接已关闭，丢弃 NapCat action: %s", action.Action)
			}
		}
	}
}

func writeLoop(conn *websocket.Conn, sendQueue <-chan queuedAction, done <-chan struct{}, closeSession func()) {
	defer closeSession()

	for {
		select {
		case queued, ok := <-sendQueue:
			if !ok {
				return
			}
			if err := conn.SetWriteDeadline(time.Now().Add(writeWait)); err != nil {
				log.Printf("设置 WebSocket 写超时失败: %v", err)
				reportActionWriteResult(queued.writeResult, err)
				return
			}
			if err := conn.WriteJSON(queued.action); err != nil {
				log.Printf("写入 NapCat action 失败: %v", err)
				reportActionWriteResult(queued.writeResult, err)
				return
			}
			reportActionWriteResult(queued.writeResult, nil)
		case <-done:
			return
		}
	}
}

func reportActionWriteResult(result chan<- error, err error) {
	if result == nil {
		return
	}
	select {
	case result <- err:
	default:
	}
}

func startOutboxPoller(done <-chan struct{}, sendQueue chan<- queuedAction, pendingActions *pendingNapcatActions, baseURL string) {
	baseURL = strings.TrimSpace(baseURL)
	if baseURL == "" {
		return
	}

	client, err := brain.NewClient(baseURL, brain.WithTimeout(outboxRequestTimeout))
	if err != nil {
		log.Printf("Brain outbox client 配置错误，跳过 outbox 轮询: %v", err)
		return
	}

	interval := parseDurationEnv("OUTBOX_POLL_INTERVAL", defaultOutboxPollInterval)
	limit := parsePositiveIntEnv("OUTBOX_POLL_LIMIT", defaultOutboxPollLimit)
	actionTimeout := parseDurationEnv("OUTBOX_ACTION_TIMEOUT", defaultOutboxActionTimeout)

	go func() {
		ticker := time.NewTicker(interval)
		defer ticker.Stop()

		for {
			pollOutboxOnce(done, sendQueue, pendingActions, client, limit, actionTimeout)

			select {
			case <-ticker.C:
			case <-done:
				return
			}
		}
	}()
}

func pollOutboxOnce(done <-chan struct{}, sendQueue chan<- queuedAction, pendingActions *pendingNapcatActions, client *brain.Client, limit int, actionTimeout time.Duration) {
	ctx, cancel := context.WithTimeout(context.Background(), outboxRequestTimeout)
	items, err := client.PullOutbox(ctx, limit)
	cancel()
	if err != nil {
		log.Printf("拉取 Brain outbox 失败: %v", err)
		return
	}

	for _, item := range items {
		select {
		case <-done:
			return
		default:
		}

		sendErr := sendOutboxItem(done, sendQueue, pendingActions, item, actionTimeout)
		ack := brain.OutboxAck{
			IDs:     []int64{item.ID},
			Success: sendErr == nil,
		}
		if sendErr != nil {
			ack.Error = sendErr.Error()
		}

		ctx, cancel := context.WithTimeout(context.Background(), outboxRequestTimeout)
		if err := client.AckOutbox(ctx, ack); err != nil {
			log.Printf("确认 Brain outbox item %d 失败: %v", item.ID, err)
		}
		cancel()
	}
}

func sendOutboxItem(done <-chan struct{}, sendQueue chan<- queuedAction, pendingActions *pendingNapcatActions, item brain.OutboxItem, actionTimeout time.Duration) error {
	action, err := napcat.NewOutboxAction(napcat.OutboxItem{
		ID:         item.ID,
		TargetType: item.TargetType,
		TargetID:   item.TargetID,
		Messages:   brainMessagesToNapcatItems(item.Messages),
	})
	if err != nil {
		return err
	}

	echo, actionResult := pendingActions.register(item.ID)
	defer pendingActions.unregister(echo)
	action.Echo = echo

	writeResult := make(chan error, 1)
	select {
	case sendQueue <- queuedAction{action: action, writeResult: writeResult}:
	case <-done:
		return fmt.Errorf("websocket connection closed before outbox item %d was queued", item.ID)
	}

	select {
	case err := <-writeResult:
		if err != nil {
			return fmt.Errorf("write outbox item %d action: %w", item.ID, err)
		}
	case <-done:
		return fmt.Errorf("websocket connection closed before outbox item %d was written", item.ID)
	}

	timer := time.NewTimer(actionTimeout)
	defer timer.Stop()

	select {
	case response := <-actionResult:
		if response.Success() {
			return nil
		}
		return fmt.Errorf("napcat outbox item %d action failed: %s", item.ID, response.ErrorText())
	case <-timer.C:
		return fmt.Errorf("napcat outbox item %d action response timed out after %s", item.ID, actionTimeout)
	case <-done:
		return fmt.Errorf("websocket connection closed before outbox item %d action response", item.ID)
	}
}

func handlePendingNapcatResponse(data []byte, pendingActions *pendingNapcatActions) bool {
	if pendingActions == nil {
		return false
	}

	var response napcat.Response
	if err := json.Unmarshal(data, &response); err != nil {
		return false
	}
	return pendingActions.complete(response)
}

func brainMessagesToNapcatItems(messages []brain.Message) []napcat.BrainMessageItem {
	if len(messages) == 0 {
		return nil
	}

	items := make([]napcat.BrainMessageItem, 0, len(messages))
	for _, message := range messages {
		items = append(items, napcat.BrainMessageItem{
			Type:    message.Type,
			Text:    message.Text,
			Content: message.Content,
			File:    message.File,
			URL:     message.URL,
			Path:    message.Path,
			Name:    message.Name,
			Data:    message.Data,
		})
	}
	return items
}

func parseDurationEnv(key string, fallback time.Duration) time.Duration {
	raw := strings.TrimSpace(os.Getenv(key))
	if raw == "" {
		return fallback
	}
	value, err := time.ParseDuration(raw)
	if err != nil || value <= 0 {
		log.Printf("%s=%q 无效，使用默认值 %s", key, raw, fallback)
		return fallback
	}
	return value
}

func parsePositiveIntEnv(key string, fallback int) int {
	raw := strings.TrimSpace(os.Getenv(key))
	if raw == "" {
		return fallback
	}
	value, err := strconv.Atoi(raw)
	if err != nil || value <= 0 {
		log.Printf("%s=%q 无效，使用默认值 %d", key, raw, fallback)
		return fallback
	}
	return value
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
		sendQueue := make(chan queuedAction, 100)
		done := make(chan struct{})
		pendingActions := newPendingNapcatActions()
		var closeOnce sync.Once
		closeSession := func() {
			closeOnce.Do(func() {
				close(done)
				_ = conn.Close()
			})
		}
		go writeLoop(conn, sendQueue, done, closeSession)
		startOutboxPoller(done, sendQueue, pendingActions, os.Getenv("BRAIN_BASE_URL"))
		defer closeSession()

		for {
			_, message, err := conn.ReadMessage()
			if err != nil {
				//log.Println("Read error:", err)
				break
			}

			//log.Println("收到消息:", string(message))
			if handlePendingNapcatResponse(message, pendingActions) {
				continue
			}
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
