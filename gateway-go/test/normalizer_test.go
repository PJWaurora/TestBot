package test

import (
	"os"
	"path/filepath"
	"testing"

	"gateway/handler/normalizer"
)

func loadNormalized(t *testing.T, elems ...string) normalizer.IncomingMessage {
	t.Helper()

	parts := append([]string{"..", "..", "json_example"}, elems...)
	data, err := os.ReadFile(filepath.Join(parts...))
	if err != nil {
		t.Fatalf("read fixture: %v", err)
	}

	message, err := normalizer.NormalizeBytes(data)
	if err != nil {
		t.Fatalf("normalize fixture: %v", err)
	}

	return message
}

func TestNormalizeGroupTextMessage(t *testing.T) {
	message := loadNormalized(t, "group", "text_example.json")

	if message.PrimaryType() != "text" {
		t.Fatalf("primary type = %q, want text", message.PrimaryType())
	}
	if message.MessageType != "group" {
		t.Fatalf("message type = %q, want group", message.MessageType)
	}
	if message.UserID != 1 || message.GroupID != 1 {
		t.Fatalf("ids = user:%d group:%d, want 1/1", message.UserID, message.GroupID)
	}
	if message.Sender.UserID != 1 || message.Sender.NickName != "用户昵称" || message.Sender.Card != "群昵称" {
		t.Fatalf("sender = %+v, want user_id=1 nickname=用户昵称 card=群昵称", message.Sender)
	}
	if message.Text != "文字消息内容" {
		t.Fatalf("text = %q, want 文字消息内容", message.Text)
	}
}

func TestNormalizePrivateTextMessage(t *testing.T) {
	message := loadNormalized(t, "private", "text_private_example.json")

	if message.PrimaryType() != "text" {
		t.Fatalf("primary type = %q, want text", message.PrimaryType())
	}
	if message.MessageType != "private" {
		t.Fatalf("message type = %q, want private", message.MessageType)
	}
	if message.TargetID != 1 || message.GroupID != 0 {
		t.Fatalf("target/group ids = %d/%d, want 1/0", message.TargetID, message.GroupID)
	}
	if message.Text != "1" {
		t.Fatalf("text = %q, want 1", message.Text)
	}
}

func TestNormalizeGroupImageMessage(t *testing.T) {
	message := loadNormalized(t, "group", "image_example.json")

	if message.PrimaryType() != "image" {
		t.Fatalf("primary type = %q, want image", message.PrimaryType())
	}
	if len(message.Images) != 1 {
		t.Fatalf("image count = %d, want 1", len(message.Images))
	}

	image := message.Images[0]
	if image.URL != "https://multimedia.nt.qq.com.cn" {
		t.Fatalf("image url = %q", image.URL)
	}
	if image.File != "1.jpg" || image.Summary != "[动画表情]" || image.SubType != "1" || image.FileSize != "823665" {
		t.Fatalf("image = %+v", image)
	}
}

func TestNormalizeGroupJSONMessage(t *testing.T) {
	message := loadNormalized(t, "group", "json_example.json")

	if message.PrimaryType() != "json" {
		t.Fatalf("primary type = %q, want json", message.PrimaryType())
	}
	if len(message.JSONMessages) != 1 {
		t.Fatalf("json message count = %d, want 1", len(message.JSONMessages))
	}

	card := message.JSONMessages[0]
	if card.Raw == "" {
		t.Fatal("json raw data is empty")
	}
	if card.Parsed["app"] != "com.tencent.miniapp_01" {
		t.Fatalf("json app = %v, want com.tencent.miniapp_01", card.Parsed["app"])
	}
	prompt, ok := card.Parsed["prompt"].(string)
	if !ok || prompt == "" {
		t.Fatalf("json prompt = %v, want non-empty string", card.Parsed["prompt"])
	}
}

func TestNormalizeReplyAtTextSegments(t *testing.T) {
	data := []byte(`{
		"post_type": "message",
		"message_type": "group",
		"user_id": 9,
		"group_id": 8,
		"sender": {"user_id": 9, "nickname": "tester"},
		"message": [
			{"type": "reply", "data": {"id": "123"}},
			{"type": "at", "data": {"qq": 456}},
			{"type": "text", "data": {"text": " hello"}}
		]
	}`)

	message, err := normalizer.NormalizeBytes(data)
	if err != nil {
		t.Fatalf("normalize synthetic message: %v", err)
	}

	if message.PrimaryType() != "reply" {
		t.Fatalf("primary type = %q, want reply", message.PrimaryType())
	}
	if message.ReplyToMessageID != 123 {
		t.Fatalf("reply id = %d, want 123", message.ReplyToMessageID)
	}
	if len(message.AtUserIDs) != 1 || message.AtUserIDs[0] != 456 {
		t.Fatalf("at users = %v, want [456]", message.AtUserIDs)
	}
	if message.Text != " hello" {
		t.Fatalf("text = %q, want ' hello'", message.Text)
	}
}

func TestNormalizeAtAllRoutesToAt(t *testing.T) {
	data := []byte(`{
		"post_type": "message",
		"message_type": "group",
		"user_id": 9,
		"group_id": 8,
		"message": [
			{"type": "at", "data": {"qq": "all"}},
			{"type": "text", "data": {"text": " announcement"}}
		]
	}`)

	message, err := normalizer.NormalizeBytes(data)
	if err != nil {
		t.Fatalf("normalize at-all message: %v", err)
	}

	if message.PrimaryType() != "at" {
		t.Fatalf("primary type = %q, want at", message.PrimaryType())
	}
	if !message.AtAll {
		t.Fatal("AtAll = false, want true")
	}
	if len(message.AtUserIDs) != 0 {
		t.Fatalf("at users = %v, want empty for at-all", message.AtUserIDs)
	}
	if message.Text != " announcement" {
		t.Fatalf("text = %q, want ' announcement'", message.Text)
	}
}

func TestNormalizeUsesJSONNumberForLargeSegmentID(t *testing.T) {
	const largeID int64 = 9007199254740993
	data := []byte(`{
		"post_type": "message",
		"message_type": "group",
		"user_id": 9,
		"group_id": 8,
		"message": [
			{"type": "at", "data": {"qq": 9007199254740993}}
		]
	}`)

	message, err := normalizer.NormalizeBytes(data)
	if err != nil {
		t.Fatalf("normalize large-id message: %v", err)
	}

	if len(message.AtUserIDs) != 1 || message.AtUserIDs[0] != largeID {
		t.Fatalf("at users = %v, want [%d]", message.AtUserIDs, largeID)
	}
}

func TestNormalizeStringMessageFallback(t *testing.T) {
	data := []byte(`{
		"post_type": "message",
		"message_type": "private",
		"user_id": 7,
		"message": "plain text"
	}`)

	message, err := normalizer.NormalizeBytes(data)
	if err != nil {
		t.Fatalf("normalize string message: %v", err)
	}

	if message.PrimaryType() != "text" || message.Text != "plain text" {
		t.Fatalf("message = type:%q text:%q, want text/plain text", message.PrimaryType(), message.Text)
	}
}
