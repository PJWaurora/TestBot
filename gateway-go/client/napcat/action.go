package napcat

import "fmt"

type Action struct {
	Action string      `json:"action"`
	Params interface{} `json:"params"`
	Echo   string      `json:"echo,omitempty"`
}

type Response struct {
	Status  string      `json:"status,omitempty"`
	RetCode int         `json:"retcode,omitempty"`
	Data    interface{} `json:"data,omitempty"`
	Message string      `json:"message,omitempty"`
	Wording string      `json:"wording,omitempty"`
	Echo    string      `json:"echo,omitempty"`
}

type SendGroupMessageParams struct {
	GroupID int64  `json:"group_id"`
	Message string `json:"message"`
}

type SendPrivateMessageParams struct {
	UserID  int64  `json:"user_id"`
	Message string `json:"message"`
}

func NewTextReplyAction(messageType string, userID, groupID int64, text string) (Action, bool) {
	reply := fmt.Sprintf("收到：%s", text)

	switch messageType {
	case "group":
		if groupID == 0 {
			return Action{}, false
		}
		return Action{
			Action: "send_group_msg",
			Params: SendGroupMessageParams{
				GroupID: groupID,
				Message: reply,
			},
		}, true

	case "private":
		if userID == 0 {
			return Action{}, false
		}
		return Action{
			Action: "send_private_msg",
			Params: SendPrivateMessageParams{
				UserID:  userID,
				Message: reply,
			},
		}, true

	default:
		return Action{}, false
	}
}
