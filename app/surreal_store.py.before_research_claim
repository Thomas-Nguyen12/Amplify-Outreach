
"""Durable, deterministic SurrealDB records for live discovery.

When enabled, reads and writes fail closed: no silent fallback to a fresh SQLite
sandbox for identity, suppression, research, or outreach-draft decisions.

SQLite remains a local API cache; for recurring ephemeral Cloud Run jobs SurrealDB
holds canonical prospects, suppression flags, research, and draft state.
"""

import hashlib
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

from .config import get_settings


def _record_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_identity(value: str) -> str:
    """Normalise common URL spelling differences without merging distinct profiles."""
    value = (value or "").strip()

    if not value:
        raise ValueError("Missing business identity")

    parts = urlsplit(value)

    if parts.scheme.lower() not in ("https", "http") or not parts.netloc:
        return value.lower().rstrip("/")

    host = (parts.hostname or "").lower()

    if host.startswith("www."):
        host = host[4:]

    if parts.port and parts.port not in (80, 443):
        host += f":{parts.port}"

    path = parts.path.rstrip("/")

    return urlunsplit(("https", host, path, "", ""))


def lead_identity(lead) -> str:
    def get(field):
        return (
            lead.get(field)
            if isinstance(lead, dict)
            else getattr(lead, field, None)
        )

    # Preserve immutable channel identity, even if the channel's website changes.
    if get("platform") == "youtube_direct" and get("profile_url"):
        return canonical_identity(get("profile_url"))

    return canonical_identity(
        get("dedupe_key")
        or get("website")
        or get("profile_url")
        or get("source_url")
    )


