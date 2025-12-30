import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


class EmailDispatcher:
    """A service for constructing and dispatching emails via SMTP.

    This class handles the creation of MIME messages and manages the 
    connection to an SMTP server to deliver communications to vendors 
    or maintenance staff.
    """
    def send_email(self, subject: str, body: str, recipient: str):
        """Constructs and sends an email using a local mock SMTP server.

        This method builds a multipart MIME message and attempts to deliver 
        it via a local SMTP instance (typically the mock_smtp.py script) 
        running on port 1025.

        Args:
            subject (str): The subject line of the email.
            body (str): The plain-text content of the email body.
            recipient (str): The email address of the receiver.

        Returns:
            str: A status message indicating whether the email was sent 
            successfully or a detailed error message if the connection 
            failed or the server was not found.
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
