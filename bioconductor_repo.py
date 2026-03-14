from git import Repo
import os
import requests
import shutil
import logging

logger = logging.getLogger(__name__)

def download_and_extract_package_names(url):
    package_names = []

    try:
        logger.info(f"Requesting package list from {url}")

        with requests.get(
            url,
            stream=True,
            timeout=(10, 60),
            headers={"User-Agent": "bioconductor-importer/1.0"}
        ) as response:
            logger.info(f"Received response: {response.status_code} from {response.url}")
            response.raise_for_status()

            content_type = response.headers.get("Content-Type", "")
            logger.info(f"Content-Type: {content_type}")

            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                if line.startswith("R  \tpackages/"):
                    package_name = line.split("/")[-1].strip()
                    package_names.append(package_name)

        logger.info(f"Extracted {len(package_names)} package names")
        return package_names

    except requests.Timeout:
        logger.exception(f"Timeout while fetching package list from {url}")
        return []
    except requests.RequestException as e:
        logger.exception(f"Error while fetching package list from {url}: {e}")
        return []


def clone_repo_shallow(repo_url, package_name):
    # Check if directory exists
    if os.path.exists(package_name):
        print('Package already cloned')
        return
    
    package_repo = f"{repo_url}/packages/{package_name}"
    clone_path = f"./{package_name}"

    # Clone the repo without checking out files
    repo = Repo.clone_from(package_repo, clone_path, no_checkout=True)
    
    # Enable sparse checkout
    git = repo.git
    git.sparse_checkout('init', '--cone')
    
    # Specify the files to include
    git.sparse_checkout('set', 'DESCRIPTION', 'inst/CITATION')
    
    # Checkout the selected files
    repo.git.checkout()
    


def clone_repo(repo_url, package_name):
    # check if directory exists:
    if os.path.exists(package_name):
      print('Package alerady cloned')
      return
    else:
      package_repo = f"{repo_url}/packages/{package_name}"
      clone_path = f"./{package_name}"
      Repo.clone_from(package_repo, clone_path)

def directory_contents(directory_path):
    # Check if the specified path is indeed a directory
    if os.path.isdir(directory_path):
        # List all files and subdirectories in the directory
        contents = os.listdir(directory_path)
        return contents

    else:
        print(f"The path {directory_path} is not a directory or does not exist.")
        return None

def remove_directory(directory_path):
    # Check if the directory exists
    if os.path.exists(directory_path):
        # Remove the directory and all its contents
        shutil.rmtree(directory_path)
        print(f"The directory '{directory_path}' has been removed successfully.")
    else:
        print(f"The directory '{directory_path}' does not exist.")






