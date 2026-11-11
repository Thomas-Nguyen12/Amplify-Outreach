"""One-time migration of canonical lead and suppression data from local SQLite.

DRY RUN by default. --apply requires SURREAL_ENABLED=true. This does not
migrate all CRM tables; see docs/SURREALDB_END_TO_END_PERSISTENCE.md.
"""
import argparse
from app.config import get_settings
from app.database import rows, init_db
from app.surreal_store import PersistentStore, lead_identity, canonical_identity


def migrate(*, apply=False, store=None):
    init_db()
    leads=rows('SELECT * FROM prospects ORDER BY id')
    suppressions=rows('SELECT * FROM suppression ORDER BY id')
    report={'mode':'apply' if apply else 'dry_run', 'prospects':len(leads),
            'suppression':len(suppressions),'written_prospects':0,
            'written_suppressions':0}
    if not apply:
        return report
    if not get_settings().surreal_enabled:
        raise RuntimeError('Set SURREAL_ENABLED=true to apply migration')
    store=store or PersistentStore()
    store.ping()
    # Migrate suppressions FIRST to prevent an unsuppressed live identity gap.
    for row in suppressions:
        store.suppress(canonical_identity(row['identity']),row['reason'])
        report['written_suppressions']+=1
    for row in leads:
        identity=lead_identity(row)
        if not store.get_prospect(identity):
            store.claim_prospect(identity,row)
            report['written_prospects']+=1
    return report


def main():
    import json
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true',help='Write to your configured SurrealDB instance')
    args=parser.parse_args()
    print(json.dumps(migrate(apply=args.apply),indent=2))


if __name__=='__main__':
    main()
