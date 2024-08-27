import os

os.system("pip uninstall --yes discord.py py-cord")
os.system("pip install --no-input py-cord")

import discord.bot
import discord
import logging
import wavelink
import json
import traceback
from dotenv import load_dotenv

from gapifunctions import *
from discord import SlashCommandGroup
from discord.commands import Option
from discord.ext import commands
from discord.ext import tasks
from google.oauth2 import service_account
from dateutil.parser import parse as dtparse
from pytz import timezone

# Defining some globals. Service account file should be located in the same directory as this file.
# Guild IDs can be changed to fit your guilds.
SCOPES = ['https://www.googleapis.com/auth/calendar']
SERVICE_ACCOUNT_FILE = 'acabot-398317-b2293b5c6d43.json'
GUILD_IDS = [1148389231484489860, 608476415825936394, 1118643846688030730, 1199791925046296686]

# Loads enviornment variables, which contains our bot token needed to run the bot
load_dotenv()

# Creation of our bot object, as well as defining some new objects.
bot = discord.Bot()

# This object holds the id's for all active polls, and a list of each user who has voted in that poll.
# This is used to prevent users from voting more than once on a single poll.
activepolls = {}

# This object holds the id's for all servers that have a conflicts list and the channel id for that list.
# This object is saved to and loads from "conflictchannels.json" to persist data across bot restarts.
conflictlists = {}

# This object holds a list of all conflict events seperated by guild id. This object is saved to and loaded
# from "conflicts.json" to persist data across bot restarts.
activeconflicts = {}

# This object holds the queue of music when using music commands
musicqueue = wavelink.Queue()

# This object holds the credentials for our service account, which is used by the Google APIs
credentials = service_account.Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)

# This object holds events that have already been seen by the bot, so that we don't send duplicate messages
# for the same event.
seen_events = []

# This function is used to get the ID of the calendar we're using for a specific guild.
def getCalID(ctx, calendar=''):
    if(ctx.guild.id == 1148389231484489860 or ctx.guild.id == 608476415825936394):
        return os.getenv('ACAPELLA_CAL_ID')
    else:
        if ctx.guild.id == 1118643846688030730:
            if calendar == "rehearsals":
                return os.getenv('SLIH_REH_CAL_ID')
            else:
                return os.getenv('SLIH_GIGS_CAL_ID')

# This function connects our bot to Lavalink servers for music playback 
async def connect_nodes(self):
    await bot.wait_until_ready()
    nodes = [wavelink.Node(uri='lava-v4.sirplancake.dev:2333', password="KBjV?Cs>#B!>pcEZa?yc1%Vy")]
    await wavelink.Pool.connect(nodes=nodes, client=self.bot, cache_capacity=100)

@bot.event
async def on_ready():
    bot.add_view(PollView())
    bot.add_view(ConflictView())
    print(f'{bot.user} is online and ready')
    #await connect_nodes()
    incremental_sync.start()
    get_upcoming.start()
    startwebhooks.start()
    print('Loading active conflicts')
    try:
        with open('conflicts.json', 'r') as file:
            global activeconflicts
            activeconflicts = json.load(file)
            print('Active conflicts loaded')
    except Exception as e:
        print('No active conflicts found')
        print(e.with_traceback())
    print('Loading conflict channels')
    try:
        with open('conflictchannels.json', 'r') as file:
            global conflictlists
            conflictlists = json.load(file)
            print('Conflict channels loaded')
    except Exception as e:
        print('No conflict channels found')
        print(e.with_traceback())

@bot.event
async def on_wavelink_node_ready(node: wavelink.Node):
    print(f"Wavelink node {node.id} ready.")  

# When a new scheduled event is created on Discord, we will also create a new event
# on the Google Calendar.
@bot.event
async def on_scheduled_event_create(event: discord.ScheduledEvent): 
    calid = None
    eventid = event.id
    match event.guild.id:
        case 1148389231484489860:
            calid = os.getenv('ACAPELLA_CAL_ID')
        case 608476415825936394:
            calid = os.getenv('ACAPELLA_CAL_ID')
        case 1118643846688030730:
            calid = os.getenv('SLIH_GIGS_CAL_ID')
        case _:
            print('Guild not found')
            return
    event = {
        'summary': event.name, 
        'description': event.description,
        'location': str(event.location),
        'start': {
            'dateTime': f'{event.start_time.isoformat()}',
            'timeZone': 'America/New_York'
        },
        'end': {
            'dateTime': f'{event.end_time.isoformat()}',
            'timeZone': 'America/New_York'
        }
    }

    existing_events = calapi_getevents(calid)
    for gcalevent in existing_events:
        description = gcalevent.get('description')
        location = gcalevent.get('location')
        if location == None:
            location = ''
        try:
            duplicate = {
                'summary': gcalevent['summary'],
                'description': description,
                'location': location,
                'start': {
                    'dateTime': str(dtparse(gcalevent['start'].get('dateTime')).astimezone(timezone('UTC')).strftime("%Y-%m-%dT%H:%M:%S+00:00")),
                    'timeZone': gcalevent['start'].get('timeZone')
                },
                'end': {
                    'dateTime': str(dtparse(gcalevent['end'].get('dateTime')).astimezone(timezone('UTC')).strftime("%Y-%m-%dT%H:%M:%S+00:00")),
                    'timeZone': gcalevent['end'].get('timeZone')
                }
            }
            if event == duplicate:
                with open('activeevents.json', 'r+') as file:
                    activeevents = json.load(file)
                    activeevents[eventid] = gcalevent['id']
                    file.seek(0)
                    json.dump(activeevents, file)
                return
        except Exception as e:
            print(e)
            pass
        
    link = calapi_createevent(event, calid)
    with open('activeevents.json', 'r+') as file:
        activeevents = json.load(file)
        activeevents[eventid] = link['id']
        file.seek(0)
        json.dump(activeevents, file)

