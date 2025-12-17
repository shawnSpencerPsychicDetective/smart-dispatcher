# mock_smtp.py
import asyncio
from aiosmtpd.controller import Controller

class DebugEmailHandler:
    async def handle_DATA(self, server, session, envelope):
        print("\n" + "!"*50)
        print("📨 EMAIL RECEIVED!")
        print("!"*50)
        print(f"FROM: {envelope.mail_from}")
        print(f"TO:   {envelope.rcpt_tos}")
        print(f"CONTENT:\n{envelope.content.decode('utf8', errors='replace')}")
        print("!"*50 + "\n")
        return '250 OK'

if __name__ == '__main__':
    # 0.0.0.0 is CRITICAL for Codespaces
    controller = Controller(DebugEmailHandler(), hostname='0.0.0.0', port=1025)
    controller.start()
    print("📡 SMTP Server Listening on 0.0.0.0:1025...")
    try:
        asyncio.get_event_loop().run_forever()
    except KeyboardInterrupt:
        controller.stop()