from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta
from typing import Any, Protocol

from schemas import BrainMessage, BrainResponse

from modules.base import ModuleArguments, ModuleResult


TOOL_NAME = "weather.get_forecast"
USAGE_TEXT = "请指定城市名：天气 <城市> 或 <城市>天气"


class ForecastProvider(Protocol):
    name: str

    def get_forecast(self, city: str) -> dict[str, Any]:
        ...


class LocalForecastProvider:
    """Deterministic provider shaped like the legacy weather API response."""

    name = "local_fake"

    _BASE_DATE = date(2026, 1, 1)
    _REPORT_TIME = datetime(2026, 1, 1, 8, 0, 0)
    _CONDITIONS = ("晴", "多云", "阴", "小雨", "阵雨", "雷阵雨", "小雪")
    _WINDS = ("东", "南", "西", "北", "东北", "东南", "西北", "西南")
    _KNOWN_LOCATIONS = {
        "北京": ("北京", "北京"),
        "北京市": ("北京", "北京"),
        "上海": ("上海", "上海"),
        "上海市": ("上海", "上海"),
        "广州": ("广东", "广州"),
        "广州市": ("广东", "广州"),
        "深圳": ("广东", "深圳"),
        "深圳市": ("广东", "深圳"),
        "杭州": ("浙江", "杭州"),
        "杭州市": ("浙江", "杭州"),
        "成都": ("四川", "成都"),
        "成都市": ("四川", "成都"),
        "重庆": ("重庆", "重庆"),
        "重庆市": ("重庆", "重庆"),
        "武汉": ("湖北", "武汉"),
        "武汉市": ("湖北", "武汉"),
        "西安": ("陕西", "西安"),
        "西安市": ("陕西", "西安"),
        "南京": ("江苏", "南京"),
        "南京市": ("江苏", "南京"),
        "苏州": ("江苏", "苏州"),
        "苏州市": ("江苏", "苏州"),
        "天津": ("天津", "天津"),
        "天津市": ("天津", "天津"),
    }

    def get_forecast(self, city: str) -> dict[str, Any]:
        query = city.strip()
        seed = int.from_bytes(hashlib.sha256(query.encode("utf-8")).digest()[:4], "big")
        province, display_city = self._resolve_location(query)
        base_low = -4 + seed % 27
        casts = []

        for offset in range(4):
            forecast_date = self._BASE_DATE + timedelta(days=offset)
            day_weather = self._CONDITIONS[(seed + offset * 2) % len(self._CONDITIONS)]
            night_weather = self._CONDITIONS[(seed + offset * 2 + 1) % len(self._CONDITIONS)]
            night_temp = base_low + (offset % 3) - 1
            day_temp = night_temp + 6 + ((seed >> (offset * 3)) % 6)
            day_wind = self._WINDS[(seed + offset) % len(self._WINDS)]

            casts.append(
                {
                    "date": forecast_date.isoformat(),
                    "week": str(forecast_date.isoweekday()),
                    "dayweather": day_weather,
                    "nightweather": night_weather,
                    "daytemp": str(day_temp),
                    "nighttemp": str(night_temp),
                    "daywind": day_wind,
                    "nightwind": day_wind,
                    "daypower": str(2 + ((seed + offset) % 4)),
                    "nightpower": str(1 + ((seed + offset) % 3)),
                }
            )

        return {
            "province": province,
            "city": display_city,
            "adcode": f"local-{seed % 1_000_000:06d}",
            "reporttime": self._REPORT_TIME.strftime("%Y-%m-%d %H:%M:%S"),
            "casts": casts,
            "source": self.name,
        }

    def _resolve_location(self, city: str) -> tuple[str, str]:
        if city in self._KNOWN_LOCATIONS:
            return self._KNOWN_LOCATIONS[city]

        if city.endswith("市") and city[:-1] in self._KNOWN_LOCATIONS:
            return self._KNOWN_LOCATIONS[city[:-1]]

        return "", city


