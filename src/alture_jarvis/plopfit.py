from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from typing import Any

from .config import JarvisConfig
from .models import RiskLevel
from .tool_gateway import ToolGateway, ToolSpec


def _decode(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value



def _raise_if_blocked(name: str, arguments: Any, result: Any) -> Any:
    """바깥 함수가 「막혔다」를 **글자로** 돌려주면 실패로 올린다.

    ★ 2026-10-04 레딧 기준선 판(70d6cffc): `reddit_hot` 이 `{"ok": false, "error": "reddit_blocked"}` 를 글자로 돌려줬는데
      걸음은 「성공」으로 찍혔고, 안내는 이 PC 에 없는 도구(tavily_search)를 권했다. 실패는 실패로 알리고, 되는 길을 댄다.
    """
    text = str(result.get("text") or "") if isinstance(result, dict) else ""
    if '"ok": false' not in text and '"ok":false' not in text:
        return result
    try:
        parsed = json.loads(text)
    except ValueError:
        return result
    if not isinstance(parsed, dict) or parsed.get("ok") is not False:
        return result
    error = str(parsed.get("error") or "blocked")
    if name == "reddit_hot":
        board = str((arguments or {}).get("subreddit") or "").strip().strip("/") or "LocalLLaMA"
        raise RuntimeError(
            f"{error} — 레딧이 이 통로를 막았다. browser_open 으로 https://www.reddit.com/r/{board}/hot/ 를 열고 "
            "browser_extract 로 읽어라 — 글 목록(제목·댓글 수·추천 수·글 주소)이 같이 온다."
        )
    raise RuntimeError(f"{error} — {str(parsed.get('message') or '')[:200]}")

class PlopfitTools:
    def __init__(self, config: JarvisConfig) -> None:
        self.config = config
        self._instances: dict[str, Any] = {}
        self._definitions = [
            self._function("naver_news", "국내 최신 뉴스와 한국어 기사 출처를 네이버 검색 API로 찾는다.", {"query": {"type": "string"}, "display": {"type": "integer", "minimum": 1, "maximum": 20}}, ["query"]),
            self._function("naver_web", "한국어·국내 웹 자료의 제목, 요약, 원문 URL을 네이버 검색 API로 찾는다.", {"query": {"type": "string"}, "display": {"type": "integer", "minimum": 1, "maximum": 20}}, ["query"]),
            self._function("github_search", "GitHub API로 공개 저장소를 검색하고 별점·설명·저장소 URL을 가져온다.", {"query": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 10}}, ["query"]),
            self._function("reddit_hot", "Reddit 공개 인기글을 조회한다.", {"subreddit": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 20}}, ["subreddit"]),
            self._function("hackernews_top", "Hacker News의 최신 인기 기술 글을 조회한다.", {"limit": {"type": "integer", "minimum": 1, "maximum": 20}}),
            self._function("google_trend", "Google Trends 공개 관심도 정보를 조회한다.", {"keyword": {"type": "string"}}, ["keyword"]),
        ]

    @staticmethod
    def _function(
        name: str,
        description: str,
        properties: dict[str, Any],
        required: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required or [],
                },
            },
        }

    @property
    def ollama_tools(self) -> list[dict[str, Any]]:
        return list(self._definitions)

    @property
    def active_ollama_tools(self) -> list[dict[str, Any]]:
        return list(self._definitions) if self.config.plopfit_enabled else []

    @property
    def names(self) -> set[str]:
        return {str(item["function"]["name"]) for item in self.active_ollama_tools}

    def _load(self, filename: str) -> Any:
        if filename in self._instances:
            return self._instances[filename]
        path = self.config.plopfit_functions_dir / filename
        if not path.exists():
            raise RuntimeError(f"plopfit_function_missing:{path}")
        os.environ["PLOPFIT_LIB_DIR"] = str(self.config.plopfit_lib_dir)
        module_name = f"alture_jarvis_plopfit_{Path(filename).stem}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"plopfit_module_load_failed:{path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        instance = module.Tools()
        self._instances[filename] = instance
        return instance

    def call(self, filename: str, method: str, arguments: dict[str, Any]) -> Any:
        instance = self._load(filename)
        function = getattr(instance, method)
        return _decode(function(**arguments))

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self.config.plopfit_enabled,
            "functions_dir": str(self.config.plopfit_functions_dir),
            "functions_available": (
                self.config.plopfit_enabled and self.config.plopfit_functions_dir.is_dir()
            ),
            "lib_dir": str(self.config.plopfit_lib_dir),
            "lib_available": self.config.plopfit_enabled and self.config.plopfit_lib_dir.is_dir(),
        }

    def register(self, gateway: ToolGateway) -> None:
        handlers = {
            "naver_news": ("plopfit_naver.py", "naver_search_news"),
            "naver_web": ("plopfit_naver.py", "naver_search_web"),
            "reddit_hot": ("plopfit_agent.py", "reddit_hot"),
            "hackernews_top": ("plopfit_agent.py", "hackernews_top"),
            "github_search": ("plopfit_agent.py", "github_search"),
            "google_trend": ("plopfit_agent.py", "google_trend"),
        }
        for definition in self._definitions:
            name = str(definition["function"]["name"])
            filename, method = handlers[name]
            gateway.register(
                ToolSpec(
                    name=name,
                    description=str(definition["function"]["description"]),
                    parameters=dict(definition["function"].get("parameters") or {}),
                    risk_level=RiskLevel.L1,
                    handler=lambda args, f=filename, m=method, n=name: _raise_if_blocked(n, args, self.call(f, m, args)),
                    enabled=self.config.plopfit_enabled,
                )
            )
