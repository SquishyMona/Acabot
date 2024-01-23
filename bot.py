import os
os.system("pip uninstall --yes discord.py py-cord")
os.system("pip install --no-input py-cord")

import discord
import logging
import wavelink
import json
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
GUILD_IDS = [1148389231484489860, 608476415825936394, 1118643846688030730]

# Loads enviornment variables, which contains our bot token needed to run the bot
load_dotenv()
#logger = logging.getLogger('discord')
#logger.setLevel(logging.DEBUG)
#handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
#handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
#logger.addHandler(handler)

# Creation of our bot object, as well as defining some new objects.
bot = discord.Bot()

# This object holds the id's for all active polls, and a list of each user who has voted in that poll.
# This is used to prevent users from voting more than once on a single poll.
activepolls = {}

# This object holds the queue of music when using music commands
musicqueue = wavelink.Queue()

# This object holds the credentials for our service account, which is used by the Google APIs
credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)

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
    print(f'{bot.user} is online and ready')
    #await connect_nodes()
    incremental_sync.start()
    get_upcoming.start()
    startwebhooks.start()

@bot.event
async def on_wavelink_node_ready(node: wavelink.Node):
    print(f"Wavelink node {node.id} ready.")  

# When a new scheduled event is created on Discord, we will also create a new event
# on the Google Calendar.
@bot.event
async def on_scheduled_event_create(event: discord.ScheduledEvent): 
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
        try:
            duplicate = {
                'summary': gcalevent['summary'],
                'description': description,
                'location': gcalevent['location'],
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
                    activeevents[event.id] = [gcalevent['id']]
                    json.dump(activeevents, file)
                return
        except Exception as e:
            print(e)
            pass
        
    link = calapi_createevent(event, calid)

# When a scheduled event is updated, we will also update the event on the Google Calendar.
@bot.event
async def on_scheduled_event_update(event: discord.ScheduledEvent):
    service = build('calendar', 'v3', credentials=credentials)

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
        modify_event = service.events().get(calendarId=calid, eventId=activeevents[event.id])
        duplicate = {
                'summary': modify_event['summary'],
                'description': description,
                'location': modify_event['location'],
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
            updated = service.events().update(calendarId=calid, eventId=activeevents[event.id], body=event)
            print(updated)

# When a scheduled event is deleted, we will also delete the event on the Google Calendar.
@bot.event
async def on_scheduled_event_delete(event: discord.ScheduledEvent):
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
                service = build('calendar', 'v3', credentials=credentials)
                service.events().delete(calendarId=calid, eventId=gcalevent['id']).execute()
                return
        except Exception as e:
            print(e)
            pass
            

@tasks.loop(hours=167)
async def startwebhooks():
    await bot.wait_until_ready()
    calapi_startwebhooks()

@tasks.loop(minutes=5)
async def incremental_sync():
    await bot.wait_until_ready()
    calapi_incrementalsync()

@tasks.loop(minutes=1)
async def get_upcoming():
    await bot.wait_until_ready()
    print('Starting Task')
    events = calapi_getupcoming()
    if events == None:
        return
    else:
        for event in events:
            if event['id'] in seen_events:
                continue
            else:
                seen_events.append(event['id'])
                channel = bot.get_channel(1148414047704850432)
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
                message = await channel.send('An event is coming up! See details below.', embed=embed)
                if channel.type == discord.ChannelType.news:
                    await message.publish()


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
    embed.set_author(name="Acabot", icon_url='https://cdn.discordapp.com/avatars/1148739423001915423/74a8f73e52d99fb77aab13a1ba73d530?size=1024')
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
    print(eventslist)
    if eventslist == None:
        await ctx.respond("There are no upcoming events!", ephemeral=hide_response)
        return
    embed = discord.Embed(title="Upcoming Events", color=discord.Colour.dark_magenta(), description="Here's whats coming up:")
    for event in eventslist:
        start = event['start'].get('dateTime')
        tmfmt = '%B %d, %Y at %I:%M %p'
        try:
            stime = datetime.datetime.strftime(dtparse(start), format=tmfmt)
        except:
            stime = datetime.datetime.strftime(dtparse(event['start'].get('date')), format='%B %d, %Y')
        embed.add_field(name=event['summary'], value=stime, inline=False)
    
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
async def poll(ctx, 
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
        await ctx.channel.send(embed=embed, view=view)
        await ctx.respond("Your poll has been created!", ephemeral=True)
    except Exception as e:
        await ctx.respond(f"Something went wrong! You can always try manually creating a poll!")
        print(e)

bot.add_application_command(calendar)
bot.add_application_command(music)

bot.run(os.getenv('BOT_KEY'))