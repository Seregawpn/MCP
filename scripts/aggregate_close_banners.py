#!/usr/bin/env python3
import argparse
import json
import os
import re
from collections import defaultdict
from datetime import datetime

try:
    import yaml  # type: ignore
except Exception:
    yaml = None  # type: ignore


SAFE_REJECT_TERMS = [
    "reject",
    "deny",
    "opt-out",
    "nein",
    "no ",  # leading space to avoid matching words like 'not'
    "отказ",
    "не принять",
]


TEXT_PATTERN = re.compile(r"button:has-text\('([^']+)'\)")


def is_safe_selector(selector: str) -> bool:
    s = selector.lower()
    for term in SAFE_REJECT_TERMS:
        if term in s:
            return False
    # basic whitelist of tokens
    allowed_tokens = [
        "button",
        "a",
        "input",
        "[role=",
        "aria-label",
        "[id",
        "[class",
        ":has-text",
        "[data-test",
        "[data-testid",
        "#",
        ".",
    ]
    if not any(tok in s for tok in allowed_tokens):
        return False
    return True


def load_existing_profiles(path: str) -> dict:
    if yaml is None or not os.path.exists(path):
        return {"version": 1, "updated_at": None, "global": {"texts": [], "selectors": []}, "domains": {}}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        return {"version": 1, "updated_at": None, "global": {"texts": [], "selectors": []}, "domains": {}}
    # normalize
    data.setdefault("version", 1)
    data.setdefault("updated_at", None)
    data.setdefault("global", {})
    data["global"].setdefault("texts", [])
    data["global"].setdefault("selectors", [])
    data.setdefault("domains", {})
    for d, val in list(data["domains"].items()):
        if not isinstance(val, dict):
            data["domains"][d] = {"selectors": []}
        else:
            val.setdefault("selectors", [])
    return data


def write_profiles(path: str, profiles: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    profiles = dict(profiles)
    profiles["updated_at"] = datetime.utcnow().isoformat() + "Z"
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(profiles, f, allow_unicode=True, sort_keys=False)


def main() -> None:
    ap = argparse.ArgumentParser(description="Aggregate close banner candidates into YAML profiles")
    ap.add_argument("--input", default=os.path.join(os.path.dirname(__file__), "..", "data", "close_banners_candidates.jsonl"))
    ap.add_argument("--output", default=os.path.join(os.path.dirname(__file__), "..", "config", "close_banners_profiles.yml"))
    ap.add_argument("--min-domain-successes", type=int, default=2)
    ap.add_argument("--min-global-domains", type=int, default=3)
    args = ap.parse_args()

    if yaml is None:
        print("PyYAML is not available. Please `pip install pyyaml`.", flush=True)
        raise SystemExit(2)

    input_path = os.path.abspath(args.input)
    output_path = os.path.abspath(args.output)

    if not os.path.exists(input_path):
        print(f"No input file found: {input_path}")
        raise SystemExit(1)

    domain_sel_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    text_to_domains: dict[str, set[str]] = defaultdict(set)

    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if not isinstance(rec, dict):
                continue
            if rec.get("type") != "CandidateSuccess":
                continue
            domain = (rec.get("domain") or "").lower()
            cta = rec.get("cta") or {}
            selector = (cta.get("selector") or "").strip()
            if not domain or not selector:
                continue
            if not is_safe_selector(selector):
                continue
            domain_sel_counts[domain][selector] += 1
            # attempt to extract has-text value for global texts
            m = TEXT_PATTERN.search(selector)
            if m:
                text = m.group(1).strip()
                if text and all(term not in text.lower() for term in SAFE_REJECT_TERMS):
                    text_to_domains[text].add(domain)

    existing = load_existing_profiles(output_path)

    # Merge domain selectors
    for domain, sel_counts in domain_sel_counts.items():
        selected = [sel for sel, cnt in sel_counts.items() if cnt >= args.min_domain_successes]
        if not selected:
            continue
        bucket = existing["domains"].setdefault(domain, {"selectors": []})
        merged = list(dict.fromkeys([*bucket.get("selectors", []), *selected]))
        # keep at most 20 per domain to avoid bloat
        bucket["selectors"] = merged[:20]

    # Merge global texts
    global_texts = [t for t, doms in text_to_domains.items() if len(doms) >= args.min_global_domains]
    if global_texts:
        existing["global"]["texts"] = list(dict.fromkeys([*existing["global"].get("texts", []), *global_texts]))

    write_profiles(output_path, existing)
    print(f"Aggregated profiles written to: {output_path}")


if __name__ == "__main__":
    main()


