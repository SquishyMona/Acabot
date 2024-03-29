from firebase_functions import https_fn, options
from firebase_admin import initialize_app
from googleapiclient.discovery import build
from discord_webhook import DiscordWebhook, DiscordEmbed
from googleapiclient.errors import HttpError
from google.oauth2 import service_account
from googleapiclient.discovery import build
from dateutil import parser as dtparse
from dateutil import relativedelta
from pytz import timezone
import requests
import json
import dotenv
import os
import traceback

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

    # This section is used when a request with an 'incremental-sync' header
    # comes through. When this happens, we will perform a full sync in order
    # to get new sync tokens. This is needed since sync tokens will expire
    # if they are not used in a timley manner, so this ensures that we
    # always have an up-to-date token to use to fetch calendar changes
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

    # Read the headers of the request to grab the Resource ID, then use that to determine which webhook URL
    # and calendar ID to use
    if req.headers.get('x-goog-resource-id') == os.getenv('ACAPELLA_RESOURCEID'):
        calendarId = os.getenv('ACAPELLA_CAL_ID')
        webhookurl = os.getenv('ACAPELLA_WEBHOOK')
        token = 'acapella'
        guildID = os.getenv('ACAPELLA_GUILD_ID')
    if req.headers.get('x-goog-resource-id') == os.getenv('SLIH_REH_RESOURCEID'):
        calendarId = os.getenv('SLIH_REH_CAL_ID')
        webhookurl = os.getenv('SLIH_REH_WEBHOOK')
        token = 'slih_reh'
        guildID = os.getenv('SLIH_GUILD_ID')
    if req.headers.get('x-goog-resource-id') == os.getenv('SLIH_GIGS_RESOURCEID'):
        calendarId = os.getenv('SLIH_GIGS_CAL_ID')
        webhookurl = os.getenv('SLIH_GIGS_WEBHOOK')
        token = 'slih_gigs'
        guildID = os.getenv('SLIH_GUILD_ID')
    
    # In an event of a sync notification, we'll need to get sync tokens to use in our subsequent requests. 
    # Here, we save the sync token given to us by making an 'event list' request to the API. We'll then 
    # store it in a JSON file to use in our next request. The sync token is used to determine what has 
    # changed since the last request.
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
    
    # If the event is not a sync notification or an incremental sync, we'll assume that something has changed
    else:
        print("Changes detected.")
        with open('synctoken.json') as json_file:
            nextSyncToken = json.load(json_file)
        try:
            events_result = service.events().list(calendarId=calendarId, syncToken=nextSyncToken[token]).execute()

        # If we get a 410 error, our sync token has expired. In this case, we'll need to get a new sync token for each
        # calendar. Unfortunetly, this means that we won't get any recently changed events since the token expiration.
        # However, we have some methods in place to ensure that we always have a valid sync token, so this shouldn't
        # happen often
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

        # Next, we'll start getting each event that has changed.
        for event in events:
            # We'll start by constructing an event object for Discord. This allows us to also create a corresponding event in
            # Discord so that we can have both a GCal event and a Discord event. We'll also construct our Discord API URL to
            # send to, as well as some headers for our request.
            description = event.get('description')
            location = event.get('location')
            if location == None:
                location = ''
            try:
                discord_event_data = json.dumps({
                    "name": event['summary'],
                    "privacy_level": 2,
                    "scheduled_start_time": dtparse.parse(event['start']['dateTime']).isoformat().replace('+00:00', '+05:00'),
                    "scheduled_end_time": dtparse.parse(event['end']['dateTime']).isoformat().replace('+00:00', '+05:00'),
                    "description": description,
                    "channel_id": None,
                    "entity_metadata": {'location': location},
                    "entity_type": 3
                })
                
            except Exception:
                print(traceback.format_exc())
                pass
            discord_event_url = f'https://discord.com/api/v10/guilds/{guildID}/scheduled-events'
            discord_event_headers = {
                'Authorization': f'Bot {os.getenv("BOT_KEY")}',
                'User-Agent': f'DiscordBot (https://discord.com/api/oauth2/authorize?client_id={os.getenv("CLIENT_ID")}) Python/3.11 aiohttp/3.8.1',
                'Content-Type': 'application/json'
            }

            # If an event has 'confirmed' status, we need to check if it's a new event, or an existing event that's
            # been updated. To do this, we compare the times between event creation and the last time the event was
            # updated. There's about a second delay between when the event is created and when it says it was last updated.
            # To determine if the event is new or updated, we'll subtract 2 seconds from the event's last updated timestamp.
            # We then compare to see if the event creation time is less than the event updated time. If it isn't, the event
            # is new. We need this calculation for the purposes of creating and managing Discord scheduled events. If it is, 
            # the event already exists and has been updated. After all this, the notification will be sent to our Discord webhook
            if event['status'] == 'confirmed':
                dtdelta = dtparse.parse(event['updated'])
                dtdelta = dtdelta - relativedelta.relativedelta(seconds=+2)
                if dtparse.parse(event['created']) <= dtdelta:
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

                    try:
                        # If our event is an existing event that's been updated, we'll also update the scheduled event in our Discord server.
                        discord_event_modify = json.dumps({
                            "name": event['summary'],
                            "scheduled_start_time": dtparse.parse(event['start']['dateTime']).isoformat().replace('+00:00', '+05:00'),
                            "scheduled_end_time": dtparse.parse(event['end']['dateTime']).isoformat().replace('+00:00', '+05:00'),
                            "description": description,
                            "entity_metadata": {'location': location}
                        })
                        with open('activeevents.json', 'r') as file:
                            activeevents = json.load(file)
                            print(activeevents)
                        discord_event_req = requests.get(f'{discord_event_url}/{activeevents[event["id"]]}', headers=discord_event_headers)
                        discord_event = discord_event_req.json()
                        if discord_event['name'] == event['summary'] and dtparse.parse(discord_event['scheduled_start_time']) == dtparse.parse(event['start']['dateTime']).astimezone(timezone('UTC')) and dtparse.parse(discord_event['scheduled_end_time']) == dtparse.parse(event['end']['dateTime']).astimezone(timezone('UTC')) and discord_event['description'] == event['description'] and str(discord_event['entity_metadata']['location']) == str(event['location']):
                            return
                        discord_event_req = requests.patch(f'{discord_event_url}/{activeevents[event["id"]]}', headers=discord_event_headers, data=discord_event_modify)
                        print(discord_event_req.text)
                    except Exception as e:
                        print(traceback.format_exc())
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
                    try:
                        # If our event is a brand new event, we'll also create a new scheduled event is our Discord server.
                        # This will also check to see if the event already exists in our Discord server, in the case that
                        # the event was created in Discord. This will prevent duplicate events from being created, as well
                        # as preventing an infinite loop of events being created in both Google Calendar and Discord.
                        discord_events_list = requests.get(discord_event_url, headers=discord_event_headers)
                        # print(discord_events_list.text)

                        for discord_event in discord_events_list.json():
                            if discord_event['name'] == event['summary'] and dtparse.parse(discord_event['scheduled_start_time']) == dtparse.parse(event['start']['dateTime']).astimezone(timezone('UTC')) and dtparse.parse(discord_event['scheduled_end_time']) == dtparse.parse(event['end']['dateTime']).astimezone(timezone('UTC')):
                                with open('activeevents.json', 'r+') as file:
                                    activeevents = json.load(file)
                                    activeevents[event['id']] = discord_event['id']
                                    file.seek(0)
                                    json.dump(activeevents, file)
                                raise Exception("Event already exists in Discord server.")
                        discord_event_req:requests.Response = requests.post(discord_event_url, headers=discord_event_headers, data=discord_event_data)
                        discord_event_res = discord_event_req.json()
                        with open('activeevents.json', 'r+') as file:
                            activeevents = json.load(file)
                            activeevents[event['id']] = discord_event_res['id']
                            file.seek(0)
                            json.dump(activeevents, file)
                        print(discord_event_req.text)
                    except Exception as e:
                        print(traceback.format_exc())
                        return https_fn.Response("Request fulfilled.")
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
                
                try:
                    # If our event is cancelled, we'll also delete the scheduled event in our Discord server
                    discord_events_list = requests.get(discord_event_url, headers=discord_event_headers)
                    print(discord_events_list.text)
                    delete_event_id = None
                    for discord_event in discord_events_list.json():
                        if discord_event['name'] == cancelledevent['summary']:
                            delete_event_id = discord_event['id']
                    if delete_event_id is None:
                        raise Exception("No event found in Discord server.")
                    discord_event_req = requests.delete(f'{discord_event_url}/{delete_event_id}', headers=discord_event_headers)
                    with open('activeevents.json', 'r+') as file:
                        activeevents = json.load(file)
                        activeevents.remove(event['id'])
                        file.seek(0)
                        json.dump(activeevents, file)
                    print(discord_event_req.text)
                except Exception as e:
                    print(traceback.format_exc())

                # This code is from when I was testing, it'll be removed at some point
                test = service.events().list(calendarId=calendarId).execute()
                print(test)
                
        return https_fn.Response("Request fulfilled.")