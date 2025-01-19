from telethon import TelegramClient, events, Button, functions, types
from telethon.errors import (
    SessionPasswordNeededError,
    PhoneCodeInvalidError,
    PhoneCodeExpiredError,
    PhoneNumberInvalidError
)
import asyncio
import nest_asyncio
from telethon.sync import TelegramClient as SyncTelegramClient
import os
from aiohttp import web
import re

# Apply nest_asyncio
nest_asyncio.apply()

# Add session cleanup function
def cleanup_sessions():
    session_files = ['bot.session', 'session_name.session']
    for file in session_files:
        try:
            if os.path.exists(file):
                os.remove(file)
                print(f"Removed existing session file: {file}")
        except Exception as e:
            print(f"Error removing session file {file}: {str(e)}")

# Configuration
API_ID = '22874714'
API_HASH = '0f5a6aca792a87d6056a70ebe90537ae'
BOT_TOKEN = '8117902471:AAFuRuJ_6V6Qdj62FPMhsLOEJFWfganWJ9s'
# Change single channel to list of channels
SOURCE_CHANNELS = [
    '@MeghUpdates',
    '@NeonManYT',
     '@geo_gaganauts' # Add your additional channels here
    
]
DESTINATION_CHANNEL = '@todaynewsuptodate'

class UserSession:
    def __init__(self):
        self.phone = None
        self.phone_code_hash = None
        self.step = 'phone'
        self.attempts = 0

