from app.services.agent.login_session import (
    assess_login_expired,
    cookies_to_string,
    detect_login_signal,
    is_verification_page,
)


class TestVerificationPage:
    def test_detects_captcha(self):
        assert is_verification_page("请完成 captcha 验证")

    def test_detects_verify_data(self):
        assert is_verification_page('const verify_data = {"code":"10000"}')

    def test_detects_chinese_verification(self):
        assert is_verification_page("<title>验证中间页</title>")

    def test_detects_security_verification(self):
        assert is_verification_page("正在进行安全验证，请稍候")

    def test_normal_content_false(self):
        assert not is_verification_page("热门视频 用户主页 直播 推荐")


class TestAssessLoginExpired:
    def test_douyin_short_verification_true(self):
        assert assess_login_expired("douyin", "验证中间页 请稍候") is True

    def test_xhs_short_verification_true(self):
        assert assess_login_expired("xiaohongshu", "captcha verify") is True

    def test_long_content_false(self):
        assert assess_login_expired("douyin", "x" * 600) is False

    def test_verification_but_long_text_false(self):
        assert assess_login_expired("douyin", "captcha" + "x" * 600) is False

    def test_generic_platform_false(self):
        assert assess_login_expired("generic", "验证中间页") is False


class TestDetectLoginSignal:
    def test_credential_cookie_hit(self):
        assert detect_login_signal("douyin", ["UIFID"]) is True

    def test_xhs_credential_cookie_hit(self):
        assert detect_login_signal("xiaohongshu", ["id_token"]) is True

    def test_xhs_anonymous_web_session_is_not_login_signal(self):
        assert detect_login_signal("xiaohongshu", ["web_session"]) is False

    def test_no_credential_false(self):
        assert detect_login_signal("douyin", ["sessionid", "ttwid"]) is False

    def test_unknown_platform_false(self):
        assert detect_login_signal("weibo", ["UIFID"]) is False


class TestCookiesToString:
    def test_basic(self):
        cookies = [{"name": "a", "value": "1"}, {"name": "b", "value": "2"}]
        assert cookies_to_string(cookies) == "a=1; b=2"

    def test_skips_empty_pairs(self):
        cookies = [{"name": "", "value": "1"}, {"name": "b", "value": ""}, {"name": "c", "value": "3"}]
        assert cookies_to_string(cookies) == "c=3"
