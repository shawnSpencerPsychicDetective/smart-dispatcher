# email_service.py
import smtplib
import sqlite3
from email.message import EmailMessage
from faker import Faker

fake = Faker()


class EmailDispatcher:
    def __init__(self, db_path='maintenance.db', smtp_host='localhost', smtp_port=1025):
        self.db_path = db_path
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port

    def generate_fake_recipient(self):
        return fake.email()

    def log_email(self, recipient, subject, body, status="DRAFT"):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO email_logs (recipient_email, subject, body, status)
            VALUES (?, ?, ?, ?)
        ''', (recipient, subject, body, status))
        conn.commit()
        log_id = cursor.lastrowid
        conn.close()
        return log_id

    def update_status(self, log_id, new_status):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('UPDATE email_logs SET status = ? WHERE id = ?', (new_status, log_id))
        conn.commit()
        conn.close()

    def send_email(self, subject, body, recipient_email=None):
        # If no recipient is passed, make one up
        if not recipient_email:
            recipient_email = self.generate_fake_recipient()

        print(f"📧 Preparing email for: {recipient_email}")

        # 1. Log Draft
        log_id = self.log_email(recipient_email, subject, body, "DRAFT")

        # 2. Build Message
        msg = EmailMessage()
        msg.set_content(body)
        msg['Subject'] = subject
        msg['From'] = "agent@maintenance-system.internal"
        msg['To'] = recipient_email

        # 3. Send to Local Mock Server
        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.send_message(msg)

            self.update_status(log_id, "SENT")
            return f"✅ Email sent to {recipient_email} (Log ID: {log_id})"

        except ConnectionRefusedError:
            self.update_status(log_id, "FAILED")
            return "❌ Connection Refused: Is the mock server running?"