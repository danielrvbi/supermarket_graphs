"""
Tools to resume failed pipelines from checkpoints.
"""

from pathlib import Path
from typing import Optional

from langgraph.checkpoint.sqlite import SqliteSaver

from v2.config.settings import settings


def resume_failed_receipt(
    pipeline,
    thread_id: str,
    store: str = "ah",
) -> Optional[dict]:
    """
    Resume a failed pipeline from the last successful checkpoint.

    Args:
        pipeline: Compiled LangGraph pipeline
        thread_id: The thread ID to resume
        store: "ah" or "jumbo"

    Returns:
        Final state, or None if no checkpoint found
    """
    db_path = Path(settings.CHECKPOINTS_DIR) / f"{store}_pipeline.db"

    import sqlite3
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    checkpointer = SqliteSaver(conn)

    config = {"configurable": {"thread_id": thread_id}}

    # Get the latest checkpoint
    checkpoint = checkpointer.get(config)

    if not checkpoint:
        print(f"No checkpoint found for {thread_id}")
        return None

    print(f"Resuming {thread_id} from checkpoint {checkpoint.checkpoint_id[:16]}...")
    print(f"  Last node: {checkpoint.metadata.get('source', 'unknown')}")
    print(f"  Items: {len(checkpoint.checkpoint.get('merged_items', []))}")

    # Resume from this state
    result = pipeline.invoke(checkpoint.checkpoint, config=config)
    return result


def resume_from_node(
    pipeline,
    thread_id: str,
    node_name: str,
    store: str = "ah",
) -> Optional[dict]:
    """
    Resume a pipeline from a specific node (go back to that stage).

    Useful for re-running verification with different settings.

    Args:
        pipeline: Compiled LangGraph pipeline
        thread_id: The thread ID
        node_name: Node to resume from (e.g., "verify", "validate")
        store: "ah" or "jumbo"
    """
    db_path = Path(settings.CHECKPOINTS_DIR) / f"{store}_pipeline.db"

    import sqlite3
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    checkpointer = SqliteSaver(conn)

    config = {"configurable": {"thread_id": thread_id}}

    # Find the checkpoint before the specified node
    history = list(checkpointer.list(config))

    target_checkpoint = None
    for cp in history:
        if node_name in cp.next:
            target_checkpoint = cp
            break

    if not target_checkpoint:
        print(f"Could not find checkpoint before node '{node_name}'")
        return None

    print(f"Resuming {thread_id} from before '{node_name}'")
    print(f"  Checkpoint: {target_checkpoint.checkpoint_id[:16]}...")

    # Resume from this state
    result = pipeline.invoke(target_checkpoint.checkpoint, config=config)
    return result
