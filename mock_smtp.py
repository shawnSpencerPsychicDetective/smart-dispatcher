import asyncio
from aiosmtpd.controller import Controller


class DebugEmailHandler:
    async def handle_DATA(self, server, session, envelope):
        print("\n" + "=" * 50)
        print("📨 INCOMING EMAIL CAPTURED (Mock Server)")
        print("=" * 50)
        print(f"FROM: {envelope.mail_from}")
        print(f"TO:   {envelope.rcpt_tos}")
        print("-" * 20)
        # Decode the email body
        content = envelope.content.decode('utf8', errors='replace')
        print(content)
        print("=" * 50 + "\n")
        return '250 Message accepted for delivery'


if __name__ == '__main__':
    # Start a local SMTP server on port 1025
    controller = Controller(DebugEmailHandler(), hostname='localhost', port=1025)
    controller.start()
    print("📡 Mock SMTP Server running on localhost:1025...")
    print("   (Keep this window open to see sent emails)")

    # Keep the script running
    try:
        asyncio.get_event_loop().run_forever()
    except KeyboardInterrupt:
        print("Stopping SMTP server...")
        controller.stop()