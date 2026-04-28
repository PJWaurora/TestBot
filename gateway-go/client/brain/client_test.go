package brain_test

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"gateway/client/brain"
	"gateway/handler/normalizer"
)

func TestPostMessageSendsNormalizedEnvelopeWithStringIDs(t *testing.T) {
	var captured map[string]interface{}

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			t.Errorf("method = %s, want POST", r.Method)
		}
		if r.URL.Path != "/api/brain/process" {
			t.Errorf("path = %s, want /api/brain/process", r.URL.Path)
		}
		if got := r.Header.Get("Content-Type"); !strings.HasPrefix(got, "application/json") {
			t.Errorf("content-type = %q, want application/json", got)
		}

		decoder := json.NewDecoder(r.Body)
		decoder.UseNumber()
		if err := decoder.Decode(&captured); err != nil {
			t.Errorf("decode request: %v", err)
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}

		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{
			"handled": true,
			"should_reply": true,
			"messages": [{"type": "text", "text": "ok"}],
			"tool_calls": [{"id": "tool-1", "name": "lookup", "arguments": {"q": "hello"}}],
			"job_id": "job-7"
		}`))
	}))
	defer server.Close()

	client, err := brain.NewClient(server.URL+"/api", brain.WithEndpoint("/brain/process"), brain.WithTimeout(time.Second))
	if err != nil {
		t.Fatalf("new client: %v", err)
	}

	message, err := normalizer.NormalizeBytes([]byte(`{
		"post_type": "message",
		"self_id": 42,
		"message_type": "group",
		"sub_type": "normal",
		"message_id": 9007199254740993,
		"user_id": 9,
		"group_id": 8,
		"group_name": "room",
		"sender": {"user_id": 9, "nickname": "tester", "card": "card", "role": "member"},
		"message": [
			{"type": "reply", "data": {"id": 321}},
			{"type": "at", "data": {"qq": 456}},
			{"type": "text", "data": {"text": " hello"}}
		]
	}`))
	if err != nil {
		t.Fatalf("normalize message: %v", err)
	}

	response, err := client.PostMessage(context.Background(), message)
	if err != nil {
		t.Fatalf("post message: %v", err)
	}
	if response == nil {
		t.Fatal("response is nil, want response")
	}
	if !response.Handled || !response.ShouldReply || response.JobID != "job-7" {
		t.Fatalf("response = %+v, want handled reply with job_id", response)
	}
	if len(response.Messages) != 1 || response.Messages[0].Type != "text" || response.Messages[0].Text != "ok" {
		t.Fatalf("messages = %+v", response.Messages)
	}
	if len(response.ToolCalls) != 1 || response.ToolCalls[0].Name != "lookup" || response.ToolCalls[0].Arguments["q"] != "hello" {
		t.Fatalf("tool calls = %+v", response.ToolCalls)
	}

	assertStringField(t, captured, "message_id", "9007199254740993")
	assertStringField(t, captured, "self_id", "42")
	assertStringField(t, captured, "user_id", "9")
	assertStringField(t, captured, "group_id", "8")
	assertStringField(t, captured, "reply_to_message_id", "321")
	assertStringField(t, captured, "primary_type", "reply")
	assertStringField(t, captured, "text", " hello")

	sender, ok := captured["sender"].(map[string]interface{})
	if !ok {
		t.Fatalf("sender = %T, want object", captured["sender"])
	}
	assertStringField(t, sender, "user_id", "9")

	atUserIDs, ok := captured["at_user_ids"].([]interface{})
	if !ok || len(atUserIDs) != 1 || atUserIDs[0] != "456" {
		t.Fatalf("at_user_ids = %#v, want [\"456\"]", captured["at_user_ids"])
	}

	segments, ok := captured["segments"].([]interface{})
	if !ok || len(segments) != 3 {
		t.Fatalf("segments = %#v, want 3 segment objects", captured["segments"])
	}

	replyData := segmentData(t, segments[0])
	assertStringField(t, replyData, "id", "321")
	atData := segmentData(t, segments[1])
	assertStringField(t, atData, "qq", "456")
}

func TestPostEnvelopeReturnsNilResponseForNon2xx(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "brain unavailable", http.StatusTeapot)
	}))
	defer server.Close()

	client, err := brain.NewClient(server.URL)
	if err != nil {
		t.Fatalf("new client: %v", err)
	}

	response, err := client.PostEnvelope(context.Background(), brain.Envelope{Text: "hello"})
	if err == nil {
		t.Fatal("error is nil, want non-2xx error")
	}
	if response != nil {
		t.Fatalf("response = %+v, want nil", response)
	}
	if !strings.Contains(err.Error(), "418") {
		t.Fatalf("error = %q, want status code", err)
	}
}

func TestPostEnvelopeReturnsNilResponseForTimeout(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		time.Sleep(100 * time.Millisecond)
		_, _ = w.Write([]byte(`{"handled": true}`))
	}))
	defer server.Close()

	client, err := brain.NewClient(server.URL, brain.WithTimeout(10*time.Millisecond))
	if err != nil {
		t.Fatalf("new client: %v", err)
	}

	response, err := client.PostEnvelope(context.Background(), brain.Envelope{Text: "hello"})
	if err == nil {
		t.Fatal("error is nil, want timeout error")
	}
	if response != nil {
		t.Fatalf("response = %+v, want nil", response)
	}
}

func TestPullOutboxSendsBearerTokenAndDecodesItems(t *testing.T) {
	var captured map[string]interface{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/outbox/pull" {
			t.Fatalf("path = %s, want /api/outbox/pull", r.URL.Path)
		}
		if got := r.Header.Get("Authorization"); got != "Bearer secret" {
			t.Fatalf("authorization = %q, want bearer token", got)
		}

		if err := json.NewDecoder(r.Body).Decode(&captured); err != nil {
			t.Fatalf("decode request: %v", err)
		}

		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{
			"items": [{
				"id": 7,
				"message_type": "group",
				"group_id": "8",
				"messages": [{"type": "image", "url": "https://example.test/a.png"}],
				"status": "processing",
				"attempts": 1,
				"max_attempts": 5
			}]
		}`))
	}))
	defer server.Close()

	client, err := brain.NewClient(server.URL+"/api", brain.WithOutboxToken("secret"))
	if err != nil {
		t.Fatalf("new client: %v", err)
	}

	items, err := client.PullOutbox(context.Background(), 3, 9)
	if err != nil {
		t.Fatalf("pull outbox: %v", err)
	}
	if captured["limit"].(float64) != 3 || captured["lease_seconds"].(float64) != 9 {
		t.Fatalf("captured request = %#v, want limit and lease", captured)
	}
	if len(items) != 1 || items[0].ID != 7 || items[0].Messages[0].URL != "https://example.test/a.png" {
		t.Fatalf("items = %+v", items)
	}
}

