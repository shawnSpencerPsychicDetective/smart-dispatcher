# mock_smtp.py
import asyncio
from aiosmtpd.controller import Controller


class DebugEmailHandler:
    """A handler class for the aiosmtpd controller to intercept and print
    email data.
    """

    async def handle_DATA(self, server, session, envelope):
        """Processes incoming email data and prints it to the console.

        This asynchronous method is called by the SMTP controller when the DATA
        command is received. It decodes the email content and logs the transaction
        details (sender, recipient, body) to standard output.

        Args:
            server: The SMTP server instance.
            session: The current SMTP session object.
            envelope: An object containing the message data, including mail_from,
                rcpt_tos, and content.

        Returns:
            str: An SMTP response code indicating success ("250 OK").
        """
        print("\n" + "!" * 50)
        print("EMAIL RECEIVED!")
        print("!" * 50)
        print(f"FROM: {envelope.mail_from}")
        print(f"TO:   {envelope.rcpt_tos}")
        print(f"CONTENT:\n{envelope.content.decode('utf8', errors='replace')}")
        print("!" * 50 + "\n")
        return "250 OK"


if __name__ == "__main__":
    # 0.0.0.0 is CRITICAL for Codespaces
    controller = Controller(DebugEmailHandler(), hostname="0.0.0.0", port=1025)
    controller.start()
    print("SMTP Server Listening on 0.0.0.0:1025...")
    try:
        asyncio.get_event_loop().run_forever()
    except KeyboardInterrupt:
        controller.stop()
