"""Sends the magic-link email via SMTP STARTTLS, or logs it in dev.

Reads SMTP_HOST/SMTP_PORT/SMTP_USERNAME/SMTP_PASSWORD/MAIL_FROM from the
gitignored .editor-smtp.env (config.load_smtp_env). If that config is
absent -- a fresh checkout, a test run, dev before personal-cloud-infra's
`make sync-blog-editor` has run -- the link is logged instead of sent, so
Peter can still sign in locally without SES ever being involved.
"""
from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from editor import config

logger = logging.getLogger("editor.auth")


def send_login_link(email: str, link: str) -> None:
    env = config.load_smtp_env()
    host = env.get("SMTP_HOST")
    port = env.get("SMTP_PORT")
    username = env.get("SMTP_USERNAME")
    password = env.get("SMTP_PASSWORD")
    sender = env.get("MAIL_FROM", "login@edit.cloudy.nyc")

    if not (host and port and username and password):
        logger.info("SMTP not configured; login link for %s: %s", email, link)
        return

    text = (
        "Here's your sign-in link for the blog editor.\n\n"
        f"{link}\n\n"
        "It expires in 15 minutes and works once. "
        "If you didn't ask for this, ignore it.\n"
    )
    html = (
        "<p>Here's your sign-in link for the blog editor.</p>"
        f'<p><a href="{link}">{link}</a></p>'
        "<p>It expires in 15 minutes and works once. "
        "If you didn't ask for this, ignore it.</p>"
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Sign in to the blog editor"
    msg["From"] = sender
    msg["To"] = email
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP(host, int(port), timeout=10) as smtp:
        smtp.starttls()
        smtp.login(username, password)
        smtp.sendmail(sender, [email], msg.as_string())
