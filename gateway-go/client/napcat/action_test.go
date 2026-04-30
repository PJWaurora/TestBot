package napcat

import (
	"reflect"
	"testing"
)

func TestNewSendTextActionBuildsGroupAction(t *testing.T) {
	action, ok := NewSendTextAction("group", 9, 8, "hello")
	if !ok {
		t.Fatal("NewSendTextAction returned ok=false")
	}
	if action.Action != "send_group_msg" {
		t.Fatalf("action = %q, want send_group_msg", action.Action)
	}

	params, ok := action.Params.(SendGroupMessageParams)
	if !ok {
		t.Fatalf("params type = %T, want SendGroupMessageParams", action.Params)
	}
	if params.GroupID != 8 || params.Message != "hello" {
		t.Fatalf("params = %+v, want group_id=8 message=hello", params)
	}
}

func TestNewTextReplyActionKeepsLegacyPrefix(t *testing.T) {
	action, ok := NewTextReplyAction("private", 9, 0, "hello")
	if !ok {
		t.Fatal("NewTextReplyAction returned ok=false")
	}

	params, ok := action.Params.(SendPrivateMessageParams)
	if !ok {
		t.Fatalf("params type = %T, want SendPrivateMessageParams", action.Params)
	}
	if params.UserID != 9 || params.Message != "收到：hello" {
		t.Fatalf("params = %+v, want user_id=9 message=收到：hello", params)
	}
}

func TestNewSendTextActionRejectsMissingTarget(t *testing.T) {
	if _, ok := NewSendTextAction("group", 9, 0, "hello"); ok {
		t.Fatal("group action with group_id=0 returned ok=true")
	}
	if _, ok := NewSendTextAction("private", 0, 8, "hello"); ok {
		t.Fatal("private action with user_id=0 returned ok=true")
	}
	if _, ok := NewSendTextAction("unknown", 9, 8, "hello"); ok {
		t.Fatal("unknown message type returned ok=true")
	}
}

func TestNewSendMessageItemsActionConvertsBrainItemsToOneBotSegments(t *testing.T) {
	action, ok := NewSendMessageItemsAction("group", 9, 8, []BrainMessageItem{
		{Type: "text", Text: "hi [CQ:poke] & ok"},
		{Type: "image", Data: map[string]interface{}{"url": "https://example.test/a,b.png"}},
		{Type: "video", Data: map[string]interface{}{"file": "video.mp4"}},
		{Type: "reply", Data: map[string]interface{}{"id": "123"}},
		{Type: "at", Data: map[string]interface{}{"qq": "456"}},
		{Type: "json", Data: map[string]interface{}{"data": `{"app":"demo"}`}},
	})
	if !ok {
		t.Fatal("NewSendMessageItemsAction returned ok=false")
	}
	if action.Action != "send_group_msg" {
		t.Fatalf("action = %q, want send_group_msg", action.Action)
	}

	params, ok := action.Params.(SendGroupMessageParams)
	if !ok {
		t.Fatalf("params type = %T, want SendGroupMessageParams", action.Params)
	}

	want := []OneBotMessageSegment{
		{Type: "text", Data: map[string]interface{}{"text": "hi [CQ:poke] & ok"}},
		{Type: "image", Data: map[string]interface{}{"file": "https://example.test/a,b.png"}},
		{Type: "video", Data: map[string]interface{}{"file": "video.mp4"}},
		{Type: "reply", Data: map[string]interface{}{"id": "123"}},
		{Type: "at", Data: map[string]interface{}{"qq": "456"}},
		{Type: "json", Data: map[string]interface{}{"data": `{"app":"demo"}`}},
	}
	if params.GroupID != 8 || !reflect.DeepEqual(params.Message, want) {
		t.Fatalf("params = %+v, want group_id=8 message=%#v", params, want)
	}
}

func TestNewSendForwardMessageActionBuildsGroupForwardAction(t *testing.T) {
	action, ok := NewSendForwardMessageAction("group", 9, 8, []BrainMessageItem{
		{
			Type: "node",
			Data: map[string]interface{}{
				"user_id":  10001,
				"nickname": "Alice",
				"messages": []interface{}{
					map[string]interface{}{"type": "text", "text": "hello"},
					map[string]interface{}{"type": "image", "url": "https://example.test/a.png"},
				},
			},
		},
		{Type: "node", Text: "plain node", Data: map[string]interface{}{"user_id": 10002, "nickname": "Bob"}},
	})
	if !ok {
		t.Fatal("NewSendForwardMessageAction returned ok=false")
	}
	if action.Action != "send_group_forward_msg" {
		t.Fatalf("action = %q, want send_group_forward_msg", action.Action)
	}

	params, ok := action.Params.(SendGroupForwardMessageParams)
	if !ok {
		t.Fatalf("params type = %T, want SendGroupForwardMessageParams", action.Params)
	}
	if params.GroupID != 8 || len(params.Messages) != 2 {
		t.Fatalf("params = %+v, want group_id=8 with 2 nodes", params)
	}
	if params.Messages[0].Type != "node" || params.Messages[1].Type != "node" {
		t.Fatalf("messages = %+v, want node segments", params.Messages)
	}
}

func TestBrainMessageItemsToCQStringUsesDataFallbacks(t *testing.T) {
	message, ok := BrainMessageItemsToCQString([]BrainMessageItem{
		{Type: "text", Data: map[string]interface{}{"content": "hello"}},
		{Type: "image", Data: map[string]interface{}{"file": "image.png"}},
	})
	if !ok {
		t.Fatal("BrainMessageItemsToCQString returned ok=false")
	}

	want := "hello[CQ:image,file=image.png]"
	if message != want {
		t.Fatalf("message = %q, want %q", message, want)
	}
}

func TestBrainMessageItemsToCQStringRejectsUnsupportedItems(t *testing.T) {
	if _, ok := BrainMessageItemsToCQString([]BrainMessageItem{{Type: "audio", File: "audio.mp3"}}); ok {
		t.Fatal("unsupported item returned ok=true")
	}
	if _, ok := BrainMessageItemsToCQString([]BrainMessageItem{{Type: "image"}}); ok {
		t.Fatal("image item without file/url returned ok=true")
	}
}
