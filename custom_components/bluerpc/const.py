from datetime import timedelta

NAME = "BlueRPC"
DOMAIN = "bluerpc"
VERSION = "1.0"
ISSUE_URL = "https://github.com/"

STARTUP_MESSAGE = f"""
-------------------------------------------------------------------
{NAME}
Version: {VERSION}
This is a custom integration!
If you have any issues with this you need to open an issue here:
{ISSUE_URL}
-------------------------------------------------------------------
"""

DEFAULT_PORT = 5052
CERT_DEFAULT_ORGANIZATION = "BlueRPC"
CERT_DEFAULT_VALIDITY = timedelta(weeks=5000)
CERT_DEFAULT_KEY_SIZE = 2048

CONF_ENCRYPTION_PASSWORD = "password"
CONF_ENCRYPTED = "encrypted"
