"""Legacy in-core Bilibili module.

This module is not loaded by the default Brain registry. It is retained only
as temporary compatibility/reference code while official Bilibili behavior
lives in the external HTTP module service configured through
``BRAIN_MODULE_SERVICES`` and ``docker-compose.modules.yml``.
"""

import os
import re
from typing import Callable

import httpx
from schemas import BrainMessage, BrainResponse

from modules.base import ModuleArguments, ModuleResult, parse_command_invocation


ShortLinkResolver = Callable[[str], tuple[str | None, str | None]]


class BilibiliModule:
    name = "bilibili"
    command_aliases = ("bili", "bilibili", "bv", "b站")
    help_text = (
        "Bilibili 用法：/bili <BV号或链接>，也支持 .bili <BV号或链接>；"
        "直接发送 BV、bilibili.com/video 或 b23.tv 链接也会自动解析。"
    )

    BVID_PATTERN = re.compile(
        r"(?<![0-9A-Za-z])BV[0-9A-Za-z]{10}(?![0-9A-Za-z])"
    )
    BILI_VIDEO_URL_PATTERN = re.compile(
        r"(?:https?://)?(?:www\.|m\.)?bilibili\.com/video/"
        r"(?P<bvid>BV[0-9A-Za-z]{10})(?![0-9A-Za-z])"
    )
    B23_URL_PATTERN = re.compile(
        r"(?:https?://)?(?:www\.)?b23\.tv/[0-9A-Za-z_-]+(?![0-9A-Za-z_-])"
    )

    def __init__(self, short_link_resolver: ShortLinkResolver | None = None) -> None:
        self.short_link_resolver = short_link_resolver

    def detect(self, text: str) -> bool:
        return parse_command_invocation(text, self.command_aliases) is not None or self._extract(text) is not None

    def parse(self, text: str) -> ModuleArguments:
        invocation = parse_command_invocation(text, self.command_aliases)
        if invocation is not None:
            if not invocation.argument:
                return {"kind": "help", "source": "command", "command": invocation.name}
            return self._extract(invocation.argument) or {
                "kind": "invalid",
                "source": "command",
                "command": invocation.name,
                "query": invocation.argument,
            }

        return self._extract(text) or {}

    def call(self, arguments: ModuleArguments) -> ModuleResult:
        bvid = arguments.get("bvid")
        short_url = arguments.get("short_url")

        if isinstance(bvid, str) and bvid:
            return {
                "kind": "video",
                "bvid": bvid,
                "canonical_url": self._canonical_url(bvid),
            }

        if isinstance(short_url, str) and short_url:
            normalized_short_url = self._normalize_url(short_url)
            resolver = self.short_link_resolver or self._resolve_short_link
            bvid, final_url = resolver(normalized_short_url)
            if bvid:
                return {
                    "kind": "video",
                    "bvid": bvid,
                    "short_url": normalized_short_url,
                    "canonical_url": self._canonical_url(bvid),
                    "resolved_url": final_url or self._canonical_url(bvid),
                }
            return {
                "kind": "short_link",
                "short_url": normalized_short_url,
                "canonical_url": final_url or "",
                "resolution": "failed",
            }

        kind = arguments.get("kind")
        if kind == "help":
            return {"kind": "help", "message": self.help_text}
        if kind == "invalid":
            return {"kind": "invalid", "message": "没有识别到 Bilibili BV号或链接。" + self.help_text}

        return {"kind": "unknown", "canonical_url": ""}

    def present(self, result: ModuleResult) -> BrainResponse:
        reply = self._reply_text(result)
        return BrainResponse(
            handled=True,
            reply=reply,
            should_reply=bool(reply),
            messages=[BrainMessage(type="text", text=reply)] if reply else [],
        )

    def _extract(self, text: str) -> ModuleArguments | None:
        video_url_match = self.BILI_VIDEO_URL_PATTERN.search(text)
        if video_url_match:
            bvid = video_url_match.group("bvid")
            return {
                "kind": "video",
                "bvid": bvid,
                "source": "bilibili_url",
                "matched_text": video_url_match.group(0),
            }

        short_url_match = self.B23_URL_PATTERN.search(text)
        if short_url_match:
            return {
                "kind": "short_link",
                "short_url": short_url_match.group(0),
                "source": "b23_url",
                "matched_text": short_url_match.group(0),
            }

        bvid_match = self.BVID_PATTERN.search(text)
        if bvid_match:
            bvid = bvid_match.group(0)
            return {
                "kind": "video",
                "bvid": bvid,
                "source": "bvid",
                "matched_text": bvid,
            }

        return None

    def _reply_text(self, result: ModuleResult) -> str:
        message = result.get("message")
        if isinstance(message, str) and message:
            return message

        bvid = result.get("bvid")
        canonical_url = result.get("canonical_url")
        has_bvid = isinstance(bvid, str) and bvid
        has_canonical_url = isinstance(canonical_url, str) and canonical_url
        if has_bvid and has_canonical_url:
            lines = [f"Bilibili video detected: {bvid}", f"Canonical URL: {canonical_url}"]
            short_url = result.get("short_url")
            resolved_url = result.get("resolved_url")
            if isinstance(short_url, str) and short_url and isinstance(resolved_url, str) and resolved_url:
                lines.append(f"Resolved from: {short_url}")
            return "\n".join(lines)

        short_url = result.get("short_url")
        if isinstance(short_url, str) and short_url:
            return (
                f"Bilibili short link detected: {short_url}\n"
                "Canonical URL: unresolved (b23.tv resolution failed)"
            )

        return ""

    @classmethod
    def _canonical_url(cls, bvid: str) -> str:
        return f"https://www.bilibili.com/video/{bvid}"

    @staticmethod
    def _normalize_url(url: str) -> str:
        if url.startswith(("http://", "https://")):
            return url
        return f"https://{url}"

    @classmethod
    def _resolve_short_link(cls, url: str) -> tuple[str | None, str | None]:
        timeout = _float_env("BILIBILI_SHORT_LINK_TIMEOUT", default=5.0)
        try:
            with httpx.Client(
                follow_redirects=True,
                timeout=timeout,
                headers={"User-Agent": "Mozilla/5.0 TestBot/1.0"},
                trust_env=_bool_env("BILIBILI_TRUST_ENV_PROXY", default=False),
            ) as client:
                response = client.get(url)
        except Exception:
            return None, None

        final_url = str(response.url)
        match = cls.BVID_PATTERN.search(final_url)
        if match:
            return match.group(0), final_url

        match = cls.BVID_PATTERN.search(response.text)
        if match:
            return match.group(0), final_url

        return None, final_url


def _float_env(key: str, default: float) -> float:
    value = os.getenv(key, "")
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _bool_env(key: str, default: bool) -> bool:
    value = os.getenv(key, "")
    if not value:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