class MessageForwarder:
    def __init__(self, client, source_channels, destination_channel):
        self.client = client
        self.source_channels = source_channels
        self.destination_channel = destination_channel
        self.last_message_ids = {channel: None for channel in source_channels}
        self.is_running = False
        self.url_pattern = re.compile(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+')

    def remove_links(self, text):
        """Remove all URLs from text"""
        if text:
            return self.url_pattern.sub('', text).strip()
        return text

    async def forward_message(self, message):
        """Forward message with links removed"""
        try:
            # Handle text messages
            if message.text:
                cleaned_text = self.remove_links(message.text)
                await self.client.send_message(
                    self.destination_channel,
                    cleaned_text,
                    file=message.media if message.media else None
                )
            # Handle media messages with captions
            elif message.media:
                cleaned_caption = self.remove_links(message.caption)
                await self.client.send_file(
                    self.destination_channel,
                    file=message.media,
                    caption=cleaned_caption
                )
            # Handle other types of messages
            else:
                await self.client.send_message(self.destination_channel, message)
            
            print(f"Forwarded message ID: {message.id} (links removed if present)")
            
        except Exception as e:
            print(f"Error forwarding message {message.id}: {str(e)}")

    async def start_forwarding(self):
        self.is_running = True
        try:
            # Get last message ID from each source channel
            for channel in self.source_channels:
                messages = await self.client.get_messages(channel, limit=1)
                if messages:
                    self.last_message_ids[channel] = messages[0].id
                print(f"Starting forwarding from {channel} to {self.destination_channel}")
                print(f"Last message ID for {channel}: {self.last_message_ids[channel]}")

            while self.is_running:
                for source_channel in self.source_channels:
                    try:
                        # Get new messages since last checked message for this channel
                        messages = await self.client.get_messages(
                            source_channel, 
                            min_id=self.last_message_ids[source_channel]
                        )

                        for message in reversed(messages):
                            await self.forward_message(message)
                            self.last_message_ids[source_channel] = max(
                                self.last_message_ids[source_channel] or 0, 
                                message.id
                            )

                    except Exception as e:
                        print(f"Error getting messages from {source_channel}: {str(e)}")

                await asyncio.sleep(5)  # Check every 5 seconds

        except Exception as e:
            print(f"Forwarding error: {str(e)}")

    def stop_forwarding(self):
        self.is_running = False

# Initialize clients with unique session names
bot = TelegramClient('bot_session', API_ID, API_HASH)
client = TelegramClient('user_session', API_ID, API_HASH)
auth_users = {}
forwarder = None

def register_handlers():
    @bot.on(events.NewMessage(pattern='/start'))
    async def start_handler(event):
        await event.respond('Welcome! Click the button below to start authentication.',
                          buttons=Button.inline('Begin Authentication', b'auth'))

    @bot.on(events.CallbackQuery(data=b'auth'))
    async def auth_handler(event):
        auth_users[event.sender_id] = UserSession()
        await event.respond('Please send your phone number (including country code, e.g., +1234567890)')

    @bot.on(events.NewMessage)
    async def message_handler(event):
        if not event.text:
            return
            
        user_id = event.sender_id
        if user_id not in auth_users:
            return

        session = auth_users[user_id]
        try:
            if session.step == 'phone':
                phone = event.text.strip()
                try:
                    if not client.is_connected():
                        await client.connect()
                    
                    # Fixed SendCodeRequest parameters
                    result = await client(functions.auth.SendCodeRequest(
                        phone_number=phone,  # Changed from phone to phone_number
                        api_id=int(API_ID),  # Ensure API_ID is int
                        api_hash=API_HASH,
                        settings=types.CodeSettings(
                            allow_flashcall=False,
                            current_number=True,  # Changed to True
                            allow_app_hash=True,
                            allow_missed_call=False
                        )
                    ))
                    
                    session.phone = phone
                    session.phone_code_hash = result.phone_code_hash
                    session.step = 'code'
                    
                    await event.respond(
                        "Please check for an OTP in official telegram account.\n"
                        "If OTP is `12345`, **please send it as** `1 2 3 4 5`\n\n"
                        "Enter /cancel to cancel the process"
                    )
                except Exception as e:
                    print(f"Debug - Error details: {str(e)}")  # Added debug print
                    await event.respond(f'Error sending code: {str(e)}. Please try again.')
                    del auth_users[user_id]

            elif session.step == 'code':
                if event.text.strip() == '/cancel':
                    await event.respond('Process cancelled!')
                    del auth_users[user_id]
                    return

                if not client.is_connected():
                    await client.connect()
                    
                code = event.text.strip().replace(" ", "")
                try:
                    await client(functions.auth.SignInRequest(
                        phone_number=session.phone,
                        phone_code_hash=session.phone_code_hash,
                        phone_code=code
                    ))
                    await start_forwarding()
                    await event.respond('Successfully logged in! Forwarding service is active.')
                    del auth_users[user_id]
                except SessionPasswordNeededError:
                    session.step = '2fa'
                    await event.respond('Two-factor authentication is enabled. Please enter your password:')
                except PhoneCodeInvalidError:
                    await event.respond('Invalid code. Please try again.')
                except PhoneCodeExpiredError:
                    await event.respond('Code expired. Please start over with /start')
                    del auth_users[user_id]
                except Exception as e:
                    await event.respond(f'Error during login: {str(e)}')
                    session.attempts += 1
                    if session.attempts >= 3:
                        del auth_users[user_id]
                        await event.respond('Too many attempts. Please start over with /start')

            elif session.step == '2fa':
                if not client.is_connected():
                    await client.connect()
                try:
                    await client.sign_in(password=event.text.strip())
                    await start_forwarding()
                    await event.respond('Successfully logged in with 2FA! Forwarding service is active.')
                    del auth_users[user_id]
                except Exception as e:
                    await event.respond(f'Invalid 2FA password: {str(e)}')
                    session.attempts += 1
                    if session.attempts >= 3:
                        del auth_users[user_id]
                        await event.respond('Too many attempts. Please start over with /start')

        except Exception as e:
            await event.respond(f'An error occurred: {str(e)}\nPlease start over with /start')
            del auth_users[user_id]

async def start_forwarding():
    global forwarder
    try:
        # Create new forwarder instance with multiple source channels
        forwarder = MessageForwarder(client, SOURCE_CHANNELS, DESTINATION_CHANNEL)
        
        # Start forwarding in background
        asyncio.create_task(forwarder.start_forwarding())
        
        print(f"Bot is running!")
        print(f"Monitoring channels: {', '.join(SOURCE_CHANNELS)}")
        print(f"Forwarding to {DESTINATION_CHANNEL}")
    except Exception as e:
        print(f"Error starting forwarder: {str(e)}")

# Add web server function
async def web_server():
    app = web.Application()
    
    async def health_check(request):
        return web.Response(text="OK", status=200)
    
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get('PORT', 8000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print(f"Web server started on port {port}")
    return runner

async def main():
    try:
        # Start web server first
        runner = await web_server()
        
        # Clean up existing sessions before starting
        cleanup_sessions()
        
        await bot.start(bot_token=BOT_TOKEN)
        await client.connect()
        
        # Register handlers
        register_handlers()
        
        if await client.is_user_authorized():
            await start_forwarding()
        else:
            print("Waiting for authentication through bot...")
            print("Please start the bot and complete authentication.")
        
        # Run both web server and bot
        await bot.run_until_disconnected()
    except Exception as e:
        print(f"Main loop error: {str(e)}")
    finally:
        if forwarder:
            forwarder.stop_forwarding()
        await client.disconnect()
        await bot.disconnect()
        await runner.cleanup()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped by user")
    except Exception as e:
        print(f"Error occurred: {str(e)}")