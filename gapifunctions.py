from __future__ import print_function

import datetime
import os.path
import os
import httplib2
import uuid
import json
import dotenv
import requests

from apiclient import discovery
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2 import service_account
from dateutil.parser import parse as dtparse

dotenv.load_dotenv()
# Define the scopes and service account file for Google's APIs, then create our credentials
SCOPES = ['https://www.googleapis.com/auth/calendar', 'https://www.googleapis.com/auth/drive']
SERVICE_ACCOUNT_FILE = 'acabot-398317-b2293b5c6d43.json'

credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)

# This function is used when watch channels are about to expire.
# First, the function checks for any active watch channels and, if it finds any, stops them. 
# Then, it creates new watch channels for the calendars that the bot is watching. These channels
# will expire in 7 days, so this function must be called at least once a week. It will save the 
# information for these channels in a file for later access.
def calapi_startwebhooks():
    service = build('calendar', 'v3', credentials=credentials)

    try:
        with open ('activechannels.json', 'r') as f:
            activechannels = json.load(f)
        
        currentacapella = {
            'id': activechannels.get('acapella').get('id'),
            'resourceId': activechannels.get('acapella').get('resourceId')
        }

        currentslihrehearsals = {
            'id': activechannels.get('slihrehearsals').get('id'),
            'resourceId': activechannels.get('slihrehearsals').get('resourceId')
        }

        currentslihgigs = {
            'id': activechannels.get('slihgigs').get('id'),
            'resourceId': activechannels.get('slihgigs').get('resourceId')
        }

        service.channels().stop(body=currentacapella).execute()
        service.channels().stop(body=currentslihgigs).execute()
        service.channels().stop(body=currentslihrehearsals).execute()
        
    except:
        print('No active channels found. Are you in the right directory?')

    acapella = {
    'id': str(uuid.uuid4()),
    'type': 'web_hook',
    'address': os.getenv('HTTP_REQUEST_URL'),
    'token': 'target=acabot-acapella'
    }

    slihrehearsal = {
    'id': str(uuid.uuid4()),
    'type': 'web_hook',
    'address': os.getenv('HTTP_REQUEST_URL'),
    'token': 'target=slih-rehearsal'
    }

    slihgig = {
    'id': str(uuid.uuid4()),
    'type': 'web_hook',
    'address': os.getenv('HTTP_REQUEST_URL'),
    'token': 'target=slih-rehearsal'
    }

    responseaca = service.events().watch(
        calendarId=os.getenv('ACAPELLA_CAL_ID'), 
        body=acapella).execute()
    print(responseaca)

    responseslihreh = service.events().watch(
        calendarId=os.getenv('SLIH_REH_CAL_ID'), 
        body=slihrehearsal).execute()
    print(responseslihreh)

    responseslihgig = service.events().watch(
        calendarId=os.getenv('SLIH_GIGS_CAL_ID'),
        body=slihgig).execute()
    print(responseslihgig)

    newactivechannels= {
        'acapella': {
            'id': responseaca.get('id'),
            'resourceId': responseaca.get('resourceId')
        },
        'slihrehearsals': {
            'id': responseslihreh.get('id'),
            'resourceId': responseslihreh.get('resourceId')
        },
        'slihgigs': {
            'id': responseslihgig.get('id'),
            'resourceId': responseslihgig.get('resourceId')
        }
    }

    with open('activechannels.json', 'w') as f:
        json.dump(newactivechannels, f)

def calapi_incrementalsync():
    url = os.getenv('HTTP_REQUEST_URL')
    headers = {'message': 'incremental-sync'}

    res = requests.post(url, headers=headers)
    print(res.text)

