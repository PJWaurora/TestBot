package main

import (
	"gateway/client/brain"
	"gateway/client/napcat"
	"os"
	"strings"
	"testing"
	"time"
)

func TestGetenvUsesFallbackForMissingValue(t *testing.T) {
	t.Setenv("TESTBOT_MISSING_VALUE", "")

	if got := getenv("TESTBOT_MISSING_VALUE", "fallback"); got != "fallback" {
		t.Fatalf("getenv returned %q, want fallback", got)
	}
}

func TestGetenvUsesEnvironmentValue(t *testing.T) {
	const key = "TESTBOT_PRESENT_VALUE"
	t.Setenv(key, "configured")

	if got := getenv(key, "fallback"); got != "configured" {
		t.Fatalf("getenv returned %q, want configured", got)
	}
}

func TestGetenvTreatsUnsetAsFallback(t *testing.T) {
	const key = "TESTBOT_UNSET_VALUE"
	prev, hadPrev := os.LookupEnv(key)
	t.Cleanup(func() {
		if hadPrev {
			if err := os.Setenv(key, prev); err != nil {
				t.Fatalf("restore %s: %v", key, err)
			}
			return
		}
		if err := os.Unsetenv(key); err != nil {
			t.Fatalf("restore unset %s: %v", key, err)
		}
	})

	if err := os.Unsetenv(key); err != nil {
		t.Fatalf("unset %s: %v", key, err)
	}

	if got := getenv(key, "fallback"); got != "fallback" {
		t.Fatalf("getenv returned %q, want fallback", got)
	}
}

func TestSendOutboxItemWaitsForNapcatActionResponseSuccess(t *testing.T) {
	done := make(chan struct{})
	sendQueue := make(chan queuedAction, 1)
	pendingActions := newPendingNapcatActions()

	result := make(chan error, 1)
	go func() {
		queued := <-sendQueue
		if queued.action.Echo == "" {
			result <- nil
			return
		}
		queued.writeResult <- nil
		if !pendingActions.complete(napcat.Response{
			Echo:    queued.action.Echo,
			Status:  "ok",
			RetCode: 0,
		}) {
			result <- nil
			return
		}
		result <- nil
	}()

	err := sendOutboxItem(done, sendQueue, pendingActions, brain.OutboxItem{
		ID:         42,
		TargetType: "group",
		TargetID:   "10001",
		Messages:   []brain.Message{{Type: "text", Text: "hello"}},
	}, time.Second)
	if err != nil {
		t.Fatalf("sendOutboxItem error = %v", err)
	}
	if err := <-result; err != nil {
		t.Fatal(err)
	}
}

func TestSendOutboxItemReturnsNapcatActionResponseFailure(t *testing.T) {
	done := make(chan struct{})
	sendQueue := make(chan queuedAction, 1)
	pendingActions := newPendingNapcatActions()

	go func() {
		queued := <-sendQueue
		queued.writeResult <- nil
		pendingActions.complete(napcat.Response{
			Echo:    queued.action.Echo,
			Status:  "failed",
			RetCode: 1400,
			Message: "permission denied",
		})
	}()

	err := sendOutboxItem(done, sendQueue, pendingActions, brain.OutboxItem{
		ID:         42,
		TargetType: "private",
		TargetID:   "10001",
		Messages:   []brain.Message{{Type: "text", Text: "hello"}},
	}, time.Second)
	if err == nil || !strings.Contains(err.Error(), "permission denied") {
		t.Fatalf("sendOutboxItem error = %v, want permission denied", err)
	}
}

func TestSendOutboxItemTimesOutWaitingForNapcatActionResponse(t *testing.T) {
	done := make(chan struct{})
	sendQueue := make(chan queuedAction, 1)
	pendingActions := newPendingNapcatActions()

	go func() {
		queued := <-sendQueue
		queued.writeResult <- nil
	}()

	err := sendOutboxItem(done, sendQueue, pendingActions, brain.OutboxItem{
		ID:         42,
		TargetType: "group",
		TargetID:   "10001",
		Messages:   []brain.Message{{Type: "text", Text: "hello"}},
	}, time.Millisecond)
	if err == nil || !strings.Contains(err.Error(), "timed out") {
		t.Fatalf("sendOutboxItem error = %v, want timeout", err)
	}
}

func TestHandlePendingNapcatResponseOnlyConsumesMatchedEcho(t *testing.T) {
	pendingActions := newPendingNapcatActions()
	echo, response := pendingActions.register(42)

	if handlePendingNapcatResponse([]byte(`{"echo":"other","status":"ok","retcode":0}`), pendingActions) {
		t.Fatal("unmatched echo was consumed")
	}
	if !handlePendingNapcatResponse([]byte(`{"echo":"`+echo+`","status":"ok","retcode":0}`), pendingActions) {
		t.Fatal("matched echo was not consumed")
	}

	select {
	case got := <-response:
		if got.Echo != echo || !got.Success() {
			t.Fatalf("response = %+v, want successful matched response", got)
		}
	default:
		t.Fatal("pending response channel is empty")
	}
}
