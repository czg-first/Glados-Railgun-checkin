"""Use the normal website UI, then verify today's official check-in ledger.

No CAPTCHA interaction, fingerprint overrides, persisted auth state or media logs.
"""
import os
import re
import sys
from urllib.parse import urlsplit

from checkin import (
    CANDIDATE_DOMAINS,
    CheckinResult,
    CheckinStatus,
    Config,
    Report,
    init_logger,
    logger,
    parse_checkin,
    to_int,
    today_checkin_points,
    write_actions_summary,
)


def cookie_records(raw, origin):
    records = []
    for part in raw.split(";"):
        name, separator, value = part.strip().partition("=")
        if separator and name:
            records.append({"name": name, "value": value, "url": origin, "secure": True, "sameSite": "Lax"})
    return records


def is_checkin_response(response, host):
    url = urlsplit(response.url)
    return response.request.method == "POST" and url.hostname == host and url.path.rstrip("/") == "/api/user/checkin"


def read_points(page):
    try:
        return page.evaluate("""async () => {
            const response = await fetch('/api/user/points', {
                credentials: 'include', cache: 'no-store', signal: AbortSignal.timeout(15000)
            });
            return response.ok ? await response.json() : null;
        }""")
    except Exception:
        return None


def run_account(browser, entry):
    host = entry.origin or "glados.one"
    if host not in CANDIDATE_DOMAINS:
        raise ValueError("Account origin is not a supported official site")
    origin = "https://" + host
    options = {"locale": "zh-CN"}
    if entry.user_agent:
        options["user_agent"] = entry.user_agent
    context = browser.new_context(**options)
    page = None
    stage = "初始化会话"
    try:
        context.add_cookies(cookie_records(entry.cookie, origin))
        page = context.new_page()
        stage = "打开官网签到页"
        page.goto(origin + "/console/checkin", wait_until="domcontentloaded", timeout=60000)

        stage = "读取官网今日签到流水"
        data = read_points(page)
        observed = today_checkin_points(data)
        if observed is not None and observed > 0:
            logger.info("账号 %s：官网今日签到入账已核实，无需重复点击。", entry.index)
            return CheckinResult(domain=host, code=CheckinStatus.REPEAT, today_points=observed, points_total=to_int(data.get("points")))

        button = page.locator("button.ckb").or_(
            page.get_by_role("button", name=re.compile(r"^(签到|check\s*-?\s*in)$", re.I))
        ).first
        stage = "等待官网签到按钮"
        button.wait_for(state="visible", timeout=25000)
        # Only the ordinary site check-in button is clicked. Verification widgets
        # remain controlled by the official page and are never interacted with.
        stage = "点击官网按钮并等待最终签到响应"
        with page.expect_response(lambda response: is_checkin_response(response, host), timeout=65000) as pending:
            button.click(timeout=20000)
            logger.info("账号 %s：已点击官网签到按钮，等待最终 POST 回执。", entry.index)
        result = parse_checkin(pending.value.json(), host, lambda emoji, message, *args: entry.log(host, emoji, message, force=True))

        stage = "核实签到后的官网流水"
        for attempt in range(3):
            data = read_points(page)
            result.today_points = today_checkin_points(data)
            if isinstance(data, dict):
                result.points_total = to_int(data.get("points"))
            if result.today_points is not None and result.today_points > 0:
                break
            if result.code is CheckinStatus.FAILURE or attempt == 2:
                break
            page.wait_for_timeout(2000)

        if result.turnstile:
            result.note = "官网要求人工验证，云端浏览器未完成；请在官网处理验证。"
        elif result.code in (CheckinStatus.SUCCESS, CheckinStatus.REPEAT) and not (result.today_points and result.today_points > 0):
            result.code = CheckinStatus.FAILURE
            result.note = "接口回执尚未被官网今日签到流水证实。"
        return result
    except Exception:
        try:
            buttons = page.locator("button.ckb").count() if page else 0
            verification_frames = page.locator("iframe[src*='challenges.cloudflare.com']").count() if page else 0
            logger.warning("账号 %s：停止阶段=%s；签到按钮数量=%s；Cloudflare 验证框数量=%s。", entry.index, stage, buttons, verification_frames)
        except Exception:
            logger.warning("账号 %s：停止阶段=%s。", entry.index, stage)
        raise
    finally:
        context.close()


def main():
    init_logger()
    config = Config()
    if not config.accounts:
        report = Report.failed(config.load_error or "No valid accounts")
        write_actions_summary(report)
        return 1
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            headless = os.environ.get("BROWSER_HEADLESS", "true").lower() not in {"false", "0", "no"}
            browser = playwright.chromium.launch(headless=headless)
            try:
                for entry in config.accounts:
                    try:
                        entry.result = run_account(browser, entry)
                    except Exception as error:
                        # Library exception text may contain page or request data.
                        logger.error("账号 %s：浏览器未能完成签到（%s）；可能需要登录或人工验证。", entry.index, type(error).__name__)
                        entry.result = CheckinResult.failure(entry.origin or "glados.one")
                        entry.result.note = "浏览器操作超时或失败，请在官网检查登录和人工验证。"
            finally:
                browser.close()
        report = Report(config.accounts)
    except Exception as error:
        logger.error("浏览器启动失败（%s）。", type(error).__name__)
        report = Report(config.accounts, error="浏览器未能启动。")
    logger.info("%s\n%s", report.title, report.render())
    write_actions_summary(report)
    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
