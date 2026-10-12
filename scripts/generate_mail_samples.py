"""Original fictional upload examples; no user mailbox is read."""
from email.message import EmailMessage
from email import policy
from pathlib import Path

directory = Path(__file__).resolve().parents[1] / "fixtures/mail"
directory.mkdir(parents=True, exist_ok=True)


def message(id, subject, body, dated=True):
    mail = EmailMessage(policy=policy.SMTP)
    mail["From"] = "Fictional Campus <notices@example.org>"
    mail["To"] = "student@example.com"
    mail["Subject"] = subject
    mail["Message-ID"] = f"<{id}@example.org>"
    if dated:
        mail["Date"] = "Mon, 12 Oct 2026 08:00:00 +0800"
    mail.set_content(body)
    return mail.as_bytes()


course = message("sample-course", "示例课程安排", "2026-10-15T09:00:00+08:00 至 2026-10-15T10:00:00+08:00 上课。本邮件完全虚构。")
deadline = message("sample-deadline", "示例项目截止", "项目应于 2026-10-16 截止，具体时刻尚未公布。本邮件完全虚构。")
unknown = message("sample-unknown", "示例活动时间待定", "活动的日期和时间尚未确定，请等待后续通知。本邮件完全虚构。", False)
(directory / "sample.eml").write_bytes(course)
envelope = b"From notices@example.org Mon Oct 12 08:00:00 2026\n"
(directory / "sample.mbox").write_bytes(b"".join(envelope + raw.replace(b"\r\n", b"\n") + b"\n" for raw in [course, deadline, unknown, course]).rstrip(b"\n") + b"\n")
print("Generated fictional EML/MBOX examples (including a duplicate and an unknown date).")
