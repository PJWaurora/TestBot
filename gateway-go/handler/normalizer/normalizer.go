package normalizer

import (
	"bytes"
	"encoding/json"
	"fmt"
	"math"
	"strconv"
	"strings"

	"gateway/handler/models"
)

type IncomingMessage struct {
	PostType         string
	MessageType      string
	SubType          string
	MessageID        int64
	UserID           int64
	GroupID          int64
	GroupName        string
	TargetID         int64
	Sender           models.Sender
	Text             string
	TextSegments     []string
	Images           []ImageContent
	JSONMessages     []JSONContent
	Videos           []VideoContent
	AtUserIDs        []int64
	AtAll            bool
	ReplyToMessageID int64
	UnknownTypes     []string
	Segments         []models.MessageSegment
	Raw              models.BaseEvent
}

type ImageContent struct {
	URL      string
	File     string
	Summary  string
	SubType  string
	FileSize string
}

type JSONContent struct {
	Raw    string
	Parsed map[string]interface{}
}

type VideoContent struct {
	URL  string
	File string
}

func NormalizeBytes(data []byte) (IncomingMessage, error) {
	var event models.BaseEvent
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.UseNumber()
	if err := decoder.Decode(&event); err != nil {
		return IncomingMessage{}, fmt.Errorf("unmarshal base event: %w", err)
	}

	return NormalizeEvent(event), nil
}

func NormalizeEvent(event models.BaseEvent) IncomingMessage {
	message := IncomingMessage{
		PostType:    event.PostType,
		MessageType: event.MessageType,
		SubType:     event.SubType,
		MessageID:   event.MessageID,
		UserID:      event.UserID,
		GroupID:     event.GroupID,
		GroupName:   event.GroupName,
		TargetID:    event.TargetID,
		Sender:      event.Sender,
		Segments:    []models.MessageSegment(event.Message),
		Raw:         event,
	}

	for _, segment := range event.Message {
		switch segment.Type {
		case "text":
			text := segmentString(segment, "text")
			if text == "" {
				continue
			}
			message.TextSegments = append(message.TextSegments, text)

		case "image":
			message.Images = append(message.Images, ImageContent{
				URL:      segmentString(segment, "url"),
				File:     segmentString(segment, "file"),
				Summary:  segmentString(segment, "summary"),
				SubType:  segmentString(segment, "sub_type"),
				FileSize: segmentString(segment, "file_size"),
			})

		case "json":
			raw := segmentString(segment, "data")
			jsonMessage := JSONContent{Raw: raw}
			if raw != "" {
				var parsed map[string]interface{}
				decoder := json.NewDecoder(strings.NewReader(raw))
				decoder.UseNumber()
				if err := decoder.Decode(&parsed); err == nil {
					jsonMessage.Parsed = parsed
				}
			}
			message.JSONMessages = append(message.JSONMessages, jsonMessage)

		case "video":
			message.Videos = append(message.Videos, VideoContent{
				URL:  segmentString(segment, "url"),
				File: segmentString(segment, "file"),
			})

		case "at":
			if segmentString(segment, "qq") == "all" {
				message.AtAll = true
				continue
			}
			if id, ok := segmentInt64(segment, "qq"); ok {
				message.AtUserIDs = append(message.AtUserIDs, id)
			}

		case "reply":
			if id, ok := segmentInt64(segment, "id"); ok {
				message.ReplyToMessageID = id
			}

		default:
			message.UnknownTypes = append(message.UnknownTypes, segment.Type)
		}
	}

	message.Text = strings.Join(message.TextSegments, "")
	return message
}

func (message IncomingMessage) PrimaryType() string {
	switch {
	case message.ReplyToMessageID != 0:
		return "reply"
	case message.AtAll || len(message.AtUserIDs) > 0:
		return "at"
	case len(message.TextSegments) > 0:
		return "text"
	case len(message.Images) > 0:
		return "image"
	case len(message.JSONMessages) > 0:
		return "json"
	case len(message.Videos) > 0:
		return "video"
	case len(message.UnknownTypes) > 0:
		return message.UnknownTypes[0]
	default:
		return "meta_or_other"
	}
}

func segmentString(segment models.MessageSegment, key string) string {
	if segment.Data == nil {
		return ""
	}

	value, ok := segment.Data[key]
	if !ok || value == nil {
		return ""
	}

	switch typed := value.(type) {
	case string:
		return typed
	case json.Number:
		return typed.String()
	case float64:
		if typed == float64(int64(typed)) {
			return strconv.FormatInt(int64(typed), 10)
		}
		return strconv.FormatFloat(typed, 'f', -1, 64)
	case float32:
		return strconv.FormatFloat(float64(typed), 'f', -1, 32)
	case int:
		return strconv.Itoa(typed)
	case int64:
		return strconv.FormatInt(typed, 10)
	case bool:
		return strconv.FormatBool(typed)
	default:
		return fmt.Sprint(typed)
	}
}

func segmentInt64(segment models.MessageSegment, key string) (int64, bool) {
	if segment.Data == nil {
		return 0, false
	}

	value, ok := segment.Data[key]
	if !ok || value == nil {
		return 0, false
	}

	switch typed := value.(type) {
	case int64:
		return typed, true
	case int:
		return int64(typed), true
	case float64:
		if typed < float64(math.MinInt64) || typed > float64(math.MaxInt64) || typed != math.Trunc(typed) {
			return 0, false
		}
		return int64(typed), true
	case json.Number:
		parsed, err := typed.Int64()
		return parsed, err == nil
	case string:
		if typed == "all" {
			return 0, false
		}
		parsed, err := strconv.ParseInt(typed, 10, 64)
		return parsed, err == nil
	default:
		return 0, false
	}
}
