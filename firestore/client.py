"""
████████████████████████████████████████████████████
█▄─▄▄─█▄─▄█▄─▄▄▀█▄─▄▄─█─▄▄▄▄█─▄─▄─█─▄▄─█▄─▄▄▀█▄─▄▄─█
██─▄████─███─▄─▄██─▄█▀█▄▄▄▄─███─███─██─██─▄─▄██─▄█▀█
█▄▄▄███▄▄▄█▄▄█▄▄█▄▄▄▄▄█▄▄▄▄▄██▄▄▄██▄▄▄▄█▄▄█▄▄█▄▄▄▄▄█ Wrapper
"""

import os

from google.oauth2 import service_account
from google.cloud import firestore

from rmrhermes.chatterbox import Chatterbox

cb = Chatterbox(module="FireStore")


class FireStore:
    """
    FireStore connection wrapper
    """

    def __init__(
            self,
            collection_name=None,
            authentication: dict | str = None
        ) -> None:
        """Builds Google FireStore document database resource from given credentials.

        Args:
            authentication: (str | dict): defaults to `constants.GOOGLE_CREDS`

        Properties:
            authentication: stored arg
            credentials: service_account.Credentials from given authentication
            db: firestore client

        Methods:
            authorize(): creates credentials
            client(): creates firestore.client connected to `rmr-cloud-services` project
        """

        if authentication is None:
            raise ValueError("Authentication params not given, unable to authenticate.")


        self.collection_name = collection_name
        self.authentication = authentication
        self.credentials = None
        self.db = None

        # attempt to authorize google drive access
        try:
            self.authorize()
            self.client()
        except ValueError as error:
            cb(f"ValueError Occured \n\tError:\n{error}", slack=True)
            raise ValueError() from error
        except Exception as error:
            cb(f"Unknown Error Occured \n\tError:\n{error}", slack=True)
            raise ValueError() from error

    def change_collection(self, new_collection_name):
        """change from current collection to new collection

        Args:
            new_collection_name (str): new collection name
        """
        self.collection_name = new_collection_name

    def authorize(self):
        """Init credentials from given authentication data.

        Sets:
            credentials: service_account.Credentials
        """
        # init service account from credential dict
        if isinstance(self.authentication, str):
            self.credentials = service_account.Credentials.from_service_account_file(
                filename=self.authentication
            )
        # init service account from credential dict
        elif isinstance(self.authentication, dict):
            self.credentials = service_account.Credentials.from_service_account_info(
                info=self.authentication
            )

    def client(self):
        """Create FireStore.Client from credentials to default database.

        Sets:
            db: firestore.Client
        """
        self.db = firestore.Client(credentials=self.credentials, project="rmr-cloud-services")

    def __collection_not_specified(self):
        """raise value error since collection is not specified

        Raises:
            ValueError: collection is not specified
        """
        raise ValueError(
            "collection_name must be set in order "
            "to get via 'get_collection' function, you can set your collection:\n"
            "at init like fs = FireStore(collection_name={COLLECTION NAME})\n"
            "or via calling change_collection(new_collection_name={COLLECTION NAME})"
        )

    def get_collection(self):
        """gets all documents from a collection

        Raises:
            ValueError: if collection is not specified

        Returns:
            dict: all documents as a dictionary
        """
        if self.collection_name is not None:
            data = self.db.collection(self.collection_name).get()
            return {doc.id: doc.to_dict() for doc in data}
        self.__collection_not_specified()

    def get_document(self, document_id):
        """gets document from collection

        Args:
            document_id (str): document id from given firestore collection
        """
        if self.collection_name is None:
            self.__collection_not_specified()
        document = self.db.collection(self.collection_name).document(document_id=document_id)
        # if document._data is None:
        #     raise ValueError("Document does not have data")
        data = document.get().to_dict()
        return data

    def delete_document(self, document_id):
        """delete document given document ID

        Args:
            document_id (str): document id from given firestore collection
        """
        self.db.collection(self.collection_name).document(document_id=document_id).delete()

    def add_to_collection(self, document_data: dict, document_id: str = None):
        """adds a document to a collection

        Args:
            document (dict): document data

        Raises:
            ValueError: if document is not type dict, raise ValueError
            ValueError: if collection is not specified
        """
        if self.collection_name is None:
            self.__collection_not_specified()
        if not isinstance(document_data, dict):
            raise ValueError("'document' must be of type 'dict' to add document to collection")
        if not isinstance(document_id, str) and document_id is not None:
            raise ValueError(
                "'document_id' must be of type 'str' or None to add document to collection"
            )
        self.db.collection(self.collection_name).add(
            document_data=document_data, document_id=document_id
        )

    def change_document(self, doc_name, attr: dict, merge=True):
        """
        attr = {settings: {"drive_letter_filescom": "D", "drive_letter_google": "G"}}
        setting the attribute with merge=True will overwrite any subdictionary
        but will not change any other values in the document'

        888  8b   d8  888b.  .d88b.  888b.  88888    db     8b  8  88888
         8   8YbmdP8  8  .8  8P  Y8  8  .8    8     dPYb    8Ybm8    8
         8   8  "  8  8wwP'  8b  d8  8wwK'    8    dPwwYb   8  "8    8
        888  8     8  8      `Y88P'  8  Yb    8   dP    Yb  8   8    8   ...

        if merge = False the ENTIRE document will be overwritten,
        this should only be used for creation of new document
        """

        self.db.collection(self.collection_name).document(doc_name).set(attr, merge=merge)


def get_firestore_connection(collection_name=None):
    """gets firestore connection with optional input collection_name

    Args:
        collection_name (str, optional): collection_name. Defaults to None.

    Returns:
        FireStore: firestore connection
    """
    try:
        return FireStore(collection_name=collection_name, authentication=GOOGLE_CREDS)
    except Exception as e:
        cb(e)
        return None
