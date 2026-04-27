import re

from schemas import BrainMessage, BrainResponse

from modules.base import ModuleArguments, ModuleResult


class BilibiliModule:
    name = "bilibili"

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

    def detect(self, text: str) -> bool:
        return self._extract(text) is not None

    def parse(self, text: str) -> ModuleArguments:
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
            return {
                "kind": "short_link",
                "short_url": self._normalize_url(short_url),
                "canonical_url": "",
                "resolution": "pending",
            }

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
        bvid = result.get("bvid")
        canonical_url = result.get("canonical_url")
        has_bvid = isinstance(bvid, str) and bvid
        has_canonical_url = isinstance(canonical_url, str) and canonical_url
        if has_bvid and has_canonical_url:
            return f"Bilibili video detected: {bvid}\nCanonical URL: {canonical_url}"

        short_url = result.get("short_url")
        if isinstance(short_url, str) and short_url:
            return (
                f"Bilibili short link detected: {short_url}\n"
                "Canonical URL: unresolved (b23.tv resolution disabled)"
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
