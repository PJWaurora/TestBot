package models

type BaseEvent struct {
	PostType    string `json:"post_type"`
	MessageType string `json:"type"`
	Message     []struct {
		Type string                 `json:"type"`
		Data map[string]interface{} `json:"data"`
	} `json:"message"`
	Sender struct {
		ID       string `json:"id"`
		NickName string `json:"nickname"`
		Card     string `json:"card"`
		Role     string `json:"role,omitempty"`
	}
}

type BaseImageEvent struct {
	BaseEvent
	ImageURL string `json:"image_url"`
}
type BaseJsonEvent struct {
	BaseEvent
	JsonData map[string]interface{} `json:"json_data"`
}

type BaseTextEvent struct {
	BaseEvent
	Text string `json:"text"`
}
type BaseVideoEvent struct {
	BaseEvent
	VideoURL string `json:"video_url"`
}

type BaseReplyEvent struct {
	BaseEvent
	ReplyToMessageID string `json:"reply_to_message_id"`
}

type BaseAtEvent struct {
	BaseEvent
	AtUserID string `json:"at_user_id"`
}
