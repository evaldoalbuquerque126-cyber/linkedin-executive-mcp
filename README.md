# LinkedIn Executive MCP backend v0.1.1

Private OAuth + MCP execution layer for the `LinkedIn Executive Profile` ChatGPT plugin.

## What this backend adds

- LinkedIn OAuth 2.0 authorization-code flow.
- Encrypted storage of the owner's LinkedIn access token.
- MCP tools:
  - `linkedin_connection_status`
  - `linkedin_get_authorization_url`
  - `linkedin_get_my_identity`
  - `linkedin_publish_text_post`
- A hard confirmation flag for publishing.
- `/privacy` and `/terms` pages for developer-app setup.

## Current supported write surface

The first safe write action is **publishing a text post** using LinkedIn's `w_member_social` permission. Profile fields such as headline/About/experience are intentionally not implemented because ordinary self-service access does not guarantee profile-edit permissions.

## Required LinkedIn products

Request/enable these products in your LinkedIn Developer app:

1. **Sign In with LinkedIn using OpenID Connect** (`openid profile email`)
2. **Share on LinkedIn** (`w_member_social`)

## Deployment order

1. Deploy this service to a stable public HTTPS URL.
2. Set `PUBLIC_BASE_URL` to that URL.
3. Use `https://YOUR-HOST/privacy` as the LinkedIn app privacy-policy URL.
4. Use `https://YOUR-HOST/auth/linkedin/callback` as the LinkedIn OAuth redirect URL.
5. Create the LinkedIn Developer app and associate it with a LinkedIn Page you administer.
6. Enable the two products above.
7. The Client ID is already prefilled as `775su739006ihs`. Put the LinkedIn Client Secret only into the host's secret/environment settings. **Do not paste the Client Secret into ChatGPT.**
8. Set a stable `FERNET_KEY` generated with:
   `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
9. Open `/auth/linkedin/start` and approve access.
10. Verify `/health`, then connect the hosted `/mcp` endpoint to the ChatGPT plugin via `mcp.json`.

## Local test

```bash
cp .env.example .env
# fill non-secret local values
uvicorn app.main:app --reload --port 8000
```

## Security notes

- Never commit `LINKEDIN_CLIENT_SECRET`, OAuth tokens, `APP_SECRET`, or `FERNET_KEY`.
- Production must set a persistent `FERNET_KEY`; changing it makes stored tokens unreadable.
- Use persistent storage for `DATA_PATH` in production if the host filesystem is ephemeral.
- The server is designed for one owner. If expanded to multiple users, replace the singleton token store with per-user records and authenticated MCP tenancy.


## Current app registration

- LinkedIn Client ID: `775su739006ihs`
- Client Secret: intentionally not stored in this package
- OAuth redirect URL: set after deployment to `https://<your-host>/auth/linkedin/callback`
- Privacy URL: `https://<your-host>/privacy`
- MCP endpoint: `https://<your-host>/mcp`
