# Deploy on Render

This package already contains `render.yaml` and a Dockerfile.

1. Create a new private Git repository and upload the contents of this folder.
2. In Render, choose **New > Blueprint** and connect the repository.
3. Set the environment variables requested by the Blueprint:
   - `PUBLIC_BASE_URL`: the final Render HTTPS service URL, e.g. `https://linkedin-executive-mcp.onrender.com`
   - `LINKEDIN_CLIENT_ID`: `775su739006ihs`
   - `LINKEDIN_CLIENT_SECRET`: copy directly from LinkedIn Developer Portal into Render; do not send it in chat.
   - `LINKEDIN_REDIRECT_URI`: `<PUBLIC_BASE_URL>/auth/linkedin/callback`
   - `FERNET_KEY`: generate locally with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
4. Deploy and verify `<PUBLIC_BASE_URL>/health` returns `ok: true`.
5. In LinkedIn Developer Portal, set:
   - Authorized redirect URL: `<PUBLIC_BASE_URL>/auth/linkedin/callback`
   - Privacy policy URL: `<PUBLIC_BASE_URL>/privacy`
6. Enable **Sign In with LinkedIn using OpenID Connect** and **Share on LinkedIn**.
7. Open `<PUBLIC_BASE_URL>/auth/linkedin/start` and authorize your own LinkedIn account.
8. Return the final HTTPS base URL to ChatGPT. The plugin can then be updated with an `mcp.json` pointing to `<PUBLIC_BASE_URL>/mcp`.
