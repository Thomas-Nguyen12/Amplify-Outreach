"""One-shot inbox reconciliation. No customer emails are sent by this script."""
import argparse
from app.config import get_settings
from app.surreal_store import enabled_store
from app.gmail_replies import poll_replies


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--limit',type=int,default=50)
    args=p.parse_args()
    s=get_settings()
    store=enabled_store()
    if not store: raise SystemExit('SURREAL_ENABLED must be true')
    print(poll_replies(store,settings=s,limit=args.limit))

if __name__=='__main__':main()
