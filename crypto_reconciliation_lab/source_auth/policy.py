"""Closed operator policies and append-only local epoch activation."""
from datetime import datetime, timezone
import json
import re
from ..migrations import transaction, validate_current
from ..model import digest, timestamp
from .crypto import AuthError, canonical, fingerprint, hex_digest, identifier, require_auth, sha256, strict_json
from .scope import capability_inventory


def observed(value=None):
    return timestamp(value if value is not None else datetime.now(timezone.utc).isoformat())


def validate_policy(value, config, receiver):
    # Copy through strict JSON so caller mutation cannot alter an activated policy.
    if type(value) is bytes:
        value = strict_json(value, limit=128 * 1024)
    else:
        try:
            value = strict_json(canonical(value), limit=128 * 1024)
        except (ValueError, TypeError) as exc:
            raise AuthError("AUTH_POLICY", "invalid policy JSON") from exc
    fields = {"format", "receiver", "configuration_digest", "sources", "keys"}
    if type(value) is not dict or set(value) != fields or value["format"] != "source-auth-policy-v1":
        raise AuthError("AUTH_POLICY", "exact source-auth-policy-v1 fields required")
    identifier(receiver, "receiver")
    if value["receiver"] != receiver or value["configuration_digest"] != digest(config):
        raise AuthError("AUTH_POLICY", "policy receiver/configuration differs from local binding")
    sources, keys = value["sources"], value["keys"]
    if type(sources) is not list or not 0 < len(sources) <= 2 or type(keys) is not list or not 0 < len(keys) <= 100:
        raise AuthError("AUTH_POLICY", "bounded nonempty sources and keys required")
    seen_sources, namespaces = set(), []
    for source in sources:
        if type(source) is not dict or set(source) != {"source", "namespace", "capabilities"}:
            raise AuthError("AUTH_POLICY", "exact source fields required")
        name, namespace = source["source"], source["namespace"]
        if type(name) is not str or name not in (config["platform"], config["custodian"]) or name in seen_sources:
            raise AuthError("AUTH_POLICY", "unknown or duplicate source")
        if type(namespace) is not str or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}:", namespace) is None:
            raise AuthError("AUTH_POLICY", "invalid ASCII stream namespace")
        if any(namespace.startswith(other) or other.startswith(namespace) for other in namespaces):
            raise AuthError("AUTH_POLICY", "overlapping stream namespaces")
        seen_sources.add(name)
        namespaces.append(namespace)
        source["capabilities"] = capability_inventory(source["capabilities"], config)
        if any(cap["source"] != name for cap in source["capabilities"]):
            raise AuthError("AUTH_POLICY", "capability belongs to a different publisher")
    seen_ids, fingerprints = set(), set()
    for key in keys:
        if type(key) is not dict or set(key) != {"key_id", "source", "public_key", "fingerprint", "status"}:
            raise AuthError("AUTH_POLICY", "exact key fields required")
        identifier(key["key_id"], "key ID")
        if key["key_id"] in seen_ids or type(key["source"]) is not str or key["source"] not in seen_sources:
            raise AuthError("AUTH_POLICY", "duplicate key ID or unknown key source")
        if not hex_digest(key["public_key"]) or not hex_digest(key["fingerprint"]) or fingerprint(bytes.fromhex(key["public_key"])) != key["fingerprint"]:
            raise AuthError("AUTH_POLICY", "public key and fingerprint disagree")
        if key["fingerprint"] in fingerprints or type(key["status"]) is not str or key["status"] not in ("active", "revoked"):
            raise AuthError("AUTH_POLICY", "ambiguous fingerprint or key status")
        seen_ids.add(key["key_id"])
        fingerprints.add(key["fingerprint"])
    value["sources"] = sorted(sources, key=lambda source: source["source"])
    value["keys"] = sorted(keys, key=lambda key: key["key_id"])
    return value


