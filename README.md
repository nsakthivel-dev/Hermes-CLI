# HERMES CLI

**HERMES** is an advanced, production-grade command-line interface for Google Workspace services (Gmail, Calendar, Drive, Sheets, Docs, Meet, Forms, Tasks, Chat) with built-in Gemini AI automation.

HERMES is built on a **centrally distributed, locally authenticated, client-side open-source architecture**:
- **Centrally Distributed:** Distributed via PyPI as `hermes-cli`.
- **Locally Authenticated:** Every user authenticates locally using their own Google account via OAuth 2.0. No developer credentials or third-party servers are ever involved.
- **Locally Cached & User-Isolated:** Tokens, cache, and configuration remain 100% on the user's local machine (`~/.config/gsuite-cli` and `~/.cache/gsuite-cli`). User A never has access to User B's tokens or Workspace data.
- **Direct Communication:** HERMES communicates directly with Google APIs and Google Gemini API—no intermediary proxy or backend server required.

---

## Quick Start Workflow

### 1. Installation

```bash
pip install hermes-cli
```

Verify the installation:

```bash
hermes --version
hermes --help
```

### 2. Initial Setup (OAuth Login)

Ensure your OAuth client credentials are configured (see [Google Cloud OAuth Setup](#google-cloud-oauth-setup-byoc) below) and run:

```bash
hermes auth login
```

This checks your local authentication status, launches a local browser for the official Google OAuth 2.0 consent flow, requests only necessary Workspace scopes, and securely saves your token to your local machine.

To force re-authentication at any time:

```bash
hermes auth login --force
```

### 3. Check Authentication

```bash
hermes auth status
```

Displays your token validity, expiration, refresh token status, and granted scopes.

### 4. Configure Gemini AI

Set your Gemini API key using either an environment variable or HERMES local configuration:

```bash
# Option A: Environment Variable (Recommended for CI / Terminals)
export GEMINI_API_KEY="your-gemini-api-key"
# On Windows PowerShell:
$env:GEMINI_API_KEY = "your-gemini-api-key"

# Option B: Persistent Local Configuration
hermes config set ai.gemini_api_key "your-gemini-api-key"
```

### 5. Use HERMES

Manage all your Google Workspace tools directly from the terminal:

```bash
# Gmail
hermes inbox
hermes gmail list --max-results 10
hermes gmail send --to "colleague@example.com" --subject "Status Update" --body "Everything is on track!"

# Calendar
hermes today
hermes calendar list
hermes calendar create --summary "Team Sync" --start "2026-09-30 10:00" --duration 30

# Google Drive
hermes drive list --page-size 10
hermes upload drive /path/to/report.pdf

# Google Sheets
hermes sheets list
hermes read sheets <SPREADSHEET_ID> --range "Sheet1!A1:D10"

# Google Docs
hermes docs list
hermes read docs <DOCUMENT_ID>

# Google Meet
hermes meet create --topic "Project Review"

# Google Forms
hermes forms list
hermes forms responses <FORM_ID>

# Google Tasks
hermes tasks list
hermes tasks add "Review PR for HERMES CLI"

# Gemini AI Features
hermes ai ask "Summarize my meetings for today"
hermes ai chat
hermes ai compose "Draft an apology email for being 5 minutes late"
```

### 6. Logout

```bash
hermes auth logout
```

Revokes your active OAuth token online with Google and removes the local token file without affecting other users.

---

## Supported Python Versions

HERMES supports:
- **Python 3.8**
- **Python 3.9**
- **Python 3.10**
- **Python 3.11**
- **Python 3.12**

Tested across Windows, Linux, and macOS.

---

## Google Cloud OAuth Setup (BYOC)

HERMES follows the **BYOC (Bring Your Own Credentials)** model. You provide your own Google Cloud OAuth 2.0 client credentials, ensuring you maintain 100% control over your data and API quota.

### 1. Create a Google Cloud Project
1. Navigate to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project (e.g., `My Hermes CLI`).

### 2. Enable Required APIs
Enable the Google Workspace APIs you want to interact with in **APIs & Services → Library**:
- Google Calendar API
- Gmail API
- Google Drive API
- Google Sheets API
- Google Docs API
- Google Meet API
- Google Forms API
- Google Tasks API
- Google Chat API
- Google People API (Contacts)

### 3. Configure OAuth Consent Screen
1. Go to **APIs & Services → OAuth consent screen**.
2. Select **External** (or **Internal** if using a Google Workspace organization).
3. Fill in the App Name (`HERMES CLI`) and User support email.
4. Add your email under **Test users** (if in Testing status).

### 4. Create Desktop OAuth Client ID
1. Go to **APIs & Services → Credentials**.
2. Click **Create Credentials → OAuth client ID**.
3. Select **Application type: Desktop app**.
4. Set the name to `HERMES Desktop Client` and click **Create**.
5. Download the JSON file.

### 5. Supply Your Credentials to HERMES
You can provide your client credentials in any of the following ways:

- **Standard File Location (Recommended):**
  - **Linux / macOS:** `~/.config/gsuite-cli/credentials.json`
  - **Windows:** `C:\Users\<username>\.config\gsuite-cli\credentials.json`

- **Environment Variable (File Path):**
  ```bash
  export HERMES_GOOGLE_CLIENT_SECRET="/path/to/downloaded-credentials.json"
  ```

- **Environment Variable (Credentials Content or Secret Key):**
  ```bash
  # As raw JSON string:
  export HERMES_GOOGLE_CLIENT_SECRET='{"installed":{"client_id":"...","client_secret":"..."}}'
  
  # Or paired with client ID:
  export HERMES_GOOGLE_CLIENT_ID="your-client-id.apps.googleusercontent.com"
  export HERMES_GOOGLE_CLIENT_SECRET="your-client-secret"
  ```

---

## Required Workspace Scopes

HERMES requests standard, user-scoped OAuth permissions depending on the service:

| Service | Scopes Requested |
|---|---|
| **Gmail** | `https://www.googleapis.com/auth/gmail.modify`, `https://www.googleapis.com/auth/gmail.settings.basic` |
| **Calendar** | `https://www.googleapis.com/auth/calendar` |
| **Drive** | `https://www.googleapis.com/auth/drive` |
| **Sheets** | `https://www.googleapis.com/auth/spreadsheets`, `https://www.googleapis.com/auth/drive.file` |
| **Docs** | `https://www.googleapis.com/auth/documents`, `https://www.googleapis.com/auth/drive` |
| **Meet** | `https://www.googleapis.com/auth/meetings.space.created`, `https://www.googleapis.com/auth/meetings.space.readonly` |
| **Forms** | `https://www.googleapis.com/auth/forms.body`, `https://www.googleapis.com/auth/forms.responses.readonly` |
| **Tasks** | `https://www.googleapis.com/auth/tasks` |
| **Chat** | `https://www.googleapis.com/auth/chat.spaces`, `https://www.googleapis.com/auth/chat.messages` |

---

## Local Credential Storage & Cache

HERMES utilizes user-isolated paths resolved via Python's standard `Path.home()`:

| Resource | Linux / macOS | Windows |
|---|---|---|
| **Configuration & Tokens** | `~/.config/gsuite-cli/` | `C:\Users\<username>\.config\gsuite-cli\` |
| **Token File** | `~/.config/gsuite-cli/token.json` | `C:\Users\<username>\.config\gsuite-cli\token.json` |
| **Local Cache** | `~/.cache/gsuite-cli/` | `C:\Users\<username>\.cache\gsuite-cli\` |

You can customize the configuration directory for any command using:
```bash
hermes --config-dir /path/to/custom/dir <command>
```

To manage the local cache:
```bash
hermes cache stats
hermes cache clear
```

---

## Security Model

1. **Zero Secret Bundling:** The distributed Python package contains zero hardcoded API keys, private OAuth secrets, or user tokens.
2. **Client-Side Only:** All network calls go directly to `googleapis.com` or `generativelanguage.googleapis.com`. No telemetry or credentials are sent to any developer-owned server.
3. **Multi-User Isolation:** Each user runs the CLI in their own operating system context. User tokens, cache databases, and configuration are saved strictly in the user's home folder with OS file permissions.
4. **Token Security:** Stored tokens are refreshed automatically using Google's OAuth token endpoint and can be cleanly revoked online and deleted locally at any time via `hermes auth logout`.

---

## Output Formats & Scripting

HERMES supports multiple output formats for easy scripting and terminal viewing:

```bash
# Standard table (default)
hermes calendar list

# JSON format (ideal for jq, Python, and scripting)
hermes calendar list --format json

# CSV format (ideal for spreadsheets and data processing)
hermes calendar list --format csv
```

---

## Troubleshooting

### "OAuth client configuration not found"
- Ensure `credentials.json` is placed in `~/.config/gsuite-cli/credentials.json` or set `HERMES_GOOGLE_CLIENT_SECRET=/path/to/credentials.json`.
- Verify the credentials type in Google Cloud is **Desktop application** (not Web application).

### "Access blocked: This app has not been verified"
- If your Google Cloud OAuth consent screen is in **Testing** status, add your Google email address under **Test users** on the Google Cloud Console OAuth consent screen page.

### "Permission denied (403)"
- Re-run `hermes auth login --force` to re-authorize and ensure all requested scope checkboxes are checked in the Google browser prompt.

### Gemini API Key Missing
- Run `hermes config set ai.gemini_api_key YOUR_KEY` or `export GEMINI_API_KEY=YOUR_KEY`.

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
