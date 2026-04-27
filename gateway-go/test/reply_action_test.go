package test

import (
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"

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
	if params.GroupID != 8 || params.Message != "brain says hi" {
		t.Fatalf("params = %+v, want group_id=8 message=brain says hi", params)
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
