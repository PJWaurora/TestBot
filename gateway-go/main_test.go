package main

import (
	"os"
	"testing"
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
