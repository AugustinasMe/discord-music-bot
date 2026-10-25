import os
import asyncio
import random
import discord
from discord.ext import commands
from dotenv import load_dotenv
import yt_dlp
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
SPOTIFY_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

# Spotify prisijungimas (jei raktai nenurodyti, Spotify tiesiog neveiks)
sp = None
if SPOTIFY_ID and SPOTIFY_SECRET:
    sp = spotipy.Spotify(
        auth_manager=SpotifyClientCredentials(
            client_id=SPOTIFY_ID,
            client_secret=SPOTIFY_SECRET,
        )
    )

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)

YDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "default_search": "ytsearch",
    "quiet": True,
}
FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

MAX_SPOTIFY_TRACKS = 50  # kiek dainų daugiausiai įdedam iš albumo

queues = {}   # kiekvieno serverio dainų eilė
loops = {}    # ar ciklas įjungtas (kiekvienam serveriui)
current = {}  # dabar grojanti daina (kiekvienam serveriui)


def get_info(query):
    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
        info = ydl.extract_info(query, download=False)
        if "entries" in info:
            info = info["entries"][0]
        return info["title"], info["url"]


def track_to_text(track):
    """Iš Spotify dainos padaro paieškos tekstą: 'Daina Atlikėjas'."""
    return f"{track['name']} {track['artists'][0]['name']}"


def spotify_to_songs(link):
    """Iš Spotify nuorodos (daina / albumas / grojaraštis) grąžina paieškos tekstų sąrašą."""
    songs = []
    if "/track/" in link:
        songs.append(track_to_text(sp.track(link)))
    elif "/album/" in link:
        result = sp.album_tracks(link, limit=MAX_SPOTIFY_TRACKS)
        for track in result["items"]:
            songs.append(track_to_text(track))
    elif "/playlist/" in link:
        result = sp.playlist_items(link, limit=MAX_SPOTIFY_TRACKS)
        for item in result["items"]:
            track = item.get("track")
            if track:
                songs.append(track_to_text(track))
    return songs


def play_next(ctx):
    guild_id = ctx.guild.id
    queue = queues.setdefault(guild_id, [])
    repeat = False

    # jei ciklas įjungtas, dabartinę dainą grąžiname į eilės pradžią
    if loops.get(guild_id) and current.get(guild_id):
        queue.insert(0, current[guild_id])
        repeat = True

    if queue and ctx.voice_client:
        title, url = queue.pop(0)

        # Spotify dainos YouTube'e ieškomos tik dabar, kai ateina jų eilė
        if url is None:
            try:
                title, url = get_info(title)
            except Exception:
                asyncio.run_coroutine_threadsafe(
                    ctx.send(f"Nepavyko rasti: {title}"), bot.loop
                )
                current.pop(guild_id, None)
                play_next(ctx)
                return

        current[guild_id] = (title, url)
        source = discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS)
        ctx.voice_client.play(source, after=lambda e: play_next(ctx))
        if not repeat:
            asyncio.run_coroutine_threadsafe(ctx.send(f"Groja: {title}"), bot.loop)
    else:
        current.pop(guild_id, None)


@bot.event
async def on_ready():
    print(f"Prisijungta kaip {bot.user}")


@bot.command()
async def ping(ctx):
    await ctx.send("eik nx!")


@bot.command()
async def play(ctx, *, query):
    if not ctx.author.voice:
        await ctx.send("Pirma prisijunk prie voice'o gaideli")
        return
    if not ctx.voice_client:
        await ctx.author.voice.channel.connect()

    queue = queues.setdefault(ctx.guild.id, [])
    already_playing = ctx.voice_client.is_playing() or ctx.voice_client.is_paused()

    if "open.spotify.com" in query:
        if sp is None:
            await ctx.send("Spotify nesukonfigūruotas: .env faile trūksta Spotify raktų.")
            return
        async with ctx.typing():
            try:
                songs = await bot.loop.run_in_executor(None, spotify_to_songs, query)
            except Exception as e:
                if "/playlist/" in query:
                    await ctx.send(
                        "Spotify nebeleidžia botam skaityti grojaraščių. "
                        "Įdėk atskiros dainos arba albumo nuorodą."
                    )
                else:
                    await ctx.send(f"Nepavyko perskaityti Spotify nuorodos: {e}")
                return
        if not songs:
            await ctx.send("Nepavyko rasti dainų šioje Spotify nuorodoje.")
            return
        for song in songs:
            queue.append((song, None))  # None = YouTube nuorodos dar neieškota
        await ctx.send(f"Įdėta į eilę dainų iš Spotify: {len(songs)}")
    else:
        async with ctx.typing():
            try:
                title, url = await bot.loop.run_in_executor(None, get_info, query)
            except Exception:
                await ctx.send("Nepavyko rasti arba paleisti šios dainos.")
                return
        queue.append((title, url))
        if already_playing:
            await ctx.send(f"Įdėta į eilę: {title}")

    if not already_playing:
        play_next(ctx)


