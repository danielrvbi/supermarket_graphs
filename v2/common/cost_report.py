"""
Cost and token usage reports.

Generates summary aggregations from the token_usage database.
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict


class CostReport:
    """Generate cost and usage reports from token_usage database."""

    def __init__(self, db_path: str):
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        """Get database connection."""
        return sqlite3.connect(self.db_path)

    def summary(self) -> Dict:
        """Overall summary of token usage and costs."""
        conn = self._connect()
        cursor = conn.execute("""
            SELECT
                COUNT(*) as total_calls,
                COUNT(DISTINCT file_path) as receipts_processed,
                COUNT(DISTINCT thread_id) as pipeline_runs,
                SUM(input_tokens) as total_input_tokens,
                SUM(cached_input_tokens) as total_cached_tokens,
                SUM(output_tokens) as total_output_tokens,
                SUM(total_tokens) as total_tokens,
                SUM(input_cost_usd) as total_input_cost,
                SUM(cached_cost_usd) as total_cached_cost,
                SUM(output_cost_usd) as total_output_cost,
                SUM(total_cost_usd) as total_cost_usd,
                MIN(datetime) as first_call,
                MAX(datetime) as last_call
            FROM token_usage
        """)
        row = cursor.fetchone()
        conn.close()

        if row[0] == 0:
            return {
                "total_calls": 0,
                "receipts_processed": 0,
                "pipeline_runs": 0,
                "total_input_tokens": 0,
                "total_cached_tokens": 0,
                "total_output_tokens": 0,
                "total_tokens": 0,
                "total_input_cost_usd": 0,
                "total_cached_cost_usd": 0,
                "total_output_cost_usd": 0,
                "total_cost_usd": 0,
                "avg_cost_per_call": 0,
                "avg_tokens_per_call": 0,
                "first_call": None,
                "last_call": None,
            }

        return {
            "total_calls": row[0],
            "receipts_processed": row[1],
            "pipeline_runs": row[2],
            "total_input_tokens": row[3] or 0,
            "total_cached_tokens": row[4] or 0,
            "total_output_tokens": row[5] or 0,
            "total_tokens": row[6] or 0,
            "total_input_cost_usd": round(row[7] or 0, 8),
            "total_cached_cost_usd": round(row[8] or 0, 8),
            "total_output_cost_usd": round(row[9] or 0, 8),
            "total_cost_usd": round(row[10] or 0, 8),
            "avg_cost_per_call": round((row[10] or 0) / row[0], 8),
            "avg_tokens_per_call": round((row[6] or 0) / row[0], 2),
            "first_call": row[11],
            "last_call": row[12],
        }

    def by_stage(self) -> List[Dict]:
        """Breakdown by stage (extract, verify, correct)."""
        conn = self._connect()
        cursor = conn.execute("""
            SELECT
                stage,
                COUNT(*) as calls,
                SUM(input_tokens) as input_tokens,
                SUM(cached_input_tokens) as cached_tokens,
                SUM(output_tokens) as output_tokens,
                SUM(total_tokens) as total_tokens,
                SUM(total_cost_usd) as cost_usd,
                AVG(total_cost_usd) as avg_cost_per_call
            FROM token_usage
            GROUP BY stage
            ORDER BY cost_usd DESC
        """)
        results = cursor.fetchall()
        conn.close()

        return [
            {
                "stage": r[0],
                "calls": r[1],
                "input_tokens": r[2] or 0,
                "cached_tokens": r[3] or 0,
                "output_tokens": r[4] or 0,
                "total_tokens": r[5] or 0,
                "cost_usd": round(r[6] or 0, 8),
                "avg_cost_per_call": round(r[7] or 0, 8),
            }
            for r in results
        ]

    def by_model(self) -> List[Dict]:
        """Breakdown by model."""
        conn = self._connect()
        cursor = conn.execute("""
            SELECT
                model_display,
                COUNT(*) as calls,
                SUM(total_tokens) as total_tokens,
                SUM(total_cost_usd) as cost_usd
            FROM token_usage
            GROUP BY model_display
            ORDER BY cost_usd DESC
        """)
        results = cursor.fetchall()
        conn.close()

        return [
            {
                "model": r[0],
                "calls": r[1],
                "total_tokens": r[2] or 0,
                "cost_usd": round(r[3] or 0, 8),
            }
            for r in results
        ]

    def by_receipt(self, file_path: Optional[str] = None) -> List[Dict]:
        """Per-receipt costs. If file_path is given, filter to that receipt."""
        conn = self._connect()
        if file_path:
            cursor = conn.execute("""
                SELECT
                    file_path,
                    stage,
                    input_tokens,
                    cached_input_tokens,
                    output_tokens,
                    total_tokens,
                    total_cost_usd,
                    datetime
                FROM token_usage
                WHERE file_path = ?
                ORDER BY datetime
            """, (file_path,))
        else:
            cursor = conn.execute("""
                SELECT
                    file_path,
                    COUNT(*) as calls,
                    SUM(input_tokens) as input_tokens,
                    SUM(cached_input_tokens) as cached_tokens,
                    SUM(output_tokens) as output_tokens,
                    SUM(total_tokens) as total_tokens,
                    SUM(total_cost_usd) as total_cost_usd
                FROM token_usage
                GROUP BY file_path
                ORDER BY total_cost_usd DESC
            """)
        results = cursor.fetchall()
        conn.close()

        if file_path:
            return [
                {
                    "file_path": r[0],
                    "stage": r[1],
                    "input_tokens": r[2],
                    "cached_tokens": r[3],
                    "output_tokens": r[4],
                    "total_tokens": r[5],
                    "cost_usd": round(r[6], 8),
                    "datetime": r[7],
                }
                for r in results
            ]
        else:
            return [
                {
                    "file_path": r[0],
                    "calls": r[1],
                    "input_tokens": r[2] or 0,
                    "cached_tokens": r[3] or 0,
                    "output_tokens": r[4] or 0,
                    "total_tokens": r[5] or 0,
                    "total_cost_usd": round(r[6] or 0, 8),
                }
                for r in results
            ]

    def by_date(self) -> List[Dict]:
        """Daily usage breakdown."""
        conn = self._connect()
        cursor = conn.execute("""
            SELECT
                DATE(datetime) as day,
                COUNT(*) as calls,
                SUM(total_tokens) as total_tokens,
                SUM(total_cost_usd) as cost_usd
            FROM token_usage
            GROUP BY DATE(datetime)
            ORDER BY day
        """)
        results = cursor.fetchall()
        conn.close()

        return [
            {
                "date": r[0],
                "calls": r[1],
                "total_tokens": r[2] or 0,
                "cost_usd": round(r[3] or 0, 8),
            }
            for r in results
        ]

    def recent_calls(self, limit: int = 10) -> List[Dict]:
        """Most recent LLM calls."""
        conn = self._connect()
        cursor = conn.execute("""
            SELECT
                datetime, model_display, stage, file_path,
                input_tokens, cached_input_tokens, output_tokens, total_tokens,
                total_cost_usd
            FROM token_usage
            ORDER BY datetime DESC
            LIMIT ?
        """, (limit,))
        results = cursor.fetchall()
        conn.close()

        return [
            {
                "datetime": r[0],
                "model": r[1],
                "stage": r[2],
                "file_path": r[3],
                "input_tokens": r[4],
                "cached_tokens": r[5],
                "output_tokens": r[6],
                "total_tokens": r[7],
                "cost_usd": round(r[8], 8),
            }
            for r in results
        ]

    def full_report(self) -> Dict:
        """Generate complete report as dict."""
        return {
            "generated_at": datetime.now().isoformat(),
            "summary": self.summary(),
            "by_stage": self.by_stage(),
            "by_model": self.by_model(),
            "by_date": self.by_date(),
            "by_receipt": self.by_receipt(),
            "recent_calls": self.recent_calls(limit=20),
        }

    def save_report(self, output_path: str = None):
        """Save full report to JSON file."""
        if output_path is None:
            output_path = str(Path("processed") / f"v2_cost_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        report = self.full_report()

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        print(f"Cost report saved to: {output_path}")
        return output_path

    def print_report(self):
        """Pretty-print summary report to console."""
        s = self.summary()

        print("=" * 70)
        print("TOKEN USAGE & COST REPORT")
        print("=" * 70)
        print(f"Generated: {datetime.now().isoformat()}")
        print()
        print(f"Total API calls:      {s['total_calls']}")
        print(f"Receipts processed:   {s['receipts_processed']}")
        print(f"Pipeline runs:        {s['pipeline_runs']}")
        print()
        print("Token Usage:")
        print(f"  Input tokens:       {s['total_input_tokens']:,}")
        print(f"  Cached tokens:      {s['total_cached_tokens']:,}")
        print(f"  Output tokens:      {s['total_output_tokens']:,}")
        print(f"  Total tokens:       {s['total_tokens']:,}")
        print(f"  Avg per call:       {s['avg_tokens_per_call']:,.0f}")
        print()
        print("Cost (USD):")
        print(f"  Input cost:         ${s['total_input_cost_usd']:.6f}")
        print(f"  Cached cost:        ${s['total_cached_cost_usd']:.6f}")
        print(f"  Output cost:        ${s['total_output_cost_usd']:.6f}")
        print(f"  TOTAL COST:         ${s['total_cost_usd']:.6f}")
        print(f"  Avg per call:       ${s['avg_cost_per_call']:.6f}")
        print()

        if s['first_call']:
            print(f"Time range: {s['first_call']} to {s['last_call']}")
            print()

        print("By Stage:")
        print("-" * 70)
        for stage in self.by_stage():
            print(f"  {stage['stage']:10} | {stage['calls']:3} calls | "
                  f"{stage['total_tokens']:>10,} tokens | ${stage['cost_usd']:.6f}")
        print()

        print("By Model:")
        print("-" * 70)
        for model in self.by_model():
            print(f"  {model['model']:20} | {model['calls']:3} calls | "
                  f"{model['total_tokens']:>10,} tokens | ${model['cost_usd']:.6f}")
        print()

        print("Recent Calls:")
        print("-" * 70)
        for call in self.recent_calls(limit=5):
            file_name = Path(call['file_path']).name[:40]
            print(f"  {call['datetime'][:19]} | {call['stage']:8} | "
                  f"{file_name} | {call['total_tokens']:>6,} tok | ${call['cost_usd']:.6f}")
        print("=" * 70)
