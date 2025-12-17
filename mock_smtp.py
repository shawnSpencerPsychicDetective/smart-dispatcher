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
        content = envelope.content.decode('utf8', errors='replace')
        print(content)
        print("=" * 50 + "\n")
        return '250 Message accepted for delivery'


if __name__ == '__main__':
    # FIX: Bind to 0.0.0.0 to ensure Codespaces containers can see it
    controller = Controller(DebugEmailHandler(), hostname='0.0.0.0', port=1025)
    controller.start()
    print("📡 Mock SMTP Server running on 0.0.0.0:1025...")
    print("   (Keep this window open to see sent emails)")

    try:
        asyncio.get_event_loop().run_forever()
    except KeyboardInterrupt:
        controller.stop()