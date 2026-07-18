import logging
from typing import Optional, TypedDict

import httpx

from ..settings import AuthSettings


class _DropWeChatCredentialLog(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return "api.weixin.qq.com/sns/jscode2session" not in record.getMessage()


logging.getLogger("httpx").addFilter(_DropWeChatCredentialLog())


class WeChatIdentity(TypedDict):
    openid: str
    unionid: Optional[str]


class WeChatLoginError(Exception):
    pass


def exchange_code(code: str, settings: AuthSettings) -> WeChatIdentity:
    try:
        response = httpx.get(
            "https://api.weixin.qq.com/sns/jscode2session",
            params={
                "appid": settings.wechat_app_id,
                "secret": settings.wechat_app_secret,
                "js_code": code,
                "grant_type": "authorization_code",
            },
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("errcode"):
            raise WeChatLoginError("微信登录失败")
        openid = payload.get("openid")
        unionid = payload.get("unionid")
        if not isinstance(openid, str) or not openid:
            raise WeChatLoginError("微信登录失败")
        return {
            "openid": openid,
            "unionid": unionid if isinstance(unionid, str) and unionid else None,
        }
    except WeChatLoginError:
        raise
    except (httpx.HTTPError, TypeError, ValueError):
        raise WeChatLoginError("微信登录失败") from None
