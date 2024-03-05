import json 
import os
import requests
import logging
from pymongo import MongoClient
from pymongo.collection import Collection
from datetime import datetime

def create_metadata(identifier: str, alambique:Collection):
    '''
    This function first checks if the entry is already in the database.
    If the entry is in the database, it creates a metadata dictionary with the 
    following fields:
        - "@last_updated_at" : current_date
        - "@updated_by" : task_run_id
    If the entry is not in the database, in addition the the previos fields,it:
    adds the following:
        - "_id": identifier
        - "@created_at" : current_date
        - "@created_by" : task_run_id
    The metadata is returned.
    '''
    # Current timestamp
    current_date = datetime.utcnow()
    # Commit url
    CI_PROJECT_NAMESPACE = os.getenv("CI_PROJECT_NAMESPACE")
    CI_PROJECT_NAME = os.getenv("CI_PROJECT_NAME")
    CI_COMMIT_SHA = os.getenv("CI_COMMIT_SHA")
    commit_url = f"https://gitlab.bsc.es/{CI_PROJECT_NAMESPACE}/{CI_PROJECT_NAME}/-/commit/{CI_COMMIT_SHA}"
    # Prepare the metadata to add or update
    metadata = {
        "_id": identifier,
        "@last_updated_at": current_date,
        "@updated_by": commit_url,
        "@updated_logs": os.getenv("CI_PIPELINE_URL")
    }
    
    # Check if the entry exists in the database
    existing_entry = alambique.find_one({"_id": identifier})
    
    if not existing_entry:
        # This entry is new, so add additional creation metadata
        metadata.update({
            "_id": identifier,
            "@created_at": current_date,
            "@created_by": commit_url,
            "@created_logs": os.getenv("CI_PIPELINE_URL")
        })
        
    # Return the entry with the new fields
    return metadata

def add_metadata_to_entry(identifier: str, entry: dict, alambique:Collection):
    '''
    This function adds metadata regarding update and returns it.
        {
            "_id": "biocodcutor/trimal/lib/1.4",
            "@created_at": "2023-01-01T00:00:00Z", 
            "@created_by": ObjectId("integration_20240210103607"),
            "@last_updated_at": "2023-02-01T12:00:00Z",
            "@updated_by": ObjectId("integration_20240214103607"),
            "data": {
                "id": "trimal",
                "version": "1.4",
                ...
            }
    '''
    document_w_metadata = create_metadata(identifier, alambique)
    document_w_metadata.update(entry)

    return document_w_metadata

def clean_date_field(tool:dict):
    if 'about' in tool['data'].keys():
        # date objects cause trouble and are prescindable
        tool['data']['about'].pop('date', None)
    return tool

def clean_date_field(tool:dict):
    if 'about' in tool['data'].keys():
        # date objects cause trouble and are prescindable
        tool['data']['about'].pop('date', None)
    return tool


def push_entry(tool:dict, collection: Collection):
    '''Push tool to collection.

    tool: dictionary. Must have at least an '@id' key.
    collection: collection where the tool will be pushed.
    log : {'errors':[], 'n_ok':0, 'n_err':0, 'n_total':len(insts)}
    '''    
    try:
        # if the entry already exists, update it
        if collection.find_one({"_id": tool['_id']}):
            update_entry(tool, collection)
        # if the entry does not exist, insert it
        else:
            inset_new_entry(tool, collection)
        
    except Exception as e:
        logging.warning(f"error - {type(e).__name__} - {e}")

    finally:
        return
    

def update_entry(entry: dict, collection: Collection):
    '''Updates an entry in the collection.

    entry: dictionary. Must have at least an '_id' key.
    collection: collection where the entry will be updated.
    '''
    # Ensure '_id' exists in entry
    if '_id' not in entry:
        logging.error("Entry must contain an '_id' field.")
        return

    # Copy entry to avoid mutating the original dict
    update_document = entry.copy()

    # keep the original creation metadata if entry exists in the collection
    original_entry = collection.find_one({'_id': entry['_id']})
    if original_entry:
        update_document['@created_at'] = original_entry['@created_at']
        update_document['@created_by'] = original_entry['@created_by']
        update_document['@created_logs'] = original_entry['@created_logs']
                                         

    try:
        # Use replace_one instead of update_one for replacing the whole document
        # Make sure to set upsert=True if you want to insert a new document when no document matches the filter
        result = collection.replace_one({"_id": entry['_id']}, update_document, upsert=True)
        if result.matched_count > 0:
            logging.info(f"Document with _id {entry['_id']} updated successfully.")
        else:
            logging.info(f"No matching document found with _id {entry['_id']}. A new document has been inserted.")
    except Exception as e:
        logging.warning(f"Error updating document - {type(e).__name__} - {e}")

        
def inset_new_entry(entry: dict, collection: Collection):
    '''Inserts a new entry in the collection.

    entry: dictionary. Must have at least an '_id' key.
    collection: collection where the entry will be inserted.
    '''
    try:
        collection.insert_one(entry)
    except Exception as e:
        logging.warning(f"error - {type(e).__name__} - {e}")
    else:
        logging.info(f"inserted_to_db_ok - {entry['_id']}")
    finally:
        return


def connect_db(collection_name: str):
    '''Connect to MongoDB and return the database and collection objects.

    '''
    # variables come from .env file
    mongoHost = os.getenv('MONGO_HOST', default='localhost')
    mongoPort = os.getenv('MONGO_PORT', default='27017')
    mongoUser = os.getenv('MONGO_USER')
    mongoPass = os.getenv('MONGO_PASS')
    mongoAuthSrc = os.getenv('MONGO_AUTH_SRC', default='admin')
    mongoDb = os.getenv('MONGO_DB', default='oeb-research-software')

    if collection_name == 'alambique':
        collection_name = os.getenv('ALAMBIQUE', default='alambique')
    
    logging.info(f"Connecting to {collection_name} collection.")
    logging.info(f"Connecting to {mongoHost}:{mongoPort} database. Dn is {mongoDb}.")
    logging.info(f"Using {mongoUser} as user and {mongoPass} as pass.")

    # Connect to MongoDB
    mongoClient = MongoClient(
        host=mongoHost,
        port=int(mongoPort),
        username=mongoUser,
        password=mongoPass,
        authSource=mongoAuthSrc,
    )
    db = mongoClient[mongoDb]
    alambique = db[collection_name]

    return alambique


def connect_db_local(collection_name: str):
    '''Connect to MongoDB and return the database and collection objects.

    '''
    # Connect to MongoDB
    mongoClient = MongoClient('localhost', 27017)
    db = mongoClient['oeb-research-software']
    alambique = db[collection_name]

    return alambique


# initializing session
session = requests.Session()
headers = {"User-Agent":"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_5) AppleWebKit 537.36 (KHTML, like Gecko) Chrome",
"Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"}


def get_url(url, verb=False):
    '''
    Takes and url as an input and returns a json response
    '''
    try:
        re = session.get(url, headers=headers, timeout=(10, 30))
    except Exception as e:
        logging.warning(f"error - {type(e).__name__} - {e}")
        return None
        
    else:
        if re.status_code == 200:
            content_decoded = decode_json(re)
            return(content_decoded)
        else:
            logging.warning(f"error - html_repoonse - error with {url}: status code {re.status_code}")
            return None

def decode_json(json_res):
    '''
    Decodes a json response
    '''
    try:
        content_decoded=json.loads(json_res.text)
    except Exception as e:
        logging.warning(f"error - {type(e).__name__} - {e}")
        logging.warning('Impossible to decode the json.')
        return None
    else:
        return(content_decoded) 

