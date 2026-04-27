package test

import (
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