# When a scheduled event is updated, we will also update the event on the Google Calendar.
@bot.event
async def on_scheduled_event_update(old, event: discord.ScheduledEvent):
    service = build('calendar', 'v3', credentials=credentials)
    eventid = event.id
    calid = None
    match event.guild.id:
        case 1148389231484489860:
            calid = os.getenv('ACAPELLA_CAL_ID')
        case 608476415825936394:
            calid = os.getenv('ACAPELLA_CAL_ID')
        case 1118643846688030730:
            calid = os.getenv('SLIH_GIGS_CAL_ID')
        case _:
            print('Guild not found')
            return
    
    description = event.description
    if description == None:
        description = ''
    event = {
        'summary': event.name, 
        'description': description,
        'location': str(event.location),
        'start': {
            'dateTime': f'{event.start_time.isoformat()}',
            'timeZone': 'America/New_York'
        },
        'end': {
            'dateTime': f'{event.end_time.isoformat()}',
            'timeZone': 'America/New_York'
        }
    }

    with open('activeevents.json', 'r') as file:
        activeevents = json.load(file)
        modify_event = service.events().get(calendarId=calid, eventId=activeevents[str(eventid)]).execute()
        modify_desc = modify_event.get('description')
        if modify_desc == None:
            modify_desc = ''
        modify_location = modify_event.get('location')
        if modify_location == None:
            modify_location = ''
        duplicate = {
                'summary': modify_event['summary'],
                'description': modify_desc,
                'location': modify_location,
                'start': {
                    'dateTime': str(dtparse(modify_event['start'].get('dateTime')).astimezone(timezone('UTC')).strftime("%Y-%m-%dT%H:%M:%S+00:00")),
                    'timeZone': modify_event['start'].get('timeZone')
                },
                'end': {
                    'dateTime': str(dtparse(modify_event['end'].get('dateTime')).astimezone(timezone('UTC')).strftime("%Y-%m-%dT%H:%M:%S+00:00")),
                    'timeZone': modify_event['end'].get('timeZone')
                }
            }
        if duplicate == event:
            return
        else:
            updated = service.events().update(calendarId=calid, eventId=activeevents[str(eventid)], body=event).execute()
            print("Event updated: " + updated['id'])

# When a scheduled event is deleted, we will also delete the event on the Google Calendar.
@bot.event
async def on_scheduled_event_delete(event: discord.ScheduledEvent):
    calid = None
    eventid = event.id
    match event.guild.id:
        case 1148389231484489860:
            calid = os.getenv('ACAPELLA_CAL_ID')
        case 608476415825936394:
            calid = os.getenv('ACAPELLA_CAL_ID')
        case 1118643846688030730:
            calid = os.getenv('SLIH_GIGS_CAL_ID')
        case _:
            print('Guild not found')
            return
    try:
        with open('activeevents.json', 'r+') as file:
            activeevents = json.load(file)
            service = build('calendar', 'v3', credentials=credentials)
            service.events().delete(calendarId=calid, eventId=activeevents[str(eventid)]).execute()
            activeevents.pop(eventid)
            file.seek(0)
            json.dump(activeevents, file)
    except Exception as e:
        print(e)
            

@tasks.loop(hours=167)
async def startwebhooks():
    await bot.wait_until_ready()
    print('\n---------------\nStarting task: startwebhooks()...')
    calapi_startwebhooks()
    print('Task completed: startwebhooks()\n---------------\n')

@tasks.loop(minutes=5)
async def incremental_sync():
    await bot.wait_until_ready()
    print ('\n---------------\nStarting task: incremental_sync()...')
    calapi_incrementalsync()
    print('Task completed: incremental_sync()\n---------------\n')

@tasks.loop(minutes=1)
async def get_upcoming():
    await bot.wait_until_ready()
    print ('\n---------------\nStarting task: get_upcoming()...')
    events = calapi_getupcoming()
    if events == None:
        print('Task completed: get_upcoming(). Result: There are no events coming up.\n---------------\n')
        return
    else:
        print('get_upcoming(): Events found.')
        for event in events:
            if event['id'] in seen_events:
                print(f'get_upcoming(): Event {event["id"]} already seen. Skipping...')
                continue
            else:
                print(f'get_upcoming(): Event {event["id"]} not seen. Sending notification...')
                seen_events.append(event['id'])
                print(f'get_upcoming(): Event {event["id"]} added to seen_events')
                channel = bot.get_channel(1148414047704850432)
                embed = discord.Embed(title=event['summary'], color=discord.Colour.dark_magenta())
                start = event['start'].get('dateTime')
                if start == None:
                    print(f'get_upcoming(): Event {event["id"]} is a full day event. Setting date only...')
                    start = event['start'].get('date')
                    embed.description = datetime.datetime.strftime(dtparse(start), format='%B %d, %Y')
                    embed.add_field(name="Time", value="TBD", inline=True)
                else:
                    print(f'get_upcoming(): Event {event["id"]} is a timed event. Setting date and time...')
                    tmfmt = '%B %d, %Y'
                    sdate = datetime.datetime.strftime(dtparse(start), format=tmfmt)
                    embed.description = sdate
                    stime= datetime.datetime.strftime(dtparse(start), format='%I:%M %p')
                    etime = datetime.datetime.strftime(dtparse(event['end'].get('dateTime')), format='%I:%M %p')
                    embed.add_field(name="Start Time", value=stime, inline=True)
                    embed.add_field(name="End Time", value=etime, inline=True)
                try:
                    embed.add_field(name="Location", value=event['location'], inline=False)
                except:
                    print(f'get_upcoming(): Event {event["id"]} has no location. Skipping...')
                    pass
                try:
                    embed.add_field(name="Description", value=event['description'], inline=False)
                except:
                    print(f'get_upcoming(): Event {event["id"]} has no description. Skipping...')
                    pass
                embed.add_field(name="More Details", value=f"[View in Google Calendar]({event.get('htmlLink')})", inline=False)
                try:
                    message = await channel.send('An event is coming up! See details below.', embed=embed)
                    if channel.type == discord.ChannelType.news:
                        await message.publish()
                    print(f'get_upcoming(): Message sent for event {event["id"]}')
                except Exception as e:
                    print(f'get_upcoming(): An error occurred while sending the message. Error: {e}')
                    pass
    print('Task completed: get_upcoming()\n---------------\n')

