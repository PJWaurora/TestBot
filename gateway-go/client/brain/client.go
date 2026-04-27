package brain

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"path"
	"strconv"
	"strings"
	"time"

	"gateway/handler/models"
	"gateway/handler/normalizer"
)

const (
	DefaultEndpoint = "/chat"
	DefaultTimeout  = 5 * time.Second
)

type Client struct {
	baseURL    *url.URL
	endpoint   string
	httpClient *http.Client
}

type Option func(*Client) error

func WithEndpoint(endpoint string) Option {
	return func(client *Client) error {
		if endpoint == "" {
			client.endpoint = ""
			return nil
		}
		client.endpoint = endpoint
		return nil
	}
}

func WithTimeout(timeout time.Duration) Option {
	return func(client *Client) error {
		if timeout <= 0 {
			return fmt.Errorf("brain timeout must be positive")
		}
		client.httpClient.Timeout = timeout
		return nil
	}
}

func WithHTTPClient(httpClient *http.Client) Option {
	return func(client *Client) error {
		if httpClient == nil {
			return fmt.Errorf("brain http client cannot be nil")
		}
		client.httpClient = httpClient
		return nil
	}
}

func NewClient(baseURL string, options ...Option) (*Client, error) {
	parsed, err := url.Parse(strings.TrimSpace(baseURL))
	if err != nil {
		return nil, fmt.Errorf("parse brain base url: %w", err)
	}
	if parsed.Scheme == "" || parsed.Host == "" {
		return nil, fmt.Errorf("brain base url must include scheme and host")
	}

	client := &Client{
		baseURL:  parsed,
		endpoint: DefaultEndpoint,
		httpClient: &http.Client{
			Timeout: DefaultTimeout,
		},
	}

	for _, option := range options {
		if err := option(client); err != nil {
			return nil, err
		}
	}

	return client, nil
}

func (client *Client) PostMessage(ctx context.Context, message normalizer.IncomingMessage) (*Response, error) {
	return client.PostEnvelope(ctx, NewEnvelope(message))
}

func (client *Client) PostEnvelope(ctx context.Context, envelope Envelope) (*Response, error) {
	if ctx == nil {
		ctx = context.Background()
	}

	envelope.Segments = newSegments(envelope.Segments)
	body, err := json.Marshal(envelope)
	if err != nil {
		return nil, fmt.Errorf("marshal brain envelope: %w", err)
	}

	targetURL := client.url()
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, targetURL.String(), bytes.NewReader(body))
	if err != nil {
		return nil, fmt.Errorf("build brain request: %w", err)
	}
	req.Header.Set("Accept", "application/json")
	req.Header.Set("Content-Type", "application/json")

	resp, err := client.httpClient.Do(req)
	if err != nil {
		if resp != nil && resp.Body != nil {
			_ = resp.Body.Close()
		}
		return nil, fmt.Errorf("post brain envelope: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode < http.StatusOK || resp.StatusCode >= http.StatusMultipleChoices {
		return nil, statusError(resp)
	}

	var brainResp Response
	if err := json.NewDecoder(resp.Body).Decode(&brainResp); err != nil {
		return nil, fmt.Errorf("decode brain response: %w", err)
	}

	return &brainResp, nil
}

func (client *Client) url() url.URL {
	return client.endpointURL(client.endpoint)
}

func (client *Client) endpointURL(endpoint string) url.URL {
	target := *client.baseURL
	if endpoint == "" {
		return target
	}

	target.Path = joinURLPath(target.Path, endpoint)
	return target
}

func (client *Client) PullOutbox(ctx context.Context, limit int) ([]OutboxItem, error) {
	if ctx == nil {
		ctx = context.Background()
	}
	if limit <= 0 {
		return nil, fmt.Errorf("outbox limit must be positive")
	}

	targetURL := client.endpointURL("/outbox/pull")
	query := targetURL.Query()
	query.Set("limit", strconv.Itoa(limit))
	targetURL.RawQuery = query.Encode()

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, targetURL.String(), nil)
	if err != nil {
		return nil, fmt.Errorf("build brain outbox pull request: %w", err)
	}
	req.Header.Set("Accept", "application/json")

	resp, err := client.httpClient.Do(req)
	if err != nil {
		if resp != nil && resp.Body != nil {
			_ = resp.Body.Close()
		}
		return nil, fmt.Errorf("pull brain outbox: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode < http.StatusOK || resp.StatusCode >= http.StatusMultipleChoices {
		return nil, statusError(resp)
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("read brain outbox response: %w", err)
	}

	var wrapped struct {
		Items []OutboxItem `json:"items"`
	}
	if err := json.Unmarshal(body, &wrapped); err == nil && wrapped.Items != nil {
		return wrapped.Items, nil
	}

	var items []OutboxItem
	if err := json.Unmarshal(body, &items); err != nil {
		return nil, fmt.Errorf("decode brain outbox response: %w", err)
	}
	return items, nil
}

