from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv
from rpy2.robjects.packages import importr

from bioconductor_repo import (
    clone_repo_shallow,
    download_and_extract_package_names,
    remove_directory,
)
from utils import push_entry, connect_db, add_metadata_to_entry

logger = logging.getLogger(__name__)


# -----------------------------
# Author parsing helpers
# -----------------------------

def parse_authors_r(authors_str: str) -> List[Dict]:
    """
    Parse Authors@R (parsed) text into a list of dicts.

    Expected format roughly like:
    * Author Name <email> [role1, role2] (<ORCID>)
    """
    pattern = re.compile(
        r"""
        \*\s*                    # starting asterisk
        ([^<\[\(]+)              # name
        (?:\s*<([^>]+)>)?        # optional email
        \s*\[([^\]]+)\]          # roles
        (?:\s*\(<([^>]+)>\))?    # optional ORCID
        """,
        re.VERBOSE,
    )

    authors = []
    for match in pattern.finditer(authors_str):
        name, email, roles, orcid = match.groups()
        author_info = {
            "name": name.strip(),
            "roles": [role.strip() for role in roles.split(",")],
        }
        if email:
            author_info["email"] = email
        if orcid:
            author_info["orcid"] = orcid
        authors.append(author_info)

    return authors


def parse_authors_complex(authors_str: str) -> List[Dict]:
    normalized_str = re.sub(r"\sand\s", ", ", authors_str)
    normalized_str = normalized_str.replace(". ", ", ")
    authors_list = re.split(r",\s*", normalized_str)
    parsed_authors = []

    for author in authors_list:
        if not author.strip():
            continue

        token_count = len(author.split())
        try:
            if "@" in author:
                if token_count == 1:
                    parsed_authors.append({"email": author.strip()})
                else:
                    if "<" in author:
                        items = author.split("<")
                        if len(items) > 2:
                            if "by" in author:
                                author = author.split("by", 1)[1]
                            elif "from" in author:
                                author = author.split("from", 1)[1]

                        name, email = author.split("<", 1)
                        parsed_authors.append(
                            {"name": name.strip(), "email": email.rstrip(">").strip()}
                        )
                    else:
                        name_parts = []
                        email = ""
                        for item in author.split():
                            if "@" in item:
                                email = item
                            else:
                                name_parts.append(item)
                        parsed_authors.append(
                            {"name": " ".join(name_parts).strip(), "email": email}
                        )
            else:
                parsed_authors.append({"name": author.strip()})

        except Exception as e:
            parsed_authors.append({"other": author})
            logger.warning("Could not parse author '%s': %s", author, e)

    return parsed_authors


def parse_authors_simple(authors_str: str) -> List[Dict]:
    normalized_str = re.sub(r"\sand\s", ", ", authors_str)
    author_entries = re.split(r"\s*[,;]\s*", normalized_str)

    authors = []
    for entry in author_entries:
        if not entry.strip():
            continue

        match = re.match(r"(.+?)(?:\s*<([^>]+)>)?$", entry)
        if match:
            name, email = match.groups()
            author_info = {"name": name.strip()}
            if email:
                author_info["email"] = email
            authors.append(author_info)
        else:
            authors.append({"name": entry.strip()})

    return authors


# -----------------------------
# Small parsing utilities
# -----------------------------

def parse_list_comma(s: str) -> List[str]:
    return [item.strip() for item in s.split(",") if item.strip()]


def parse_list_space(s: str) -> List[str]:
    return [item.strip() for item in s.split() if item.strip()]


def remove_ansi_color_codes(s: str) -> str:
    ansi_escape = re.compile(r"\x1B[@-_][0-?]*[ -/]*[@-~]")
    return ansi_escape.sub("", s)


def clean_text(text: Optional[str]) -> Optional[str]:
    if not text:
        return text

    text = text.strip('"')
    text = text.lstrip("{").rstrip("}")
    text = text.strip(",")
    text = text.strip('"')
    text = re.sub(r"^\{\s*,?\s*\}$", "", text)
    return text.strip()