class WeatherModule:
    name = "weather"

    _AFTER_COMMAND = re.compile(r"^天气(?:\s+|[:：])?(?P<city>.+)$")
    _BEFORE_COMMAND = re.compile(r"^(?P<city>.+?)\s*天气$")

    def __init__(self, provider: ForecastProvider | None = None) -> None:
        self.provider = provider or LocalForecastProvider()

    def detect(self, text: str) -> bool:
        stripped = text.strip()
        return stripped == "天气" or self._extract_city(stripped) is not None

    def parse(self, text: str) -> ModuleArguments:
        city = self._extract_city(text.strip())
        return {"city": city or "", "query": text.strip()}

    def call(self, arguments: ModuleArguments) -> ModuleResult:
        city = str(arguments.get("city", "")).strip()
        if not city:
            return {
                "tool_name": TOOL_NAME,
                "ok": False,
                "error": "missing_city",
                "message": USAGE_TEXT,
            }

        try:
            forecast = self.provider.get_forecast(city)
        except Exception as exc:
            return {
                "tool_name": TOOL_NAME,
                "ok": False,
                "city": city,
                "error": "provider_error",
                "message": f"查询 {city} 天气失败：{exc}",
            }

        return {
            "tool_name": TOOL_NAME,
            "ok": True,
            "city": city,
            "provider": getattr(self.provider, "name", "unknown"),
            "forecast": forecast,
        }

    def present(self, result: ModuleResult) -> BrainResponse:
        reply = self._reply_text(result)
        metadata = {
            "tool_name": str(result.get("tool_name", TOOL_NAME)),
            "ok": bool(result.get("ok", False)),
        }
        if result.get("city"):
            metadata["city"] = str(result["city"])
        if result.get("provider"):
            metadata["provider"] = str(result["provider"])
        if result.get("error"):
            metadata["error"] = str(result["error"])

        return BrainResponse(
            handled=True,
            reply=reply,
            should_reply=bool(reply),
            messages=[BrainMessage(type="text", text=reply)] if reply else [],
            metadata=metadata,
        )

    def _extract_city(self, text: str) -> str | None:
        normalized = text.strip()
        if not normalized:
            return None

        after_match = self._AFTER_COMMAND.match(normalized)
        if after_match:
            return self._clean_city(after_match.group("city"))

        before_match = self._BEFORE_COMMAND.match(normalized)
        if before_match:
            return self._clean_city(before_match.group("city"))

        return None

    @staticmethod
    def _clean_city(city: str) -> str | None:
        cleaned = city.strip(" \t\r\n:：,，。")
        return cleaned or None

    def _reply_text(self, result: ModuleResult) -> str:
        if not result.get("ok"):
            return str(result.get("message") or USAGE_TEXT)

        forecast = result.get("forecast")
        if not isinstance(forecast, dict):
            return "天气数据格式不正确"

        return self._format_forecast_text(forecast)

    @staticmethod
    def _format_forecast_text(forecast: dict[str, Any]) -> str:
        province = str(forecast.get("province", ""))
        city = str(forecast.get("city", ""))
        location = f"{province}{city}" if province and province != city else city or province
        reporttime = str(forecast.get("reporttime", ""))
        casts = forecast.get("casts", [])

        if not isinstance(casts, list) or not casts:
            return f"{location or '该城市'}暂无天气预报数据"

        title = f"{location}天气预报" if location else "天气预报"
        if forecast.get("source") == LocalForecastProvider.name:
            title = f"{title}（本地模拟）"

        lines = [title, f"更新时间：{reporttime}", ""]
        day_labels = ("今天", "明天", "后天")

        for index, cast in enumerate(casts[:4]):
            if not isinstance(cast, dict):
                continue

            date_text = str(cast.get("date", ""))
            label = day_labels[index] if index < len(day_labels) else date_text[-5:]
            day_weather = str(cast.get("dayweather", ""))
            night_weather = str(cast.get("nightweather", ""))
            day_temp = str(cast.get("daytemp", ""))
            night_temp = str(cast.get("nighttemp", ""))
            day_wind = str(cast.get("daywind", ""))
            day_power = str(cast.get("daypower", ""))

            if day_weather == night_weather:
                weather = day_weather
            else:
                weather = f"{day_weather}转{night_weather}"
            temp_range = f"{night_temp}°C ~ {day_temp}°C"
            wind = f"{day_wind}风 {day_power}级"

            lines.append(f"【{label}】{weather}")
            lines.append(f"  {temp_range} | {wind}")

        return "\n".join(lines)


__all__ = ["ForecastProvider", "LocalForecastProvider", "WeatherModule"]
