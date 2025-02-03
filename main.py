from rpy2.robjects.packages import importr
import rpy2.robjects as ro
import re
import logging
import argparse
import sys
import json
import os
from typing import Dict, List

from dotenv import load_dotenv

from bioconductor_repo import download_and_extract_package_names, clone_repo, directory_contents, remove_directory, clone_repo_shallow
from utils import push_entry, connect_db, add_metadata_to_entry


def parse_authors_r(authors_str):
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


def parse_authors_complex(authors_str):

    # Now process individual authors and emails
    # Normalize separators by replacing "and" with a comma for consistency
    # Assuming "and" is not part of any names or email addresses
    normalized_str = re.sub(r'\sand\s', ', ', authors_str)
    normalized_str = normalized_str.replace('. ', ', ')
    authors_list = re.split(r',\s*', normalized_str)
    parsed_authors = []

    for author in authors_list:
        #count terms 
        l = len(author.split(' '))
        try:
            # if there is an email
            if '@' in author:
                # only an email, no name
                if l==1:
                    # Directly parse the author with an email
                    parsed_authors.append({"email": author})
                # name and email
                else:
                    if '<' in author:
                        items = author.split('<')
                        # sometimes there are more than 2 items, usually a URL and email
                        if items and len(items) > 2:
                            if 'by' in author:
                                author = author.split('by')[1]
                                name, email = author.split('<')
                                parsed_authors.append({"name": name.strip(), "email": email[:-1]})
                            elif 'from' in author:
                                author = author.split('from')[1]
                                name, email = author.split('<')
                                parsed_authors.append({"name": name.strip(), "email": email[:-1]})
                        
                        else:
                            name, email = author.split('<')
                            parsed_authors.append({"name": name.strip(), "email": email[:-1]})
                    # email not in <>
                    else:
                        name = ''
                        email = ''
                        for item in author.split(' '):
                            if '@' in item:
                                email = item
                            else:
                                name += item + ' '
                        parsed_authors.append({"name": name.strip(), "email": email})
            else:
                # For names without an explicit email, use the domain
                parsed_authors.append({"name": author})
        except Exception as e:
            parsed_authors.append({"other": author})
            logging.warning(f"error - {author} - Could not parse author - {e}")


    return parsed_authors


def parse_authors_simple(authors_str):
    # Normalize separators by replacing "and" with a comma for consistency
    # Assuming "and" is not part of any names or email addresses
    normalized_str = re.sub(r'\sand\s', ', ', authors_str)

    # Split authors by comma or semicolon, accounting for potential spaces around separators
    author_entries = re.split(r'\s*[,;]\s*', normalized_str)

    authors = []
    for entry in author_entries:
        # Match the name and optional email pattern
        match = re.match(r'(.+?)(?:\s*<([^>]+)>)?$', entry)
        if match:
            name, email = match.groups()
            author_info = {"name": name.strip()}
            if email:
                author_info["email"] = email
            authors.append(author_info)
        else:
            # Handle the case where the entry does not match the expected pattern
            authors.append({"name": entry.strip()})

    return authors

def parse_list_comma(s: str):
    '''
    Parse a list of items separated by commas from a string
    '''
    return [item.strip() for item in s.split(',')]

def parse_list_space(s: str):
    '''
    Parse a list of items separated by spaces from a string
    '''
    return [item.strip() for item in s.split()]

def get_citation_path(package_name: str):
    '''
    Get the path to the CITATION file of a package
    - package_name: name of the package
    '''
    path = f"./{package_name}/inst/CITATION"
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as file:
            lines = file.readlines()
        return lines
    return None


def get_files(REPO_URL: str, package_name: str):
    try:
        utils = importr('utils')
        # Clone the repo
        clone_repo_shallow(REPO_URL, package_name)

        meta = get_meta(package_name)

        citation_lines = get_citation_path(package_name)

        # Remove directory
        remove_directory(package_name)
    except Exception as e:
        logging.warning(f"error - {package_name} - Could not get files - {e}")
        return None, None
    
    else: 
        return meta, citation_lines


def get_meta(package_name: str):
    '''
    Gets the metadata of a package from Bioconductor
    - REPO_URL: URL of the Bioconductor repository
    - package_name: name of the package
    '''
    # Import the desc package
    desc = importr('desc')

    # Read the DESCRIPTION file using desc
    try:
        # Any of the following two lines can fail
        desc_obj = desc.desc(package_name)
        string = desc_obj["print"]()

    except Exception as e:
        logging.warning(f"error - {package_name} - Could not get metadata - {e}")
        return None

    else:
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


