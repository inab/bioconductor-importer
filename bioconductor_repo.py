from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import List

import requests

logger = logging.getLogger(__name__)


def download_and_extract_package_names(url: str) -> List[str]:
    """
    # WARNING:
    # Package names are currently extracted by scraping the root response of
    # https://git.bioconductor.org. This is brittle: the response format may change
    # without notice because it is not a documented stable API. If that happens,
    # this function may return incomplete results or no packages at all.
    # TODO: replace this with a stable Bioconductor package index or official API.

    Download the package listing and extract package names.
    """
    package_names = []

    try:
        logger.info("Requesting package list from %s", url)

        with requests.get(
            url,
            stream=True,
            timeout=(10, 60),
            headers={"User-Agent": "bioconductor-importer/1.0"},
        ) as response:
            logger.info(
                "Package list response: status=%s final_url=%s content_type=%s content_length=%s",
                response.status_code,
                response.url,
                response.headers.get("Content-Type"),
                response.headers.get("Content-Length"),
            )
            response.raise_for_status()

            for raw_line in response.iter_lines(decode_unicode=True):
                if not raw_line:
                    continue

                line = raw_line.strip()
                if line.startswith("R  \tpackages/"):
                    package_name = line.split("/")[-1].strip()
                    if package_name:
                        package_names.append(package_name)

        logger.info("Extracted %d package names", len(package_names))
        return package_names

    except requests.Timeout:
        logger.exception("Timeout while fetching package list from %s", url)
        return []
    except requests.RequestException:
        logger.exception("Error while fetching package list from %s", url)
        return []


def clone_repo_shallow(repo_url: str, package_name: str, timeout: int = 180) -> None:
    """
    Shallow clone a package repo and sparse-checkout only DESCRIPTION and inst/CITATION.
    """
    clone_path = Path(package_name)

    if clone_path.exists():
        logger.warning("Directory already exists for package %s, removing it first", package_name)
        remove_directory(str(clone_path))

    package_repo = f"{repo_url}/packages/{package_name}"
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"

    commands = [
        ["git", "clone", "--depth", "1", "--no-checkout", package_repo, str(clone_path)],
        ["git", "-C", str(clone_path), "sparse-checkout", "init", "--cone"],
        ["git", "-C", str(clone_path), "sparse-checkout", "set", "DESCRIPTION", "inst/CITATION"],
        ["git", "-C", str(clone_path), "checkout"],
    ]

    for cmd in commands:
        logger.info("Running command for %s: %s", package_name, " ".join(cmd))
        result = subprocess.run(
            cmd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

        if result.stdout:
            logger.debug("stdout [%s]: %s", package_name, result.stdout.strip())
        if result.stderr:
            logger.debug("stderr [%s]: %s", package_name, result.stderr.strip())

        if result.returncode != 0:
            raise RuntimeError(
                f"Git command failed for {package_name}: {' '.join(cmd)}\n"
                f"Return code: {result.returncode}\n"
                f"stderr: {result.stderr.strip()}"
            )


def clone_repo(repo_url: str, package_name: str, timeout: int = 300) -> None:
    """
    Full clone with timeout.
    """
    clone_path = Path(package_name)

    if clone_path.exists():
        logger.warning("Directory already exists for package %s, removing it first", package_name)
        remove_directory(str(clone_path))

    package_repo = f"{repo_url}/packages/{package_name}"
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"

    cmd = ["git", "clone", package_repo, str(clone_path)]
    logger.info("Running command for %s: %s", package_name, " ".join(cmd))

    result = subprocess.run(
        cmd,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )

    if result.stdout:
        logger.debug("stdout [%s]: %s", package_name, result.stdout.strip())
    if result.stderr:
        logger.debug("stderr [%s]: %s", package_name, result.stderr.strip())

    if result.returncode != 0:
        raise RuntimeError(
            f"Git clone failed for {package_name}\n"
            f"Return code: {result.returncode}\n"
            f"stderr: {result.stderr.strip()}"
        )


def directory_contents(directory_path: str):
    path = Path(directory_path)
    if path.is_dir():
        return [p.name for p in path.iterdir()]

    logger.warning("The path %s is not a directory or does not exist", directory_path)
    return None


def remove_directory(directory_path: str) -> None:
    path = Path(directory_path)
    if path.exists():
        shutil.rmtree(path)
        logger.info("Removed directory '%s'", directory_path)
    else:
        logger.debug("Directory '%s' does not exist", directory_path)