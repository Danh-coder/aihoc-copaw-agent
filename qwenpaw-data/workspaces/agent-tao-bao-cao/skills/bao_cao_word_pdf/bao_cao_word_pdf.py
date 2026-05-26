#!/usr/bin/env python3
"""Compatibility CLI wrapper for bao_cao_word_pdf skill.

This file exists because some models call this exact path directly.
It maps short Vietnamese args to the existing generate_report.py script.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    stream=sys.stderr,
    force=True,
)
logger = logging.getLogger("qwenpaw.skill.bao_cao_word_pdf.wrapper")


def _truncate(value: object, max_len: int = 1200) -> str:
    text = str(value)
    if len(text) <= max_len:
        return text
    return text[:max_len] + "...<truncated>"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate report from short params")
    parser.add_argument("--so_nguoi", type=int, required=True)
    parser.add_argument("--quoc_tich", default="")
    parser.add_argument("--gioi_tinh", choices=["male", "female", ""], default="")
    parser.add_argument("--seed", default="")
    parser.add_argument("--ten_file", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logger.info(
        "skill_wrapper_start status=started so_nguoi=%s quoc_tich=%s "
        "gioi_tinh=%s ten_file=%s",
        args.so_nguoi,
        args.quoc_tich,
        args.gioi_tinh,
        args.ten_file,
    )

    skill_root = Path(__file__).resolve().parent
    workspace_root = skill_root.parent.parent
    template_path = workspace_root / "templates" / "demo_bao_cao_template.docx"
    output_dir = workspace_root / "reports"
    script_path = skill_root / "scripts" / "generate_report.py"

    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")
    if not script_path.exists():
        raise FileNotFoundError(f"Script not found: {script_path}")

    cmd = [
        sys.executable,
        str(script_path),
        "--template",
        str(template_path),
        "--output-dir",
        str(output_dir),
        "--report-title",
        args.ten_file,
        "--report-period",
        "Auto",
        "--generated-by",
        "Agent Tao Bao Cao",
        "--summary-text",
        "Bao cao bao gom {} nguoi, quoc tich {}, gioi tinh {}".format(
            args.so_nguoi, args.quoc_tich or "ngau nhien", args.gioi_tinh or "ngau nhien"
        ),
        "--results",
        str(args.so_nguoi),
        "--nat",
        args.quoc_tich,
        "--gender",
        args.gioi_tinh,
        "--seed",
        args.seed,
    ]

    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    logger.info(
        "skill_wrapper_subprocess_finish status=%s returncode=%s stdout=%s stderr=%s",
        "success" if proc.returncode == 0 else "failed",
        proc.returncode,
        _truncate(proc.stdout.strip()),
        _truncate(proc.stderr.strip()),
    )
    if proc.returncode != 0:
        stderr_text = proc.stderr.strip()
        stdout_text = proc.stdout.strip()
        # Try to bubble up structured script error for better user-facing messaging.
        structured_error = None
        if stdout_text:
            try:
                parsed = json.loads(stdout_text)
                if isinstance(parsed, dict) and parsed.get("status") == "failed":
                    structured_error = parsed
            except json.JSONDecodeError:
                structured_error = None

        failure_result = {
            "status": "failed",
            "error": (
                structured_error.get("error")
                if isinstance(structured_error, dict)
                else (stderr_text or "Report generation failed")
            ),
            "error_type": (
                structured_error.get("error_type")
                if isinstance(structured_error, dict)
                else "SubprocessError"
            ),
            "returncode": proc.returncode,
            "hint": "Check input params and environment dependencies, then retry.",
        }
        logger.error(
            "skill_wrapper_finish status=failed returncode=%s error=%s",
            proc.returncode,
            _truncate(failure_result.get("error") or "unknown error"),
        )
        print(json.dumps(failure_result, ensure_ascii=False))
        sys.exit(1)

    stdout = proc.stdout.strip()
    if stdout:
        logger.info(
            "skill_wrapper_finish status=success has_stdout=true output=%s",
            _truncate(stdout),
        )
        print(stdout)
    else:
        logger.info(
            "skill_wrapper_finish status=success has_stdout=false output=%s",
            '{"status": "ok", "note": "no output"}',
        )
        print(json.dumps({"status": "ok", "note": "no output"}))


if __name__ == "__main__":
    main()
