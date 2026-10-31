"""
Build the graph db from the processing db.

Usage:
    python -m v2.main graph-db                        # processed/processed_data.db -> processed/graph.db
    python -m v2.main graph-db --out other/graph.db
    python -m v2.main graph-db --source copy_of_processing.db
"""

import argparse
import sys

from v2.common.settings import settings
from v2.stage4_graph_db.build import BuildError, build


def main():
    parser = argparse.ArgumentParser(description="Stage 4: build the graph db (rebuilt from scratch)")
    parser.add_argument("--source", default=settings.PROCESSED_DB, help="Processing db (read-only)")
    parser.add_argument("--out", default=settings.GRAPH_DB, help="Graph db to (re)create")
    args = parser.parse_args()

    try:
        report = build(args.source, args.out)
    except BuildError as e:
        print(f"Build failed, {args.out} left unchanged:\n{e}")
        sys.exit(1)

    print(f"Built {report.path} from {args.source}")
    for table, n in report.counts.items():
        print(f"  {table:12} {n:6}")
    print(f"  spend        {report.spend:,.2f} (processing db: {report.source_spend:,.2f})")


if __name__ == "__main__":
    main()
