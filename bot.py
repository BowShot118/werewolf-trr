# Testing Discord bot Platform for Individual Cog Testing
# Author: BowShot118 / bowshottoerana@gmail.com
# Created with Python 3.13
import discord
from discord import app_commands
from discord.ext import commands, tasks
import sys
from pathlib import Path
import os
import asyncio



# Token Import
from config import token

projectRoot = Path(__file__).resolve().parent.parent
if str(projectRoot) not in sys.path:
    sys.path.insert(0,str(projectRoot))

# Loading Cogs
initialExtensions = []

for filename in os.listdir("./cogs"):
    if filename.endswith(".py"):
        initialExtensions.append(f"cogs.{filename[:-3]}")

bot = commands.Bot(command_prefix="!",intents=discord.Intents.all())
@bot.event
async def on_ready():
    print(f'We have logged in as {bot.user}')
    try:
        synced_commands = await bot.tree.sync()
        print("Synced")
    except Exception as e:
        print(f'Exception: ',e)

async def cogLoad():
    for extension in initialExtensions:
        await bot.load_extension(extension)
        print(f"Loaded {extension}")

async def botRun():
    async with bot:
        await cogLoad()
        await bot.start(token)

asyncio.run(botRun())