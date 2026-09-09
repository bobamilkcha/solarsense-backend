"""Root test config.

This module runs before any test module is collected, so it is the right place
to force the runtime environment. `ENVIRONMENT=testing` makes app_config skip the
"changethis" secret check and disables the Secure flag on cookies (see
app_config.refresh_cookie_secure), which lets the test client read them over HTTP.

os.environ takes precedence over the .env file in pydantic-settings, so this wins
even though .env sets ENVIRONMENT=local.
"""

import os

os.environ["ENVIRONMENT"] = "testing"
