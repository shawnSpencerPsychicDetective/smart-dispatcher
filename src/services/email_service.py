import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


class EmailDispatcher:
    def send_email(self, subject, body, recipient):
        """Constructs and sends an email using a local mock SMTP server
        running on port 1025.
        """
        sender_email = "dispatch@smartbuilding.com"

        # Create a standard email object
        msg = MIMEMultipart()
        msg["From"] = sender_email
        msg["To"] = recipient
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        try:
            # Connect to our local Mock SMTP Server (Part 1)
            # Note: We use port 1025, not the standard 25/587
            with smtplib.SMTP("localhost", 1025) as server:
                server.send_message(msg)

            return f"Email successfully dispatched to {recipient} via Mock Server."
        except ConnectionRefusedError:
            return (
                "Error: Mock SMTP Server is not running. Run "
                "'python mock_smtp.py' in a separate terminal."
            )
        except Exception as e:
            return f"Error sending email: {str(e)}"