def active_policy(db):
    row = db.execute("""SELECT a.*,s.payload FROM auth_policy_activations a
        JOIN auth_policy_snapshots s ON s.policy_hash=a.policy_hash ORDER BY epoch DESC LIMIT 1""").fetchone()
    if row is None:
        return None
    result = dict(row)
    result["payload"] = json.loads(result["payload"])
    return result


def protection(db):
    exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='auth_configuration'").fetchone()
    if not exists:
        return None
    row = db.execute("SELECT * FROM auth_configuration WHERE id=1").fetchone()
    return dict(row) if row is not None else None


def _append(db, value, epoch, previous, when):
    serialized = canonical(value)
    policy_hash = sha256(serialized)
    db.execute("INSERT OR IGNORE INTO auth_policy_snapshots(policy_hash,payload) VALUES (?,?)", (policy_hash, serialized.decode("ascii")))
    db.execute("INSERT INTO auth_policy_activations VALUES (?,?,?,?,?)",
               (epoch, policy_hash, previous["epoch"] if previous else None, previous["policy_hash"] if previous else None, when))
    for key in value["keys"]:
        db.execute("INSERT OR IGNORE INTO auth_keys VALUES (?,?,?,?,?)",
                   (key["key_id"], key["source"], bytes.fromhex(key["public_key"]), key["fingerprint"], epoch))
    return {"epoch": epoch, "policy_hash": policy_hash, "payload": value}


def enable_protection(store, receiver, policy, *, observed_at=None):
    require_auth()
    value = validate_policy(policy, store.config, receiver)
    when = observed(observed_at)
    with transaction(store.db):
        validate_current(store.db)
        if protection(store.db) is not None:
            raise AuthError("AUTH_SETUP", "protection is already permanently configured")
        # Only configuration and migration metadata may predate protection.
        exempt = {"configuration", "schema_migrations"}
        tables = [row[0] for row in store.db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for table in tables:
            if table.startswith("sqlite_") or table in exempt:
                continue
            if store.db.execute('SELECT 1 FROM "' + table.replace('"', '""') + '" LIMIT 1').fetchone():
                raise AuthError("AUTH_SETUP", "protection requires an empty database")
        result = _append(store.db, value, 1, None, when)
        store.db.execute("INSERT INTO auth_configuration VALUES (1,?,?,?)", (receiver, digest(store.config), result["policy_hash"]))
    return result


def activate_policy(store, policy, expected_epoch, expected_hash, *, observed_at=None):
    require_auth()
    if type(expected_epoch) is not int or expected_epoch < 1 or not hex_digest(expected_hash):
        raise AuthError("AUTH_POLICY", "exact expected epoch/hash required")
    when = observed(observed_at)
    with transaction(store.db):
        validate_current(store.db)
        protected = protection(store.db)
        if protected is None:
            raise AuthError("AUTH_POLICY", "database is not protected")
        value = validate_policy(policy, store.config, protected["receiver"])
        previous = active_policy(store.db)
        if previous["epoch"] != expected_epoch or previous["policy_hash"] != expected_hash:
            raise AuthError("AUTH_POLICY_STALE", "active epoch/hash differs from expected predecessor")
        old_sources = {source["source"]: source for source in previous["payload"]["sources"]}
        new_sources = {source["source"]: source for source in value["sources"]}
        if any(name not in new_sources or old["namespace"] != new_sources[name]["namespace"] for name, old in old_sources.items()):
            raise AuthError("AUTH_POLICY", "historical source namespaces are immutable")
        old_keys = {key["key_id"]: key for key in previous["payload"]["keys"]}
        new_keys = {key["key_id"]: key for key in value["keys"]}
        for key_id, old in old_keys.items():
            new = new_keys.get(key_id)
            if new is None or any(new[field] != old[field] for field in ("source", "public_key", "fingerprint")):
                raise AuthError("AUTH_POLICY", "historical key identity is immutable")
            if old["status"] == "revoked" and new["status"] != "revoked":
                raise AuthError("AUTH_POLICY", "revocation is permanent")
        return _append(store.db, value, previous["epoch"] + 1, previous, when)
