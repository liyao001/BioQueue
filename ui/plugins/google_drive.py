#!/usr/bin/env python
# coding=utf-8
# Created by: Li Yao
# Created on: 1/28/20
import pickle
import os
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.http import MediaFileUpload


class GoogleDrive(object):
    SCOPES = ['https://www.googleapis.com/auth/drive.file', 'https://www.googleapis.com/auth/drive.metadata.readonly']

    def __init__(self, token_file="token.pickle", app_credential="client_secret.json"):
        creds = None
        # The file token.pickle stores the user's access and refresh tokens, and is
        # created automatically when the authorization flow completes for the first
        # time.
        if os.path.exists(token_file):
            with open(token_file, 'rb') as token:
                creds = pickle.load(token)
        # If there are no (valid) credentials available, let the user log in.
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    app_credential, self.SCOPES)
                creds = flow.run_local_server(port=0)
            # Save the credentials for the next run
            with open(token_file, 'wb') as token:
                pickle.dump(creds, token)
        self.service = build('drive', 'v3', credentials=creds)

    def create_folder(self, folder_name):
        file_metadata = {
            'name': folder_name,
            'mimeType': 'application/vnd.google-apps.folder',
        }
        file = self.service.files().create(body=file_metadata, fields='id').execute()
        folder_id = file.get('id')
        return folder_id

    def already_folder(self, folder_name):
        results = self.service.files().list(
            q="mimeType='application/vnd.google-apps.folder' and name='" + folder_name + "'",
            fields="nextPageToken, files(id, name)").execute()
        items = results.get('files', [])
        if items:
            return True, items[-1]['id']
        else:
            return False, ""

    def upload_file(self, file_name, file_path, folder_id, description='', mimetype='application/x-compressed'):
        file_metadata = {
            'name': file_name,
            'parents': [folder_id],
            'description': description,

        }
        media = MediaFileUpload(file_path,
                                mimetype=mimetype,
                                resumable=True)
        file = self.service.files().create(body=file_metadata,
                                           media_body=media,
                                           fields='id').execute()
        file_id = file.get('id')
        return file_id

    def update_file(self, file_id, new_file, new_mimetype='application/x-compressed'):
        try:
            file = self.service.files().get(fileId=file_id).execute()
            file['mimeType'] = new_mimetype

            media_body = MediaFileUpload(new_file, mimetype=new_mimetype, resumable=True)
            updated_file = self.service.files().update(
                fileId=file_id,
                body=file,
                new_revision=True,
                media_body=media_body
            ).execute()
            return updated_file.get('id')
        except Exception as e:
            print(e)
            return None

    def share_with_person(self, file_id, share_with, msg='', permission='reader'):
        def callback(request_id, response, exception):
            if exception:
                # Handle error
                print(exception)
            else:
                print("Permission Id: %s" % response.get('id'))

        batch = self.service.new_batch_http_request(callback=callback)
        for user in share_with:
            user_permission = {
                'type': 'user',
                'role': permission,
                'emailAddress': user
            }
            batch.add(self.service.permissions().create(
                fileId=file_id,
                body=user_permission,
                fields='id',
                emailMessage=msg,
            ))
        res = batch.execute()
        return res.get('id')