# -----------------------------
# File access helpers
# -----------------------------

def get_citation_path(package_dir: str) -> Optional[List[str]]:
    path = Path(package_dir) / "inst" / "CITATION"
    if path.exists():
        return path.read_text(encoding="utf-8").splitlines()
    return None


def init_r_dependencies() -> None:
    """
    Initialize R packages once at startup.
    """
    logger.info("Initializing R dependencies")
    importr("utils")
    importr("desc")
    logger.info("R dependencies initialized")


def get_meta(package_dir: str) -> Optional[str]:
    """
    Read DESCRIPTION metadata through the R 'desc' package.
    """
    try:
        desc = importr("desc")
        desc_obj = desc.desc(package_dir)
        string = desc_obj.rx2("print")()
        return str(string)
    except Exception as e:
        logger.warning("Could not get metadata for '%s': %s", package_dir, e)
        return None


def get_files(repo_url: str, package_name: str) -> Tuple[Optional[str], Optional[List[str]]]:
    """
    Clone a package shallowly, read DESCRIPTION and CITATION, and always clean up.
    """
    package_dir = Path(package_name)

    try:
        logger.info("Cloning repo for package %s", package_name)
        clone_repo_shallow(repo_url, package_name)
        logger.info("Clone completed for package %s", package_name)

        logger.info("Reading DESCRIPTION for package %s", package_name)
        meta = get_meta(str(package_dir))
        logger.info("Finished DESCRIPTION for package %s", package_name)

        logger.info("Reading CITATION for package %s", package_name)
        citation_lines = get_citation_path(str(package_dir))
        logger.info("Finished CITATION for package %s", package_name)

        return meta, citation_lines

    except Exception:
        logger.exception("Could not get files for package %s", package_name)
        return None, None

    finally:
        try:
            if package_dir.exists():
                logger.info("Removing local directory for package %s", package_name)
                remove_directory(str(package_dir))
        except Exception:
            logger.exception("Failed to remove local directory for package %s", package_name)


# -----------------------------
# Metadata parsing
# -----------------------------

def build_dictionary(metadata: str) -> Dict:
    clean_metadata = remove_ansi_color_codes(metadata)
    lines = clean_metadata.strip().split("\n")

    parsed_data = {}
    current_key = None

    for line in lines:
        if ":" in line and not line.startswith("    "):
            key, value = line.split(":", 1)
            current_key = key.strip()
            parsed_data[current_key] = value.strip()
        elif current_key:
            parsed_data[current_key] += " " + line.strip()

    return parsed_data


def parse_citation_file(citation_lines: List[str]) -> List[Dict]:
    try:
        article = False
        publications = []
        new_pub = {}
        last_key = None

        for line in citation_lines:
            if "entry" in line:
                if new_pub:
                    publications.append(new_pub)
                    new_pub = {}
                    last_key = None

                article = 'entry="article"' in line
                continue

            if not article:
                continue

            if "=" in line:
                if "title" in line:
                    new_pub["title"] = clean_text(line.split("title = ", 1)[1].strip())
                    last_key = "title"
                elif "journal" in line:
                    new_pub["journal"] = clean_text(line.split("journal = ", 1)[1].strip())
                    last_key = "journal"
                elif "doi" in line:
                    new_pub["doi"] = clean_text(line.split("doi = ", 1)[1].strip())
                    last_key = "doi"
                elif "year" in line:
                    new_pub["year"] = clean_text(line.split("year = ", 1)[1].strip())
                    last_key = "year"
                elif "url" in line:
                    new_pub["url"] = clean_text(line.split("url = ", 1)[1].strip())
                    last_key = "url"
            elif last_key:
                new_pub[last_key] += clean_text(line.strip()) or ""

        if new_pub:
            publications.append(new_pub)

        return publications

    except Exception as e:
        logger.error("Error parsing CITATION content: %s", e)
        return []


