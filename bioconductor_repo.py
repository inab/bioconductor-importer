from git import Repo
import os
import requests
import shutil
def download_and_extract_package_names(url):
    try:
        # Send a GET request to the URL
        response = requests.get(url)
        # Raise an exception if the request was unsuccessful
        response.raise_for_status()

        # Extract lines from the response content
        lines = response.text.split('\n')

        # List to hold extracted package names
        package_names = []

        # Iterate through each line to find package names
        for line in lines:
            # Check if the line contains a package name
            if line.strip().startswith('R  \tpackages/'):
                # Extract the package name and add it to the list
                package_name = line.strip().split('/')[-1]
                package_names.append(package_name)

        return package_names
    except requests.RequestException as e:
        print(f"An error occurred while fetching the package list: {e}")
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