func (client *Client) AckOutbox(ctx context.Context, ack OutboxAck) error {
	if ctx == nil {
		ctx = context.Background()
	}
	if len(ack.IDs) == 0 {
		return fmt.Errorf("outbox ack ids cannot be empty")
	}

	body, err := json.Marshal(ack)
	if err != nil {
		return fmt.Errorf("marshal brain outbox ack: %w", err)
	}

	targetURL := client.endpointURL("/outbox/ack")
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, targetURL.String(), bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("build brain outbox ack request: %w", err)
	}
	req.Header.Set("Accept", "application/json")
	req.Header.Set("Content-Type", "application/json")

	resp, err := client.httpClient.Do(req)
	if err != nil {
		if resp != nil && resp.Body != nil {
			_ = resp.Body.Close()
		}
		return fmt.Errorf("ack brain outbox: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode < http.StatusOK || resp.StatusCode >= http.StatusMultipleChoices {
		return statusError(resp)
	}

	return nil
}

func joinURLPath(basePath, endpoint string) string {
	if basePath == "" || basePath == "/" {
		if strings.HasPrefix(endpoint, "/") {
			return endpoint
		}
		return "/" + endpoint
	}

	joined := path.Join(basePath, endpoint)
	if strings.HasPrefix(basePath, "/") && !strings.HasPrefix(joined, "/") {
		joined = "/" + joined
	}
	return joined
}

func statusError(resp *http.Response) error {
	body, err := io.ReadAll(io.LimitReader(resp.Body, 4096))
	if err != nil {
		return fmt.Errorf("brain returned status %d and response body could not be read: %w", resp.StatusCode, err)
	}

	bodyText := strings.TrimSpace(string(body))
	if bodyText == "" {
		return fmt.Errorf("brain returned status %d", resp.StatusCode)
	}
	return fmt.Errorf("brain returned status %d: %s", resp.StatusCode, bodyText)
}

type Envelope struct {
	PostType         string                  `json:"post_type,omitempty"`
	MessageType      string                  `json:"message_type,omitempty"`
	SubType          string                  `json:"sub_type,omitempty"`
	PrimaryType      string                  `json:"primary_type,omitempty"`
	MessageID        string                  `json:"message_id,omitempty"`
	UserID           string                  `json:"user_id,omitempty"`
	GroupID          string                  `json:"group_id,omitempty"`
	GroupName        string                  `json:"group_name,omitempty"`
	TargetID         string                  `json:"target_id,omitempty"`
	Sender           Sender                  `json:"sender,omitempty"`
	Text             string                  `json:"text,omitempty"`
	TextSegments     []string                `json:"text_segments,omitempty"`
	Images           []Image                 `json:"images,omitempty"`
	JSONMessages     []JSONMessage           `json:"json_messages,omitempty"`
	Videos           []Video                 `json:"videos,omitempty"`
	AtUserIDs        []string                `json:"at_user_ids,omitempty"`
	AtAll            bool                    `json:"at_all,omitempty"`
	ReplyToMessageID string                  `json:"reply_to_message_id,omitempty"`
	UnknownTypes     []string                `json:"unknown_types,omitempty"`
	Segments         []models.MessageSegment `json:"segments,omitempty"`
}

type Sender struct {
	UserID   string `json:"user_id,omitempty"`
	NickName string `json:"nickname,omitempty"`
	Card     string `json:"card,omitempty"`
	Role     string `json:"role,omitempty"`
}

type Image struct {
	URL      string `json:"url,omitempty"`
	File     string `json:"file,omitempty"`
	Summary  string `json:"summary,omitempty"`
	SubType  string `json:"sub_type,omitempty"`
	FileSize string `json:"file_size,omitempty"`
}

type JSONMessage struct {
	Raw    string                 `json:"raw,omitempty"`
	Parsed map[string]interface{} `json:"parsed,omitempty"`
}

type Video struct {
	URL  string `json:"url,omitempty"`
	File string `json:"file,omitempty"`
}

func NewEnvelope(message normalizer.IncomingMessage) Envelope {
	return Envelope{
		PostType:         message.PostType,
		MessageType:      message.MessageType,
		SubType:          message.SubType,
		PrimaryType:      message.PrimaryType(),
		MessageID:        idString(message.MessageID),
		UserID:           idString(message.UserID),
		GroupID:          idString(message.GroupID),
		GroupName:        message.GroupName,
		TargetID:         idString(message.TargetID),
		Sender:           newSender(message.Sender),
		Text:             message.Text,
		TextSegments:     copyStrings(message.TextSegments),
		Images:           newImages(message.Images),
		JSONMessages:     newJSONMessages(message.JSONMessages),
		Videos:           newVideos(message.Videos),
		AtUserIDs:        idStrings(message.AtUserIDs),
		AtAll:            message.AtAll,
		ReplyToMessageID: idString(message.ReplyToMessageID),
		UnknownTypes:     copyStrings(message.UnknownTypes),
		Segments:         newSegments(message.Segments),
	}
}

func newSender(sender models.Sender) Sender {
	return Sender{
		UserID:   idString(sender.UserID),
		NickName: sender.NickName,
		Card:     sender.Card,
		Role:     sender.Role,
	}
}

