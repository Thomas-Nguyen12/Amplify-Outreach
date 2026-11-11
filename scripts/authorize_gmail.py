"""Local, interactive OAuth setup. Never execute on a headless server.

Usage: python -m scripts.authorize_gmail --read-replies
Existing send-only token is replaced only after successful authorisation.
"""
import argparse
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow
from app.config import get_settings
from app.gmail_service import SEND_SCOPE, READ_SCOPE, safe_path


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--read-replies',action='store_true',help='Also request restricted Gmail read-only scope')
    args=p.parse_args()
    s=get_settings()
    client=safe_path(s.gmail_oauth_client_file)
    token=safe_path(s.gmail_token_file)
    if not client.is_file():
        raise SystemExit(f'Could not find OAuth client JSON: {client}')
    scopes=[SEND_SCOPE]+([READ_SCOPE] if args.read_replies else [])
    flow=InstalledAppFlow.from_client_secrets_file(str(client),scopes)
    credentials=flow.run_local_server(port=0,prompt='consent',access_type='offline')
    token.parent.mkdir(parents=True,exist_ok=True)
    token.write_text(credentials.to_json(),encoding='utf-8')
    token.chmod(0o600)
    print('Gmail authorised. Token saved privately to',token)
    print('Granted scopes:', ', '.join(scopes))

if __name__=='__main__':main()
