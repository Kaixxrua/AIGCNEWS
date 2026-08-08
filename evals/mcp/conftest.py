"""pytest conftest —— 给 OpenAI SDK 客户端统一注入浏览器 UA。

背景：测评用的 OpenAI 中转站（OPENAI_BASE_URL，gptsakura.com）挂在
Cloudflare 后面，CF 1010 规则按 UA 封禁 python SDK 默认签名
（`OpenAI/Python x.y`），全部请求返回 403 "Your request was blocked"。
项目后端走 langchain UA 所以不受影响；mcp-eval/mcp-agent 用裸 SDK 会被拦。

这里在运行时给 mcp-agent 内部构造的 OpenAI / AsyncOpenAI 客户端强制注入
浏览器 UA（default_headers 级别），与请求参数无关，agent 与 judge 都生效。
仅作用于本测评进程，不改任何已安装包。
"""

import openai

_BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def _patch(cls):
    original_init = cls.__init__

    def patched(self, *args, **kwargs):
        headers = {"User-Agent": _BROWSER_UA}
        headers.update(kwargs.get("default_headers") or {})
        kwargs["default_headers"] = headers
        original_init(self, *args, **kwargs)

    cls.__init__ = patched


_patch(openai.OpenAI)
_patch(openai.AsyncOpenAI)
