package main

import (
	"encoding/json"
	brainclient "gateway/client/brain"
	"gateway/client/napcat"
	"net/http"
	"net/http/httptest"
	"os"
	"sync/atomic"
	"testing"
)

func TestGetenvUsesFallbackForMissingValue(t *testing.T) {
	t.Setenv("TESTBOT_MISSING_VALUE", "")

	if got := getenv("TESTBOT_MISSING_VALUE", "fallback"); got != "fallback" {
		t.Fatalf("getenv returned %q, want fallback", got)
	}
}

func TestGetenvUsesEnvironmentValue(t *testing.T) {
	const key = "TESTBOT_PRESENT_VALUE"
	t.Setenv(key, "configured")

	if got := getenv(key, "fallback"); got != "configured" {
		t.Fatalf("getenv returned %q, want configured", got)
	}
}

func TestGetenvTreatsUnsetAsFallback(t *testing.T) {
	const key = "TESTBOT_UNSET_VALUE"
	prev, hadPrev := os.LookupEnv(key)
	t.Cleanup(func() {
		if hadPrev {
			if err := os.Setenv(key, prev); err != nil {
				t.Fatalf("restore %s: %v", key, err)
			}
			return
		}
		if err := os.Unsetenv(key); err != nil {
			t.Fatalf("restore unset %s: %v", key, err)
		}
	})

	if err := os.Unsetenv(key); err != nil {
		t.Fatalf("unset %s: %v", key, err)
	}

	if got := getenv(key, "fallback"); got != "fallback" {
		t.Fatalf("getenv returned %q, want fallback", got)
	}
}

func TestPollOutboxOnceSendsActionAndAcks(t *testing.T) {
	var ackCalls atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if got := r.Header.Get("Authorization"); got != "Bearer secret" {
			t.Fatalf("authorization = %q, want bearer token", got)
		}

		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/outbox/pull":
			_, _ = w.Write([]byte(`{
				"items": [{
					"id": 7,
					"message_type": "group",
					"group_id": "8",
					"messages": [{"type": "text", "text": "queued"}],
					"status": "processing",
					"attempts": 0,
					"max_attempts": 5
				}]
			}`))
		case "/outbox/7/ack":
			ackCalls.Add(1)
			_, _ = w.Write([]byte(`{"id":7,"message_type":"group","group_id":"8","status":"sent","attempts":0,"max_attempts":5}`))
		default:
			t.Fatalf("unexpected path %s", r.URL.Path)
		}
	}))
	defer server.Close()

	client, err := brainclient.NewClient(server.URL, brainclient.WithOutboxToken("secret"))
	if err != nil {
		t.Fatalf("new client: %v", err)
	}

	var sentAction napcat.Action
	sendQueue := make(chan outboundAction, 1)
	done := make(chan struct{})
	go func() {
		outbound := <-sendQueue
		sentAction = outbound.action
		outbound.onSent(nil)
	}()

	pollOutboxOnce(client, sendQueue, done)

	params, ok := sentAction.Params.(napcat.SendGroupMessageParams)
	if !ok {
		t.Fatalf("params type = %T, want SendGroupMessageParams", sentAction.Params)
	}
	if params.GroupID != 8 || params.Message != "queued" {
		t.Fatalf("params = %+v, want queued group message", params)
	}
	if ackCalls.Load() != 1 {
		t.Fatalf("ack calls = %d, want 1", ackCalls.Load())
	}
}

func TestPollOutboxOnceFailsInvalidItem(t *testing.T) {
	var failBody map[string]interface{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		switch r.URL.Path {
		case "/outbox/pull":
			_, _ = w.Write([]byte(`{
				"items": [{
					"id": 7,
					"message_type": "group",
					"messages": [{"type": "text", "text": "queued"}],
					"status": "processing",
					"attempts": 0,
					"max_attempts": 5
				}]
			}`))
		case "/outbox/7/fail":
			if err := json.NewDecoder(r.Body).Decode(&failBody); err != nil {
				t.Fatalf("decode fail body: %v", err)
			}
			_, _ = w.Write([]byte(`{"id":7,"message_type":"group","status":"pending","attempts":1,"max_attempts":5}`))
		default:
			t.Fatalf("unexpected path %s", r.URL.Path)
		}
	}))
	defer server.Close()

	client, err := brainclient.NewClient(server.URL, brainclient.WithOutboxToken("secret"))
	if err != nil {
		t.Fatalf("new client: %v", err)
	}

	sendQueue := make(chan outboundAction, 1)
	done := make(chan struct{})
	pollOutboxOnce(client, sendQueue, done)

	if len(sendQueue) != 0 {
		t.Fatalf("send queue length = %d, want 0", len(sendQueue))
	}
	if failBody["error"] != "unsupported_or_invalid_outbox_item" {
		t.Fatalf("fail body = %#v, want invalid item reason", failBody)
	}
}