@bot.command()
async def skip(ctx):
    if ctx.voice_client:
        current.pop(ctx.guild.id, None)  # kad praleista daina nesikartotų
        ctx.voice_client.stop()


@bot.command()
async def pause(ctx):
    if ctx.voice_client:
        ctx.voice_client.pause()


@bot.command()
async def resume(ctx):
    if ctx.voice_client:
        ctx.voice_client.resume()


@bot.command()
async def loop(ctx):
    guild_id = ctx.guild.id
    loops[guild_id] = not loops.get(guild_id, False)
    if loops[guild_id]:
        await ctx.send("🔁 Ciklas įjungtas: dabartinė daina kartosis.")
    else:
        await ctx.send("Ciklas išjungtas.")


@bot.command()
async def leave(ctx):
    if ctx.voice_client:
        queues[ctx.guild.id] = []
        current.pop(ctx.guild.id, None)
        loops[ctx.guild.id] = False
        await ctx.voice_client.disconnect()


@bot.command()
async def roll(ctx, kiekis: int = 2):
    if kiekis < 2 or kiekis > 20:
        await ctx.send("Pasirinkite skaičių nuo 2 iki 20.")
        return

    await ctx.send(
        f"Rašykite {kiekis} dalykus, kiekvieną atskira žinute. "
        "(Atšaukti: parašykite `atsaukti`)"
    )

    def check(m):
        return m.author == ctx.author and m.channel == ctx.channel

    dalykai = []
    while len(dalykai) < kiekis:
        try:
            zinute = await bot.wait_for("message", check=check, timeout=60)
        except asyncio.TimeoutError:
            await ctx.send("Per ilgai laukiau, atšaukta.")
            return
        if zinute.content.lower() == "atsaukti":
            await ctx.send("Atšaukta.")
            return
        dalykai.append(zinute.content)
        await ctx.send(f"Gauta {len(dalykai)}/{kiekis}")

    random.shuffle(dalykai)
    eilute = "\n".join(f"{i}. {d}" for i, d in enumerate(dalykai, start=1))
    await ctx.send("Atsitiktinė tvarka:\n" + eilute)


@roll.error
async def roll_error(ctx, error):
    if isinstance(error, commands.BadArgument):
        await ctx.send("Įrašykite skaičių, pvz., `!roll 5`")


@bot.command()
@commands.has_permissions(manage_messages=True)
@commands.bot_has_permissions(manage_messages=True, read_message_history=True)
async def clear(ctx, kiekis: int):
    if kiekis < 1 or kiekis > 200:
        await ctx.send("Pasirinkite skaičių nuo 1 iki 200.")
        return
    istrinta = await ctx.channel.purge(limit=kiekis + 1)
    await ctx.send(f"Ištrinta žinučių: {len(istrinta) - 1}", delete_after=3)


@clear.error
async def clear_error(ctx, error):
    if isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("Įrašykite skaičių, pvz., `!clear 10-200`")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("Įrašykite skaičių, pvz., `!clear 10-200`")
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("Neturite teisės trinti žinučių.")
    elif isinstance(error, commands.BotMissingPermissions):
        await ctx.send("Botas neturi teisės trinti žinučių šiame kanale.")


@bot.command(name="help")
async def help_command(ctx):
    embed = discord.Embed(
        title="Muzikos boto komandos",
        color=discord.Color.blurple(),
    )
    embed.add_field(name="!play <daina arba nuoroda>", value="Groja dainą (YouTube paieška, YouTube/SoundCloud arba Spotify daina / albumas)", inline=False)
    embed.add_field(name="!skip", value="Praleidžia dabartinę dainą", inline=False)
    embed.add_field(name="!pause", value="Sustabdo grojimą", inline=False)
    embed.add_field(name="!resume", value="Tęsia grojimą", inline=False)
    embed.add_field(name="!loop", value="Įjungia / išjungia dabartinės dainos kartojimą", inline=False)
    embed.add_field(name="!leave", value="Išvalo eilę ir botas išeina iš kanalo", inline=False)
    embed.add_field(name="!roll <kiekis>", value="Įrašote nurodytą kiekį dalykų, o botas išrašo juos atsitiktine tvarka", inline=False)
    embed.add_field(name="!clear <skaičius>", value="Ištrina nurodytą kiekį žinučių šiame kanale (reikia teisės trinti žinutes)", inline=False)
    embed.add_field(name="!ping", value="Patikrina, ar botas veikia", inline=False)
    embed.add_field(name="!help", value="Parodo šį sąrašą", inline=False)
    await ctx.send(embed=embed)


bot.run(TOKEN)