@bot.slash_command(name="ping", description="Simple command to test if the bot is responsive", guild_ids=GUILD_IDS)
async def ping(ctx):
    await ctx.respond("Pong!", ephemeral=True)

@bot.slash_command(name="help", description="Get help with the bot", guild_ids=GUILD_IDS)
async def help(ctx):
    embed = discord.Embed(
        title="Acabot Guide", 
        color=discord.Colour.dark_magenta(), 
        description="Welcome to Acabot, a bot made to assist you in all you acapella needs! See below for a list of commands and their descriptions."
    )
    embed.set_author(name="Acabot", icon_url='https://cdn.discordapp.com/avatars/1148739423001915423/a55dd65701d1cb0a0903be088c681390?size=1024')
    embed.add_field(name="/calendar", 
                    value="Commands in this group are used to interact with Google Calendar. Type '/calendar' for a full list of what you can do. Some commands take a 'calendar' as an option, but if your server is only handling one calendar (like the Fredonia Acapella server), you can leave this blank.", 
                    inline=False)
    embed.add_field(name="/music",
                    value="Commands in this group are used to interact with the music player, which will pull from YouTube, with support for Google Drive audio files hopefully coming soon! Type '/music' for a full list of what you can do. (You have to be in a voice channel for these commands to work)",
                    inline=False)
    embed.add_field(name="/music queue",
                    value="Commands in this subgroup are used to interact with the music queue, if music is playing. Type '/music queue' for a full list of what you can do. (You have to be in a voice channel for these commands to work)",
                    inline=False)
    embed.add_field(name="/poll",
                    value="This command is used to create a poll for others to vote on. You can have up to 6 options in one poll. The poll will close after the time you specify, in hours, or if left blank, 24 hours after no one has interacted with the poll. You can only vote once per poll and cannot change your vote! (This may change in the future, stay tuned!).",
                    inline=False)
    embed.add_field(name="/ping",
                    value="This command is used to test if the bot is responsive. If the bot seems slow or unresponsive, try this commands to see if it's just you or the bot.",
                    inline=False)
    embed.set_footer(text="If you have any questions or feature suggestions, feel free to contact Ian (@squishymona on Discord)!")
    await ctx.respond(embed=embed, ephemeral=True)

# Calendar commands
calendar = SlashCommandGroup("calendar", "Commands used to interact with Google Calendar")

async def autocomp_calendars(ctx: discord.AutocompleteContext):
    if ctx.interaction.guild.id == 1118643846688030730:
        return ["rehearsals", "gigs"]

@calendar.command(name="list", description="List the next 10 events on the calendar", guild_ids=GUILD_IDS)
@commands.has_permissions(manage_channels=True)
async def list(ctx, 
               calendar: Option(str, description="The calendar you're listing. (Acapella community server can leave blank)", autocomplete=discord.utils.basic_autocomplete(autocomp_calendars), required=False),
               hide_response: Option(bool, description="If true, only you will be able to see the bot's response. Set to False if left blank", required=False)):
    calid = getCalID(ctx, calendar)
    eventslist = calapi_getevents(calid)
    if eventslist == None:
        await ctx.respond("There are no upcoming events!", ephemeral=hide_response)
        return
    print("/calendar list: Events have been found.")
    embed = discord.Embed(title="Upcoming Events", color=discord.Colour.dark_magenta(), description="Here's whats coming up:")
    for event in eventslist:
        start = event['start'].get('dateTime')
        tmfmt = '%B %d, %Y at %I:%M %p'
        try:
            stime = datetime.datetime.strftime(dtparse(start), format=tmfmt)
        except:
            stime = datetime.datetime.strftime(dtparse(event['start'].get('date')), format='%B %d, %Y')
        embedValue = f'{stime}'
        if "youtube.com" in str(event.get('description')):
            split = str(event.get('description')).split(' ')
            for item in split:
                if "youtube.com" in item:
                    embedValue = f'{stime} \n [Watch on YouTube]({item})'
        embed.add_field(name=event['summary'], value=embedValue, inline=False)
    
    await ctx.respond(embed=embed, ephemeral=hide_response)

async def autocomp_getevent(ctx: discord.AutocompleteContext):
    calid = getCalID(ctx.interaction, calendar)
    eventslist = calapi_getevents(calid)
    if eventslist == None:
        return
    else:
        eventnames = []
        for event in eventslist:
            eventnames.append(event['summary'])
        return eventnames
    
