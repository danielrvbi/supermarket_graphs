"""
Tools to inspect LangGraph checkpoints for debugging and auditing.
"""

import json
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime

from langgraph.checkpoint.sqlite import SqliteSaver

from v2.common.settings import settings


def get_checkpointer(store: str) -> SqliteSaver:
    """Get a checkpointer for the specified store ('ah' or 'jumbo')."""
    import sqlite3
    db_path = Path(settings.CHECKPOINTS_DIR) / f"{store}_pipeline.db"
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    return checkpointer


def list_checkpoints(
    thread_id: str,
    store: str = "ah",
) -> List[Dict[str, Any]]:
    """
    List all checkpoints for a receipt.

    Args:
        thread_id: The thread ID (e.g., "ah_AH_kassabon_YYYY-MM-DD_HHMM_STORE")
        store: "ah" or "jumbo"

    Returns:
        List of checkpoint info dicts, oldest first
    """
    checkpointer = get_checkpointer(store)
    config = {"configurable": {"thread_id": thread_id}}
    # checkpointer.list() yields newest first
    history = reversed(list(checkpointer.list(config)))

    checkpoints = []
    for cp in history:
        state = cp.checkpoint.get("channel_values", {})
        # Node that produced this checkpoint = last entry appended to processing_steps
        steps = state.get("processing_steps") or []
        # Pending nodes are recorded as "branch:to:<node>" channels
        next_nodes = [
            ch.removeprefix("branch:to:")
            for ch in cp.checkpoint.get("updated_channels") or []
            if ch.startswith("branch:to:")
        ]
        checkpoints.append({
            "checkpoint_id": cp.config["configurable"]["checkpoint_id"],
            "thread_id": cp.config["configurable"]["thread_id"],
            "node_name": steps[-1] if steps else cp.metadata.get("source", "unknown"),
            "created_at": cp.checkpoint.get("ts", "unknown"),
            "next_nodes": next_nodes,
            "items_count": len(state.get("merged_items", [])),
            "confidence": state.get("overall_confidence", 0.0),
            "status": state.get("final_status", "in_progress"),
            "errors": state.get("errors", []),
        })

    return checkpoints


def get_state_at(
    thread_id: str,
    checkpoint_id: str,
    store: str = "ah",
) -> Optional[Dict[str, Any]]:
    """
    Get the full state at a specific checkpoint.

    Args:
        thread_id: The thread ID
        checkpoint_id: The checkpoint ID
        store: "ah" or "jumbo"

    Returns:
        State dict at that checkpoint, or None
    """
    checkpointer = get_checkpointer(store)
    config = {
        "configurable": {
            "thread_id": thread_id,
            "checkpoint_id": checkpoint_id,
        }
    }
    cp = checkpointer.get(config)
    if cp:
        return cp.get("channel_values", {})
    return None


def inspect_receipt(thread_id: str, store: str = "ah"):
    """
    Pretty-print the full checkpoint history for a receipt.

    Shows the pipeline flow and where it might have failed.
    """
    print("=" * 70)
    print(f"Checkpoint Inspection: {thread_id}")
    print(f"Store: {store}")
    print("=" * 70)

    checkpoints = list_checkpoints(thread_id, store)

    if not checkpoints:
        print("No checkpoints found for this receipt.")
        return

    print(f"\nFound {len(checkpoints)} checkpoint(s):\n")

    for i, cp in enumerate(checkpoints, 1):
        status_icon = "✓" if not cp["errors"] else "✗"
        print(f"{i}. [{status_icon}] Node: {cp['node_name']}")
        print(f"   Checkpoint ID: {cp['checkpoint_id'][:16]}...")
        print(f"   Created: {cp['created_at']}")
        print(f"   Items: {cp['items_count']}, Confidence: {cp['confidence']:.2f}")
        print(f"   Status: {cp['status']}")
        if cp["errors"]:
            print(f"   Errors: {cp['errors']}")
        if cp["next_nodes"]:
            print(f"   Next: {', '.join(cp['next_nodes'])}")
        print()

    # Identify failure point
    last = checkpoints[-1]
    if last["errors"]:
        print("=" * 70)
        print(f"⚠️  PIPELINE ISSUE DETECTED")
        print(f"   Last successful node: {checkpoints[-2]['node_name'] if len(checkpoints) > 1 else 'N/A'}")
        print(f"   Failed at: {last['node_name']}")
        print(f"   Errors: {last['errors']}")
        print("=" * 70)


def compare_stages(
    thread_id: str,
    checkpoint_id_1: str,
    checkpoint_id_2: str,
    store: str = "ah",
):
    """
    Compare state between two checkpoints to see what changed.

    Useful for debugging: see exactly what a node changed.
    """
    state_1 = get_state_at(thread_id, checkpoint_id_1, store)
    state_2 = get_state_at(thread_id, checkpoint_id_2, store)

    if not state_1 or not state_2:
        print("Could not load one or both checkpoints.")
        return

    print("=" * 70)
    print(f"Stage Comparison: {thread_id}")
    print(f"From: {checkpoint_id_1[:16]}...")
    print(f"To:   {checkpoint_id_2[:16]}...")
    print("=" * 70)

    # Compare items
    items_1 = state_1.get("merged_items", [])
    items_2 = state_2.get("merged_items", [])

    print(f"\nItems: {len(items_1)} → {len(items_2)}")

    # Find added/removed/changed items
    names_1 = {i.get("item_name", "").upper() for i in items_1}
    names_2 = {i.get("item_name", "").upper() for i in items_2}

    added = names_2 - names_1
    removed = names_1 - names_2

    if added:
        print(f"  Added: {added}")
    if removed:
        print(f"  Removed: {removed}")

    # Compare other fields
    for field in ["validation_passed", "arithmetic_ok", "reconciliation_ok",
                  "verification_confidence", "overall_confidence", "final_status"]:
        val_1 = state_1.get(field)
        val_2 = state_2.get(field)
        if val_1 != val_2:
            print(f"\n{field}: {val_1} → {val_2}")

    # Compare errors
    errors_1 = state_1.get("errors", [])
    errors_2 = state_2.get("errors", [])
    if errors_1 != errors_2:
        print(f"\nErrors changed:")
        print(f"  Before: {errors_1}")
        print(f"  After:  {errors_2}")

    print("\n" + "=" * 70)


def list_all_threads(store: str = "ah") -> List[str]:
    """List all thread IDs that have checkpoints."""
    db_path = Path(settings.CHECKPOINTS_DIR) / f"{store}_pipeline.db"
    if not db_path.exists():
        return []

    import sqlite3
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT thread_id FROM checkpoints")
    threads = [row[0] for row in cursor.fetchall()]
    conn.close()

    return threads
