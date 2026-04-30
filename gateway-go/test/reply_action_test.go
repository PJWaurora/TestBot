package test

import (
	"gateway/client/brain"
	"net/http"
	"net/http/httptest"
	"reflect"
	"sync/atomic"
	"testing"
	"time"

	"gateway/client/napcat"
	"gateway/handler"
	"gateway/handler/normalizer"
)

func TestDispatchSilencesGroupTextWithoutBrain(t *testing.T) {
	t.Setenv("BRAIN_BASE_URL", "")
	data := []byte(`{
		"post_type": "message",
		"message_type": "group",
		"user_id": 9,
		"group_id": 8,
		"message": [
			{"type": "text", "data": {"text": "hello"}}
		]
	}`)

	actions := handler.Dispatch(data)
	if len(actions) != 0 {
		t.Fatalf("action count = %d, want 0", len(actions))
	}
}

func TestDispatchSilencesPrivateTextWithoutBrain(t *testing.T) {
	t.Setenv("BRAIN_BASE_URL", "")
	data := []byte(`{
		"post_type": "message",
		"message_type": "private",
		"user_id": 9,
		"message": [
			{"type": "text", "data": {"text": "hello"}}
		]
	}`)

	actions := handler.Dispatch(data)
	if len(actions) != 0 {
		t.Fatalf("action count = %d, want 0", len(actions))
	}
}

func TestDispatchUsesBrainWhenEnabled(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/chat" {
			t.Fatalf("path = %s, want /chat", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{
			"handled": true,
			"should_reply": true,
			"messages": [{"type": "text", "text": "brain says hi"}]
		}`))
	}))
	defer server.Close()
	t.Setenv("BRAIN_BASE_URL", server.URL)

	data := []byte(`{
		"post_type": "message",
		"message_type": "group",
		"user_id": 9,
		"group_id": 8,
		"message": [
			{"type": "text", "data": {"text": "hello"}}
		]
	}`)

	actions := handler.Dispatch(data)
	if len(actions) != 1 {
		t.Fatalf("action count = %d, want 1", len(actions))
	}

	params, ok := actions[0].Params.(napcat.SendGroupMessageParams)
	if !ok {
		t.Fatalf("params type = %T, want SendGroupMessageParams", actions[0].Params)
	}
	want := []napcat.OneBotMessageSegment{{Type: "text", Data: map[string]interface{}{"text": "brain says hi"}}}
	if params.GroupID != 8 || !reflect.DeepEqual(params.Message, want) {
		t.Fatalf("params = %+v, want group_id=8 message=brain says hi", params)
	}
}

func TestDispatchUsesSeparateActionsForImageAndTextMessages(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{
			"handled": true,
			"should_reply": true,
			"messages": [
				{"type": "image", "url": "https://example.test/card.png"},
				{"type": "text", "text": "detail text"}
			]
		}`))
	}))
	defer server.Close()
	t.Setenv("BRAIN_BASE_URL", server.URL)

	data := []byte(`{
		"post_type": "message",
		"message_type": "group",
		"user_id": 9,
		"group_id": 8,
		"message": [
			{"type": "text", "data": {"text": "hello"}}
		]
	}`)

	actions := handler.Dispatch(data)
	if len(actions) != 2 {
		t.Fatalf("action count = %d, want 2", len(actions))
	}

	first, ok := actions[0].Params.(napcat.SendGroupMessageParams)
	if !ok {
		t.Fatalf("first params type = %T, want SendGroupMessageParams", actions[0].Params)
	}
	second, ok := actions[1].Params.(napcat.SendGroupMessageParams)
	if !ok {
		t.Fatalf("second params type = %T, want SendGroupMessageParams", actions[1].Params)
	}

	if !reflect.DeepEqual(first.Message, []napcat.OneBotMessageSegment{
		{Type: "image", Data: map[string]interface{}{"file": "https://example.test/card.png"}},
	}) {
		t.Fatalf("first message = %q", first.Message)
	}
	if !reflect.DeepEqual(second.Message, []napcat.OneBotMessageSegment{
		{Type: "text", Data: map[string]interface{}{"text": "detail text"}},
	}) {
		t.Fatalf("second message = %q", second.Message)
	}
}

func TestDispatchSilencesWhenBrainDoesNotHandle(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"handled": false, "should_reply": false}`))
	}))
	defer server.Close()
	t.Setenv("BRAIN_BASE_URL", server.URL)

	data := []byte(`{
		"post_type": "message",
		"message_type": "private",
		"user_id": 9,
		"message": [
			{"type": "text", "data": {"text": "hello"}}
		]
	}`)

	actions := handler.Dispatch(data)
	if len(actions) != 0 {
		t.Fatalf("action count = %d, want 0", len(actions))
	}
}

func TestDispatchDoesNotFallbackWhenBrainErrors(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "down", http.StatusServiceUnavailable)
	}))
	defer server.Close()
	t.Setenv("BRAIN_BASE_URL", server.URL)

	data := []byte(`{
		"post_type": "message",
		"message_type": "group",
		"user_id": 9,
		"group_id": 8,
		"message": [
			{"type": "text", "data": {"text": "hello"}}
		]
	}`)

	actions := handler.Dispatch(data)
	if len(actions) != 0 {
		t.Fatalf("action count = %d, want 0", len(actions))
	}
}

func TestDispatchIgnoresNonMessageEvents(t *testing.T) {
	var brainCalls atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		brainCalls.Add(1)
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{
			"handled": true,
			"should_reply": true,
			"messages": [{"type": "text", "text": "should not send"}]
		}`))
	}))
	defer server.Close()
	t.Setenv("BRAIN_BASE_URL", server.URL)

	data := []byte(`{
		"message": {"unexpected": "shape"},
		"user_id": 0,
		"group_id": 0
	}`)

	actions := handler.Dispatch(data)
	if len(actions) != 0 {
		t.Fatalf("action count = %d, want 0", len(actions))
	}
	if brainCalls.Load() != 0 {
		t.Fatalf("brain calls = %d, want 0", brainCalls.Load())
	}
}

