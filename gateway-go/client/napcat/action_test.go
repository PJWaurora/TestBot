package napcat

import "testing"

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

func TestNewSendMessageItemsActionConvertsBrainItemsToCQMessage(t *testing.T) {
	action, ok := NewSendMessageItemsAction("group", 9, 8, []BrainMessageItem{
		{Type: "text", Text: "hi [CQ:poke] & ok"},
		{Type: "image", Data: map[string]interface{}{"url": "https://example.test/a,b.png"}},
		{Type: "video", Data: map[string]interface{}{"file": "video.mp4"}},
		{Type: "file", Data: map[string]interface{}{"file": "report.pdf", "name": "report,final.pdf"}},
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

	want := "hi &#91;CQ:poke&#93; &amp; ok" +
		"[CQ:image,file=https://example.test/a&#44;b.png]" +
		"[CQ:video,file=video.mp4]" +
		"[CQ:file,file=report.pdf,name=report&#44;final.pdf]"
	if params.GroupID != 8 || params.Message != want {
		t.Fatalf("params = %+v, want group_id=8 message=%s", params, want)
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
