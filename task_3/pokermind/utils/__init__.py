"""Notebook helpers: environment setup and compact result tables (`report`)."""

import logging
from pathlib import Path

from dotenv import load_dotenv


def prepare_notebook(root: Path) -> tuple[Path, Path, Path]:
    """Load credentials and route notebook logs to a file; return the result dirs."""
    load_dotenv(root / ".env")
    results = root / "task_3" / "results"
    notebook_results = results / "notebook_observation"
    log_path = root / "task_3" / "logs" / "pokermind_notebook.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("task_3")
    if not any(
        isinstance(h, logging.FileHandler)
        and Path(h.baseFilename) == log_path.resolve()
        for h in logger.handlers
    ):
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logging.getLogger("strands").setLevel(logging.CRITICAL)
    logging.getLogger("openai").setLevel(logging.CRITICAL)
    return results, notebook_results, log_path