func TestDispatchIgnoresSelfMessages(t *testing.T) {
	var brainCalls atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		brainCalls.Add(1)
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{
			"handled": true,
			"should_reply": true,
			"messages": [{"type": "text", "text": "should not send"}]
		}`))
	}))
	defer server.Close()
	t.Setenv("BRAIN_BASE_URL", server.URL)

	data := []byte(`{
		"post_type": "message",
		"message_type": "group",
		"self_id": 9,
		"user_id": 9,
		"group_id": 8,
		"message": [
			{"type": "text", "data": {"text": "bot echo"}}
		]
	}`)

	actions := handler.Dispatch(data)
	if len(actions) != 0 {
		t.Fatalf("action count = %d, want 0", len(actions))
	}
	if brainCalls.Load() != 0 {
		t.Fatalf("brain calls = %d, want 0", brainCalls.Load())
	}
}

func TestDispatchBrainTreatsUnhandledResponseAsHandled(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"handled": false, "should_reply": false}`))
	}))
	defer server.Close()
	t.Setenv("BRAIN_BASE_URL", server.URL)

	actions, handled := handler.DispatchBrain(normalizer.IncomingMessage{
		PostType:    "message",
		MessageType: "group",
		UserID:      9,
		GroupID:     8,
		Text:        "hello",
		TextSegments: []string{
			"hello",
		},
	})
	if !handled {
		t.Fatal("handled = false, want true")
	}
	if len(actions) != 0 {
		t.Fatalf("action count = %d, want 0", len(actions))
	}
}

func TestDispatchBrainUsesConfigurableTimeout(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		time.Sleep(50 * time.Millisecond)
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{
			"handled": true,
			"should_reply": true,
			"messages": [{"type": "text", "text": "too late"}]
		}`))
	}))
	defer server.Close()
	t.Setenv("BRAIN_BASE_URL", server.URL)
	t.Setenv("GATEWAY_BRAIN_TIMEOUT_SECONDS", "0.01")

	actions, handled := handler.DispatchBrain(normalizer.IncomingMessage{
		PostType:    "message",
		MessageType: "group",
		UserID:      9,
		GroupID:     8,
		Text:        "hello",
		TextSegments: []string{
			"hello",
		},
	})
	if !handled {
		t.Fatal("handled = false, want true")
	}
	if len(actions) != 0 {
		t.Fatalf("action count = %d, want 0", len(actions))
	}
}

func TestOutboxActionUsesBrainMessageCQConversion(t *testing.T) {
	action, ok := handler.OutboxAction(brain.OutboxItem{
		ID:          7,
		MessageType: "group",
		GroupID:     "8",
		Messages: []brain.Message{
			{Type: "text", Text: "queued"},
			{Type: "image", URL: "https://example.test/a,b.png"},
			{Type: "video", File: "clip.mp4"},
		},
	})
	if !ok {
		t.Fatal("OutboxAction returned ok=false")
	}

	params, ok := action.Params.(napcat.SendGroupMessageParams)
	if !ok {
		t.Fatalf("params type = %T, want SendGroupMessageParams", action.Params)
	}

	want := []napcat.OneBotMessageSegment{
		{Type: "text", Data: map[string]interface{}{"text": "queued"}},
		{Type: "image", Data: map[string]interface{}{"file": "https://example.test/a,b.png"}},
		{Type: "video", Data: map[string]interface{}{"file": "clip.mp4"}},
	}
	if params.GroupID != 8 || !reflect.DeepEqual(params.Message, want) {
		t.Fatalf("params = %+v, want group_id=8 message=%#v", params, want)
	}
}

func TestDispatchUsesForwardActionForNodeMessages(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{
			"handled": true,
			"should_reply": true,
			"messages": [
				{
					"type": "node",
					"data": {
						"user_id": 10001,
						"nickname": "Alice",
						"messages": [{"type": "text", "text": "hello"}]
					}
				}
			]
		}`))
	}))
	defer server.Close()
	t.Setenv("BRAIN_BASE_URL", server.URL)

	data := []byte(`{
		"post_type": "message",
		"message_type": "group",
		"user_id": 9,
		"group_id": 8,
		"message": [
			{"type": "text", "data": {"text": "forward"}}
		]
	}`)

	actions := handler.Dispatch(data)
	if len(actions) != 1 {
		t.Fatalf("action count = %d, want 1", len(actions))
	}
	if actions[0].Action != "send_group_forward_msg" {
		t.Fatalf("action = %q, want send_group_forward_msg", actions[0].Action)
	}
	params, ok := actions[0].Params.(napcat.SendGroupForwardMessageParams)
	if !ok {
		t.Fatalf("params type = %T, want SendGroupForwardMessageParams", actions[0].Params)
	}
	if params.GroupID != 8 || len(params.Messages) != 1 || params.Messages[0].Type != "node" {
		t.Fatalf("params = %+v, want one node for group 8", params)
	}
}

func TestOutboxActionRejectsInvalidTarget(t *testing.T) {
	if _, ok := handler.OutboxAction(brain.OutboxItem{
		MessageType: "group",
		Messages:    []brain.Message{{Type: "text", Text: "queued"}},
	}); ok {
		t.Fatal("OutboxAction returned ok=true, want false")
	}
}