func TestAckAndFailOutboxUseItemEndpoints(t *testing.T) {
	var paths []string
	var failBody map[string]interface{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		paths = append(paths, r.URL.Path)
		if got := r.Header.Get("Authorization"); got != "Bearer secret" {
			t.Fatalf("authorization = %q, want bearer token", got)
		}
		if r.URL.Path == "/outbox/7/fail" {
			if err := json.NewDecoder(r.Body).Decode(&failBody); err != nil {
				t.Fatalf("decode fail request: %v", err)
			}
		}

		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"id":7,"message_type":"group","group_id":"8","status":"sent","attempts":0,"max_attempts":5}`))
	}))
	defer server.Close()

	client, err := brain.NewClient(server.URL, brain.WithOutboxToken("secret"))
	if err != nil {
		t.Fatalf("new client: %v", err)
	}

	if err := client.AckOutbox(context.Background(), 7); err != nil {
		t.Fatalf("ack outbox: %v", err)
	}
	if err := client.FailOutbox(context.Background(), 7, "send failed"); err != nil {
		t.Fatalf("fail outbox: %v", err)
	}

	if strings.Join(paths, ",") != "/outbox/7/ack,/outbox/7/fail" {
		t.Fatalf("paths = %v, want ack then fail", paths)
	}
	if failBody["error"] != "send failed" {
		t.Fatalf("fail body = %#v, want error", failBody)
	}
}

func TestPullOutboxRequiresToken(t *testing.T) {
	client, err := brain.NewClient("http://localhost:8000")
	if err != nil {
		t.Fatalf("new client: %v", err)
	}

	if _, err := client.PullOutbox(context.Background(), 1, 1); err == nil {
		t.Fatal("error is nil, want missing token error")
	}
}

func TestNewClientValidatesBaseURLAndTimeout(t *testing.T) {
	if _, err := brain.NewClient("localhost:8000"); err == nil {
		t.Fatal("error is nil, want invalid base URL error")
	}
	if _, err := brain.NewClient("http://localhost:8000", brain.WithTimeout(0)); err == nil {
		t.Fatal("error is nil, want invalid timeout error")
	}
}

func assertStringField(t *testing.T, data map[string]interface{}, key, want string) {
	t.Helper()

	got, ok := data[key].(string)
	if !ok {
		t.Fatalf("%s = %T(%#v), want string %q", key, data[key], data[key], want)
	}
	if got != want {
		t.Fatalf("%s = %q, want %q", key, got, want)
	}
}

func segmentData(t *testing.T, segment interface{}) map[string]interface{} {
	t.Helper()

	segmentMap, ok := segment.(map[string]interface{})
	if !ok {
		t.Fatalf("segment = %T, want object", segment)
	}
	data, ok := segmentMap["data"].(map[string]interface{})
	if !ok {
		t.Fatalf("segment data = %T, want object", segmentMap["data"])
	}
	return data
}