def calapi_getupcoming():
    try:
        service = build('calendar', 'v3', credentials=credentials)

        now = datetime.datetime.now(datetime.UTC).isoformat() + 'Z'
        maxTime = datetime.datetime.now(datetime.UTC) + datetime.timedelta(hours=2)
        maxTime = maxTime.isoformat() + 'Z'
        print('Getting the upcoming 10 events...')
        events_result = service.events().list(calendarId=os.getenv('ACAPELLA_CAL_ID'), timeMin=now,
                                              timeMax=maxTime,
                                              maxResults=10, singleEvents=True,
                                              orderBy='startTime').execute()
        events = events_result.get('items', [])
        if events_result is not None:
            print("Events found.")

        if not events:
            print('No upcoming events found.')
            return

        return events

    except HttpError as error:
        print('An error occurred: %s' % error)
        return 'An error has occurred, check bot logs for more information.'
    

# Calls the Google Calendar API to get the next 10 events on the calendar.
def calapi_getevents(calid: str):
    try:
        service = build('calendar', 'v3', credentials=credentials)

        now = datetime.datetime.now(datetime.UTC).isoformat() + 'Z'
        print('Getting the upcoming 10 events')
        events_result = service.events().list(calendarId=calid, timeMin=now,
                                              maxResults=10, singleEvents=True,
                                              orderBy='startTime').execute()
        events = events_result.get('items', [])

        if not events:
            print('No upcoming events found.')
            return

        return events

    except HttpError as error:
        print('An error occurred: %s' % error)
        return 'An error has occurred, check bot logs for more information.'
    
# Calls the Google Calendar API to create a new event on the calendar whose ID is specified.
def calapi_createevent(newevent, calid: str):
    try:
        service = build('calendar', 'v3', credentials=credentials)
        event = service.events().insert(calendarId=calid, body=newevent).execute()
        print('Event created: %s' % (event.get('htmlLink')))
        return event
    except HttpError as error:
        print('An error occurred: %s' % error)

# Gets a specific event from the calendar whose ID is specified. Takes in a name argument to search for.
def calapi_gcalgetevent(eventname, calid: str):
    try:
        service = build('calendar', 'v3', credentials=credentials)
        now = datetime.datetime.utcnow().isoformat() + 'Z'
        events_result = service.events().list(calendarId=calid, timeMin=now,
                                              maxResults=10, singleEvents=True,
                                              orderBy='startTime').execute()
        events = events_result.get('items', [])

        for event in events:
            if event['summary'] == eventname:
                return event
        return None
    except HttpError as error:
        print('An error occurred: %s' % error)
        return None

# Not yet implemeted in the bot. When creating a new event, this function searches for any events that fall in the same time range.
# If any are found, it will notify the user with an option to continue or cancel.
def cal_apifindconflicts(start, end, calid: str):
    try:
        service = build('calendar', 'v3', credentials=credentials)
        events_result = service.events().list(calendarId=calid, timeMin=start, timeMax=end,
                                              singleEvents=True,
                                              orderBy='startTime').execute()
        events = events_result.get('items', [])
        return events
    except HttpError as error:
        print('An error occurred: %s' % error)
        return None       

# Not implimented and probably will not be unless the API changes
#
# Theoretically, these functions would allow the bot to list and then grab an audio file from Google Drive.
# With this audio file, the bot could then play it in the voice channel.
#
# Unfortunately, the API does not allow this for private files. The only way to play audio from Google Drive 
# is to either download it to the local machine and play from there, or to make the file public and get its url.
#
# At the moment, the only option I consider feasable is the latter, but making the files public is not something
# that I or the acapella groups want
#   def driveapi_listmusicfiles():
#       try:
#           service = build('drive', 'v3', credentials=credentials)
#           file = service.files().list(q="mimeType contains 'audio/' and parents in '1jnRS6e4AmFWZr4qEM-3Qt4OFWra7Sqfy'").execute()
#           print(file)
#       except HttpError as error:
#           print('An error occurred: %s' % error)
#           return None         
#   
#   def driveapi_getfile(fileid: str):
#       try:
#           service = build('drive', 'v3', credentials=credentials)
#           file = service.files().get(fileId=fileid, fields='webContentLink', alt='media').execute()
#           print(file)
#           return file['webContentLink']
#       except HttpError as error:
#           print('An error occurred: %s' % error)
#           return None  