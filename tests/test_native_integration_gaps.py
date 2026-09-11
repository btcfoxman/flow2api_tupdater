import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from token_updater import api
from token_updater.session_validation import scoped_google_cookies, validate_google_cookies
from token_updater.sync_errors import destination_error
from token_updater.updater import TokenSyncer

JAR = [{"name":"SID","value":"root-secret","domain":".google.com","path":"/","expires":4102444800},
       {"name":"OSID","value":"flow-secret","domain":"flow.google.com","path":"/","expires":4102444900}]
PROFILE = {"id":1,"name":"test","email":"user@example.com","is_active":1,
           "google_cookies":json.dumps(JAR),"captcha_proxy_url":"socks5://host.docker.internal:20001"}
ACK = {"success":True,"auth_mode":"flow","email":"user@example.com","cookies_updated":True,
       "flow_cookies_configured":True,"google_session_cookies_configured":True,"proxy_updated":True,
       "proxy_configured":True,"flow_identity_verified":True,"native_session_verified":True,"account_active":True}


@asynccontextmanager
async def gate(*args, **kwargs):
    yield


@pytest.mark.asyncio
async def test_protocol_api_hydrates_only_scoped_cookies_and_returns_no_credentials():
    result={"success":True,"auth_mode":"flow","email":"user@example.com",
            "session_token":"flow:user@example.com","google_cookies":JAR}
    with patch.object(api.execution_gate,"hold",gate), \
         patch.object(api.profile_db,"get_profile",AsyncMock(return_value=PROFILE)), \
         patch.object(api.profile_db,"update_profile",AsyncMock()), \
         patch.object(api.dashboard_events,"publish",AsyncMock()), \
         patch("token_updater.protocol_login.protocol_loginer.login",AsyncMock(return_value=result)), \
         patch.object(api.browser_manager,"import_cookies",AsyncMock(return_value={"success":True,"has_token":True})) as imported:
        response=await api.protocol_login(1,api.ProtocolLoginRequest(google_cookies=json.dumps(JAR)),token="test")
    assert response["success"] and response["auth_mode"]=="flow"
    assert json.loads(imported.await_args.args[1])==JAR
    assert "session_token" not in response and "google_cookies" not in response
    assert "secret" not in str(response)


@pytest.mark.asyncio
@pytest.mark.parametrize("change",[{"session_token":None},{"auth_mode":"labs"},{"email":"wrong@example.com"},{"google_cookies":[]}])
async def test_unverified_protocol_result_never_changes_source_browser(change):
    result={"success":True,"auth_mode":"flow","email":"user@example.com",
            "session_token":"flow:user@example.com","google_cookies":JAR,**change}
    with patch.object(api.execution_gate,"hold",gate), \
         patch.object(api.profile_db,"get_profile",AsyncMock(return_value=PROFILE)), \
         patch("token_updater.protocol_login.protocol_loginer.login",AsyncMock(return_value=result)), \
         patch.object(api.browser_manager,"import_cookies",AsyncMock()) as imported:
        with pytest.raises(HTTPException):
            await api.protocol_login(1,api.ProtocolLoginRequest(google_cookies=json.dumps(JAR)),token="test")
    imported.assert_not_awaited()


@pytest.mark.asyncio
async def test_api_key_session_export_has_real_flow_payload_not_pseudo_st():
    with patch.object(api.execution_gate,"hold",gate), \
         patch.object(api.profile_db,"get_profile",AsyncMock(return_value=PROFILE)), \
         patch.object(api.browser_manager,"extract_token",AsyncMock(return_value="flow:user@example.com")):
        response=await api.ext_get_token(1,api_key="test")
    assert response.headers["cache-control"]=="no-store"
    result=json.loads(response.body)
    assert result["auth_mode"]=="flow" and result["session_token"] is None
    assert result["google_cookies"]==JAR
    assert result["captcha_proxy_url"]==PROFILE["captcha_proxy_url"]


@pytest.mark.asyncio
@pytest.mark.parametrize("email",[None,"wrong@example.com"])
async def test_destination_must_acknowledge_same_structured_email(email):
    client=AsyncMock(); client.__aenter__.return_value=client
    client.post.return_value=SimpleNamespace(status_code=200,json=lambda:{**ACK,"email":email})
    with patch("token_updater.updater.httpx.AsyncClient",return_value=client):
        result=await TokenSyncer()._push_to_flow2api("flow:user@example.com","http://target","key",
            google_cookies=JAR,captcha_proxy_url=PROFILE["captcha_proxy_url"])
    assert result["error_code"]=="identity_mismatch"


@pytest.mark.asyncio
async def test_success_uses_structured_email_even_with_localized_message():
    client=AsyncMock(); client.__aenter__.return_value=client
    client.post.return_value=SimpleNamespace(status_code=200,json=lambda:{**ACK,"message":"会话同步成功"})
    with patch("token_updater.updater.httpx.AsyncClient",return_value=client):
        result=await TokenSyncer()._push_to_flow2api("flow:user@example.com","http://target","key",
            google_cookies=JAR,captcha_proxy_url=PROFILE["captcha_proxy_url"])
    assert result["email"]=="user@example.com" and result["native_session_verified"]


@pytest.mark.asyncio
@pytest.mark.parametrize("receipt,jar",[("flow:user@example.com",None),("old-st",JAR),("flow:invalid",JAR)])
async def test_flow_identity_marker_never_travels_as_a_credential(receipt,jar):
    with patch("token_updater.updater.httpx.AsyncClient") as client:
        result=await TokenSyncer()._push_to_flow2api(receipt,"http://target","key",google_cookies=jar,
            captcha_proxy_url=PROFILE["captcha_proxy_url"])
    assert not result["success"]
    client.assert_not_called()


def test_expiry_aliases_and_cookie_scope_survive_new_sync_payload():
    aliases=[{k:v for k,v in c.items() if k!='expires'}|{"expiry":c['expires'],"storeId":"not-forwarded"} for c in JAR]
    assert scoped_google_cookies(aliases)==JAR
    for extra in ({"partitioned":True},{"partitionKey":{"topLevelSite":"https://flow.google.com"}},{"expires":1},{"path":"/other"}):
        assert not validate_google_cookies(scoped_google_cookies([JAR[0],{**JAR[1],**extra}]))["success"]
    assert scoped_google_cookies([JAR[0],{**JAR[1],"domain":"..flow.google.com"}])==[JAR[0]]


@pytest.mark.parametrize("code,expected",[("flow_account_busy","destination_busy"),
    ("local_session_external_sync_forbidden","independent_login"),("unsupported_auth_mode","destination_version"),
    ("flow_auth_mode_required","destination_version"),("flow_verification_unavailable","destination_unavailable")])
def test_new_destination_errors_do_not_trigger_legacy_relogin(code,expected):
    result=destination_error(SimpleNamespace(status_code=409,json=lambda:{"detail":{"code":code,"message":"private-secret"}}))
    assert result["error_code"]==expected and "private-secret" not in str(result)


def test_malformed_error_code_does_not_raise():
    result=destination_error(SimpleNamespace(status_code=409,json=lambda:{"detail":{"code":{}}}))
    assert result["error_code"]=="destination_conflict"
