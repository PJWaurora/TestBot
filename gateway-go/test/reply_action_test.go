package test

import (
	"net/http"
	"net/http/httptest"
	"testing"

	"gateway/client/napcat"
	"gateway/handler"
)

func TestDispatchBuildsGroupTextReplyAction(t *testing.T) {
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

	action := actions[0]
	if action.Action != "send_group_msg" {
		t.Fatalf("action = %q, want send_group_msg", action.Action)
	}

	params, ok := action.Params.(napcat.SendGroupMessageParams)
	if !ok {
		t.Fatalf("params type = %T, want SendGroupMessageParams", action.Params)
	}
	if params.GroupID != 8 || params.Message != "收到：hello" {
		t.Fatalf("params = %+v, want group_id=8 message=收到：hello", params)
	}
}

func TestDispatchBuildsPrivateTextReplyAction(t *testing.T) {
	data := []byte(`{
		"post_type": "message",
		"message_type": "private",
		"user_id": 9,
		"message": [
			{"type": "text", "data": {"text": "hello"}}
		]
	}`)

	actions := handler.Dispatch(data)
	if len(actions) != 1 {
		t.Fatalf("action count = %d, want 1", len(actions))
	}

	action := actions[0]
	if action.Action != "send_private_msg" {
		t.Fatalf("action = %q, want send_private_msg", action.Action)
	}

	params, ok := action.Params.(napcat.SendPrivateMessageParams)
	if !ok {
		t.Fatalf("params type = %T, want SendPrivateMessageParams", action.Params)
	}
	if params.UserID != 9 || params.Message != "收到：hello" {
		t.Fatalf("params = %+v, want user_id=9 message=收到：hello", params)
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

func TestDispatchFallsBackWhenBrainDoesNotHandle(t *testing.T) {
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
	if len(actions) != 1 {
		t.Fatalf("action count = %d, want 1", len(actions))
	}

	params, ok := actions[0].Params.(napcat.SendPrivateMessageParams)
	if !ok {
		t.Fatalf("params type = %T, want SendPrivateMessageParams", actions[0].Params)
	}
	if params.UserID != 9 || params.Message != "收到：hello" {
		t.Fatalf("params = %+v, want legacy fallback", params)
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