class PersistentStore:
    """Thin SurrealDB SDK wrapper with one database session per operation."""

    def __init__(self, settings=None):
        self.settings = settings or get_settings()

    def _session(self):
        from surrealdb import Surreal

        return Surreal(self.settings.surreal_url)

    def _connect(self, db):
        s = self.settings

        db.signin({
            "username": s.surreal_username,
            "password": s.surreal_password,
        })

        db.use(
            s.surreal_namespace,
            s.surreal_database,
        )

    @staticmethod
    def _rid(table, identity):
        from surrealdb import RecordID

        return RecordID(table, _record_key(identity))

    @staticmethod
    def _result(value):
        # SDK 2.x executes reads directly; SDK 3.x may use builders.
        return value.execute() if hasattr(value, "execute") else value

    def ping(self):
        with self._session() as db:
            self._connect(db)
            self._result(db.query("RETURN true"))

        return True

    def create_once(
        self,
        table: str,
        identity: str,
        payload: dict,
    ) -> bool:
        """Atomically create a record without interpreting transport errors as duplicates."""

        with self._session() as db:
            self._connect(db)

            rid = self._rid(table, identity)

            try:
                self._result(
                    db.create(
                        rid,
                        {
                            **payload,
                            "identity_key": _record_key(identity),
                        },
                    )
                )

                return True

            except Exception:
                existing = self._result(db.select(rid))

                if existing:
                    return False

                raise

    def get(self, table: str, identity: str):
        with self._session() as db:
            self._connect(db)

            value = self._result(
                db.select(self._rid(table, identity))
            )

        if isinstance(value, list):
            return value[0] if value else None

        return value

    def put(
        self,
        table: str,
        identity: str,
        data: dict,
    ):
        with self._session() as db:
            self._connect(db)

            return db.upsert(
                self._rid(table, identity),
                {
                    **data,
                    "identity_key": _record_key(identity),
                    "updated_at": datetime.now(
                        timezone.utc
                    ).isoformat(),
                },
            )

    def list_records(
        self,
        table: str,
        limit: int = 100,
    ):
        allowed_tables = (
            "prospects",
            "research_briefs",
            "outreach_drafts",
            "suppression",
            "subscription_opportunities",
            "contact_routes",
            "outreach_send_claims",
            "outreach_daily_slots",
            "outreach_send_attempts",
            "outreach_reply_events",
        )

        if table not in allowed_tables:
            raise ValueError("Unsupported table")

        # SDK 2.x and 3.x both accept a table name here.
        # The SDK may retrieve the entire table; implement pagination
        # before using this method for large-scale production workloads.
        with self._session() as db:
            self._connect(db)

            value = self._result(db.select(table))

        return (value or [])[
            : max(1, min(limit, 500))
        ]

    def remove(
        self,
        table: str,
        identity: str,
    ):
        with self._session() as db:
            self._connect(db)

            return self._result(
                db.delete(self._rid(table, identity))
            )

    def is_suppressed(
        self,
        identity: str,
    ) -> bool:
        return (
            self.get(
                "suppression",
                canonical_identity(identity),
            )
            is not None
        )

    def suppress(
        self,
        identity: str,
        reason: str,
    ):
        identity = canonical_identity(identity)

        return self.put(
            "suppression",
            identity,
            {
                "identity": identity,
                "reason": reason,
                "created_at": datetime.now(
                    timezone.utc
                ).isoformat(),
            },
        )

    def get_prospect(
        self,
        identity: str,
    ):
        return self.get(
            "prospects",
            canonical_identity(identity),
        )

    def save_prospect(
        self,
        identity: str,
        lead: dict,
    ):
        identity = canonical_identity(identity)

        payload = {
            k: v
            for k, v in lead.items()
            if k != "id"
        }

        payload["dedupe_key"] = identity
        payload["created_at"] = (
            lead.get("created_at")
            or datetime.now(timezone.utc).isoformat()
        )

        return self.put(
            "prospects",
            identity,
            payload,
        )

    def claim_prospect(
        self,
        identity: str,
        lead: dict,
    ) -> bool:
        """Atomically create a prospect record.

        Returns False if another execution already created the record.
        SurrealDB record-ID uniqueness is the concurrency arbiter.
        """

        identity = canonical_identity(identity)

        payload = {
            k: v
            for k, v in lead.items()
            if k != "id"
        }

        payload.update(
            dedupe_key=identity,
            identity_key=_record_key(identity),
            created_at=datetime.now(
                timezone.utc
            ).isoformat(),
        )

        with self._session() as db:
            self._connect(db)

            rid = self._rid(
                "prospects",
                identity,
            )

            try:
                self._result(db.create(rid, payload))
                return True

            except Exception:
                existing = self._result(db.select(rid))

                if existing:
                    return False

                raise

    # ==========================================================
    # HelloMinds research reservations
    # ==========================================================

    def claim_research(
        self,
        identity: str,
        alias: str,
    ) -> bool:
        """Atomically reserve one HelloMinds research job per prospect.

        Returns:
            True: this execution created the reservation.
            False: a research record already exists.

        Existing reservations, pending jobs and completed reports
        are never overwritten by this method.

        A reservation is NOT permission to resend a prompt after
        a crash. Recovery must inspect the existing conversation.
        """

        identity = canonical_identity(identity)

        if (
            not isinstance(alias, str)
            or not alias
            or len(alias) > 100
            or not all(
                char.isalnum() or char in "_-"
                for char in alias
            )
            or not alias.isascii()
        ):
            raise ValueError(
                "A valid HelloMinds conversation alias is required"
            )

        now = datetime.now(
            timezone.utc
        ).isoformat()

        payload = {
            "prospect_identity": identity,
            "alias": alias,
            "status": "reserved",
            "reply": "",
            "identity_key": _record_key(identity),
            "created_at": now,
            "updated_at": now,
        }

        with self._session() as db:
            self._connect(db)

            rid = self._rid(
                "research_briefs",
                identity,
            )

            try:
                self._result(
                    db.create(rid, payload)
                )
                return True

            except Exception:
                # The record may have been created by another
                # Cloud Run execution. Only classify it as
                # already claimed if it now exists.
                existing = self._result(
                    db.select(rid)
                )

                if existing:
                    return False

                # Preserve unexpected database/transport errors.
                raise

    def get_research(
        self,
        identity: str,
    ):
        return self.get(
            "research_briefs",
            canonical_identity(identity),
        )

    def save_research(
        self,
        identity: str,
        result: dict,
    ):
        from .research_assessment import classify_research

        identity = canonical_identity(identity)
        state = classify_research(result)

        payload = {
            "prospect_identity": identity,
            "mind_id": result.get(
                "mind_id",
                "",
            ),
            "alias": result.get(
                "alias",
                "",
            ),
            "reply": result.get(
                "reply",
                "",
            ),
            "status": state,
            "created_at": datetime.now(
                timezone.utc
            ).isoformat(),
        }

        if "after_fingerprint" in result:
            payload["after_fingerprint"] = (
                result["after_fingerprint"]
            )

        return self.put(
            "research_briefs",
            identity,
            payload,
        )

    # ==========================================================
    # Outreach drafts
    # ==========================================================

    def save_draft(
        self,
        identity: str,
        subject: str,
        message: str,
    ):
        return self.put(
            "outreach_drafts",
            canonical_identity(identity),
            {
                "prospect_identity": canonical_identity(
                    identity
                ),
                "subject": subject,
                "message": message,
                "status": "draft",
                "created_at": datetime.now(
                    timezone.utc
                ).isoformat(),
                "sent": False,
            },
        )

    def get_draft(
        self,
        identity: str,
    ):
        return self.get(
            "outreach_drafts",
            canonical_identity(identity),
        )


def enabled_store():
    return (
        PersistentStore()
        if get_settings().surreal_enabled
        else None
    )


def mirror_record(
    table: str,
    identity: str,
    data: dict,
) -> None:
    store = enabled_store()

    if store:
        store.put(
            table,
            identity,
            data,
        )


def mirror_prospect(
    lead: dict,
) -> None:
    store = enabled_store()

    if store:
        store.save_prospect(
            lead_identity(lead),
            lead,
        )


def mirror_research(
    lead_id: int,
    result: dict,
    *,
    identity: str = "",
) -> None:
    store = enabled_store()

    if store:
        if not identity:
            from .database import rows

            lead = rows(
                "SELECT * FROM prospects WHERE id=?",
                (lead_id,),
            )

            if not lead:
                raise ValueError(
                    "Cannot persist research without its prospect"
                )

            identity = lead_identity(lead[0])

        store.save_research(
            identity,
            result,
        )

