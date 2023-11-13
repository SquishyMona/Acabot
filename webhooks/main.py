from firebase_functions import https_fn, options
from firebase_admin import initialize_app
from googleapiclient.discovery import build
from discord_webhook import DiscordWebhook, DiscordEmbed
from googleapiclient.errors import HttpError
from google.oauth2 import service_account
from googleapiclient.discovery import build
from dateutil import parser as dtparse
import json
import dotenv
import os

dotenv.load_dotenv()

# Defining some globals. Service account file should be located in the same directory as this file.
# Resource IDs are used to identify which webhook to send to.
SCOPES = ['https://www.googleapis.com/auth/calendar']
SERVICE_ACCOUNT_FILE = 'acabot-398317-b2293b5c6d43.json'

credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)

# This function runs on HTTP request to our function, which in this case, should be a GCal API push notification.
@https_fn.on_request(cors=options.CorsOptions(cors_origins="*", cors_methods=["get", "post"]))
def on_request_example(req: https_fn.Request) -> https_fn.Response:
    service = build('calendar', 'v3', credentials=credentials)

    # This section may be needed in the future, pending testing. This will handle a POST request with a header
    # 'message' set to 'incremental-sync'. This will trigger a full sync to be performed, which will get new sync
    # tokens for each calendar. Sync tokens may expire after a set period of time, so idealy, this function would
    # be called every so often to ensure we always have valid tokens.
    if req.headers.get('message') == 'incremental-sync':
        try:
            print("Incremental sync received, getting new tokens.")
            with open('synctoken.json') as json_file:
                nextSyncToken = json.load(json_file)
            events_result = service.events().list(calendarId=os.getenv('ACAPELLA_CAL_ID')).execute()
            nextSyncToken['acapella'] = events_result['nextSyncToken']
            events_result = service.events().list(calendarId=os.getenv('SLIH_REH_CAL_ID')).execute()
            nextSyncToken['slih_reh'] = events_result['nextSyncToken']
            events_result = service.events().list(calendarId=os.getenv('SLIH_GIGS_CAL_ID')).execute()
            nextSyncToken['slih_gigs'] = events_result['nextSyncToken']
            with open('synctoken.json', 'w') as outfile:
                json.dump(nextSyncToken, outfile)
            return https_fn.Response("Incremntal sync successful.")
        except:
            return https_fn.Response("Incremental sync failed, see Cloud Logs.")

    # Read the headers of the request to grab the Resource ID, then use that to determine which webhook to send to
    if req.headers.get('x-goog-resource-id') == os.getenv('ACAPELLA_RESOURCEID'):
        calendarId = os.getenv('ACAPELLA_CAL_ID')
        webhookurl = os.getenv('ACAPELLA_WEBHOOK')
        token = 'acapella'
    if req.headers.get('x-goog-resource-id') == os.getenv('SLIH_REH_RESOURCEID'):
        calendarId = os.getenv('SLIH_REH_CAL_ID')
        webhookurl = os.getenv('SLIH_REH_WEBHOOK')
        token = 'slih_reh'
    if req.headers.get('x-goog-resource-id') == os.getenv('SLIH_GIGS_RESOURCEID'):
        calendarId = os.getenv('SLIH_GIGS_CAL_ID')
        webhookurl = os.getenv('SLIH_GIGS_WEBHOOK')
        token = 'slih_gigs'
    
    # In an event of a sync notification, we'll need to get new sync tokens to use in our subsequent requests. In this
    # case, we'll check for a sync notification, then to get our next sync token, we'll make and 'event list' request
    # to the API, grab the sync token, then store it in a JSON file to use in our next request. The sync token is used
    # to determine which events have been updated since the last request.
    if req.headers.get('x-goog-resource-state') == 'sync':
        with open('synctoken.json') as json_file:
            nextSyncToken = json.load(json_file)
        print(f"Sync event received, channel started for id {req.headers.get('x-goog-resource-id')}")
        events_result = service.events().list(calendarId=calendarId).execute()
        nextSyncToken[token] = events_result['nextSyncToken']
        print(f'The next sync token is {events_result["nextSyncToken"]} for calendar {token}')
        with open('synctoken.json', 'w') as outfile:
            json.dump(nextSyncToken, outfile)
        return https_fn.Response("Sync event received")
    
    # If the event is not a sync notification, something has changed on one of our calendars.
    else:
        print("Changes detected.")
        with open('synctoken.json') as json_file:
            nextSyncToken = json.load(json_file)
        try:
            events_result = service.events().list(calendarId=calendarId, syncToken=nextSyncToken[token]).execute()

        # If we get a 410 error, our sync token has expired. In this case, we'll need to get a new sync token for each
        # calendar. We can then call the entire function again to get the new events. I'm not entirely sure if this
        # will get us the new events from the previous sync token, but from a first test it looks like it might. If it
        # ends up not doing this, the section of code towards the top of the function will be used to periodically get
        # new sync tokens so we always have a valid one.
        except HttpError as err:
            if err.resp.status == 410:
                print("Sync token expired, getting new token.")
                events_result = service.events().list(calendarId=os.getenv('ACAPELLA_CAL_ID')).execute()
                nextSyncToken['acapella'] = events_result['nextSyncToken']
                events_result = service.events().list(calendarId=os.getenv('SLIH_REH_CAL_ID')).execute()
                nextSyncToken['slih_reh'] = events_result['nextSyncToken']
                events_result = service.events().list(calendarId=os.getenv('SLIH_GIGS_CAL_ID')).execute()
                nextSyncToken['slih_gigs'] = events_result['nextSyncToken']
                with open('synctoken.json', 'w') as outfile:
                    json.dump(nextSyncToken, outfile)
                on_request_example(req)
                return https_fn.Response("Successfully refreshed token.")
            else:
                raise err
        nextSyncToken[token] = events_result['nextSyncToken']
        # In case our JSON file fails, we'll print the next sync token to our console in case we need to manually specify it.
        print(f'The next sync token is {events_result["nextSyncToken"]} for calendar {token}')
        with open('synctoken.json', 'w') as outfile:
            json.dump(nextSyncToken, outfile)
        events = events_result.get('items', [])

        for event in events:
            # If an event has 'confirmed' status, we need to check if it's a new event, or an existing event that's
            # been updated. In this case, we'll check the 'created' and 'updated' fields to see if they're the same.
            # This might not be completely accurate, as there's a millisecond difference between 'created' and 'updated'
            # when an event is created, but it's the best we can do for now. To help this fact, we'll also cut the
            # milliseconds from our calculations. After all this, the notification will be sent to our Discord webhook
            if event['status'] == 'confirmed':
                if int(dtparse.parse(event['created']).strftime('%Y%m%d%H%M%S')) != int(dtparse.parse(event['updated']).strftime('%Y%m%d%H%M%S')):
                    print(f"An event on calendar {token} has been updated. Debug Info:\n\n{event}")
                    webhook = DiscordWebhook(url=webhookurl, content="An event has been updated!")
                    embed = DiscordEmbed(title=event['summary'], description=f'[View on Google Calendar]({event["htmlLink"]})', color=242424)
                    embed.set_author(name='Google Calendar', icon_url='https://uxwing.com/wp-content/themes/uxwing/download/brands-and-social-media/google-calendar-icon.png')
                    try:
                        embed.add_embed_field(name='Date', value=dtparse.parse(event['start']['dateTime']).strftime('%B %d, %Y'), inline=False)
                        embed.add_embed_field(name='Start Time', value=dtparse.parse(event['start']['dateTime']).strftime('%-I:%M %p'))
                        embed.add_embed_field(name='End Time', value=dtparse.parse(event['end']['dateTime']).strftime('%-I:%M %p'))
                    except:
                        embed.add_embed_field(name='Date', value=dtparse.parse(event['start']['date']).strftime('%B %d, %Y'), inline=False)
                    try:
                        embed.add_embed_field(name='Location', value=event['location'], inline=False)
                    except KeyError:
                        pass
                    try:
                        embed.add_embed_field(name='Description', value=event['description'], inline=False)
                    except KeyError:
                        pass
                    webhook.add_embed(embed)
                    webhook.execute()
                else: 
                    print(f"A new event on calendar {token} has been added. Debug Info:\n\n{event}")
                    webhook = DiscordWebhook(url=webhookurl, content="A new event has been added!")
                    embed = DiscordEmbed(title=event['summary'], description=f'[View on Google Calendar]({event["htmlLink"]})', color=242424)
                    embed.set_author(name='Google Calendar', icon_url='https://uxwing.com/wp-content/themes/uxwing/download/brands-and-social-media/google-calendar-icon.png')
                    try:
                        embed.add_embed_field(name='Date', value=dtparse.parse(event['start']['dateTime']).strftime('%B %d, %Y'), inline=False)
                        embed.add_embed_field(name='Start Time', value=dtparse.parse(event['start']['dateTime']).strftime('%-I:%M %p'))
                        embed.add_embed_field(name='End Time', value=dtparse.parse(event['end']['dateTime']).strftime('%-I:%M %p'))
                    except:
                        embed.add_embed_field(name='Date', value=dtparse.parse(event['start']['date']).strftime('%B %d, %Y'), inline=False)
                    try:
                        embed.add_embed_field(name='Location', value=event['location'], inline=False)
                    except KeyError:
                        pass
                    try:
                        embed.add_embed_field(name='Description', value=event['description'], inline=False)
                    except KeyError:
                        pass
                    webhook.add_embed(embed)
                    webhook.execute()
            # If an event has 'cancelled' status, we'll send a notification to Discord that the event has been cancelled.
            elif event['status'] == 'cancelled':
                print(f"An event on calendar {token} has been removed. Debug Info:\n\n{event}")
                cancelledevent = service.events().get(calendarId=calendarId, eventId=event['id']).execute()
                webhook = DiscordWebhook(url=webhookurl, content="An event has been cancelled!")
                embed = DiscordEmbed(title=cancelledevent['summary'], color=242424)
                embed.set_author(name='Google Calendar', icon_url='https://uxwing.com/wp-content/themes/uxwing/download/brands-and-social-media/google-calendar-icon.png')
                try:
                    embed.add_embed_field(name='Date', value=dtparse.parse(cancelledevent['start']['dateTime']).strftime('%B %d, %Y'), inline=False)
                    embed.add_embed_field(name='Start Time', value=dtparse.parse(cancelledevent['start']['dateTime']).strftime('%-I:%M %p'))
                    embed.add_embed_field(name='End Time', value=dtparse.parse(cancelledevent['end']['dateTime']).strftime('%-I:%M %p'))
                except:
                    embed.add_embed_field(name='Date', value=dtparse.parse(cancelledevent['start']['date']).strftime('%B %d, %Y'), inline=False)
                try:
                    embed.add_embed_field(name='Location', value=cancelledevent['location'], inline=False)
                except KeyError:
                    pass
                try:
                    embed.add_embed_field(name='Description', value=cancelledevent['description'], inline=False)
                except KeyError:
                    pass
                webhook.add_embed(embed)
                webhook.execute()

                # This code is from when I was testing, it'll be removed at some point
                test = service.events().list(calendarId=calendarId).execute()
                print(test)
                
        return https_fn.Response("Request fulfilled.")