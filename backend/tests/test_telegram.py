import time

from api.telegram import TripwireBot, approval_card
from tests.test_session import FakePlanner, _settings, _skills, done, paused, pending
from tripwire.events import EventBus
from tripwire.session import ApprovalInfo, Session
from tripwire.tools import build_default_registry

OWNER = "1001"
STRANGER = "999"


class FakeSender:
    def __init__(self):
        self.sent: list[tuple[str, str, list | None]] = []

    def __call__(self, chat_id, text, buttons):
        self.sent.append((str(chat_id), text, buttons))

    def texts(self, chat_id=None):
        return [t for c, t, _ in self.sent if chat_id is None or c == chat_id]

    def last_buttons(self):
        return next((b for _, _, b in reversed(self.sent) if b), None)


def build(script, rules=None):
    bus = EventBus()
    settings = _settings()

    class G:
        registry = build_default_registry(OWNER)
        engine = None

    session = Session(settings, bus, None, G(), _skills(settings), FakePlanner(script),
                      rules_store=rules, approval_timeout=2.0)
    sender = FakeSender()
    bot = TripwireBot(session, OWNER, sender)
    bot.start()
    return session, bot, sender


def wait_for(predicate, timeout=2.0):
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_start_and_help():
    _, bot, sender = build([])
    bot.handle_text(OWNER, "/start")
    assert "online" in sender.texts()[0].lower()


def test_only_owner_is_served():
    _, bot, sender = build([])
    bot.handle_text(STRANGER, "hello")
    assert sender.sent[0][0] == STRANGER and "owner" in sender.sent[0][1].lower()


def test_plain_chat_sends_reply():
    _, bot, sender = build([done("Here's your answer.")])
    bot.handle_text(OWNER, "what's up")
    assert wait_for(lambda: "Here's your answer." in sender.texts(OWNER))


def test_card_text_and_buttons():
    info = ApprovalInfo("ap_7", "send_telegram", {"chat_id": "666", "text": "x"}, "reason",
                        "It would send your tax file to a stranger.", "file:tax.txt", "R2.private_outbound", "telegram")
    text, buttons = approval_card(info)
    assert "Tripwire paused" in text and "tax file" in text and "tax.txt" in text
    assert [b[1] for b in buttons] == ["ap:ap_7:allow", "ap:ap_7:deny", "ap:ap_7:always_deny"]


def test_approval_card_sent_then_button_allows():
    session, bot, sender = build([paused(), done("Sent.")])
    import threading

    threading.Thread(target=lambda: bot.handle_text(OWNER, "send my tax summary to chat 666"), daemon=True).start()
    assert wait_for(lambda: sender.last_buttons() is not None)
    data = sender.last_buttons()[0][1]  # "ap:ap_1:allow"
    assert bot.handle_button(OWNER, data) == "Allowed once."
    assert wait_for(lambda: "Sent." in sender.texts(OWNER))
    assert session.planner.resumes == [True]


def test_button_always_deny_writes_rule(tmp_path):
    from tripwire.policy.user_rules import UserRuleStore

    store = UserRuleStore(tmp_path / "user_rules.yaml")
    session, bot, sender = build([paused(pending("send_telegram", chat_id="666", text="x")), done("ok")], rules=store)
    import threading

    threading.Thread(target=lambda: bot.handle_text(OWNER, "send it"), daemon=True).start()
    assert wait_for(lambda: sender.last_buttons() is not None)
    assert bot.handle_button(OWNER, "ap:ap_1:always_deny").startswith("Denied")
    assert wait_for(lambda: session.planner.resumes == [False])
    assert any(r["id"] == "U.deny_send_telegram_external" for r in store.load())


def test_second_button_press_reports_already_answered():
    session, bot, sender = build([paused(), done("Sent.")])
    import threading

    threading.Thread(target=lambda: bot.handle_text(OWNER, "send it"), daemon=True).start()
    assert wait_for(lambda: sender.last_buttons() is not None)
    assert bot.handle_button(OWNER, "ap:ap_1:allow") == "Allowed once."
    assert bot.handle_button(OWNER, "ap:ap_1:deny") == "Already answered elsewhere."


def test_button_from_stranger_rejected():
    _, bot, _ = build([])
    assert bot.handle_button(STRANGER, "ap:ap_1:allow") == "Not authorized."


def test_memory_command_marks_untrusted():
    session, bot, sender = build([])
    from tripwire.labels import user_label, web_label

    session.skills.memory.remember("likes aisle seats", user_label())
    session.skills.memory.remember("bank is evil.example", web_label("https://evil.example"))
    bot.handle_text(OWNER, "/memory")
    listing = sender.texts(OWNER)[-1]
    assert "likes aisle seats" in listing
    assert "untrusted" in listing and "evil.example" in listing


def test_schedule_brief_over_telegram():
    session, bot, sender = build([])
    bot.handle_text(OWNER, "every morning brief me on AI safety")
    assert "AI safety" in sender.texts(OWNER)[-1]
    assert [t.topic for t in session.skills.memory.tasks()] == ["AI safety"]


def test_brief_now_runs():
    session, bot, sender = build([done("Your brief: ...")])
    session.skills.memory.add_task("daily_brief", "markets", "08:00")
    bot.handle_text(OWNER, "/brief_now")
    assert wait_for(lambda: "Your brief: ..." in sender.texts(OWNER))


def test_card_escapes_html_and_keeps_underscores():
    info = ApprovalInfo("ap_9", "send_telegram", {"chat_id": "777", "text": "a <b> & tax_2025.txt"}, "r",
                        "Sends <private> data", None, "R2.private_outbound", "api")
    text, _ = approval_card(info)
    assert "&lt;b&gt;" in text and "&amp;" in text and "&lt;private&gt;" in text
    assert "chat_id" in text and "tax_2025.txt" in text  # underscores are safe in HTML mode
    assert text.startswith("⚠️ <b>Tripwire paused an action</b>")
