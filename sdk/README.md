# LicenseServer Python SDK

Official client for the [LicenseServer](LICENSE-SERVER) licensing platform.

```python
from licensify import LicenseClient

client = LicenseClient(
    base_url="https://your-server.example.com",
    app_id="app_xxx",
    app_secret="csec_xxx",  # shown once in the admin dashboard
)

# Activate a key on this machine (binds the HWID)
session = client.activate(key="ABCDE-FGHJK-MNPQR-STUVW-23456", hwid="your-machine-id")
print(session.session_token)

# Verify repeatedly with the rotating session token
session = client.verify(session.session_token)

# Done — release the device slot
client.deactivate(session.session_token)
```

## Notes

- The **server is the sole authority** over key validity. This SDK never mints or
  validates license keys on the client.
- `verify()` **rotates** the session token every call — the old token stops
  working immediately. Use the returned token on the next call.
- The raw HWID you send is never stored; the server stores an HMAC of it.
- Handle `LicenseError` for server rejections (expired/banned key, HWID
  mismatch, max activations, wrong credentials).