@calendar.command(name="getevent", description="Get the details of a specific event", guild_ids=GUILD_IDS)
@commands.has_permissions(manage_channels=True)
async def getevent(ctx, 
                   eventname: Option(str, description="Name of the event you want to get details for", autocomplete=discord.utils.basic_autocomplete(autocomp_getevent)),
                   calendar: Option(str, description="The calendar you're adding to. (Acapella community server can leave blank)", autocomplete=discord.utils.basic_autocomplete(autocomp_calendars), required=False),
                   hide_response: Option(bool, description="If true, only you will be able to see the bot's response. Set to False if left blank", required=False)):
    calid = getCalID(ctx, calendar)
    event = calapi_gcalgetevent(eventname, calid)
    if event == None:
        await ctx.respond("That event does not exist!")
    else:
        embed = discord.Embed(title=event['summary'], color=discord.Colour.dark_magenta())
        start = event['start'].get('dateTime')
        if start == None:
            start = event['start'].get('date')
            embed.description = datetime.datetime.strftime(dtparse(start), format='%B %d, %Y')
            embed.add_field(name="Time", value="TBD", inline=True)
        else:
            tmfmt = '%B %d, %Y'
            sdate = datetime.datetime.strftime(dtparse(start), format=tmfmt)
            embed.description = sdate
            stime= datetime.datetime.strftime(dtparse(start), format='%I:%M %p')
            etime = datetime.datetime.strftime(dtparse(event['end'].get('dateTime')), format='%I:%M %p')
            embed.add_field(name="Start Time", value=stime, inline=True)
            embed.add_field(name="End Time", value=etime, inline=True)
        try:
            embed.add_field(name="Location", value=event['location'], inline=False)
        except:
            pass
        try:
            embed.add_field(name="Description", value=event['description'], inline=False)
        except:
            pass
        embed.add_field(name="More Details", value=f"[View in Google Calendar]({event.get('htmlLink')})", inline=False)
        await ctx.respond(embed=embed, ephemeral=hide_response)

@calendar.command(name="create", description="Create a new event on the calendar", guild_ids=GUILD_IDS)
@commands.has_permissions(manage_channels=True)
async def list(ctx, 
               name: Option(str, description="Name of your event"), 
               date: Option(str, description="Date of your event (Format as MM/DD/YY)"), 
               starttime: Option(str, description="Start time of your event (Format as HH:MM PM/AM)"),
               endtime: Option(str, description="End time of your event (Optional, if blank, end time will be one hour after the start time)", required=False),
               location: Option(str, description="Location of your event (Optional)", required=False),
               description: Option(str, description="Description of your event (Optional)", required=False),
               calendar: Option(str, description="The calendar you're adding to. (Acapella community server can leave blank)", autocomplete=discord.utils.basic_autocomplete(autocomp_calendars), required=False)):
    calid = getCalID(ctx, calendar)
    dtformatted = f'{date} {starttime}'
    dtformatted = dtparse(dtformatted)
    if endtime:
        dtformattedend = f'{date} {endtime}'
        dtformattedend = dtparse(dtformattedend)
    else:
        dtformattedend = dtformatted.replace(hour=dtformatted.hour + 1)
#    conflicts = findconflicts(dtformatted.isoformat(), dtformattedend.isoformat(), calid)
#    if conflicts:
#        await ctx.respond("There is a conflict with this event! Please check the calendar and try again.")
#        return
    dtformattedend = dtformattedend.strftime("%Y-%m-%dT%H:%M:%S")
    dtformatted = dtformatted.strftime("%Y-%m-%dT%H:%M:%S")
    event = {
        'summary': name, 
        'description': description,
        'location': location,
        'start': {
            'dateTime': f'{dtformatted}',
            'timeZone': 'America/New_York'
        },
        'end': {
            'dateTime': f'{dtformattedend}',
            'timeZone': 'America/New_York'
        }
        }
            
    link = calapi_createevent(event, calid)
    await ctx.respond("Your event has been created! You can find it at " + link.get('htmlLink'), ephemeral=True)

# Music Commands
music = SlashCommandGroup("music", "Commands used to interact with the music player", guild_ids=GUILD_IDS)

@music.command(name="play", description="Play a song or playlist", guild_ids=GUILD_IDS)
async def play(ctx, name: str):
    try:
        if not ctx.voice_client:
            vc: wavelink.Player = await ctx.author.voice.channel.connect(cls=wavelink.Player)
        else:
            vc: wavelink.Player = ctx.voice_client
        
        if ctx.author.voice.channel.id != vc.channel.id:
            await ctx.respond("You must be in the same voice channel as the bot to use music commands!", ephemeral=True)
            return
        
        song = await wavelink.Playable.search(name)

        if not song:
            await ctx.respond("No songs found with that name.", ephemeral=True)
            return
        if vc.current == None:
            await vc.play(song[0])
            await ctx.respond(f"Now playing {song[0].title}!")
        else:
            await ctx.respond(f"Added {song[0].title} to the queue!")
            musicqueue.put(song[0])
    except Exception as e:
        await ctx.respond(f"Something went wrong! You can always try manually adding a song!", ephemeral=True)
        print(e)

@music.command(name="pause", description="Pause the current song", guild_ids=GUILD_IDS)
async def pause(ctx):
    try:
        if not ctx.voice_client:
            await ctx.respond("You must be in a voice channel to use music commands!", ephemeral=True)
            return
        
        if ctx.author.voice.channel.id != ctx.voice_client.channel.id:
            await ctx.respond("You must be in the same voice channel as the bot to use music commands!", ephemeral=True)
            return
        
        await ctx.voice_client.pause()
        await ctx.respond("Music paused!")
    except Exception as e:
        await ctx.respond(f"Something went wrong!", ephemeral=True)
        print(e)

