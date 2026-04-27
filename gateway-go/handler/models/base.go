package models

import "encoding/json"

type BaseEvent struct {
	SelfID        int64           `json:"self_id,omitempty"`
	UserID        int64           `json:"user_id,omitempty"`
	Time          int64           `json:"time,omitempty"`
	MessageID     int64           `json:"message_id,omitempty"`
	MessageSeq    int64           `json:"message_seq,omitempty"`
	RealID        int64           `json:"real_id,omitempty"`
	RealSeq       string          `json:"real_seq,omitempty"`
	PostType      string          `json:"post_type"`
	MessageType   string          `json:"message_type,omitempty"`
	SubType       string          `json:"sub_type,omitempty"`
	RawMessage    string          `json:"raw_message,omitempty"`
	Font          int             `json:"font,omitempty"`
	Message       MessageSegments `json:"message,omitempty"`
	MessageFormat string          `json:"message_format,omitempty"`
	GroupID       int64           `json:"group_id,omitempty"`
	GroupName     string          `json:"group_name,omitempty"`
	TargetID      int64           `json:"target_id,omitempty"`
	Sender        Sender          `json:"sender"`
}

type Sender struct {
	UserID   int64  `json:"user_id,omitempty"`
	NickName string `json:"nickname,omitempty"`
	Card     string `json:"card,omitempty"`
	Role     string `json:"role,omitempty"`
}

type MessageSegments []MessageSegment

func (segments *MessageSegments) UnmarshalJSON(data []byte) error {
	var arraySegments []MessageSegment
	if err := json.Unmarshal(data, &arraySegments); err == nil {
		*segments = arraySegments
		return nil
	}

	var text string
	if err := json.Unmarshal(data, &text); err != nil {
		return err
	}

	*segments = []MessageSegment{
		{
			Type: "text",
			Data: map[string]interface{}{
				"text": text,
			},
		},
	}
	return nil
}

type MessageSegment struct {
	Type string                 `json:"type"`
	Data map[string]interface{} `json:"data"`
}

type BaseImageEvent struct {
	BaseEvent
	ImageURL string `json:"image_url,omitempty"`
}

type BaseJsonEvent struct {
	BaseEvent
	JsonData map[string]interface{} `json:"json_data,omitempty"`
}

type BaseTextEvent struct {
	BaseEvent
	Text string `json:"text,omitempty"`
}

type BaseVideoEvent struct {
	BaseEvent
	VideoURL string `json:"video_url,omitempty"`
}

type BaseReplyEvent struct {
	BaseEvent
	ReplyToMessageID string `json:"reply_to_message_id,omitempty"`
}

type BaseAtEvent struct {
	BaseEvent
	AtUserID string `json:"at_user_id,omitempty"`
}