def parse_description(metadata: str) -> Dict:
    metadata_dict = build_dictionary(metadata)

    if "Authors@R (parsed)" in metadata_dict:
        metadata_dict["Authors@R (parsed)"] = parse_authors_r(
            metadata_dict["Authors@R (parsed)"]
        )

    if "Author" in metadata_dict:
        metadata_dict["Author"] = parse_authors_complex(metadata_dict["Author"])

    if "Maintainer" in metadata_dict:
        metadata_dict["Maintainer"] = parse_authors_simple(metadata_dict["Maintainer"])

    list_comma_attributes = [
        "Depends",
        "Imports",
        "LinkingTo",
        "Suggests",
        "Enhances",
        "License",
        "biocViews",
    ]
    for attribute in list_comma_attributes:
        if attribute in metadata_dict:
            metadata_dict[attribute] = parse_list_comma(metadata_dict[attribute])

    list_space_attributes = ["Collate"]
    for attribute in list_space_attributes:
        if attribute in metadata_dict:
            metadata_dict[attribute] = parse_list_space(metadata_dict[attribute])

    return metadata_dict


def parse_metadata(raw_metadata: str, citation_lines: Optional[List[str]]) -> Dict:
    parsed_metadata = parse_description(raw_metadata)

    if citation_lines:
        parsed_metadata["publication"] = parse_citation_file(citation_lines)
        logger.info("Parsed %d publications", len(parsed_metadata["publication"]))

    return parsed_metadata


# -----------------------------
# Import workflow
# -----------------------------

def import_data() -> int:
    repo_url = "https://git.bioconductor.org"

    logger.info("state_importation - 1")

    success_count = 0
    skipped_count = 0
    failed_count = 0

    try:
        logger.info("Connecting to database")
        alambique = connect_db("alambique")

        init_r_dependencies()

        logger.info("Fetching package list from %s", repo_url)
        package_names = download_and_extract_package_names(repo_url)

        if not package_names:
            logger.warning("No package names were retrieved from %s", repo_url)
            logger.info("state_importation - 2")
            return 1

        logger.info("Retrieved %d package names", len(package_names))

        for i, package_name in enumerate(package_names, start=1):
            logger.info("Processing package %d/%d: %s", i, len(package_names), package_name)

            try:
                description, citation_lines = get_files(repo_url, package_name)

                if not description:
                    logger.warning("Skipping %s: empty description", package_name)
                    skipped_count += 1
                    continue

                parsed_metadata = parse_metadata(description, citation_lines)

                if not parsed_metadata:
                    logger.warning("Skipping %s: metadata could not be parsed", package_name)
                    skipped_count += 1
                    continue

                version = parsed_metadata.get("Version")
                if not version:
                    logger.warning("Skipping %s: missing Version field", package_name)
                    skipped_count += 1
                    continue

                identifier = f"bioconductor/{package_name}/lib/{version}"

                tool = {
                    "data": parsed_metadata,
                    "_id": identifier,
                    "@data_source": "bioconductor",
                    "@source_url": f"{repo_url}/packages/{package_name}",
                }

                logger.info("Adding provenance metadata for %s", package_name)
                document_w_metadata = add_metadata_to_entry(identifier, tool, alambique)

                logger.info("Pushing entry for %s", package_name)
                push_entry(document_w_metadata, alambique)

                success_count += 1

            except Exception:
                failed_count += 1
                logger.exception("Failed while processing package %s", package_name)
                continue

    except Exception:
        logger.exception("Fatal exception during import")
        logger.info("state_importation - 2")
        return 1

    logger.info(
        "Import finished. Success: %d, skipped: %d, failed: %d",
        success_count,
        skipped_count,
        failed_count,
    )
    logger.info("state_importation - 0")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Importer of Bioconductor packages metadata to the database."
    )
    parser.add_argument(
        "--loglevel",
        "-l",
        help="Set the logging level",
        default="INFO",
    )

    args = parser.parse_args()
    numeric_level = getattr(logging, args.loglevel.upper(), logging.INFO)

    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s - %(levelname)s - %(message)s",
        stream=sys.stdout,
    )

    sys.exit(import_data())


if __name__ == "__main__":
    load_dotenv()
    main()