@music.command(name="resume", description="Resume the current song", guild_ids=GUILD_IDS)
async def resume(ctx):
    try:
        if not ctx.voice_client:
            await ctx.respond("You must be in a voice channel to use music commands!", ephemeral=True)
            return
        
        if ctx.author.voice.channel.id != ctx.voice_client.channel.id:
            await ctx.respond("You must be in the same voice channel as the bot to use music commands!", ephemeral=True)
            return
        
        await ctx.voice_client.resume()
        await ctx.respond("Music resumed!")
    except Exception as e:
        await ctx.respond(f"Something went wrong!", ephemeral=True)
        print(e)

@music.command(name="stop", description="Stop the current song", guild_ids=GUILD_IDS)
async def stop(ctx):
    try:
        if not ctx.voice_client:
            await ctx.respond("You must be in a voice channel to use music commands!", ephemeral=True)
            return
        
        if ctx.author.voice.channel.id != ctx.voice_client.channel.id:
            await ctx.respond("You must be in the same voice channel as the bot to use music commands!", ephemeral=True)
            return
        
        await ctx.voice_client.stop()
        await ctx.respond("Music stopped!")
    except Exception as e:
        await ctx.respond(f"Something went wrong!", ephemeral=True)
        print(e)

class MusicSkip():
    async def on_timeout(self):
        self.disable_all_items()
        await self.message.edit(embed=self.message.embeds[0].add_field(name="Not enough votes to skip!", inline=False))
    
    @discord.ui.button(label="Skip", style=discord.ButtonStyle.blurple)
    async def skip(self, button: discord.ui.Button, interaction: discord.Interaction):
        button = self.get_item(interaction.data['custom_id'])
        if interaction.user.id in activepolls[self.id]:
            await interaction.response.send_message("You have already voted to skip!", ephemeral=True)
            return
        await self.message.edit(embed=self.message.embeds[0].set_field_at(0, name="Votes to skip", value=str(int(self.message.embeds[0].fields[0].value) + 1), inline=True))
        if int(self.message.embeds[0].fields[0].value) >= len(self.message.guild.voice_client.channel.members) - 1:
            await self.message.guild.voice_client.stop()
            await self.message.edit(embed=self.message.embeds[0].add_field(name="The vote has ended!", value="The song has been skipped!", inline=False))
            return
        await interaction.response.send_message("You have voted to skip", ephemeral=True)
        activepolls[self.id].append(interaction.user.id)

@music.command(name="skip", description="Skip the current song", guild_ids=GUILD_IDS)
async def skip(ctx):
    try:
        if not ctx.voice_client:
            await ctx.respond("You must be in a voice channel to use music commands!", ephemeral=True)
            return
        if ctx.author.voice.channel.id != ctx.voice_client.channel.id:
            await ctx.respond("You must be in the same voice channel as the bot to use music commands!", ephemeral=True)
            return
        
        if len(ctx.voice_client.channel.members) == 2:
            await ctx.voice_client.stop()
            await ctx.voice_client.play(musicqueue.get())
            await ctx.respond("Music skipped!")
            return
        else:
            view = MusicSkip()
            embed = discord.Embed(title=f"Vote to skip{ctx.voice_client.source.track.title}", color=discord.Colour.dark_magenta(), description="Click the button to vote to skip!")
            activepolls.update({view.id: []})
            view.disable_on_timeout = True
            view.timeout = 60
            view.children[0].label = "Votes to skip"
            embed.add_field(name="Votes to skip", value="0", inline=True)
            await ctx.respond(embed=embed, view=view)
    except Exception as e:
        await ctx.respond(f"Something went wrong!", ephemeral=True)
        print(e)

# Music queue commands
queue = music.create_subgroup(name="queue", description="Commands used to interact with the queue")

@queue.command(name="view", description="View the current queue", guild_ids=GUILD_IDS)
async def view(ctx):
    try:
        if not ctx.voice_client:
            await ctx.respond("You must be in a voice channel to use music commands!", ephemeral=True)
            return
        if ctx.author.voice.channel.id != ctx.voice_client.channel.id:
            await ctx.respond("You must be in the same voice channel as the bot to use music commands!", ephemeral=True)
            return
        if musicqueue.is_empty:
            await ctx.respond("The queue is empty!")
            return
        else:
            embed = discord.Embed(title="Music Queue", color=discord.Colour.dark_magenta(), description="Here's whats coming up:")
            for i in range(len(musicqueue)):
                embed.add_field(name=f"#{i + 1}", value=musicqueue[i].title, inline=False)
            await ctx.respond(embed=embed)
    except Exception as e:
        await ctx.respond(f"Something went wrong!", ephemeral=True)
        print(e)

@queue.command(name="clear", description="Clear the current queue", guild_ids=GUILD_IDS)
async def clear(ctx):
    try:
        if not ctx.voice_client:
            await ctx.respond("You must be in a voice channel to use music commands!", ephemeral=True)
            return
        if ctx.author.voice.channel.id != ctx.voice_client.channel.id:
            await ctx.respond("You must be in the same voice channel as the bot to use music commands!", ephemeral=True)
            return
        if musicqueue.is_empty:
            await ctx.respond("The queue is already empty!")
            return
        else:
            musicqueue.clear()
            await ctx.respond("The queue has been cleared!")
            
    except Exception as e:
        await ctx.respond(f"Something went wrong!", ephemeral=True)
        print(e)

