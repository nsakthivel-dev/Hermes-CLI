"""
Hermes-CLI Project Zipping Utility
==================================
Packages the project into a clean ZIP file on the Desktop.
- Excludes:
  * Real API keys, OAuth credentials, tokens, secrets, .env files
  * Virtual environments (venv, .venv, env)
  * Python cache (__pycache__, *.pyc, *.pyo, *.pyd)
  * Test & build caches (.pytest_cache, *.egg-info, build, dist)
  * IDE metadata (.vscode, .idea)
  * Version control directories (.git)
  * Temporary and log files (*.log, Thumbs.db, .DS_Store)
- Substitutes:
  * Safe duplicate / mock template files for credentials and environment variables
    so the project structure stays intact without leaking personal data or secrets.
- Output:
  * Saved directly to the user's Desktop (supports standard and OneDrive-synced Desktop).
"""

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
import zipfile

# ---------------------------------------------------------------------------
# Safe Dummy / Template Content for Sensitive Files
# ---------------------------------------------------------------------------
DUMMY_CREDENTIALS_JSON = json.dumps(
    {
        "installed": {
            "client_id": "YOUR_CLIENT_ID_HERE.apps.googleusercontent.com",
            "project_id": "YOUR_PROJECT_ID_HERE",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_secret": "YOUR_CLIENT_SECRET_HERE",
            "redirect_uris": [
                "http://localhost"
            ]
        }
    },
    indent=2
) + "\n"

DUMMY_TOKEN_JSON = json.dumps(
    {
        "token": "DUMMY_ACCESS_TOKEN_PLACEHOLDER",
        "refresh_token": "DUMMY_REFRESH_TOKEN_PLACEHOLDER",
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": "YOUR_CLIENT_ID_HERE.apps.googleusercontent.com",
        "client_secret": "YOUR_CLIENT_SECRET_HERE",
        "scopes": [
            "https://www.googleapis.com/auth/calendar",
            "https://www.googleapis.com/auth/gmail.modify",
            "https://www.googleapis.com/auth/tasks",
            "https://www.googleapis.com/auth/drive"
        ],
        "expiry": "2099-01-01T00:00:00Z"
    },
    indent=2
) + "\n"

DUMMY_ENV = (
    "# Hermes-CLI Environment Configuration Template\n"
    "# Replace these placeholder values with your own keys\n"
    "GOOGLE_APPLICATION_CREDENTIALS=credentials.json\n"
    "API_KEY=YOUR_API_KEY_HERE\n"
    "SECRET_KEY=YOUR_SECRET_KEY_HERE\n"
    "HERMES_ENV=development\n"
)

# Directory names to completely skip
EXCLUDE_DIRS = {
    "__pycache__",
    ".pytest_cache",
    ".git",
    ".github",
    ".venv",
    "venv",
    "env",
    ".env",
    "build",
    "dist",
    "develop-eggs",
    "eggs",
    ".eggs",
    ".vscode",
    ".idea",
    ".cache",
    "cache",
    "data",
}

# File names/patterns to exclude from raw copying
EXCLUDE_EXACT_FILES = {
    "zip_project.py",
    "zip_project.bat",
    "credentials.json",
    "token.json",
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    ".installed.cfg",
    "Thumbs.db",
    ".DS_Store",
}

EXCLUDE_EXTENSIONS = {
    ".pyc",
    ".pyo",
    ".pyd",
    ".log",
    ".tmp",
    ".zip",
}

# Files that should be replaced with dummy/template versions in the zip archive
REPLACE_WITH_DUMMY = {
    "credentials.json": DUMMY_CREDENTIALS_JSON,
    "token.json": DUMMY_TOKEN_JSON,
    ".env": DUMMY_ENV,
}


def get_desktop_dir() -> Path:
    """Accurately locates the user's Desktop directory on Windows (including OneDrive)."""
    if os.name == "nt":
        try:
            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            # CSIDL_DESKTOPDIRECTORY = 0x0010
            if ctypes.windll.shell32.SHGetFolderPathW(None, 0x0010, None, 0, buf) == 0:
                desktop = Path(buf.value)
                if desktop.exists():
                    return desktop
        except Exception:
            pass

    # Fallbacks
    user_profile = Path(os.environ.get("USERPROFILE", Path.home()))
    onedrive_desktop = user_profile / "OneDrive" / "Desktop"
    if onedrive_desktop.exists():
        return onedrive_desktop

    standard_desktop = user_profile / "Desktop"
    if standard_desktop.exists():
        return standard_desktop

    return Path.cwd().parent


