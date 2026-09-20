"""Offline packaged-EXE smoke test with an isolated DB and a headless Edge UI."""

import argparse
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.request
from contextlib import closing
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", type=Path)
    parser.add_argument("--legacy", action="store_true")
    parser.add_argument("--expected-version", default=None)
    args = parser.parse_args()
    expected_version = args.expected_version or tomllib.loads(
        (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    )["project"]["version"]
    executable = args.executable.resolve(strict=True)
    with tempfile.TemporaryDirectory(prefix="bili-package-smoke-") as temporary:
        work = Path(temporary)
        if args.legacy:
            (work / "data").mkdir()
            with closing(sqlite3.connect(work / "data/assistant.sqlite3")) as old:
                old.executescript("""
                    CREATE TABLE activity_origins (
                        source_article_id INTEGER NOT NULL, activity_id INTEGER NOT NULL,
                        source_position INTEGER NOT NULL, discovered_in_run_id INTEGER NOT NULL,
                        PRIMARY KEY (source_article_id, activity_id));
                    INSERT INTO activity_origins VALUES (10, 20, 3, 30);
                    CREATE TABLE discovery_selections (
                        discovery_run_id INTEGER NOT NULL, source_article_id INTEGER NOT NULL,
                        readlist_id INTEGER NOT NULL, family VARCHAR NOT NULL,
                        selected_rank INTEGER NOT NULL, source_position INTEGER NOT NULL,
                        like_state_snapshot VARCHAR NOT NULL, decision VARCHAR NOT NULL,
                        decision_reason VARCHAR NOT NULL,
                        PRIMARY KEY (discovery_run_id, source_article_id));
                    INSERT INTO discovery_selections VALUES
                        (30, 10, 40, 'official', 1, 3, 'unliked', 'process', 'legacy');
                """)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        env = {key: value for key, value in os.environ.items() if not key.startswith("BILI_")}
        env.update(
            BILI_DATA_DIR=str(work / "data"),
            BILI_HOST="127.0.0.1",
            BILI_PORT=str(port),
            BILI_OFFICIAL_AUTOMATION_ENABLED="false",
            BILI_UNOFFICIAL_AUTOMATION_ENABLED="false",
            BILI_SOURCE_LIKE_AUTOMATION_ENABLED="false",
            BROWSER=f'"{sys.executable}" -c "pass" %s',
        )
        log_path = work / "server.log"
        with log_path.open("w", encoding="utf-8") as output:
            process = subprocess.Popen(
                [str(executable)],
                cwd=work,
                env=env,
                stdout=output,
                stderr=output,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            try:
                base = f"http://127.0.0.1:{port}"
                health = None
                for _ in range(150):
                    if process.poll() is not None:
                        raise RuntimeError(log_path.read_text(encoding="utf-8"))
                    try:
                        with urllib.request.urlopen(base + "/api/health", timeout=1) as response:
                            health = json.load(response)
                        break
                    except OSError:
                        time.sleep(0.2)
                assert health and health["version"] == expected_version, health
                assert health["browserReady"] is False
                print("HEALTH", health, flush=True)
                with sync_playwright() as playwright:
                    browser = playwright.chromium.launch(channel="msedge", headless=True)
                    page = browser.new_page()
                    # Only the local console is permitted; never contact Bilibili/DeepSeek.
                    page.route(
                        "**/*",
                        lambda route: (
                            route.continue_()
                            if route.request.url.startswith(base + "/")
                            else route.abort()
                        ),
                    )
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.goto(base, wait_until="networkidle")
                    expect(
                        page.get_by_role("heading", name="概览与准备", exact=True)
                    ).to_be_visible()
                    expect(page.locator("[data-source-profile] option")).to_have_count(3)
                    page.locator('[name="deepseekApiKey"]').fill("unsaved-offline-draft")
                    page.locator('[data-view="discovery"]').click()
                    expect(page.locator('a[href*="space.bilibili.com"]')).to_have_count(2)
                    page.reload(wait_until="networkidle")
                    expect(page.get_by_role("heading", name="来源发现", exact=True)).to_be_visible()
                    runtime = page.request.get(base + "/api/runtime").json()
                    assert runtime["desktopClients"] >= 1, runtime
                    assert not errors, errors
                    page.close()
                    browser.close()
                process.wait(timeout=15)
                assert process.returncode == 0
                print("UI_RESOURCES_WS_REFRESH_AND_SHUTDOWN_PASS", flush=True)
                for relative in [
                    "web_static/dist/index.html",
                    "backend/activity_engine/interface_contracts.yaml",
                    "backend/source_adapters/lottery_toolman/interface_contracts.yaml",
                ]:
                    assert (executable.parent / "_internal" / relative).is_file(), relative
                print("PACKAGED_DATA_PASS", flush=True)
                if args.legacy:
                    backups = list((work / "data").glob("*.bak"))
                    assert len(backups) == 1
                    with closing(sqlite3.connect(backups[0])) as old:
                        assert old.execute("SELECT * FROM activity_origins").fetchall() == [
                            (10, 20, 3, 30)
                        ]
                    with closing(sqlite3.connect(work / "data/assistant.sqlite3")) as upgraded:
                        columns = upgraded.execute("PRAGMA table_info(activity_origins)").fetchall()
                        assert {r[1] for r in columns if r[5]} == {
                            "source_article_id",
                            "activity_id",
                            "discovered_in_run_id",
                        }
                        assert upgraded.execute(
                            "SELECT count(*) FROM activity_origins"
                        ).fetchone() == (1,)
                    print("PACKAGED_LEGACY_BACKUP_AND_MIGRATION_PASS", flush=True)
            except BaseException:
                print(log_path.read_text(encoding="utf-8", errors="replace"), flush=True)
                raise
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=10)


if __name__ == "__main__":
    main()