@queue.command(name="remove", description="Remove a song from the queue", guild_ids=GUILD_IDS)
async def remove(ctx, index: int):
    index = index - 1
    try:
        if not ctx.voice_client:
            await ctx.respond("You must be in a voice channel to use music commands!", ephemeral=True)
            return
        if ctx.author.voice.channel.id != ctx.voice_client.channel.id:
            await ctx.respond("You must be in the same voice channel as the bot to use music commands!", ephemeral=True)
            return
        if musicqueue.is_empty:
            await ctx.respond("The queue is empty!")
            return
        else:
            if index > len(musicqueue):
                await ctx.respond("That song isn't in the queue!")
                return
            else:
                musicqueue.remove(index)
                await ctx.respond(f"Song #{index + 1} has been removed from the queue!")
    except Exception as e:
        await ctx.respond(f"Something went wrong!", ephemeral=True)
        print(e)

@bot.slash_command(name="create_plan", description="Create a new channel with the groups of your choosing!", guild_ids=[1148389231484489860, 608476415825936394])
@commands.has_permissions(manage_channels=True)
async def create_plan(ctx, 
                      name: str, 
                      group1: Option(discord.Role, required=True),
                      group2: Option(discord.Role, required=True),
                      group3: Option(discord.Role, required=False),
                      group4: Option(discord.Role, required=False),
                      group5: Option(discord.Role, required=False),
                      group6: Option(discord.Role, required=False)):
    try:
        guild = ctx.guild
        channel = await guild.create_text_channel(name)
        if guild.id == 1148389231484489860:
            await channel.edit(category=guild.get_channel(1149705404394254517))
        await channel.set_permissions(guild.default_role, read_messages=False, send_messages=False)
        await channel.set_permissions(group1, read_messages=True, send_messages=True)
        await channel.set_permissions(group2, read_messages=True, send_messages=True)
        if group3:
            await channel.set_permissions(group3, read_messages=True, send_messages=True)
        if group4:
            await channel.set_permissions(group4, read_messages=True, send_messages=True)
        if group5:
            await channel.set_permissions(group5, read_messages=True, send_messages=True)
        if group6:
            await channel.set_permissions(group6, read_messages=True, send_messages=True)
        await ctx.respond(f"Channel created successfully! You can your group(s) can find it at {channel.mention}", ephemeral=True)
    except Exception as e:
        await ctx.respond(f"Something went wrong! You can always try manually creating a channel!", ephemeral=True)
        print(e)
    