func newImages(images []normalizer.ImageContent) []Image {
	if len(images) == 0 {
		return nil
	}

	out := make([]Image, 0, len(images))
	for _, image := range images {
		out = append(out, Image{
			URL:      image.URL,
			File:     image.File,
			Summary:  image.Summary,
			SubType:  image.SubType,
			FileSize: image.FileSize,
		})
	}
	return out
}

func newJSONMessages(messages []normalizer.JSONContent) []JSONMessage {
	if len(messages) == 0 {
		return nil
	}

	out := make([]JSONMessage, 0, len(messages))
	for _, message := range messages {
		out = append(out, JSONMessage{
			Raw:    message.Raw,
			Parsed: copyMap(message.Parsed),
		})
	}
	return out
}

func newVideos(videos []normalizer.VideoContent) []Video {
	if len(videos) == 0 {
		return nil
	}

	out := make([]Video, 0, len(videos))
	for _, video := range videos {
		out = append(out, Video{
			URL:  video.URL,
			File: video.File,
		})
	}
	return out
}

func newSegments(segments []models.MessageSegment) []models.MessageSegment {
	if len(segments) == 0 {
		return nil
	}

	out := make([]models.MessageSegment, 0, len(segments))
	for _, segment := range segments {
		out = append(out, models.MessageSegment{
			Type: segment.Type,
			Data: normalizeSegmentData(segment.Data),
		})
	}
	return out
}

func normalizeSegmentData(data map[string]interface{}) map[string]interface{} {
	if len(data) == 0 {
		return nil
	}

	out := make(map[string]interface{}, len(data))
	for key, value := range data {
		if isIDKey(key) {
			out[key] = idValueString(value)
			continue
		}
		out[key] = value
	}
	return out
}

func isIDKey(key string) bool {
	switch strings.ToLower(key) {
	case "id", "qq", "self_id", "user_id", "group_id", "target_id", "message_id", "message_seq", "real_id", "reply_to_message_id":
		return true
	default:
		return false
	}
}

func idString(id int64) string {
	if id == 0 {
		return ""
	}
	return strconv.FormatInt(id, 10)
}

func idStrings(ids []int64) []string {
	if len(ids) == 0 {
		return nil
	}

	out := make([]string, 0, len(ids))
	for _, id := range ids {
		if encoded := idString(id); encoded != "" {
			out = append(out, encoded)
		}
	}
	return out
}

func idValueString(value interface{}) interface{} {
	switch typed := value.(type) {
	case nil:
		return nil
	case string:
		return typed
	case json.Number:
		return typed.String()
	case int:
		return strconv.Itoa(typed)
	case int8:
		return strconv.FormatInt(int64(typed), 10)
	case int16:
		return strconv.FormatInt(int64(typed), 10)
	case int32:
		return strconv.FormatInt(int64(typed), 10)
	case int64:
		return strconv.FormatInt(typed, 10)
	case uint:
		return strconv.FormatUint(uint64(typed), 10)
	case uint8:
		return strconv.FormatUint(uint64(typed), 10)
	case uint16:
		return strconv.FormatUint(uint64(typed), 10)
	case uint32:
		return strconv.FormatUint(uint64(typed), 10)
	case uint64:
		return strconv.FormatUint(typed, 10)
	case float32:
		return strconv.FormatFloat(float64(typed), 'f', -1, 32)
	case float64:
		return strconv.FormatFloat(typed, 'f', -1, 64)
	default:
		return fmt.Sprint(typed)
	}
}

func copyStrings(values []string) []string {
	if len(values) == 0 {
		return nil
	}

	out := make([]string, len(values))
	copy(out, values)
	return out
}

func copyMap(in map[string]interface{}) map[string]interface{} {
	if len(in) == 0 {
		return nil
	}

	out := make(map[string]interface{}, len(in))
	for key, value := range in {
		out[key] = value
	}
	return out
}

type Response struct {
	Handled     bool       `json:"handled"`
	ShouldReply bool       `json:"should_reply"`
	Messages    []Message  `json:"messages,omitempty"`
	Reply       string     `json:"reply,omitempty"`
	ToolCalls   []ToolCall `json:"tool_calls,omitempty"`
	JobID       string     `json:"job_id,omitempty"`
}

type Message struct {
	Type    string                 `json:"type,omitempty"`
	Text    string                 `json:"text,omitempty"`
	Content string                 `json:"content,omitempty"`
	File    string                 `json:"file,omitempty"`
	URL     string                 `json:"url,omitempty"`
	Path    string                 `json:"path,omitempty"`
	Name    string                 `json:"name,omitempty"`
	Data    map[string]interface{} `json:"data,omitempty"`
}

type ToolCall struct {
	ID        string                 `json:"id,omitempty"`
	Name      string                 `json:"name,omitempty"`
	Arguments map[string]interface{} `json:"arguments,omitempty"`
}

type OutboxItem struct {
	ID         int64     `json:"id"`
	TargetType string    `json:"target_type"`
	TargetID   string    `json:"target_id"`
	Messages   []Message `json:"messages"`
}

type OutboxAck struct {
	IDs     []int64 `json:"ids"`
	Success bool    `json:"success"`
	Error   string  `json:"error,omitempty"`
}
