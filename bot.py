import os
import asyncio
import discord
from discord.ext import commands
from dotenv import load_dotenv
import yt_dlp

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

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

queues = {}  # kiekvieno serverio dainų eilė


def get_info(query):
    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
        info = ydl.extract_info(query, download=False)
        if "entries" in info:
            info = info["entries"][0]
        return info["title"], info["url"]


def play_next(ctx):
    queue = queues.get(ctx.guild.id, [])
    if queue and ctx.voice_client:
        title, url = queue.pop(0)
        source = discord.FFmpegPCMAudio(url, **FFMPEG_OPTIONS)
        ctx.voice_client.play(source, after=lambda e: play_next(ctx))
        asyncio.run_coroutine_threadsafe(ctx.send(f"Groja: {title}"), bot.loop)


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
    async with ctx.typing():
        title, url = await bot.loop.run_in_executor(None, get_info, query)
    queues.setdefault(ctx.guild.id, []).append((title, url))
    if ctx.voice_client.is_playing() or ctx.voice_client.is_paused():
        await ctx.send(f"Įdėta į eilę: {title}")
    else:
        play_next(ctx)


@bot.command()
async def skip(ctx):
    if ctx.voice_client:
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
async def leave(ctx):
    if ctx.voice_client:
        queues[ctx.guild.id] = []
        await ctx.voice_client.disconnect()

@bot.command(name="help")
async def help_command(ctx):
    embed = discord.Embed(
        title="Muzikos boto komandos",
        color=discord.Color.blurple(),
    )
    embed.add_field(name="!play <daina arba nuoroda>", value="Groja dainą (YouTube paieška arba YouTube/SoundCloud nuoroda)", inline=False)
    embed.add_field(name="!skip", value="Praleidžia dabartinę dainą", inline=False)
    embed.add_field(name="!pause", value="Sustabdo grojimą", inline=False)
    embed.add_field(name="!resume", value="Tęsia grojimą", inline=False)
    embed.add_field(name="!leave", value="Išvalo eilę ir botas išeina iš kanalo", inline=False)
    embed.add_field(name="!ping", value="Patikrina, ar botas veikia", inline=False)
    embed.add_field(name="!help", value="Parodo šį sąrašą", inline=False)
    await ctx.send(embed=embed)

bot.run(TOKEN)