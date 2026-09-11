import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from curl_cffi.requests.cookies import Cookies
from token_updater.browser import BrowserManager
from token_updater.protocol_login import ProtocolLogin
from token_updater.session_validation import validate_flow_identity
from token_updater.updater import TokenSyncer

JAR=[{"name":"SID","value":"root","domain":".google.com","path":"/"},
     {"name":"OSID","value":"flow","domain":"flow.google.com","path":"/"}]
IDENTITY={"origin":"https://flow.google.com","path":"/","ready":True,"email":"user@example.com"}


@pytest.mark.asyncio
async def test_browser_completion_needs_no_labs_authorization_or_cookie():
    manager=BrowserManager()
    page=SimpleNamespace(url="https://flow.google.com/",evaluate=AsyncMock(return_value=IDENTITY))
    profile={"id":1,"name":"test","email":"user@example.com"}
    with patch.object(manager,"_ensure_labs_authorization",AsyncMock(side_effect=AssertionError("Labs forbidden"))) as labs, \
         patch.object(manager,"_wait_for_flow_cookies",AsyncMock()), \
         patch.object(manager,"_save_google_cookies_from_context",AsyncMock(return_value=True)), \
         patch.object(manager,"_persist_login_state",AsyncMock()) as persist:
        assert await manager._complete_flow_session(profile,None,page)=="flow:user@example.com"
    labs.assert_not_awaited()
    persist.assert_awaited_once_with(1,"flow:user@example.com",email="user@example.com")


@pytest.mark.asyncio
async def test_protocol_default_only_gets_flow_and_keeps_scoped_jar():
    session=SimpleNamespace(cookies=Cookies(),get=AsyncMock())
    session.get.return_value=SimpleNamespace(status_code=200,text='window.WIZ_global_data='+json.dumps({
        "oPEP7c":"user@example.com","SNlM0e":"xsrf-test","cfb2h":"build","FdrFJe":"page-session"})+';')
    cm=AsyncMock()
    cm.__aenter__.return_value=session
    with patch("token_updater.protocol_login.AsyncSession",return_value=cm):
        jar = [{**c,"expires":2100000000,"httpOnly":True,"sameSite":"Lax"} for c in JAR]
        result=await ProtocolLogin().login(json.dumps(jar),proxy="socks5://127.0.0.1:20022",email="user@example.com")
    assert result["success"]
    assert result["auth_mode"]=="flow"
    assert result["session_token"]=="flow:user@example.com"
    session.get.assert_awaited_once_with("https://flow.google.com/",allow_redirects=False)
    assert all(c["domain"].lstrip(".") in {"google.com","flow.google.com"} for c in result["google_cookies"])
    assert all(c["expires"]==2100000000 and c["httpOnly"] and c["sameSite"]=="Lax" for c in result["google_cookies"])
    for cookie in session.cookies.jar:
        assert cookie.domain_specified == cookie.domain.startswith('.')
        assert cookie.domain_initial_dot == cookie.domain.startswith('.')
        assert cookie.expires == 2100000000 and not cookie.discard


@pytest.mark.asyncio
async def test_new_site_ready_never_waits_for_legacy_session_cookie():
    manager=BrowserManager()
    page=SimpleNamespace(url="https://flow.google.com/",evaluate=AsyncMock(return_value=IDENTITY))
    with patch.object(manager,"_safe_page_text",AsyncMock(return_value="Flow")), \
         patch.object(manager,"_get_session_cookie",AsyncMock(side_effect=AssertionError("Labs forbidden"))) as old:
        assert await manager._settle_flow_session({"id":1,"email":"user@example.com"},page)
    old.assert_not_awaited()


@pytest.mark.asyncio
async def test_new_sender_omits_st_and_requires_new_target_identity_ack():
    client=AsyncMock()
    client.__aenter__.return_value=client
    client.post.return_value=SimpleNamespace(status_code=200,json=lambda:{"success":True,"cookies_updated":True,
        "flow_cookies_configured":True,"google_session_cookies_configured":True,"proxy_updated":True,
        "proxy_configured":True,"oauth_verified":True,"account_active":True})
    with patch("token_updater.updater.httpx.AsyncClient",return_value=client):
        result=await TokenSyncer()._push_to_flow2api("flow:user@example.com","http://server","key",
            google_cookies=JAR,captcha_proxy_url="socks5://host.docker.internal:20022")
    sent=client.post.await_args.kwargs["json"]
    assert sent["auth_mode"]=="flow"
    assert sent["email"]=="user@example.com"
    assert "session_token" not in sent
    assert result["error_code"]=="flow_identity_unconfirmed"


@pytest.mark.parametrize("change",[{"ready":False},{"path":"/about"},{"origin":"https://evil.test"},{"email":""}])
def test_new_login_requires_real_identity(change):
    assert not validate_flow_identity({**IDENTITY,**change})["success"]


@pytest.mark.asyncio
async def test_new_peek_does_not_use_oauth():
    manager=BrowserManager()
    page=SimpleNamespace(url="https://flow.google.com/",evaluate=AsyncMock(return_value=IDENTITY))
    context=SimpleNamespace(pages=[page],cookies=AsyncMock(return_value=JAR))
    with patch.object(manager,"_validate_context_session",AsyncMock(side_effect=AssertionError("Labs forbidden"))) as labs:
        assert await manager._peek_context_session({"id":1,"email":"user@example.com"},context)=="flow:user@example.com"
    labs.assert_not_awaited()