def is_excluded_dir(dir_path: Path, root_path: Path) -> bool:
    """Check if any folder in the relative path matches excluded directory rules."""
    rel = dir_path.relative_to(root_path)
    for part in rel.parts:
        if part in EXCLUDE_DIRS or part.endswith(".egg-info"):
            return True
    return False


def is_sensitive_or_excluded_file(file_path: Path, root_path: Path) -> bool:
    """Determine if a file should be excluded from raw copying."""
    name = file_path.name.lower()
    suffix = file_path.suffix.lower()

    if suffix in EXCLUDE_EXTENSIONS:
        return True

    if name in {f.lower() for f in EXCLUDE_EXACT_FILES}:
        return True

    if name.startswith(".env") or name.endswith((".key", ".pem", ".p12", ".pfx")):
        return True

    return False


def create_project_zip(root_path: Path, output_zip_path: Path) -> tuple[int, int, list[str]]:
    """Creates the sanitized project zip file."""
    archive_root_name = "Hermes-CLI"
    files_added = 0
    files_replaced = 0
    replaced_list = []

    # Ensure target directory exists
    output_zip_path.parent.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(output_zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        # 1. Walk through all files in project root
        for dirpath_str, dirnames, filenames in os.walk(root_path):
            dirpath = Path(dirpath_str)

            # Skip excluded directories entirely
            if is_excluded_dir(dirpath, root_path):
                dirnames.clear()
                continue

            # Filter out subdirectories that shouldn't be traversed
            dirnames[:] = [
                d for d in dirnames
                if d not in EXCLUDE_DIRS and not d.endswith(".egg-info")
            ]

            for filename in filenames:
                file_path = dirpath / filename
                rel_path = file_path.relative_to(root_path)
                arcname = f"{archive_root_name}/{rel_path.as_posix()}"

                # Check if it is a sensitive file that needs a duplicate dummy replacement
                if filename in REPLACE_WITH_DUMMY:
                    dummy_content = REPLACE_WITH_DUMMY[filename]
                    zf.writestr(arcname, dummy_content)
                    files_replaced += 1
                    replaced_list.append(rel_path.as_posix())
                    continue

                # Check if excluded
                if is_sensitive_or_excluded_file(file_path, root_path):
                    continue

                # Add normal source file
                try:
                    zf.write(file_path, arcname)
                    files_added += 1
                except Exception as e:
                    print(f"  [!] Warning: Could not add {rel_path}: {e}")

        # Ensure that if gsuite_cli/credentials.json wasn't already replaced, we add a template
        # for standard onboarding so the repo works out of the box
        default_cred_arc = f"{archive_root_name}/gsuite_cli/credentials.json"
        if default_cred_arc not in zf.namelist():
            zf.writestr(default_arc, DUMMY_CREDENTIALS_JSON)
            files_replaced += 1
            replaced_list.append("gsuite_cli/credentials.json (template created)")

        # Also add a duplicate .env.example template for standard environment setup
        env_example_arc = f"{archive_root_name}/.env.example"
        if env_example_arc not in zf.namelist():
            zf.writestr(env_example_arc, DUMMY_ENV)
            files_replaced += 1
            replaced_list.append(".env.example (template created)")

    return files_added, files_replaced, replaced_list


def main():
    root_path = Path(__file__).resolve().parent
    desktop_dir = get_desktop_dir()
    zip_filename = "Hermes-CLI.zip"
    output_zip_path = desktop_dir / zip_filename

    print("==========================================================")
    print("       Hermes-CLI Clean Project Packaging Tool            ")
    print("==========================================================")
    print(f"Project Source : {root_path}")
    print(f"Destination    : {output_zip_path}")
    print("----------------------------------------------------------")
    print("Processing files and sanitizing secrets...")

    try:
        added_count, replaced_count, replaced_list = create_project_zip(root_path, output_zip_path)
        size_bytes = output_zip_path.stat().st_size
        size_kb = size_bytes / 1024
        size_mb = size_kb / 1024

        size_str = f"{size_mb:.2f} MB" if size_mb >= 1.0 else f"{size_kb:.1f} KB"

        print("----------------------------------------------------------")
        print("Packaging Completed Successfully!")
        print(f"Total source code files included: {added_count}")
        print(f"Sensitive files replaced with safe templates: {replaced_count}")
        for r in replaced_list:
            print(f"   -> [Safe Template] {r}")
        print(f"Archive Size: {size_str}")
        print(f"Zip Location: {output_zip_path}")
        print("==========================================================")
        print("Real API keys, secrets, credentials, and cache directories")
        print("were excluded. Duplicate template files were injected.")
        print("==========================================================")
    except Exception as e:
        print(f"\n[ERROR] Failed to package project: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