class PollView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def on_timeout(self):
        self.disable_all_items()
        results = []
        results.append(int(self.message.embeds[0].fields[0].value))
        results.append(int(self.message.embeds[0].fields[1].value))
        if len(self.children) > 2:
            for i in range(2, len(self.children)):
                results.append(int(self.message.embeds[0].fields[i].value))
        winner = self.children[results.index(max(results))].label
        await self.message.edit(embed=self.message.embeds[0].add_field(name="This poll has ended!", value=f"The winner is **{winner}**!", inline=False))

    @discord.ui.button(label="Option 1", custom_id="opt1", style=discord.ButtonStyle.blurple)
    async def option1(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.defer()
        editembed = self.message.embeds[0]
        button = self.get_item(interaction.data['custom_id'])
        if interaction.user.id in activepolls[self.id].keys():
            oldchoice = self.get_item(activepolls[self.id][interaction.user.id])
            oldindex = self.children.index(oldchoice)
            await self.message.edit(embed=editembed.set_field_at(
                oldindex,
                name=editembed.fields[oldindex].name,
                value=str(int(editembed.fields[oldindex].value) - 1), 
                inline=True))
        await self.message.edit(embed=self.message.embeds[0].set_field_at(
            self.children.index(button),
            name=button.label,
            value=str(int(self.message.embeds[0].fields[self.children.index(button)].value) + 1), 
            inline=True))
        await interaction.followup.send("Your vote has been recorded, thanks for responding!", ephemeral=True)
        activepolls[self.id][interaction.user.id] = button.custom_id

    @discord.ui.button(label="Option 2", custom_id="opt2", style=discord.ButtonStyle.blurple)
    async def option2(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.defer()
        editembed = self.message.embeds[0]
        if interaction.user.id in activepolls[self.id].keys():
            oldchoice = self.get_item(activepolls[self.id][interaction.user.id])
            oldindex = self.children.index(oldchoice)
            await self.message.edit(embed=editembed.set_field_at(
                oldindex,
                name=editembed.fields[oldindex].name,
                value=str(int(editembed.fields[oldindex].value) - 1), 
                inline=True))
        await self.message.edit(embed=editembed.set_field_at(
            1, 
            name=editembed.fields[1].name, 
            value=str(int(self.message.embeds[0].fields[1].value) + 1), 
            inline=True))
        await interaction.followup.send("Your vote has been recorded, thanks for responding!", ephemeral=True)
        activepolls[self.id][interaction.user.id] = button.custom_id

@bot.slash_command(name="poll", description="Create a poll with the given question and options", guild_ids=GUILD_IDS)
async def poll(ctx: commands.Context, 
               question: str, 
               option1: str, 
               option2: str, 
               option3: Option(str, required=False), 
               option4: Option(str, required=False), 
               option5: Option(str, required=False), 
               option6: Option(str, required=False)):
    try:
        view = PollView()
        embed = discord.Embed(title=question, color=discord.Colour.dark_magenta(), description="Click a button to vote!")
        activepolls.update({view.id: {}})
        view.disable_on_timeout = True
        view.children[0].label = option1
        view.children[1].label = option2
        embed.add_field(name=option1, value="0", inline=True)
        embed.add_field(name=option2, value="0", inline=True)
        if option3:
            view.add_item(discord.ui.Button(label=option3, custom_id="opt3", style=discord.ButtonStyle.blurple))
            view.children[2].callback = view.children[0].callback
            embed.add_field(name=option3, value="0", inline=True)
        if option4:
            view.add_item(discord.ui.Button(label=option4, custom_id="opt4", style=discord.ButtonStyle.blurple))
            view.children[3].callback = view.children[0].callback
            embed.add_field(name=option4, value="0", inline=True)
        if option5:
            view.add_item(discord.ui.Button(label=option5, custom_id="opt5", style=discord.ButtonStyle.blurple))
            view.children[4].callback = view.children[0].callback
            embed.add_field(name=option5, value="0", inline=True)
        if option6:
            view.add_item(discord.ui.Button(label=option6, custom_id="opt6", style=discord.ButtonStyle.blurple))
            view.children[5].callback = view.children[0].callback
            embed.add_field(name=option6, value="0", inline=True)
        #await ctx.respond(embed=embed, view=view)
        if ctx.guild.id == 1118643846688030730:
            await ctx.channel.send("Please fill out the following poll @everyone", embed=embed, view=view)
        else:
            await ctx.channel.send(embed=embed, view=view)
        await ctx.respond("Your poll has been created!", ephemeral=True)
    except Exception as e:
        await ctx.respond(f"Something went wrong! You can always try manually creating a poll!")
        print(e)

conflicts = SlashCommandGroup("conflicts", "Commands used to interact with the conflict checker", guild_ids=GUILD_IDS)

@conflicts.command(name="channel", description="Set the channel to send conflict notifications to", guild_ids=GUILD_IDS)
@commands.has_permissions(manage_channels=True)
async def conflictchannel(ctx: commands.Context, 
                          channel: Option(discord.TextChannel, description="The channel you want to send conflict notifications to")):
    conflictlists[ctx.guild.id] = channel.id
    with open("conflictchannels.json", "r+") as f:
        f.seek(0)
        json.dump(conflictlists, f, indent=4)
    await channel.send(f'''Attention: This server has set up conflict event notifications in this channel! Please check here frequently for updates on events that may conflict with the group's schedule.\nIf you see an event that you may have to attend, please let everyone know by clicking the "I'm Going To This!" button. This will help us to better plan gigs and shows around everyone's schedule.\n\n@everyone''')
    await ctx.respond(f"Conflict notifications will now be sent to {channel.mention}", ephemeral=True)

class ConflictView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def on_timeout(self):
        self.disable_all_items()
        await self.message.delete()

    @discord.ui.button(label="I'm Going To This!", custom_id="goingbtn", style=discord.ButtonStyle.blurple)
    async def going(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.defer()
        messageid = str(interaction.message.id)
        conflictindex = 0
        for event in activeconflicts[str(interaction.guild_id)]:
            if str(event['id']) == messageid:
                break
            conflictindex += 1
        if interaction.user.id in activeconflicts[str(interaction.guild_id)][conflictindex]['going']:
            activeconflicts[str(interaction.guild_id)][conflictindex]['going'].remove(interaction.user.id)
            goingstr = ""
            for member in activeconflicts[str(interaction.guild_id)][conflictindex]['going']:
                goingstr += f"<@{member}>\n"
            await self.message.edit(embed=self.message.embeds[0].set_field_at(3, name="People Going", value=goingstr, inline=False))
            await interaction.followup.send(f'''You've unmarked yourself as going to this event!''', ephemeral=True)
            with open("conflicts.json", "r+") as f:
                f.seek(0)
                json.dump(activeconflicts, f, indent=4)
            return
        else:
            activeconflicts[str(interaction.guild_id)][conflictindex]['going'].append(interaction.user.id)
            goingstr = ""
            for member in activeconflicts[str(interaction.guild_id)][conflictindex]['going']:
                goingstr += f"<@{member}>\n"
            await self.message.edit(embed=self.message.embeds[0].set_field_at(3, name="People Going", value=goingstr, inline=False))
            await interaction.followup.send(f'''Thank you for letting us know! If this was a mistake, click the "I'm Going To This" button again!''', ephemeral=True)
            with open("conflicts.json", "r+") as f:
                f.seek(0)
                json.dump(activeconflicts, f, indent=4)
            return
        
class ConflictModal(discord.ui.Modal):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        self.add_item(discord.ui.InputText(label="Event Name", placeholder="Title of the event you're adding", required=True, style=discord.InputTextStyle.short))
        self.add_item(discord.ui.InputText(label="Description", placeholder="What is this event for?", required=False, style=discord.InputTextStyle.long))
        self.add_item(discord.ui.InputText(label="Date", placeholder="The date of the event", required=True, style=discord.InputTextStyle.short))
        self.add_item(discord.ui.InputText(label="Start Time", placeholder="What time the event starts (Optional) (Ex: 11:00PM)", required=False, style=discord.InputTextStyle.short))
        self.add_item(discord.ui.InputText(label="End Time", placeholder="What time the event ends (Optional) (Ex: 11:00PM)", required=False, style=discord.InputTextStyle.short))

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            if self.children[0].value in [event['title'] for event in activeconflicts[str(interaction.guild_id)]]:
                await interaction.respond("An event with the same name already exists in the conflicts list! Please choose a different name.")
                return
            view = ConflictView()
            new_data = {
                'id': '',
                'title': self.children[0].value, 
                'description': self.children[1].value, 
                'date': self.children[2].value,
                'starttime': self.children[3].value,
                'endtime': self.children[4].value,
                'going': []
            }
            embed = discord.Embed(title=new_data['title'], description=new_data['description'], color=0x00ff00)
            embed.add_field(name="Date", value=new_data['date'], inline=False)
            embed.add_field(name="Start Time", value=new_data['starttime'], inline=True)
            embed.add_field(name="End Time", value=new_data['endtime'], inline=True)
            embed.add_field(name="People Going", value='', inline=False)

            sendchannel = bot.get_channel(conflictlists.get(str(interaction.guild.id)))
            message = await sendchannel.send(f'''A potential conflict has been posted. Please indicate if you will be going to this by clicking "I'm Going To This!"''', embed=embed, view=view)
            new_data['id'] = message.id
            with open("conflicts.json", "r+") as f:
                try:
                    activeconflicts[str(interaction.guild_id)].append(new_data)
                except:
                    activeconflicts[str(interaction.guild_id)] = []
                    activeconflicts[str(interaction.guild_id)].append(new_data)
                f.seek(0)
                json.dump(activeconflicts, f, indent=4)
            await interaction.respond("This conflict has been posted!", ephemeral=True)
        except Exception as e:
            print(e.with_traceback())
            await interaction.respond("Something went wrong! Please try again.")


@conflicts.command(name="add", description="Add an event to the conflicts list", guild_ids=GUILD_IDS)
async def conflictadd(ctx: commands.Context):
    if str(ctx.guild.id) in conflictlists.keys():
        modal = ConflictModal(title="Add a new conflict")
        await ctx.send_modal(modal)
    else:
        await ctx.respond("There is no conflicts channel set up for this server! If you're a server admin, use /conflicts channel, followed by the channel ID of the channel you'd like to designate.")
        return

async def getconflictbyname(ctx: discord.AutocompleteContext):
    if str(ctx.interaction.guild.id) in activeconflicts.keys():
        return [conflict['title'] for conflict in activeconflicts[str(ctx.interaction.guild_id)]]

@conflicts.command(name="remove", description="Remove an event from the conflicts list", guild_ids=GUILD_IDS)
@commands.has_permissions(manage_channels=True)
async def conflictremove(ctx: commands.Context, 
                         conflictname: Option(str, description="Name of the event you want to remove", autocomplete=discord.utils.basic_autocomplete(getconflictbyname)),
                         hide_response: Option(bool, description="If true, only you will be able to see the bot's response. Set to False if left blank", required=False),
                         debug: Option(bool, description="Only set this if you know what you're doing", required=False)):
    try:
        conflictindex = 0
        for event in activeconflicts[str(ctx.guild_id)]:
            if str(event['title']) == conflictname:
                break
            conflictindex += 1
        messageid = activeconflicts[str(ctx.guild_id)][conflictindex]['id']
        channel = bot.get_channel(conflictlists[str(ctx.guild_id)])
        message: discord.Message = await channel.fetch_message(messageid)
        print(message)
        await message.delete()
        with open("conflicts.json", "r+") as f:
            activeconflicts[str(ctx.guild_id)].pop(conflictindex)
            f.seek(0)
            json.dump(activeconflicts, f, indent=4)
        await ctx.respond("The event has been removed from the conflicts list!", ephemeral=hide_response)
    except KeyError as e:
        if debug:
            await ctx.respond(f"Event does not exist in conflicts list, displaying debug info:\n\n {traceback.print_exc()}", ephemeral=True)
        else:
            await ctx.respond("Could not find event. Please check the name and try again.", ephemeral=True)
        print(traceback.print_exc())
    except Exception as e:
        if debug:
            await ctx.respond(f"Unknown error while deleting the event. Displaying debug info:\n\n {traceback.print_exc()}", ephemeral=True)
        else:
            await ctx.respond(f"An error occurred while trying to remove the event. Please try again.", ephemeral=True)
        print(traceback.print_exc())

@conflicts.command(name="view" , description="View the current conflicts list", guild_ids=GUILD_IDS)
async def conflictview(ctx: commands.Context, 
                        conflictname: Option(str, description="Name of the event you want to remove", autocomplete=discord.utils.basic_autocomplete(getconflictbyname)),
                        hide_response: Option(bool, description="If true, only you will be able to see the bot's response. Set to False if left blank", required=False),
                        debug: Option(bool, description="Only set this if you know what you're doing", required=False)):
    try:
        conflictindex = 0
        for event in activeconflicts[str(ctx.guild_id)]:
            if str(event['title']) == conflictname:
                break
            conflictindex += 1
        messageid = activeconflicts[str(ctx.guild_id)][conflictindex]['id']
        channel = bot.get_channel(conflictlists[str(ctx.guild_id)])
        message: discord.Message = await channel.fetch_message(messageid)
        embed = message.embeds[0]
        embed.set_footer(text="Please note: This message does not dynamically update. Please use the '/conflicts view' command to see the most up-to-date information.")
        await ctx.respond(embed=embed, ephemeral=hide_response)
    except Exception as e:
        if debug:
            await ctx.respond(f"Unknown error while finding event. Displaying debug info:\n\n {traceback.print_exc()}", ephemeral=True)
        else:
            await ctx.respond(f"An error occurred while trying to display the event. Please try again.", ephemeral=True)
        print(traceback.print_exc())
    
bot.add_application_command(conflicts)
bot.add_application_command(calendar)
bot.add_application_command(music)

bot.run(os.getenv('BOT_KEY'))