def clean_text(text: str) -> str:
    """
    Cleans a string by removing:
    - Leading and trailing quotes (")
    - Leading '{' and trailing '}'
    - Leading and trailing commas (',')
    - Fixes cases like '{, }' and '", "'

    Args:
        text (str): The input string.

    Returns:
        str: The cleaned string.
    """
    if not text:
        return text  # Return empty or None as-is

    # Remove leading and trailing quotes
    text = text.strip('"')

    # Remove leading '{' and trailing '}'
    text = text.lstrip("{").rstrip("}")

    # Remove leading and trailing commas
    text = text.strip(",")

    # Remove leading and trailing quotes
    text = text.strip('"')

    # Fix patterns like "{, }" or "{ , }" → empty string
    text = re.sub(r"^\{\s*,?\s*\}$", "", text)

    return text.strip()  # Ensure no unwanted spaces remain



def parse_citation_file(citation_lines: List) -> List[Dict]:
    """
    Parses a list of lines from an R CITATION file using R.

    Args:
        citation_lines (List[str]): List of lines from the CITATION file.

    Returns:
        List[Dict]: A list of dictionaries containing citation details.
    """
    try:
        article = False
        publications = []
        new_pub = {}
        for line in citation_lines:
            if 'entry' in line:
                if new_pub:
                    publications.append(new_pub)
                    new_pub = {}
            
                # new entry
                if 'entry="article"' in line:
                    new_pub = {}
                    article = True
                else:
                    article = False
            
            elif article:
                if '=' in line:
                    last_key = ''
                    # Parse the line
                    if 'title' in line:                        
                        new_pub['title'] = clean_text(line.split('title = ')[1].strip())
                        last_key = 'title'
                    elif 'journal' in line:
                        new_pub['journal'] = clean_text(line.split('journal = ')[1].strip())
                        last_key = 'journal'
                    elif 'doi' in line:
                        new_pub['doi'] = clean_text(line.split('doi = ')[1].strip())
                        last_key = 'doi'
                    elif 'year' in line:
                        new_pub['year'] = clean_text(line.split('year = ')[1].strip())
                        last_key = 'year'
                    elif 'url' in line:
                        new_pub['url'] = clean_text(line.split('url = ')[1].strip())
                        last_key = 'url'
                elif last_key:
                    new_pub[last_key] += clean_text(line.strip())

        if new_pub:
            publications.append(new_pub)

        return publications

    except Exception as e:
        logging.error(f"Error parsing CITATION content: {str(e)}")
        return []



def parse_metadata(raw_metadata, citation_lines):
    parsed_metadata = parse_description(raw_metadata)
    if citation_lines:
        parsed_metadata['publication'] = parse_citation_file(citation_lines)
        logging.info(f"publications - {parsed_metadata['publication']}")

    return parsed_metadata



def parse_description(metadata):
    '''
    Parses the DESCRIPTION string into a dictionary, and then parses the authors, 
    which require special parsing functions
    - metadata: DESCRIPTION file as a string
    '''
    # Parse the metadata
    metadata_dict = build_dictionary(metadata)
    # Parse authors
    if "Authors@R (parsed)" in metadata_dict:
        metadata_dict["Authors@R (parsed)"] = parse_authors_r(metadata_dict['Authors@R (parsed)'])
    
    if "Author" in metadata_dict:
        metadata_dict["Author"] = parse_authors_complex(metadata_dict['Author'])
    
    if "Maintainer" in metadata_dict:
        metadata_dict["Maintainer"] = parse_authors_simple(metadata_dict['Maintainer'])

    # Parse attributes that are lists of strings separated by commas
    list_comma_attributes = ["Depends", "Imports", "LinkingTo", "Suggests", "Enhances", "License", "biocViews"]
    for attribute in list_comma_attributes:
        if attribute in metadata_dict:
            metadata_dict[attribute] = parse_list_comma(metadata_dict[attribute])

    # Parse attributes that are lists of strings separated by spaces
    list_space_attributes = ["Collate"]
    for attribute in list_space_attributes:
        if attribute in metadata_dict:
            metadata_dict[attribute] = parse_list_space(metadata_dict[attribute])
    

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
            description, citation_lines = get_files(REPO_URL, package_name)
            if description:
                parsed_metadata = parse_metadata(description, citation_lines)
                if parsed_metadata:
                    name = package_name
                    version = parsed_metadata.get('Version')
                    type_ = 'lib'
                    identifier = f"bioconductor/{name}/{type_}/{version}"
                    tool = {
                        'data': parsed_metadata,
                        '_id' : identifier,
                        '@data_source' : 'bioconductor',
                        '@source_url' : f"{REPO_URL}/packages/{name}",
                    }

                    document_w_metadata = add_metadata_to_entry(identifier, tool, alambique)
                    push_entry(document_w_metadata, alambique)
                
                else:
                        logging.warning(f"no parsed metadata - empty")
        
     
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