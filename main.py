from rpy2.robjects.packages import importr
import re
import logging
import argparse
import sys
from dotenv import load_dotenv

from bioconductor_repo import download_and_extract_package_names, clone_repo, directory_contents, remove_directory
from utils import push_entry, connect_db, add_metadata_to_entry


def parse_authors(authors_str):
    '''
    Parse the authors string into a list of dictionaries.
    The authors string is a string with the following format:
    * Author Name <email> [role1, role2] (<ORCID>)
    email and ORCID are optional
    - authors_str: string with authors information
    '''
    # Pattern to match each part of an author's information, including optional email and ORCID
    pattern = re.compile(r'''
        \*\s*                    # Starting asterisk and optional whitespace
        ([^<\[\(]+)              # Author name, excluding <, [, and (
        (?:\s*<([^>]+)>)?        # Optional email in <>
        \s*\[([^\]]+)\]          # Roles in []
        (?:\s*\(<([^>]+)>\))?    # Optional ORCID in <>
    ''', re.VERBOSE)

    authors = []
    for match in pattern.finditer(authors_str):
        name, email, roles, orcid = match.groups()
        author_info = {
            "name": name.strip(),
            "roles": [role.strip() for role in roles.split(',')]
        }
        if email:
            author_info["email"] = email
        if orcid:
            author_info["orcid"] = orcid
        authors.append(author_info)

    return authors


def get_meta(REPO_URL: str, package_name: str):
    '''
    Gets the metadata of a package from Bioconductor
    - REPO_URL: URL of the Bioconductor repository
    - package_name: name of the package
    '''
    utils = importr('utils')
    # Clone the repo
    clone_repo(REPO_URL, package_name)
    
    # Import the desc package
    desc = importr('desc')

    # Read the DESCRIPTION file using desc
    desc_obj = desc.desc(package_name)
    string = desc_obj["print"]()

    # Remove directory
    remove_directory(package_name)

    # Return the metadata
    return str(string)

def remove_ansi_color_codes(s: str):
    '''
    Remove ANSI color codes from a string
    - s: string to remove color codes from
    '''
    # ANSI color code regex
    ansi_escape = re.compile(r'\x1B[@-_][0-?]*[ -/]*[@-~]')
    return ansi_escape.sub('', s)

def build_dictionary(metadata: str):
    '''
    Parse the DESCRIPTION metadata, which is a string into a dictionary
    - metadata: DESCRIPTION file as a string
    '''
    # Parse the metadata
    clean_metadata = remove_ansi_color_codes(metadata)

    lines = clean_metadata.strip().split('\n')
    parsed_data = {}
    current_key = None
    for line in lines:
        if ':' in line and not line.startswith('    '):  # New key-value pair
            key, value = line.split(':', 1)
            current_key = key.strip()
            parsed_data[current_key] = value.strip()
        elif current_key:  # Continuation of a value (multi-line value)
            parsed_data[current_key] += ' ' + line.strip()
    
    return parsed_data


def parse_metadata(metadata):
    '''
    Parses the DESCRIOTION string into a dictionary, and then parses the authors, 
    which require special parsing functions
    - metadata: DESCRIPTION file as a string
    '''
    # Parse the metadata
    metadata_dict = build_dictionary(metadata)
    # Parse authors
    if "Authors@R (parsed)" in metadata_dict:
        metadata_dict["Authors@R (parsed)"] = parse_authors(metadata_dict['Authors@R (parsed)'])
    
    #TODO: add parsing for simple authors. Need to find a package that has this
    
    return metadata_dict


def import_data():
    '''
    Main function to import data from Bioconductor. The steps performed are:
    0. Set up logging
    1. Connect to the database
    2. Get the list of package names
    3. For each package, get the metadata and parse it
    4. Add the metadata (provenance info) to the entry
    5. Push the entry to the database
    '''
    try:
        # 0.1 Set up logging
        parser = argparse.ArgumentParser(
            description="Importer of Bioconductor packages metadata to the database."
        )
        parser.add_argument(
            "--loglevel", "-l",
            help=("Set the logging level"),
            default="INFO",
        )

        args = parser.parse_args()
        numeric_level = getattr(logging, args.loglevel.upper())

        logging.basicConfig(level=numeric_level, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stdout)        


        logging.info("state_importation - 1")

        # 1. connect to DB/ set files
        alambique = connect_db('alambique')

        # 2. Get metrics metadata from Biocondcutor
        REPO_URL = "https://git.bioconductor.org"
        package_names = download_and_extract_package_names(REPO_URL)
        for package_name in package_names:
            p = get_meta(REPO_URL, package_name)
            parsed_metadata = parse_metadata(p)
            if parsed_metadata:
                name = package_name
                version = parsed_metadata.get('Version')
                type_ = 'lib'
                identifier = f"bioconductor/{name}/{type_}/{version}"
                tool = {
                    'data': parsed_metadata,
                    '_id' : identifier,
                    '@data_source' : 'sourceforge',
                    '@source_url' : f"{REPO_URL}/packages/{name}",
                }

                document_w_metadata = add_metadata_to_entry(identifier, tool, alambique)
                push_entry(document_w_metadata, alambique)
            
            else:
                    logging.warning(f"no soup - empty")
        
     
    except Exception as e:
        logging.exception("Exception occurred")
        logging.error(f'error - {type(e).__name__}')
        logging.info("state_importation - 2")
        exit(1)

    else:
        logging.info("state_importation - 0")


if __name__ == "__main__":
    load_dotenv()
    import_data()