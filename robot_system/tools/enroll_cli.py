#!/usr/bin/env python3
"""Minimal face enrollment CLI — promote candidate or register by id."""

from __future__ import annotations

import argparse
import sys

from face_core.repository import FaceRepository
from vision.face_db import FaceDB


def main() -> int:
    parser = argparse.ArgumentParser(description="FaceDB enrollment utility")
    sub = parser.add_subparsers(dest="cmd", required=True)

    list_p = sub.add_parser("list", help="List known person ids")
    list_p.add_argument("--limit", type=int, default=20)

    promote_p = sub.add_parser("promote", help="Promote candidate to known person")
    promote_p.add_argument("candidate_id")
    promote_p.add_argument("name")

    vip_p = sub.add_parser("set-vip", help="Set VIP level for a person")
    vip_p.add_argument("person_id")
    vip_p.add_argument(
        "level",
        choices=[
            "executive",
            "director",
            "sales_director",
            "consultant",
            "vip_customer",
            "regular_customer",
        ],
    )

    args = parser.parse_args()
    repo = FaceRepository(FaceDB())

    if args.cmd == "list":
        ids = repo.list_known_ids()[: args.limit]
        for pid in ids:
            print(f"{pid}\t{repo.get_name(pid)}\t{repo.get_vip_level(pid)}")
        return 0

    if args.cmd == "promote":
        ok = repo.promote_candidate(args.candidate_id, args.name)
        if not ok:
            print(f"Failed to promote {args.candidate_id}", file=sys.stderr)
            return 1
        print(f"Promoted {args.candidate_id} -> {args.name}")
        return 0

    if args.cmd == "set-vip":
        ok = repo.set_vip_level(args.person_id, args.level)
        if not ok:
            print(f"Unknown person_id: {args.person_id}", file=sys.stderr)
            return 1
        print(f"Set {args.person_id} vip_level={args.level}")
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
