# RejectBot Werewolf Cog
# Author: BowShot118 / bowshottoerana@gmail.com
# Created with Python 3.13

import discord
from discord import app_commands
from discord.ext import commands
import time
from time import sleep
import asyncio
import os
import math
import csv
import sys
import random
import logging
import sqlite3
from difflib import get_close_matches
from collections import Counter
from pathlib import Path

projectRoot = Path(__file__).resolve().parent.parent
if str(projectRoot) not in sys.path:
    sys.path.insert(0,str(projectRoot))

# Setup
logs = logging.getLogger(__name__)
logging.basicConfig(filename='werewolf.log',level=logging.INFO,format="%(asctime)s:%(levelname)s:%(name)s:%(message)s")
statsDb = projectRoot / "data" / "werewolf.db" 

### Player Class
class player():
    def __init__(self, member: discord.Member, game):
        # Core Information
        self.member = member
        self.gameSession = game
        self.role = "V-1"
        self.originalRole = "V-1"
        self.secondaryRoles = []
        # Player Status
        self.alive = True
        self.isHome = True
        self.actionDone = False
        # Player Stats
        self.lives = 1
        self.votingPower = 1
        self.bullets = 0
        self.nightActions = 1 # For wolf shaman (it is assigned as 2 at night start), only checked with kill and give commands
        self.causeOfDeath = ""
        # Totems
        self.giveTotem = "" # Totem to give
        self.receivedTotems = [] # Totems held by the player (and that impact them)
        self.specialTotems = [] # Totems with unique mechanics or that last for a unique amount of time
        self.lastTarget = 0 # Last target of the totem
        # Visitors, Lovers, etc
        self.visitors = []
        self.lovers = []
        self.target = 0 # Assassin role target
    
    async def defineRole(self, role: str, primary: bool = True):
        if primary == True:
            self.role = role
        else:
            self.secondaryRoles.append(role)
    
    async def processActions(self):
        """Player class function to process a player's actions. This is used to handle players with multiple night actions."""
        if self.nightActions <= 1:
            self.actionDone = True
            print(f"{self.member.name} has completed their night actions")
        else:
            self.nightActions -= 1

    async def death(self,deathCause : str=""):
        """Player class function to process a player death
        Returns:
            role (str): The player role to be directly relayed to the game players"""
        roleToReturn = ""
        self.causeOfDeath = deathCause
        game = self.gameSession
        # Updating Player Status
        self.alive = False
        await self.member.remove_roles(game.playerRole,reason=f"[{game.gameId}] Werewolf Game Death")
        await game.spectatorChannel.set_permissions(self.member,overwrite=None,reason=f"[{game.gameId}] Werewolf Game Death")
        game.livingPlayersNames.pop(self.member.id)
        # Removing Access from wolf chat for wolf team members
        await game.wolfChannel.set_permissions(self.member,overwrite=None,reason=f"[{game.gameId}] Werewolf Game Death")

        # Traitor Game Rule
        if self.role == "W-2":
            roleToReturn = "V-1"
        else:
            roleToReturn = self.role

        # Wolf Cub Rule
        if self.role == "W-4":
            game.doubleKill = True
        try:
            # Traitor Promotion
            if self.role in ["W-1"]:
                traitorPromo = await game.checkTraitor()
                if traitorPromo:
                    await game.gameChannel.send(f"Insert fancy language here to indicate a traitor has become a wolf")
        except Exception as e:
            print(f"{e}")
        game.tempDeadPlayers.append(self)
        consequenceKills = None
        if deathCause == "quit":
            pass
        else:
            # Consequence death calculations (deaths that occur as the result of this player's death)
            if "S-4" in self.secondaryRoles or "S-5" in self.secondaryRoles:
                consequenceKills = ""
                print(f"Consequence Kills for {self.member.name}")
                # Lovers
                if "S-4" in self.secondaryRoles:
                    for loverId in self.lovers:
                        lover = game.players[loverId]
                        if lover.alive:
                            loverRole, additionalLoverDeaths = await lover.death(deathCause="lover")
                            consequenceKills += f"Saddened by the loss of their lover {self.member.name}, {lover.member.name}, a {game.roles[loverRole]}, has committed suicide.\n"
                            if additionalLoverDeaths != None:
                                consequenceKills += additionalLoverDeaths
                # Assassin
                try:
                    if "S-5" in self.secondaryRoles:
                        # Verifies there is actually a target
                        print(f"{self.target}")
                        if self.target != 0:
                            targetedPlayer = game.players[self.target]
                            if targetedPlayer.alive:
                                playerRole, additionalDeaths = await targetedPlayer.death(deathCause="assassin")
                                consequenceKills += f"Shortly before death, {self.member.name} whips out some ninja moves and kills {targetedPlayer.member.name}, a {game.roles[playerRole]}"
                                if additionalDeaths != None:
                                    consequenceKills += additionalDeaths
                except Exception as e:
                    logs.warning(f"{self.member.id} Assassin Kill Error, Target: {self.target}, Error: {e}")
        logs.info(f"Player Death: {self.member.id}")
        return roleToReturn, consequenceKills

    async def saveStats(self, gameId: int, winning: bool):
        """Player class function to save individual stats
        Args:
            gameId (int): The ID of the game the stats are for
            winning (bool): Whether the player won or not"""
        try:
            if winning:
                winner = 1
            else:
                winner = 0
            if self.alive:
                self.causeOfDeath = "alive"
            with sqlite3.connect(statsDb) as con:
                cur = con.cursor()
                res = cur.execute("INSERT INTO playerStats VALUES(?,?,?,?,?)",(self.member.id,gameId,self.originalRole,self.causeOfDeath,winner))
                con.commit()
            logs.info(f"Player Stats Saved, ID: {self.member.id}")
        except Exception as e:
            print(f"{e}")
            logs.warning(f"Player stats saving failed, ID: {self.member.id}. Error: {e}")



#### Commands

class werewolf(commands.Cog):
    def __init__(self, bot: discord.BotIntegration):
        self.bot = bot
        # Setting Variables
        from config import gameChannelId, spectatorsChannelId, wolfchatChannelId, playerRoleId, serverId, gameAdmins, hostId
        self.gameChannelId = gameChannelId
        self.spectatorsChannelId = spectatorsChannelId
        self.wolfchatChannelId = wolfchatChannelId
        self.playerRoleId = playerRoleId
        self.serverId = serverId
        self.admins = gameAdmins
        self.host = hostId
        #######################
        self.guild : discord.Guild | None = None
        self.everyoneRole : discord.Role | None = None
        self.gameChannel : discord.TextChannel | None = None
        self.spectatorChannel : discord.TextChannel | None = None
        self.playerRole : discord.Role | None = None
        # Status Variables
        self.gameRunning = False
        self.isDay = True
        self.dayCount = 0
        self.nightCount = 0
        self.winningTeam = None
        self.timeTracker = 0
        self.killVotes = []
        self.impatientVoters = [] # Players holding impatience totems
        self.testing = False
        self.doubleKill = False
        self.gameId = 0
        self.savingStats = True
        # Player Variables
        self.players = {} # Used to store the player classes
        self.livingPlayersNames = {} # Used to store the living player names for use in voting
        self.playerVotes = {} # Used to store the players votes
        self.startVoters = []
        self.gamemodes = ["default","orgy","chaos"]
        self.selectedMode = ""
        self.additionalWinners = [] # List of IDs of winners that reach their win condition mid game
        self.tempDeadPlayers = [] # List of players that died during a change in stage
        self.winningFool = 0 # Id of the winning fool, if the fool was lynched

        self.roles = { 
            "V-1" : "Villager", 
            "V-2" : "Seer", 
            "V-3" : "Shaman", 
            "V-4" : "Harlot",
            "V-5" : "Matchmaker", 
            "W-1" : "Wolf", 
            "W-2" : "Traitor",
            "W-3" : "Wolf Shaman",
            "W-4" : "Wolf Cub", 
            "T-1" : "Cultist", 
            "S-1" : "Cursed", 
            "S-2" : "Gunner",
            "S-3" : "Sharpshooter",
            "S-4" : "Lover",
            "S-5" : "Assassin",
            "N-1" : "Crazed Shaman",
            "N-2" : "Jester",
            "N-3" : "Fool" 
        }

        self.roleIntroductions = {
            "V-1" : "Your role is **Villager**. You are on the **village team** and your job is to lynch all of the wolves during the day.",
            "V-2" : "Your role is **Seer**. You are on the **village team** and you may choose one person to see the role off each night. Use the `!see <player>` command in dms to do this.",
            "V-3" : "Your role is **Shaman**. You are on the **village team** and you are given a single totem which you may give to any player during the night. Use the `!give <player>` command in dms to do this.",
            "V-4" : "Your role is **Harlot**. You are on the **village team** and you may visit a single player during the night. You can do this using the `!visit <player>` command in dms. You may stay home using the `!stayhome` command.",
            "V-5" : "Your role is **Matchmaker**. You are on the **village team** and you may select two players to be lovers during night one. You can do this using the `!choose <player1> and <player2>` command in dms.",
            "W-1" : f"Your role is **Wolf**. You are on the **wolf team** and your job is to kill all of the villagers. You may kill a villager during the night using the `!kill <player>` command. See https://discord.com/channels/{self.serverId}/{self.wolfchatChannelId}.",
            "W-2" : f"Your role is **Traitor**. You are on the **wolf team** and appear as a villager if killed. You may not kill during the night, but if all of the wolves die you will become a wolf. See https://discord.com/channels/{self.serverId}/{self.wolfchatChannelId}.",
            "W-3" : f"Your role is **Wolf Shaman**. You are on the **wolf team** and your job is to kill all of the villagers. You are also given a single totem which you may give to any player during the night. Use the `!give <player>` command to give your totem. To kill, use the `<!kill player>` command in wolf chat. See See https://discord.com/channels/{self.serverId}/{self.wolfchatChannelId}.",
            "W-4" : f"Your role is **Wolf Cub**. You are on the **wolf team** and your job is to kill all of the villagers. If you die, the wolf team will get two kills the following night. You may kill a villager during the night using the `!kill <player>` command. See https://discord.com/channels/{self.serverId}/{self.wolfchatChannelId}.",
            "T-1" : "Your role is **Cultist**. You are on the **wolf team** but do not know who they are.",
            # Secondary roles have no descriptions
            "S-1" : "Cursed",
            "S-2" : "Gunner",
            "S-3" : "Sharpshooter",
            "S-4" : "Lover",
            "S-5" : "Assassin",
            # Neutral Roles
            "N-1" : "Your role is **Crazed Shaman**. You win by surviving to the end of the game. You are given a single totem, which you are not told, to give to another player during the night. Use the `!give <player>` command in dms to do this.",
            "N-2" : "Your role is **Jester**. You win by being lynched during the day.",
            "N-3" : "Your role is **Fool**. You win by being lynched during the day. This also ends the game and makes you the sole winner*."
        }

        self.roleDescriptions = {
            "V-1" : "Villagers are members of the **village team**. Their job is to lynch all of the wolves.",
            "V-2" : "Seers are members of the **village team**. They may observe the role of a single player during the night.",
            "V-3" : "Shamans are members of the **village team**. They may give a single player a known totem during the night, but may not give the same player a totem two nights in a row.",
            "V-4" : "Harlots are members of the **village team**. They may visit another player during the night.",
            "V-5" : "Matchmakers are members of the **villager team**. During night one, they may select two players to be lovers.",
            "W-1" : "Wolves are part of the **wolf team**. They may kill players during the night.",
            "W-2" : "Traitors are part of the **wolf team**. They appear as villagers, but when all the wolves die they become a wolf.",
            "W-3" : "Wolf Shamans are part of the **wolf team**. They may kill during the night, and may give a single player a known totem during the night, but may not give the same player a totem two nights in a row.",
            "W-4" : "Wolf Cubs are part of the **wolf team**. They may kill during the night. If they are killed, wolf team will get two kills the following night.",
            "T-1" : "Cultists are part of the **wolf team**. They do not have access to the wolf's lair, and may not kill.",
            "S-1" : "Cursed villagers appear as wolves to seeing roles.",
            "S-2" : "Gunners start with a gun and some bullets which they may use during the day.",
            "S-3" : "A Sharpshooter is a gunner with an education.",
            "S-4" : "A lover will die if their other lover dies. Lovers may win the game if they are the only survivors at the end of a game, alongside their usual win conditions.",
            "S-5" : "Assassins may select someone to target during night 1, who will die if they die.",
            "N-1" : "Crazed Shamans are **neutral**. They may give a single unknown totem to a player during the night, and may not give the same player a totem two nights in a row. They win by staying alive.",
            "N-2" : "Jesters are **neutral**. They win by being lynched during the day.",
            "N-3" : "Fools are **neutral**. If they are lynched during the day, they become the game's sole winner*."
        }

        self.totems = {
            "Protection" : "", 
            "Death"      : "", 
            "Impatience" : "", 
            "Influence"  : "", 
            "Silence"    : "", 
            "Reveal"     : "", 
            "Pacifism"   : "", 
            "Desperation": ""
        }
        # Roles and Role Number for 
        self.testingMode = {
            "players" : [4,5,6,7,8,9,10,11,12,13,14,15,16],
            "V-1"     : [0,0,0,0,0,0,0 ,0 ,0 ,0 ,0 ,0 ,1 ], # Villager
            "V-2"     : [0,0,0,0,1,1,1 ,1 ,1 ,1 ,1 ,1 ,7 ], # Seer
            "V-3"     : [3,4,4,5,4,4,4 ,5 ,5 ,5 ,5 ,6 ,2 ], # Shaman
            "V-4"     : [0,0,0,0,0,0,0 ,0 ,0 ,0 ,0 ,0 ,0 ], # Harlot
            "V-5"     : [0,0,0,0,0,0,0 ,0 ,0 ,0 ,0 ,0 ,0 ], # Matchmaker
            "W-1"     : [1,1,1,1,1,1,1 ,1 ,2 ,2 ,2 ,2 ,2 ], # Wolf
            "W-2"     : [0,0,0,0,0,0,0 ,0 ,0 ,0 ,0 ,0 ,0 ], # Traitor
            "W-3"     : [0,0,0,0,1,1,1 ,1 ,1 ,1 ,2 ,2 ,2 ], # Wolf Shaman
            "W-4"     : [0,0,0,0,0,0,1 ,1 ,1 ,1 ,1 ,1 ,1 ], # Wolf Cub
            "T-1"     : [0,0,0,0,0,0,0 ,0 ,0 ,0 ,0 ,0 ,0 ], # Cultist
            "N-1"     : [0,0,0,0,0,1,1 ,1 ,1 ,1 ,1 ,1 ,1 ], # Crazed Shaman
            "N-2"     : [0,0,1,1,1,1,1 ,1 ,1 ,2 ,2 ,2 ,2 ], # Jester
            "N-3"     : [0,0,0,0,0,0,0 ,0 ,0 ,0 ,0 ,0 ,0 ], # Fool
            "S-1"     : [0,0,0,0,0,0,0 ,0 ,0 ,0 ,0 ,0 ,0 ], # Cursed
            "S-2"     : [1,5,1,1,1,2,2 ,2 ,3 ,3 ,3 ,3 ,3 ], # Gunner
            "S-5"     : [0,0,0,0,0,1,1 ,2 ,2 ,2 ,2 ,3 ,3 ]  # Assassin
        }
        self.default = {
            "players" : [4,5,6,7,8,9,10,11,12,13,14,15,16],
            "V-1"     : [2,3,4,3,3,3,3 ,3 ,3 ,3 ,4 ,4 ,4 ], # Villager
            "V-2"     : [1,1,1,1,1,1,1 ,1 ,1 ,2 ,2 ,2 ,2 ], # Seer
            "V-3"     : [0,0,0,1,1,1,1 ,1 ,1 ,1 ,1 ,1 ,1 ], # Shaman
            "V-4"     : [0,0,0,0,1,1,1 ,1 ,1 ,1 ,1 ,1 ,1 ], # Harlot
            "V-5"     : [0,0,0,0,0,0,0 ,1 ,1 ,1 ,1 ,1 ,1 ], # Matchmaker
            "W-1"     : [1,1,1,1,1,1,1 ,1 ,2 ,2 ,2 ,3 ,3 ], # Wolf
            "W-2"     : [0,0,0,0,1,1,1 ,1 ,1 ,1 ,1 ,1 ,1 ], # Traitor
            "W-3"     : [0,0,0,0,0,0,0 ,0 ,0 ,0 ,0 ,0 ,0 ], # Wolf Shaman
            "W-4"     : [0,0,0,0,0,0,1 ,1 ,1 ,1 ,1 ,1 ,1 ], # Wolf Cub
            "T-1"     : [0,0,0,1,0,0,0 ,0 ,0 ,0 ,0 ,0 ,0 ], # Cultist
            "N-1"     : [0,0,0,0,0,1,1 ,1 ,1 ,1 ,1 ,1 ,1 ], # Crazed Shaman
            "N-2"     : [0,0,0,0,0,0,0 ,0 ,0 ,0 ,0 ,0 ,1 ], # Jester
            "N-3"     : [0,0,0,0,0,0,0 ,0 ,0 ,0 ,0 ,0 ,0 ], # Fool
            "S-1"     : [0,0,1,0,1,1,1 ,1 ,1 ,1 ,2 ,2 ,2 ], # Cursed
            "S-2"     : [0,0,0,0,0,0,1 ,1 ,1 ,1 ,1 ,1 ,1 ], # Gunner
            "S-5"     : [0,0,0,0,0,0,0 ,0 ,0 ,1 ,1 ,1 ,1 ]  # Assassin
        }
        self.chaos = {
            "players" : [4,5,6,7,8,9,10,11,12,13,14,15,16],
            "V-1"     : [0,0,0,0,0,0,0 ,0 ,0 ,0 ,0 ,0 ,1 ], # Villager
            "V-2"     : [0,0,0,0,1,1,1 ,1 ,1 ,1 ,1 ,1 ,7 ], # Seer
            "V-3"     : [3,4,4,5,4,4,4 ,5 ,5 ,5 ,5 ,6 ,2 ], # Shaman
            "V-4"     : [0,0,0,0,0,0,0 ,0 ,0 ,0 ,0 ,0 ,0 ], # Harlot
            "V-5"     : [0,0,0,0,0,0,0 ,0 ,0 ,0 ,0 ,0 ,0 ], # Matchmaker
            "W-1"     : [1,1,1,1,1,1,1 ,1 ,2 ,2 ,2 ,2 ,2 ], # Wolf
            "W-2"     : [0,0,0,0,0,0,0 ,0 ,0 ,0 ,0 ,0 ,0 ], # Traitor
            "W-3"     : [0,0,0,0,1,1,1 ,1 ,1 ,1 ,2 ,2 ,2 ], # Wolf Shaman
            "W-4"     : [0,0,0,0,0,0,1 ,1 ,1 ,1 ,1 ,1 ,1 ], # Wolf Cub
            "T-1"     : [0,0,0,0,0,0,0 ,0 ,0 ,0 ,0 ,0 ,0 ], # Cultist
            "N-1"     : [0,0,0,0,0,1,1 ,1 ,1 ,1 ,1 ,1 ,1 ], # Crazed Shaman
            "N-2"     : [0,0,1,1,1,1,1 ,1 ,1 ,2 ,2 ,2 ,2 ], # Jester
            "N-3"     : [0,0,0,0,0,0,0 ,0 ,0 ,0 ,0 ,0 ,0 ], # Fool
            "S-1"     : [0,0,0,0,0,0,0 ,0 ,0 ,0 ,0 ,0 ,0 ], # Cursed
            "S-2"     : [1,1,1,1,1,2,2 ,2 ,3 ,3 ,3 ,3 ,3 ], # Gunner
            "S-5"     : [0,0,0,0,0,1,1 ,2 ,2 ,2 ,2 ,3 ,3 ]  # Assassin
        }
        self.orgy = {
            "players" : [4,5,6,7,8,9,10,11,12,13,14,15,16],
            "V-1"     : [0,0,0,0,0,0,0 ,0 ,0 ,0 ,0 ,0 ,0 ], # Villager
            "V-2"     : [0,0,0,0,0,0,0 ,0 ,0 ,0 ,0 ,0 ,0 ], # Seer
            "V-3"     : [0,0,0,0,0,0,0 ,0 ,0 ,0 ,0 ,0 ,0 ], # Shaman
            "V-4"     : [3,4,4,4,3,4,3 ,4 ,5 ,4 ,4 ,4 ,4 ], # Harlot
            "V-5"     : [0,0,1,1,1,1,2 ,2 ,2 ,2 ,3 ,3 ,4 ], # Matchmaker
            "W-1"     : [1,1,1,1,1,1,2 ,2 ,2 ,3 ,3 ,3 ,3 ], # Wolf
            "W-2"     : [0,0,0,0,1,1,1 ,1 ,1 ,1 ,1 ,2 ,2 ], # Traitor
            "W-3"     : [0,0,0,0,0,0,0 ,0 ,0 ,0 ,0 ,0 ,0 ], # Wolf Shaman
            "W-4"     : [0,0,0,0,0,0,0 ,0 ,0 ,0 ,0 ,0 ,0 ], # Wolf Cub
            "T-1"     : [0,0,0,0,0,0,0 ,0 ,0 ,0 ,0 ,0 ,0 ], # Cultist
            "N-1"     : [0,0,0,0,1,1,1 ,1 ,1 ,2 ,2 ,2 ,2 ], # Crazed Shaman
            "N-2"     : [0,0,0,0,0,0,0 ,0 ,0 ,0 ,0 ,0 ,0 ], # Jester
            "N-3"     : [0,0,0,1,1,1,1 ,1 ,1 ,1 ,1 ,1 ,1 ], # Fool
            "S-1"     : [0,0,0,0,0,0,0 ,0 ,0 ,0 ,0 ,0 ,0 ], # Cursed
            "S-2"     : [0,0,0,0,0,0,0 ,0 ,0 ,0 ,0 ,0 ,0 ], # Gunner
            "S-5"     : [0,0,0,0,0,0,0 ,0 ,0 ,0 ,0 ,0 ,0 ]  # Assassin
        }
    async def guildDef(self):
        try:
            await self.bot.wait_until_ready()
            print("guild def running")
            self.guild = self.bot.get_guild(self.serverId)
            self.everyoneRole = self.guild.default_role
            self.gameChannel = self.guild.get_channel(self.gameChannelId)
            self.wolfChannel = self.guild.get_channel(self.wolfchatChannelId)
            self.playerRole = self.guild.get_role(self.playerRoleId)
            self.spectatorChannel = self.guild.get_channel(self.spectatorsChannelId)
        except Exception as e:
            print(f"{e}")
    
    async def cog_load(self):
        self.bot.loop.create_task(self.guildDef())

    ### Game Commands --- Commands accessible to all players used to interact with the game itself

    ## Pre-Start Commands --- Commands that only work before the start of a game

    @commands.command(name="join",aliases=["j"])
    async def join(self, ctx):
        """Werewolf Join Command. Is used for players to join the game"""
        try:
            if ctx.author.id in self.players:
                await ctx.reply(f"You are already in the game")
            else:
                # Defines the player and adds them to all of the relevant variables
                newPlayer = player(ctx.author,self)
                self.players[ctx.author.id] = newPlayer
                self.livingPlayersNames[ctx.author.id] = ctx.author.name
                self.playerVotes[ctx.author.id] = None
                await ctx.reply(f"You have joined the game. There are {len(self.players)} players in the game.")
                logs.info(f"Player joined the game, ID: {ctx.author.id}")
        except Exception as e:
            logs.warning(f"Player Join Error, ID: {ctx.author.id}. Error: {e}")
            await self.gameChannel.send(f"Join Error for {ctx.author.id}. If issues persist, inform host")

    @commands.command(name="start")
    async def start(self, ctx):
        """Werewolf command to start a game"""
        if self.gameRunning == False:
            if ctx.author.id in self.players:
                if len(self.players) > 3:
                    if ctx.author.id not in self.startVoters:
                        self.startVoters.append(ctx.author.id)
                        if len(self.startVoters) >= math.ceil(len(self.players)/3):
                            self.gameRunning = True
                            await ctx.send("Game is Starting")
                            await self.gameStart()
                        else:
                            await ctx.reply(f"You have voted to start the game. {len(self.startVoters)} out of the required {math.ceil(len(self.players)/3)} have voted to start the game.")
                    else:
                        await ctx.reply("You have already voted to start.")
                else:
                    await ctx.reply("Not enough players. A minimum of 4 players are necessary to start the game.")

    ## Joint Commands --- Commands that can be used both before the start of and during a game

    @commands.command(name="quit",aliases=["q","leave"])
    async def quit(self, ctx):
        """Werewolf Quit Command. It is used for players to quit the game"""
        try:
            if self.gameRunning:
                # The process for quitting mid game is more complicated at avoid breaking it. It does not make the player leave, it kills them.
                if ctx.author.id in self.players and ctx.channel.id == self.gameChannelId:
                    player = self.players[ctx.author.id]
                    playerRole, consequenceKills = await player.death(deathCause="quit")
                    await ctx.send(f"{player.member.display_name}, a {self.roles[playerRole]}, has fallen off a really, really, really tall mountain.")
                    winCalc = await self.winCalculation(results=False)
                    if await self.winCalculation(results=False):
                        await self.gameOver()
            else:
                # Verifies that the player has actually joined the game
                if ctx.author.id in self.players and ctx.channel.id == self.gameChannelId:
                    self.players.pop(ctx.author.id)
                    self.livingPlayersNames.pop(ctx.author.id)
                    self.playerVotes.pop(ctx.author.id)
                    await ctx.reply(f"You have left the game. There are {len(self.players)} players remaining.")
                    logs.info(f"Player left game, ID: {ctx.author.id}")
                else:
                    return
        except Exception as e:
            print(f"{e}")
            logs.warning(f"Player Quit Error, ID: {ctx.author.id}. Error: {e}")
            await self.gameChannel.send(f"Quit error for {ctx.author.id}. If issues persist, inform host.")

    @commands.command(name="vote",aliases=["v","lynch"])
    async def vote(self, ctx, msg):
        """Werewolf Vote Command. Is used for pre-start gamemode voting and post start lynch voting."""
        try:
            # Verifies the channel the command is being used in
            if ctx.channel.id == self.gameChannelId:
            # This section runs if the game itself is started, uses logic for lynching votes
                if self.gameRunning:
                    if self.isDay:
                        player = self.players[ctx.author.id]
                        target, targetId = await self.closestMatch(msg)
                        if target == None:
                            await ctx.reply(f"Target {msg} not found. Please be more specific")
                            return
                        alreadyVoted = False
                        # Checks if they have already voted, if they have then it updates all of their vote - a player may have several votes (all for the same target) if they have a voting power > 1
                        for vote in self.killVotes:
                            if vote[0] == ctx.author.id:
                                index = self.killVotes.index(vote)
                                self.killVotes[index][1] = target
                                alreadyVoted = True
                        if alreadyVoted == False:
                            # Adds the number of votes equal to the player's voting power
                            for i in range(0,player.votingPower):
                                self.killVotes.append([ctx.author.id,target])
                        # Response to the player
                        await ctx.reply(f"You have voted to lynch {target}")
                        # Runs the lynching calculation at the end
                        lynchResult, resultsMessage = await self.lynchCalculation()
                        if lynchResult:
                            await self.gameChannel.send(resultsMessage)
                            await self.nightTime()
                        else:
                            return
                    else:
                        return
                # This section runs if the game has not started, uses logic for gamemode voting
                else:
                    # Verifies the player is in the game
                    if ctx.author.id in self.players:
                        matches = []
                        # Checks for matches based on their vote
                        for gamemode in self.gamemodes:
                            if msg.lower() in gamemode:
                                matches.append(gamemode)
                        # Responses depending on how many matches are found, if several or none are found their vote isn't registered
                        if matches == []:
                            await ctx.reply("Gamemode not found.")
                        elif len(matches) > 1:
                            outputStr = ""
                            for match in matches:
                                outputStr += match + ", "
                            outputStr = outputStr[:-2]
                            await ctx.reply(f"Several gamemodes found: {outputStr}")
                        else:
                            self.playerVotes[ctx.author.id] = matches[0]
                        await ctx.reply(f"You have voted for {matches[0]}.")
                    else:
                        await ctx.reply("You cannot vote on the gamemode as you haven't joined the game.")
        except Exception as e:
            logs.warning(f"Vote Command Error, ID: {ctx.author.id}. Error: {e}")

    @commands.command(name="retract",aliases=["r"])
    async def retract(self, ctx):
        """Werewolf vote retraction command. Used to withdraw a player's vote in gamemode selection, start voting and post start lynch voting"""
        try:
            if self.gameRunning:
                # Removes all votes by that user as they may have several votes
                self.killVotes = [vote for vote in self.killVotes if vote[0] != ctx.author.id]
                await ctx.reply("Votes withdrawn")
            else:
                if ctx.author.id in self.players:
                    voteWithdrawn = False
                    if ctx.author.id in self.startVoters:
                        self.startVoters.remove(ctx.author.id)
                        voteWithdrawn = True
                    if self.playerVotes[ctx.author.id] != None:
                        self.playerVotes[ctx.author.id] = None
                        voteWithdrawn = True
                    if voteWithdrawn:
                        await ctx.reply("Your vote has been withdrawn.")
                    else:
                        return
                else:
                    pass
                
        except Exception as e:
            logs.warning(f"Retract Command Error, ID: {ctx.author.id}. Error: {e}")
        
    ### Information Commands --- Commands that can be used to get specific information

    @commands.command(name="votes")
    async def votes(self, ctx):
        """Werewolf Votes Command. Used to view the current votecounts for both gamemode selection and post start lynch voting"""
        try:
            # Restricts the command to the relevant werewolf channels
            if ctx.channel.id in [self.gameChannelId, self.spectatorsChannelId]:
                if self.gameRunning:
                    if self.isDay:
                        # Checks if there are any votes:
                        if self.killVotes == []:
                            await ctx.reply("There have been no votes")
                        else:
                            # Extracts the lynch candidates
                            lynchCandidates = []
                            lynchCandidatesAndVoters = []
                            for vote in self.killVotes:
                                if vote[1] not in lynchCandidates:
                                    lynchCandidates.append(vote[1])
                                    lynchCandidatesAndVoters.append([vote[1],[vote[0]]])
                                else:
                                    for row in lynchCandidatesAndVoters:
                                        if row[0] == vote[1]:
                                            row[1].append(vote[0])
                            votesEmbed = discord.Embed(title="Lynch Voting",description=f"{math.ceil(len(self.livingPlayersNames)/2)} required to lynch. If no one is lynched before the end of the day, the person with the most votes will be lynched")
                            for row in lynchCandidatesAndVoters:
                                voters = ""
                                for player in row[1]:
                                    voters += f"<@!{player}>\n"
                                votesEmbed.add_field(name=row[0].title(),value=f"Votes: {len(row[1])}\n{voters}",inline=False)
                            await ctx.send(embed=votesEmbed)
                    else:
                        return
                else:
                    totalVotes = []
                    # Checks votes and voters for each gamemode and totals them up
                    for gamemode in self.gamemodes:
                        gamemodeVoters = []
                        gamemodeVotes = 0
                        for playerID, playerVote in self.playerVotes.items():
                            if playerVote == gamemode:
                                gamemodeVoters.append(playerID)
                                gamemodeVotes += 1
                        if gamemodeVotes > 0:
                            totalVotes.append([gamemode,gamemodeVoters,gamemodeVotes])
                    livingPlayers = await self.livingPlayersMessage(raw=True)
                    if totalVotes == []:
                        await ctx.reply(f"There have been no votes\n```{livingPlayers}```")
                    else:
                        lynchThreshold = math.floor((len(self.livingPlayersNames)/2) + 1)
                        votesEmbed = discord.Embed(title="Gamemode Votes",description=f"{lynchThreshold} votes required to decide a gamemode.\n{livingPlayers}",colour=discord.Color.dark_gold())
                        for row in totalVotes:
                            voters = ""
                            for player in row[1]:
                                voters += f"<@!{player}>\n"
                            votesEmbed.add_field(name=row[0].title(),value=f"Votes: {row[2]}\n{voters}",inline=False)
                        await ctx.reply(embed=votesEmbed)
            else:
                return
        except Exception as e:
            logs.warning(f"Votes Command Error, ID: {ctx.author.id}. Error: {e}")

    @commands.command(name="time",aliases=["t"])
    async def time(self,ctx):
        """Werewolf time command to view the time left in the day"""
        try:
            if ctx.channel.id in [self.gameChannelId, self.spectatorsChannelId] and self.gameRunning:
                if self.isDay:
                    timeLeft = (10*60)-self.timeTracker
                    await ctx.reply(f"Seconds Left: {timeLeft}")
                else:
                    timeLeft = 120 - self.timeTracker
                    await ctx.reply(f"Seconds Left: {timeLeft}")
            else:
                return
        except Exception as e:
            print(f"{e}")
            logs.warning(f"Time Command Error, ID: {ctx.author.id}. Error: {e}")

    @commands.command(name="info")
    async def info(self,ctx):
        """Werewolf info command to return info about the status of the game"""
        try:
            if ctx.channel.id in [self.gameChannelId, self.spectatorsChannelId, self.wolfchatChannelId]:
                if self.gameRunning:
                    # Data Gathering
                    livingPlayers = await self.livingPlayersMessage(raw=True)
                    livingPlayerCount = len(self.livingPlayersNames)
                    if self.isDay:
                        timeOfDay = "Day"
                    else:
                        timeOfDay = "Night"
                    lynchThreshold = math.floor((len(self.livingPlayersNames)/2) + 1)
                    roles = await self.getModeRoles(self.selectedMode,len(self.players),visualList=True)
                    # Embed Construction
                    infoEmbed = discord.Embed(title=f"[{self.gameId}] Game Information",description=f"A {len(self.players)} player game of {self.selectedMode}.\n"+
                    f"It is currently `{timeOfDay}`, and there are `{livingPlayerCount}` living players. The threshold to lynch a player is `{lynchThreshold}`.\n"+
                    f"{livingPlayers}")
                    infoEmbed.add_field(name="Gamemode Roles",value=roles)
                else:
                    infoEmbed = discord.Embed(title="Information",description="Werewolf discord bot for the Rejected Realms by BowShot118")
                    infoEmbed.add_field(name="Gamemodes",value="- Default (16) - The standard werewolf experience\n"+
                                        "- Chaos (16) - (∩｀-´)⊃━☆ﾟ.*･｡ﾟ\n"+
                                        "- Orgy (16) - 👉👈\n")
                await ctx.reply(embed=infoEmbed)
        except Exception as e:
            print(f"{e}")
            logs.warning(f"Info Command Error, ID: {ctx.author.id}. Error: {e}")

    @commands.command(name="roles")
    async def rolesCmd(self, ctx):
        """Werewolf roles command to return overarching roles information. Currently minimally implemented"""
        try:
            if ctx.channel.id in [self.gameChannelId, self.spectatorsChannelId, self.wolfchatChannelId]:
                if self.gameRunning:
                    await ctx.send("Use !info for mid game information")
                else:
                    await ctx.send("A breakdown of roles present in each gamemode can found here: https://docs.google.com/document/d/1hkRtlS_WYfkbp0Q1lQLXpcJ4I5aVFPm9PuDvPkUpdr0/edit?usp=sharing\n"+
                    "This command will be fully implemented in a later version")
        except Exception as e:
            print(f"{e}")
            logs.warning(f"Roles Command Error, ID: {ctx.author.id}. Error: {e}")

    @commands.command(name="role")
    async def roleCmd(self, ctx, *, msg):
        """Werewolf role command to look for specific information on roles"""
        try:
            if ctx.channel.id in [self.gameChannelId, self.spectatorsChannelId, self.wolfchatChannelId]:
                allRoleNames = list(self.roles.values())
                closestOption = None
                for role in allRoleNames:
                    if msg.lower() == role.lower():
                        closestOption = role
                if closestOption == None:
                    await ctx.send(f"Role {msg} not found.")
                    return
                closestMatchId = next((k for k, v in self.roles.items() if v.lower() == closestOption.lower()), None)
                if closestMatchId == None:
                    await ctx.send("An error has occured")
                    return
                await ctx.send(f"{self.roleDescriptions[closestMatchId]}")
        except Exception as e:
            logs.warning(f"Role Command Error, ID: {ctx.author.id}. Error: {e}")
    ### Admin Commands --- Commands to test or force specific interactions. Accessible only to program author

    @commands.command(name="test")
    async def test(self, ctx):
        try:
            if ctx.author.id in self.admins:
                from config import testingIds
                self.testing = True
                for user in testingIds:
                    guild = ctx.guild
                    member = guild.get_member(user)
                    newPlayer = player(member,self)
                    self.players[member.id] = newPlayer
                    self.livingPlayersNames[member.id] = member.name
                    self.playerVotes[member.id] = None
                logs.info(f"Admin Command Used: test, ID: {ctx.author.id}")
                await self.gameStart()
            else:
                return
        except Exception as e:
            print(f"Test Command Error: {e}")
        
    @commands.command(name="force-lynch")
    async def forceLynch(self,ctx):
        try:
            if ctx.author.id in self.admins:
                lynchResult, resultsMessage = await self.lynchCalculation(forceEnd=True)
                if lynchResult:            
                    await self.gameChannel.send(resultsMessage)
                    await self.nightTime()
                logs.info(f"Admin Command Used: force-lynch, ID: {ctx.author.id}")
        except Exception as e:
            print(e)

    @commands.command(name="skip-night")
    async def skipNight(self,ctx):
        try:
            if ctx.author.id in self.admins:
                logs.info(f"Admin Command Used: skip-night, ID: {ctx.author.id}")
                for item in self.players:
                    player = self.players[item]
                    player.actionDone = True
            else:
                return
        except Exception as e:
            print(f"{e}")
    
    @commands.command(name="force-end")
    async def forceEnd(self,ctx):
        try:
            if ctx.author.id in self.admins:
                logs.info(f"Admin Command Used: force-end, ID: {ctx.author.id}")
                await self.gameOver(forceEnd=True)
            else:
                return
        except Exception as e:
            print(f"{e}")

    @commands.command(name="reset")
    async def reset(self,ctx):
        try:
            if ctx.author.id in self.admins:
                logs.info(f"Game Reset by Admin, ID: {ctx.author.id}")
                # Removes Access
                for player in self.players.values():
                    if player.alive:
                        await player.member.remove_roles(self.playerRole,reason=f"Admin Game Reset [{ctx.author.display_name}]")
                        await self.spectatorChannel.set_permissions(player.member,overwrite=None,reason=f"Admin Game Reset [{ctx.author.display_name}]")
                        await self.wolfChannel.set_permissions(player.member,overwrite=None,reason=f"Admin Game Reset [{ctx.author.display_name}]")
                # Clear and Reset Variables
                self.gameRunning = False
                self.isDay = True
                self.winningTeam = None
                self.doubleKill = False
                self.killVotes = []
                self.players = {}
                self.livingPlayersNames = {}
                self.startVoters = []
                self.additionalWinners = []
                self.nightCount = 0
                self.dayCount = 0
                self.winningFool = 0
                self.gameId = 0
                self.impatientVoters = []

                chatOverwrite = self.gameChannel.overwrites_for(self.everyoneRole)
                chatOverwrite.send_messages = True
                await self.gameChannel.set_permissions(self.everyoneRole, overwrite=chatOverwrite, reason=f"Admin Game Reset [{ctx.author.display_name}]")
                await self.gameChannel.send("Game Reset Successfully")
        except Exception as e:
            print(f"{e}")
            logs.critical(f"Reset attempted failed. Admin: {ctx.author.id}. Error: {e}")
 
                    
                    
                    

    ### Game Processes --- Functions to execute stages of the game

    async def gameStart(self):
        try:
            gamemode = "default"
            self.selectedMode = "default"
            # Gathers the list of roles
            rawVotes = list(self.playerVotes.values())
            try:
                if self.testing:
                    gamemode = "testing"
                    self.selectedMode = "testing"
                else:
                    gmCounter = Counter(rawVotes)
                    gamemode, gmCount = gmCounter.most_common(1)[0]
                    # Makes sure a majority of voting players have voted for the gamemode. If they haven't, then it default to default
                    if gmCount >= math.ceil((len(self.playerVotes)/2)):
                        # None is the default vote entered when a player joins the game
                        if gamemode == None:
                            gamemode = "default"
                            self.selectedMode = "default"
                        else:
                            self.selectedMode = gamemode
                    else:
                        self.selectedMode = "default"
                        gamemode = "default"
            except Exception as e:
                print(f"Vote Calculation Error: {e}")
                self.selectedMode = "default"
                gamemode = "default"
            success = await self.initialiseStats()
            if success:
                self.savingStats = True
            else:
                await self.gameChannel.send("Stats failed to initialise.")
                self.savingStats = False
                self.gameId = -1
            self.gameRunning = True
            playerCount = len(self.players)
            vilCount = None
            villagers = []
            gameRoles, secondaryRoles = await self.getModeRoles(self.selectedMode,playerCount)
            # If cursed is present, monitor how many villagers there are so cursed can be properly assigned
            if "S-1" in secondaryRoles:
                vilCount = gameRoles.count("V-1")
            # Locks the channel
            chatOverwrite = self.gameChannel.overwrites_for(self.everyoneRole)
            chatOverwrite.send_messages = False
            await self.gameChannel.set_permissions(self.everyoneRole, overwrite=chatOverwrite, reason=f"[{self.gameId}] Werewolf Game Start")
            ##
            pingList = ""
            # Goes through per player assignment
            for member in self.players:
                pingList += f"<@!{member}>"
                # Player Definition
                indPlayer = self.players[member]
                # Discord Role Assignment
                playerRole = indPlayer.member.guild.get_role(self.playerRoleId)
                await indPlayer.member.add_roles(playerRole,reason=f"[{self.gameId}] Werewolf Game Initiation")
                await self.spectatorChannel.set_permissions(indPlayer.member, read_messages = False, send_messages = False, reason = f"[{self.gameId}] Werewolf Game Initiation")
                # Game Role Assignment
                roleIndex = random.randint(0,(len(gameRoles)-1))
                indPlayer.role = gameRoles[roleIndex]
                indPlayer.originalRole = gameRoles[roleIndex]
                gameRoles.pop(roleIndex)
                print(f"{indPlayer.member.name}, {indPlayer.role}")
                if indPlayer.role == "V-1":
                    villagers.append(indPlayer)
                # Gives wolves explicit access to wolfchat
                if indPlayer.role[0] == "W":
                    await self.wolfChannel.set_permissions(indPlayer.member, read_messages = True, send_messages = True, reason=f"[{self.gameId}] Werewolf Game Initiation")
                else:
                    await self.wolfChannel.set_permissions(indPlayer.member, read_messages = False, send_messages = False, reason=f"[{self.gameId}] Werewolf Game Initiation")
                # DM Portion
                try:
                    await indPlayer.member.send(f"{self.roleIntroductions[indPlayer.role]}")
                except Exception as e:
                    print(f"DM Error: {e}")
                    await self.gameChannel.send(f"<@!{indPlayer.member.id}> The bot cannot dm you, and thus you cannot effectively play the game. Please unblock the bot and run `!myrole` in dms")
            ## Secondary Role Assignment
            # S-1 (Cursed)
            if "S-1" in secondaryRoles:
                cursedCount = secondaryRoles.count("S-1")
                potentialCursed = villagers
                for i in range(1,cursedCount):
                    vilIndex = random.randint(0,vilCount-1)
                    await potentialCursed[vilIndex].defineRole("S-1",False)
                    potentialCursed.pop(vilIndex)
            # S-2 and S-3 (Gunner and Variations)
            if "S-2" in secondaryRoles:
                bulletCount = 0
                assignmentAttempts = 0
                listToManipulate = list(self.players.values())
                # 1 Bullet for every 5 players above 10
                if playerCount < 11:
                    bulletCount = 1
                else:
                    bulletCount = 1 + math.floor((playerCount-10) // 5)
                while "S-2" in secondaryRoles:
                    potentialGunner = random.choice(listToManipulate)
                    validAssignment = False
                    # Prevents wolf team gunner when not using chaos or random
                    if gamemode in ["chaos","random"] and "S-2" not in potentialGunner.secondaryRoles and "S-3" not in potentialGunner.secondaryRoles:
                        validAssignment = True
                    elif potentialGunner.role[0] != "W" and "S-2" not in potentialGunner.secondaryRoles and "S-3" not in potentialGunner.secondaryRoles:
                        validAssignment = True
                    if validAssignment:
                        sharpChance = random.randint(1,5) # 20% Chance of sharpshooter
                        if sharpChance == 1:
                            await potentialGunner.defineRole("S-3",False)
                            potentialGunner.bullets += bulletCount
                            await potentialGunner.member.send("You are a sharpshooter, you cannot miss and you were educated in gun care as a child, or something")
                        else:
                            await potentialGunner.defineRole("S-2",False)
                            potentialGunner.bullets += bulletCount
                        await potentialGunner.member.send(f"You have a gun and {bulletCount} bullets. You may use it during the day to kill someone using `!shoot <player>`")
                        secondaryRoles.remove("S-2")
                    listToManipulate.remove(potentialGunner)
                    assignmentAttempts += 1
                    if assignmentAttempts > 50:
                        await self.gameChannel.send("Issue assigning all of the guns")
                        break
            # S-5 (Assassin)
            if "S-5" in secondaryRoles:
                assignmentAttempts = 0
                while "S-5" in secondaryRoles:
                    potentialAssassin = random.choice(list(self.players.values()))
                    # Eligiblity criteria, must be a villager or cultist (unless it is chaos, when it can be anyone), cannot already be an assassin.
                    if (potentialAssassin.role in ["V-1","T-1"] or gamemode in ["chaos","random"]) and "S-5" not in potentialAssassin.secondaryRoles:
                        potentialAssassin.secondaryRoles.append("S-5")
                        await potentialAssassin.member.send("You are an assassin. You may choose someone to target, who will die if you die, using the `!target <player>` command")
                        secondaryRoles.remove("S-5")
                    assignmentAttempts += 1
                    if assignmentAttempts > 50:
                        await self.gameChannel.send("Issue assigning Assassins")
                        break

            # Channel Messaging
            introEmbed = discord.Embed(title=f"[{self.gameId}] Game Start",description=f"A {playerCount} player game of Werewolf using the {gamemode} gamemode.\n"+
                                    "- All players should have received a dm with their role\n"+
                                    "- All role specific actions take place either in dms with the bot or wolfchat\n"+
                                    "- If there are any issues, please contact BowShot118")
            await self.gameChannel.send(embed=introEmbed,content=pingList)

            # Night Time Initiation
            await self.nightTime()
        except Exception as e:
            logs.critical(f"Game Start Error: {e}")
            await self.gameChannel.send(f"Game Start Failure <@!{self.host}>: {e}")
            print(f"Start Error {e}")

    async def gameOver(self,forceEnd: bool=False):
        """Werewolf function to end the game"""
        try:
            print("Game Over Called")
            # Functional bit, removes living player roles and access
            for item in self.livingPlayersNames:
                player = self.players[item]
                await player.member.remove_roles(self.playerRole,reason=f"[{self.gameId}] Werewolf Game End")
                await self.spectatorChannel.set_permissions(player.member,overwrite=None,reason=f"[{self.gameId}] Werewolf Game End")
                await self.wolfChannel.set_permissions(player.member,overwrite=None,reason=f"[{self.gameId}] Werewolf Game End")
            # Aesthetics Bit
            winningTeam = ""
            if not forceEnd:
                winningTeam, winners = await self.winCalculation(results=True)
            pingList = ""
            winnersText = "Winners: "
            playerRoles = ""
            for item in self.players:
                player = self.players[item]
                pingList += f"<@!{item}>"
                playerRoles += f"{player.member.name} ({self.roles[player.originalRole]})\n"
                if not forceEnd:
                    if player.member.id in winners:
                        winnersText += f"{player.member.name} "
            
            # Stats Saving
            if forceEnd:
                winningTeam = "force-end"
                winners = []
            await self.endOfGameStats(winners,winningTeam)

            # Visual Tweak
            if winningTeam == "village":
                winningTeam = "Village"
            elif winningTeam == "wolfteam":
                winningTeam = "Wolf Team"
            elif winningTeam  == "lovers":
                winningTeam = "Lovers"
            elif winningTeam == "fool":
                winningTeam = "Fool"
            if forceEnd:
                winningTeam = "Forced Quit"
                winnersText = None
            gameEndEmbed = discord.Embed(title=f"[{self.gameId}] Game Over - {winningTeam} Victory",description=winnersText)
            gameEndEmbed.add_field(name="Player Roles",value=playerRoles)
            
            await self.gameChannel.send(content=pingList,embed=gameEndEmbed)

            # Reset the Variables
            self.gameRunning = False
            self.isDay = True
            self.winningTeam = None
            self.doubleKill = False
            self.killVotes = []
            self.players = {}
            self.livingPlayersNames = {}
            self.startVoters = []
            self.additionalWinners = []
            self.nightCount = 0
            self.dayCount = 0
            self.winningFool = 0
            self.impatientVoters = []
            
            # Restoring game channel access
            chatOverwrite = self.gameChannel.overwrites_for(self.everyoneRole)
            chatOverwrite.send_messages = True
            await self.gameChannel.set_permissions(self.everyoneRole, overwrite=chatOverwrite,reason=f"[{self.gameId}] Werewolf Game End")
            self.gameId = 0
            logs.info("Game Over processed successfully")
        except Exception as e:
            logs.critical(f"Game Over Error: {e}")
            await self.gameChannel.send(f"Game End Error <@!{self.host}>: {e}")
            print(f"{e}")

    ## Night Time Functions --- Functions to manage the start of night and end of day

    async def nightTime(self):
        """Werewolf function for the start of night time"""
        try:
            if self.gameRunning:
                # Flips the daytime variable, allowing night actions to take place
                self.nightCount += 1
                self.killVotes = []
                self.impatientVoters = []
                liveWolfTeam = ""
                # Win Condition Check
                if await self.winCalculation(results=False):
                    await self.gameOver()
                    return
                # Living Player Check
                livingPlayersMessage = await self.livingPlayersMessage()

                # Night time action assignments for living players
                for member in self.livingPlayersNames:
                    indPlayer = self.players[member]
                    indPlayer.nightActions = 1
                    # Totem processing for living players
                    if indPlayer.receivedTotems != []:
                        await self.removeTotems(indPlayer.member.id)
                    if "Silence" in indPlayer.specialTotems:
                        indPlayer.specialTotems = []
                        await indPlayer.member.send("You are silenced and cannot carry out any actions tonight")
                        indPlayer.actionDone = True
                    else:
                        indPlayer.specialTotems = []
                        # Roles without Dms
                        if indPlayer.role in ["V-1","T-1"]:
                            indPlayer.actionDone = True
                        # Wolf Team
                        elif indPlayer.role[0] == "W":
                            liveWolfTeam += f"<@!{member}>"
                            # Double kill rule, increases actions by 1 if double kill is enabled
                            if self.doubleKill:
                                indPlayer.nightActions += 1
                            # Traitor Action Flip
                            if indPlayer.role == "W-2":
                                indPlayer.actionDone = True
                            # Wolf Shaman Action Adjustment
                            elif indPlayer.role == "W-3":
                                indPlayer.nightActions += 1
                        # Generic Night Time
                        elif indPlayer.role in ["V-2","V-4"]:
                            await indPlayer.member.send(livingPlayersMessage)
                        # Matchmaker
                        elif indPlayer.role in ["V-5"]:
                            # Only has an action night 1
                            if self.nightCount == 1:
                                await indPlayer.member.send(livingPlayersMessage)
                            else:
                                indPlayer.actionDone = True
                        # Totem Giving Roles
                        if indPlayer.role in ["V-3","N-1","W-3"]:
                            totemOptions = list(self.totems.keys())
                            indPlayer.giveTotem = random.choice(totemOptions)
                            # Shaman & Wolf Shaman
                            if indPlayer.role in ["V-3","W-3"]:
                                await indPlayer.member.send(f"You have the {indPlayer.giveTotem} totem. To give it to another player, use the `!give <player>` command")
                            # Crazed Shaman
                            else:
                                await indPlayer.member.send(f"You have one totem. To give it to another player, use the `!give <player>` command")
                            await indPlayer.member.send(livingPlayersMessage)
                        # Assassin
                        if "S-5" in indPlayer.secondaryRoles and self.nightCount == 1:
                            # If it's with a non power role, it flips the night action back and goes no further
                            if indPlayer.role in ["V-1","T-1","W-2"]:
                                indPlayer.actionDone = False
                            else:
                                indPlayer.nightActions += 1
                            await indPlayer.member.send(livingPlayersMessage)


                # Wolf Chat
                await self.wolfChannel.send(f"{liveWolfTeam}\n{livingPlayersMessage}")
                if self.doubleKill:
                    await self.wolfChannel.send(f"As a wolf cub has died, you may kill **two** players tonight. You do this by voting several times. More than 2 votes will override the old vote.")
                # Starts the two minute timer for night
                self.isDay = False
                logs.info(f"Start of night {self.nightCount} processed successfuly.")
                await self.nightCounter()
        except Exception as e:
            logs.critical(f"Night Time Error: {e}")
            await self.gameChannel(f"Night Time Error <@!{self.host}>: {e}")
            print(f"{e}")

    async def nightCounter(self):
        """Werewolf function that manages the 2 minute countdown for nighttime."""
        try:
            livingPlayerPing = await self.livingPlayersPing()
            await self.gameChannel.send(f"{livingPlayerPing}\nIt is now night")
            self.timeTracker = 0
            for i in range(0,90):
                await asyncio.sleep(1)
                self.timeTracker += 1
                if await self.nightOverCheck():
                    self.isDay = True
                    await self.dayTime()
                    return
            await self.gameChannel.send("30s Remains")
            for i in range(0,20):
                await asyncio.sleep(1)
                self.timeTracker += 1
                if await self.nightOverCheck():
                    self.isDay = True
                    await self.dayTime()
                    return
            await self.gameChannel.send("10s Remains")
            for i in range(0,10):
                await asyncio.sleep(1)
                self.timeTracker += 1
                if await self.nightOverCheck():
                    self.isDay = True
                    await self.dayTime()
                    return
            self.isDay = True
            await self.dayTime()
        except Exception as e:
            print(f"{e}")

    async def nightOverCheck(self):
        """Werewolf function to check if night can end yet or not"""
        canEnd = True
        # Checks if every living player has done their night actions
        for member in self.livingPlayersNames:
            indPlayer = self.players[member]
            if indPlayer.actionDone == False:
                canEnd = False
        return canEnd

    ## Day Time Functions --- Functions to manage the start of day and the end of night

    async def dayTime(self):
        """Werewolf function to execute the start of day"""
        try:
            if self.gameRunning:
                self.dayCount += 1
                self.isDay = True
                livingPlayersPing = await self.livingPlayersPing()
                startOfDayMessage = f"{livingPlayersPing}\nIt is morning\n"
                totemMessages = ""
                deathMessages = ""
                someoneDied = False
                ## Wolf Kill Calculation
                rawWolfVotes = []
                votingWolves = []
                wolfTarget = None
                if self.killVotes == []:
                    pass
                else:
                    for vote in self.killVotes:
                        rawWolfVotes.append(vote[1])
                        if vote[0] not in votingWolves:
                            votingWolves.append(vote[0])
                    if self.doubleKill:
                        doubleNumber = Counter(rawWolfVotes).most_common(2)
                        if len(doubleNumber) == 1:
                            targetOne, targetTwo = doubleNumber[0][0], None
                        else:
                            targetOne, targetTwo = doubleNumber[0][0], doubleNumber[1][0]
                        wolfTarget = [targetOne, targetTwo]
                    else:
                        wolfTarget = [Counter(rawWolfVotes).most_common(1)[0][0]]
                                # Wolf Kill
                try:
                    if wolfTarget == None:
                        pass
                    else:
                        for target in wolfTarget:
                            deadVisitors = []
                            targetPlayer = self.players[target]
                            targetPlayer.lives -= 1
                            if targetPlayer.lives < 1 and targetPlayer.alive:
                                # Visitor Checks for deaths and future saviour Guardians
                                if targetPlayer.visitors != []:
                                    for id in targetPlayer.visitors:
                                        visitor = self.players[id]
                                        # Harlot Visitors also die
                                        if visitor.role == "V-4":
                                            deadVisitors.append(visitor)
                                if targetPlayer.isHome:
                                    playerRole, loverDeaths = await targetPlayer.death("wolf-target")
                                    deathMessages += f"{targetPlayer.member.name}, a {self.roles[playerRole]}, has been consumed by the wolves\n"
                                    someoneDied = True
                                    # If they have bullets, the first voting wolf is given them, unless the bullet holder is a sharpshooter, in which case they are killed
                                    if targetPlayer.bullets > 0:
                                        firstWolf = self.players[votingWolves[0]]
                                        if "S-3" in targetPlayer.secondaryRoles:
                                            deadWolfRole = await firstWolf.death("shot-night")
                                            deathmessages += f"{targetPlayer.member.name} was a sharpshooter and was able to fatally wound {firstWolf.member.name}, a {self.roles[deadWolfRole]}."
                                        else:
                                            firstWolf.bullets = targetPlayer.bullets
                                            await self.wolfChannel.send(f"Amongst the wreckage {firstWolf.member.name} found a gun and {firstWolf.bullets} bullets. They may use `!shoot <player>` during the day to use it.")
                                    if loverDeaths != None:
                                        deathMessages += loverDeaths
                                else:
                                    deathMessages += f"{targetPlayer.member.name} returned home to see their house ransacked\n"
                            # Visitor Deaths
                            if deadVisitors != []:
                                someoneDied = True
                                for visitor in deadVisitors:
                                    visitorRole, loverDeaths = await visitor.death("wolf-victim-visit")
                                    deathMessages += f"{visitor.member.name}, a {self.roles[visitorRole]}, was visiting {targetPlayer.member.name} and was subsequently also consumed by the wolves\n"
                                    if loverDeaths != None:
                                        deathMessages += loverDeaths
                except Exception as e:
                    print(f"No Wolf Kill {e}")
                self.doubleKill = False
                ## Player checks to apply totems and carry out any deaths through to poorly decided visits
                for item in self.players:
                    player = self.players[item]
                    if player.receivedTotems != []:
                        await self.addTotems(player.member.id)
                        if player.alive:
                            totemMessages += f"{player.member.name} has received a totem\n"
                        # Totem Kill
                        if player.lives < 1 and "Death" in player.receivedTotems:
                            playerRole, loverDeaths = await player.death("totem")
                            deathMessages += f"{player.member.name}, a {self.roles[playerRole]}, exploded in the night\n"
                            someoneDied = True
                            if loverDeaths != None:
                                deathMessages += loverDeaths
                        # Visitiation Kills
                    if player.role in ["W-1","W-3","W-4"]:
                        if player.visitors != []:
                            for id in player.visitors:
                                victim = self.players[id]
                                if victim.role in ["V-4"]:
                                    playerRole, loverDeaths = await victim.death("wolf-visit")
                                    deathMessages += f"{victim.member.name}, a {self.roles[playerRole]}, visited a wolf and was killed\n"
                                    someoneDied = True
                                    if loverDeaths != None:
                                        deathMessages += loverDeaths

                if someoneDied == False:
                    deathMessages += f"Everyone appears to have made it through the night unscathed"
                # Lovers Deaths

                    

                # Updates / Clears the relevant variables
                self.killVotes = []
                for item in self.livingPlayersNames:
                    player = self.players[item]
                    player.actionDone = False
                    player.visitors = []
                    player.isHome = True
                
                startOfDayMessage += totemMessages
                startOfDayMessage += deathMessages

                await self.gameChannel.send(startOfDayMessage)
                logs.info(f"Start of day {self.dayCount} processed successfully")
                # Checks if the game has been won or not
                if await self.winCalculation(results=False) == True:
                    await self.gameOver()
                else:
                    await self.dayTimeCounter()
                
        except Exception as e:
            logs.critical(f"Day Start Error: {e}")
            await self.gameChannel.send(f"Day Start Error <@!{self.host}>: {e}")
            print(f"{e}")

    async def dayTimeCounter(self):
        """Werewolf function to handle the automate ending of day after 10 minutes"""
        try:
            self.timeTracker = 0
            for i in range(0,480):
                await asyncio.sleep(1)
                self.timeTracker += 1
                if self.isDay == False or self.gameRunning == False:
                    return
            await self.gameChannel.send("2 Minutes Left")
            for i in range(0,60):
                await asyncio.sleep(1)
                self.timeTracker += 1
                if self.isDay == False or self.gameRunning == False:
                    return
            await self.gameChannel.send("1 Minute Left")
            if i in range(0,30):
                await asyncio.sleep(1)
                self.timeTracker += 1
                if self.isDay == False or self.gameRunning == False:
                    return
            await self.gameChannel.send("30 Seconds Left")
            for i in range(0,30):
                await asyncio.sleep(1)
                self.timeTracker += 1
                if self.isDay == False or self.gameRunning == False:
                    return
            # Call the relevant functions to end day here
            revealed = False
            lynchResult, resultsMessage = await self.lynchCalculation(forceEnd=True)
            if lynchResult:
                await self.gameChannel.send(f"{resultsMessage}")
            self.isDay = False
            await self.nightTime()
        except Exception as e:
            print(f"{e}")

    ### Role Commands - Commands tied to specific roles or specific user requirements

    ## Night Time Commands --- Role functions that can only be used during the night

    @commands.command(name="kill")
    async def kill(self, ctx, msg):
        """Werewolf kill command for wolf team"""
        try:
            # Verifies that it is being called in wolf chat, otherwise it cannot be called. Other night time kill commands will use the target command
            if ctx.channel.id == self.wolfchatChannelId:
                # Verifies the caller has a killer role. Other roles (e.g. Traitor) that cannot kill do have access to wolf chat
                player = self.players[ctx.author.id]
                privilegedIds = []
                if self.testing:
                    privilegedIds = self.admins
                if player.role in ["W-1","W-3","W-4"] or ctx.author.id in privilegedIds:
                    # Can only be used during night
                    if self.isDay == False and "Silence" not in player.specialTotems:
                        target, targetId = await self.closestMatch(msg)
                        if target == None:
                            await ctx.reply(f"Target {msg} not found. Please be more specific")
                            return
                        actualActionDone = False
                        # Splits here, different proccesses/checks depending on if there is a double kill or not
                        if self.doubleKill:
                            existingVotes = []
                            # Finds and collates the player's existing votes
                            for vote in self.killVotes:
                                if vote[0] == ctx.author.id:
                                    index = self.killVotes.index(vote)
                                    existingVotes.append([vote,index])
                            # Checks to see if they have exhausted their votes
                            if len(existingVotes) == 2:
                                noChange = False
                                # This section will replace the first vote in the list with the new target. To prevent the first vote being repeated replaced and not the second, the order of the votes is also swapped
                                for vote in existingVotes:
                                    # No changes if the target has already been voted for
                                    if vote[0][1] == targetId:
                                        noChange = True
                                        break
                                if not noChange:
                                    index1 = existingVotes[0][1]
                                    index2 = existingVotes[1][1]
                                    # Swap the votes and replaces the relevant one
                                    self.killVotes[index1], self.killVotes[index2] = self.killVotes[index2], [ctx.author.id,targetId]
                            elif len(existingVotes) == 1:
                                # Checks if it's already been voted for
                                if existingVotes[0][0][1] == targetId:
                                    pass
                                else:
                                    self.killVotes.append([ctx.author.id,targetId])
                                    actualActionDone = True
                            else:
                                self.killVotes.append([ctx.author.id,targetId])
                                actualActionDone = True
                        else:
                            # Checks if they've already voted. If they have, the vote is updated, if not, their vote is added
                            alreadyVoted = False
                            for vote in self.killVotes:
                                if vote[0] == ctx.author.id:
                                    index = self.killVotes.index(vote)
                                    self.killVotes[index][1] = targetId
                                    alreadyVoted = True
                                    break
                            if alreadyVoted == False:
                                self.killVotes.append([ctx.author.id,targetId])
                                actualActionDone = True
                        if actualActionDone:
                            await player.processActions()
                        await ctx.reply(f"You have voted to kill {target}")
                    else:
                        await ctx.reply("You may only kill during night")
                else:
                    pass
            else:
                pass
        except Exception as e:
            print(e)
            logs.warning(f"Kill Command Error, ID: {ctx.author.id}. Error: {e}")
            await self.wolfChannel.send("Kill Command Error. If issue persists, contact host.")
    
    @commands.command(name="see")
    async def see(self, ctx, msg):
        """Werewolf see command for Seers"""
        try:
            # Checks if the command is being called in dms
            if isinstance(ctx.channel, discord.DMChannel):
                # Checks if the player is a seer
                player = self.players[ctx.author.id]
                if player.role == "V-2":
                    # Verifies it is night
                    if self.isDay == False and "Silence" not in player.specialTotems:
                        # Verifies that the player has not already done their night action. If they have, they cannot use the command again
                        if player.actionDone == False:
                            target, targetId = await self.closestMatch(msg)
                            if target == None:
                                await ctx.reply(f"Target {msg} not found. Please be more specific")
                                return
                            targetPlayer = self.players[targetId]
                            await player.processActions()
                            # Checking if the target player is cursed, as that overrides the seer results
                            if "S-1" in targetPlayer.secondaryRoles:
                                await ctx.reply(f"{target} is a Wolf")
                            # Traitor Check
                            elif targetPlayer.role == "W-2":
                                await ctx.reply(f"{target} is a villager.")
                            else:
                                await ctx.reply(f"{target} is a {self.roles[targetPlayer.role]}")
                        else:
                            await ctx.reply("You may only see one player per night")
            else:
                pass
        except Exception as e:
            logs.warning(f"See Command Error, ID: {ctx.author.id}. Error: {e}")
            print(f"{e}")
        
    @commands.command(name="give")
    async def give(self, ctx, msg):
        """Werewolf give command for shamans of all flavour to give their totems"""
        try:
            if isinstance(ctx.channel, discord.DMChannel):
                player = self.players[ctx.author.id]
                # Verifies that they are a totem giving role
                if player.role in ["V-3","N-1","W-3"]:
                    if self.isDay == False and "Silence" not in player.specialTotems and player.actionDone == False:
                        # Verifies that they haven't already sent a totem/have one to send
                        if player.giveTotem == "":
                            return
                        totem = player.giveTotem
                        target, targetId = await self.closestMatch(msg)
                        if target == None:
                            await ctx.send(f"Target {msg} not found. Please be more specific")
                            return
                        if targetId == player.lastTarget:
                            await ctx.send("You cannot give a totem to the same person twice in a row")
                            return
                        player.lastTarget = targetId
                        targetPlayer = self.players[targetId]
                        targetPlayer.receivedTotems.append(totem)
                        player.giveTotem = ""
                        await player.processActions()
                        if player.role in ["N-1"]:
                            await ctx.send(f"{targetPlayer.member.name} has been given the totem")
                        else:
                            await ctx.send(f"{targetPlayer.member.name} has been given the **{totem.title()}** totem")
        except Exception as e:
            logs.warning(f"Give Command Error, ID: {ctx.author.id}. Error: {e}")
            print(f"{e}")

    @commands.command(name="visit")
    async def visit(self, ctx, msg):
        """Werewolf visit command for players to visit other players during the night"""
        try:
            if isinstance(ctx.channel, discord.DMChannel):
                player = self.players[ctx.author.id]
                # Verifies that the player is a visiting role
                if player.role in ["V-4"]:
                    # Verifies it is night, they aren't silenced, and they haven't already carried out their night action
                    if self.isDay == False and "Silence" not in player.specialTotems and player.actionDone == False and player.isHome:
                        target, targetId = await self.closestMatch(msg)
                        if target == None:
                            await ctx.send(f"Target {msg} not found. Please be more specific")
                            return
                        try:
                            targetPlayer = self.players[targetId]
                        except Exception as e:
                            print(f"Target Issue: {e}")
                        if targetId == player.member.id:
                            await ctx.send(f"If you want to stay home, use the `!stayhome` command.")
                            return
                        # Adds the player in question to the target player's visitor list and signifies that they aren't home
                        targetPlayer.visitors.append(player.member.id)
                        player.isHome = False
                        await player.processActions()
                        # Harlot Specific Code - Unnecessary check at command creation but this will be used for other roles e.g. Guardian
                        if player.role == "V-4":
                            await ctx.reply(f"You are now visiting {targetPlayer.member.name}.")
                            # Tells the target they've been visited
                            await targetPlayer.member.send(f"You have been visited by {player.member.name}")
        except Exception as e:
            logs.warning(f"Visit Command Error, ID: {ctx.author.id}. Error: {e}")
            print(f"{e}")

    @commands.command(name="stayhome")
    async def stayHome(self, ctx):
        """Werewolf stay home command for visiting players to stay home during the night"""
        try:
            if isinstance(ctx.channel, discord.DMChannel):
                player = self.players[ctx.author.id]
                # Verifies the player is a visiting role
                if player.role in ["V-4"]:
                    if self.isDay == False and "Silence" not in player.specialTotems and player.actionDone == False:
                        await ctx.send("You are staying home tonight.")
                        player.isHome = True
                        await player.processActions()
        except Exception as e:
            logs.warning(f"Stay Home Command Error, ID: {ctx.author.id}. Error: {e}")
            print(f"{e}")

    @commands.command(name="choose")
    async def choose(self, ctx, *, msg):
        """Werewolf choose command, to choose two individuals. Used by matchmaker"""
        try:
            if isinstance(ctx.channel, discord.DMChannel):
                player = self.players[ctx.author.id]
                # Verifies the player is a correct role
                if player.role in ["V-5"]:
                    if self.isDay == False and "Silence" not in player.specialTotems and player.actionDone == False:
                        # Verifies input format
                        if " and " not in msg:
                            await ctx.send("Formatting Error, please use `!choose <player1> and <player2>`")
                            return
                        
                        # Strip and format the message for processing
                        target1, target2 = msg.split(" and ",1)
                        target1 = target1.strip().lower()
                        target2 = target2.strip().lower()

                        # Actual Target Identification
                        player1, player1id = await self.closestMatch(target1)
                        player2, player2id = await self.closestMatch(target2)
                        if player1 == None:
                            await ctx.send(f"Cannot find {target1}")
                        if player2 == None:
                            await ctx.send(f"Cannot find {target2}")
                        if player1 is not None and player2 is not None:
                            # Logic to define lovers goes here
                            result = await self.pairLovers(player1,player2)
                            if result:
                                await ctx.send(f"You have chosen {player1} and {player2}")
                        await player.processActions()
        except Exception as e:
            logs.warning(f"Choose Command Error, ID: {ctx.author.id}. Error: {e}")
            print(f"{e}")

    @commands.command(name="target")
    async def target(self, ctx, msg):
        """Werewolf target command, to target an individual. Used by assassin"""
        try:
            if isinstance(ctx.channel, discord.DMChannel):
                player = self.players[ctx.author.id]
                # Verifies player role
                if "S-5" in player.secondaryRoles:
                    if self.isDay == False and self.nightCount == 1 and player.actionDone == False:
                        target, targetId = await self.closestMatch(msg)
                        if target == None:
                            await ctx.send(f"Target {msg} not found. Please be more specific")
                            return
                        if player.target != 0:
                            await ctx.send(f"You have already targeted a player.")
                            return
                        player.target = targetId
                        print(player.target)
                        print(targetId)
                        await player.processActions()
                        targetPlayer = self.players[targetId]
                        await ctx.reply(f"You have targeted {targetPlayer.member.name}.")
        except Exception as e:
            logs.warning(f"Target Command Error, ID: {ctx.author.id}. Error: {e}")
            print(f"{e}")
    ## Day Time Commands --- Role functions that can only be used during the night

    @commands.command(name="shoot")
    async def shoot(self, ctx, msg):
        """Werewolf shoot command for gunners"""
        try:
            if ctx.channel.id == self.gameChannelId and self.isDay:
                player = self.players[ctx.author.id]
                deadPlayer = None
                accident = False
                if player.bullets == 0:
                    await player.member.send("You have no bullets")
                    return
                else:
                    target, targetId = await self.closestMatch(msg)
                    print(f"Target: {target}")
                    if target == None:
                        await ctx.send(f"Target {msg} not found. Please be more specific")
                        return
                    try:
                        targetPlayer = self.players[targetId]
                    except Exception as e:
                        print(f"Target Issue: {e}")
                    # If they are silly enough to target themselves they are guaranteed to die
                    if targetId == player.member.id:
                        traitorifiedRole = player.role
                        if player.role == "W-2":
                            traitorifiedRole = "V-1"
                        await self.gameChannel.send(f"{player.member.name}, a {self.roles[traitorifiedRole]}, decided it was a good idea to look down the barrel of the gun while pulling the trigger.")
                        deadPlayer = player
                    else:
                        # The gun has a chance to blow up on use unless they are a sharpshooter
                        blowupRoll = random.randint(1,5) # 20% chance
                        if blowupRoll == 1 and "S-3" not in player.secondaryRoles:
                            traitorifiedRole = player.role
                            if player.role == "W-2":
                                traitorifiedRole = "V-1"
                            await self.gameChannel.send(f"{player.member.name}, a {self.roles[traitorifiedRole]}, pulled the trigger and the gun exploded.")
                            deadPlayer = player
                            accident = True
                        else:
                            deadPlayer = targetPlayer
                            traitorifiedRole = targetPlayer.role
                            if player.role == "W-2":
                                traitorifiedRole = "V-1"
                            await self.gameChannel.send(f"{targetPlayer.member.name}, a {self.roles[traitorifiedRole]}, was shot and killed by {player.member.name}.")
                            player.bullets -= 1
                    # Executes the death and evaluates the win condition
                    if accident:
                        deadPlayerRole, deadLovers = await deadPlayer.death("shot-accident")
                    else:
                        deadPlayerRole, deadLovers = await deadPlayer.death("shot-day")
                    if deadLovers != None:
                        await self.gameChannel.send(deadLovers)
                    if await self.winCalculation(results=False):
                        await self.gameOver()

        except Exception as e:
            logs.warning(f"Shoot Command Error, ID: {ctx.author.id}. Error: {e}")
            print(f"{e}")

    @commands.command(name="nl",aliases=["nolynch"])
    async def noLynch(self, ctx):
        try:
            if ctx.channel.id == self.gameChannelId and self.isDay:
                player = self.players[ctx.author.id]
                alreadyVoted = False
                # Checks for existing votes, if there are any it updates those votes
                for vote in self.killVotes:
                    if vote[0] == ctx.author.id:
                        index = self.killVotes.index(vote)
                        self.killVotes[index][1] = "nl"
                        alreadyVoted = True
                # Adds votes (the number of votes added varies based on the player's voting power) if they have not already voted
                if alreadyVoted == False:
                    for i in range(0,player.votingPower):
                        self.killVotes.append([ctx.author.id,"nl"])
                
                await ctx.reply(f"You have voted to abstain today")

                # Runs a no lynch calculation
                if await self.noLynchCheck():
                    await self.gameChannel.send("The village has decided to not lynch anyone today")
                    
                    await self.nightTime()

        except Exception as e:
            logs.warning(f"No Lynch Command Error, ID: {ctx.author.id}. Error: {e}")
            print(f"{e}")

    ## 24/7 Commands --- Role functions that can be used any time of day

    @commands.command(name="myrole")
    async def myRole(self,ctx):
        """Werewolf command to see their own role"""
        try:
            if isinstance(ctx.channel, discord.DMChannel):
                if ctx.author.id in self.livingPlayersNames:
                    player = self.players[ctx.author.id]
                    await ctx.reply(f"{self.roleIntroductions[player.role]}")
                    if player.actionDone == False:
                        livePlayerMessage = await self.livingPlayersMessage()
                        await ctx.send(f"{livePlayerMessage}")
        except Exception as e:
            logs.warning(f"My Role Command Error, ID: {ctx.author.id}. Error: {e}")
            print(f"{e}")

    ### Check Functions --- Functions that check specific conditions or calculate and execute specific processes used throughout the game

    async def lynchCalculation(self,forceEnd: bool=False):
        """Werewolf function to calculate lynch voting.
        Args:
            forceEnd (bool): Toggleable option to force calculate the 'winner' of the vote, even if the threshold has not been met. Used for end of day calculations
        Returns:
            List | None"""
        try:
            # Checks if there are any votes
            if self.killVotes == []:
                return None
            # Generates a list of raw votes
            lynchVotes = []
            for vote in self.killVotes:
                lynchVotes.append(vote[1])
            counter = Counter(lynchVotes)
            maxCount = max(counter.values())
            mostCommonItems = [item for item, count in counter.items() if count == maxCount]
            target = mostCommonItems
            # If the most popular vote is no lynch then no lynching occurs
            if target == "nl":
                return None
            # Checks for a tie
            if len(target) > 1:
                return None
            else:
                self.workingImpatientVoters = []
                target = mostCommonItems[0]
                # Impatience Calculations
                for voter in self.impatientVoters:
                    # Checking if the target is the impatient voter
                    valid = True
                    if target == self.livingPlayersNames[voter]:
                        valid = False
                    else:
                        for vote in self.killVotes:
                            # Checking if the impatient voter has already voted for the target
                            if vote[0] == voter:
                                if vote[1] == target:
                                    valid = False
                                    break

                    if valid == True:
                        # Pacifism Check
                        votingPlayer = self.players[voter]
                        print(votingPlayer.votingPower)
                        if votingPlayer.votingPower > 0:
                            self.workingImpatientVoters.append(voter)
                threshold = math.floor((len(self.livingPlayersNames)/2)-len(self.workingImpatientVoters) + 1)
                print(f"Lynch Threshold: {threshold}")
                # Checking if the target has met the threshold and the game isn't forcing a lynch calculation
                if maxCount < threshold and forceEnd == False:
                    return False, None
                else:
                    targetId = next((k for k, v in self.livingPlayersNames.items() if v == target), None)
                    resultsMessage = ""
                    lynchedPlayer = self.players[targetId]
                    if len(self.workingImpatientVoters) > 0:
                        for voter in self.workingImpatientVoters:
                            await self.gameChannel.send(f"<@!{voter}> was impatient and voted for {lynchedPlayer.member.name}.")
                    if "Reveal" in lynchedPlayer.specialTotems:
                        lynchedRole = await self.revealTotem(targetId)
                        revealed = True
                        resultsMessage = f"{lynchedPlayer.member.name} has a fancy totem thing and survived, they are revealed to be a {self.roles[lynchedRole]}"
                    else:
                        targetRole, loverDeaths = await lynchedPlayer.death("lynch")
                        resultsMessage = f"{lynchedPlayer.member.name}, a {self.roles[targetRole]}, has been lynched.\n"
                        # Fool gamerule
                        if targetRole == "N-3":
                            self.winningFool = lynchedPlayer.member.id
                        # Jester
                        if targetRole in ["N-2"]:
                            self.additionalWinners.append(lynchedPlayer.member.id)
                        if loverDeaths != None:
                            resultsMessage += loverDeaths
                        if "Desperation" in lynchedPlayer.specialTotems:
                            lastVoter = self.killVotes[-1][0]
                            lastVoterPlayer = self.players[lastVoter]
                            lastVoterRole, loverDeaths = await lastVoterPlayer.death("totem-desp")
                            resultsMessage += f"There is a blinding flashing light, or something, I don't remember how these go, {lastVoterPlayer.member.name}, a {self.roles[lastVoterRole]}, is found dead\n"
                            if loverDeaths != None:
                                resultsMessage += loverDeaths
                return True, resultsMessage
        except Exception as e:
            print(f"Lynch Error: {e}")

    async def noLynchCheck(self):
        """Werewolf function to check if a no lynch has taken place
        Returns:
            Result (bool): True for a successful nolynch, false otherwise"""
        try:
            # Checks if there are any votes and totals up the votes for no lynching
            if self.killVotes == []:
                return False
            nlCount = 0
            for vote in self.killVotes:
                if vote[1] == "nl":
                    nlCount += 1
            # Calculation portion - nolynch has a different threshold, impatient voters are ignored and it is an exact 50%, not a 50%+ threshold
            threshold = math.ceil(len(self.livingPlayersNames)/2)
            if nlCount >= threshold:
                return True
            else:
                return False
        except Exception as e:
            print(f"No Lynch Calc Error: {e}")

    async def winCalculation(self,results: bool):
        """Werewolf function to calculate when a win condition has been reached
        Args:
            results (bool): When True - Returns the full results, when False, returns whether or not the win condition has been met or not"""
        try:
            # Categorises the surviving players
            aliveVillageTeam = []
            aliveWolfTeam = []
            survivingWinners = []
            otherSurvivors = []
            loverSurvivors = []
            villageTeam = []
            wolfTeam = []
            winningTeam = ""
            winners = []
            winnersList = []
            haveWinners = False
            # Gathering survivors
            for item in self.livingPlayersNames:
                player = self.players[item]
                if player.role[0] == "V":
                    aliveVillageTeam.append(player.member.id)
                elif player.role[0] == "W":
                    aliveWolfTeam.append(player.member.id)
                else:
                    otherSurvivors.append(player.member.id)
                if "S-4" in player.secondaryRoles:
                    loverSurvivors.append(player.member.id)
            # Fool winner calculation
            if self.winningFool != 0:
                winners = "fool"
                haveWinners = True
            # Lovers Win Calculation
            if len(loverSurvivors) >= len(self.livingPlayersNames):
                winners = "lovers"
                haveWinners = True
            else:
            # Wolf Team Win Calculation
                if len(aliveWolfTeam) >= (len(aliveVillageTeam) + len(survivingWinners) + len(otherSurvivors)):
                    winners = "wolfteam"
                    haveWinners = True
                # Village Team Win Calculation
                elif len(aliveWolfTeam) == 0:
                    winners = "village"
                    haveWinners = True
            if haveWinners == False:
                return None
            if results == True:
                # Gathers the teams
                for item in self.players:
                    player = self.players[item]
                    if player.role[0] == "V":
                        villageTeam.append(player.member.id)
                    elif player.role[0] == "W" or player.role[0] == "T":
                        wolfTeam.append(player.member.id)
                    # Crazed Shaman unique win condition
                    elif player.role == "N-1" and player.alive:
                        winnersList.append(player.member.id)
                # Team based winners added
                if winners == "village":
                    for player in villageTeam:
                        winnersList.append(player)
                elif winners == "wolfteam":
                    for player in wolfTeam:
                        winnersList.append(player)
                elif winners == "lovers":
                    for player in loverSurvivors:
                        winnersList.append(player)
                elif winners == "fool":
                    winnersList.append(self.winningFool)
                # Adding mid game winners
                for row in self.additionalWinners:
                    winnersList.append(row)
                return winners, winnersList
            else:
                return haveWinners
        except Exception as e:
            print(f"Win Calculation Error: {e}")

    async def checkTraitor(self):
        """Werewolf function to check if the requirements for a traitor to wolf-ify are met
        Returns:
            promotion (bool): True = Promotion, False = No Promotion"""
        livingWolfCount = 0
        validTraitorIds = []
        # Gathers the number of wolves and the ids of all surviving traitors
        for item in self.livingPlayersNames:
            player = self.players[item]
            if player.role in ["W-1"]:
                livingWolfCount += 1
            elif player.role == "W-2":
                validTraitorIds.append(player.member.id)
        
        # Checks if there are any living wolves
        if livingWolfCount > 0:
            return False
        # If there are no living wolves
        else:
            # Checks for eligible traitors. If there any, takes the first out of the list
            if validTraitorIds != []:
                # Changes the traitor's role to wolf and returns True to signify a promotion has occured
                promotionId = validTraitorIds[0]
                promotedTraitor = self.players[promotionId]
                promotedTraitor.role = "W-1"
                await promotedTraitor.member.send(f"As all the wolves have died, you are now a **Wolf**. You may kill a villager during the night using the `!kill <player>` command. See See https://discord.com/channels/{self.serverId}/{self.wolfchatChannelId}.")
                return True
        return False

    async def pairLovers(self,lover1 : str,lover2 : str):
        """Werewolf function to process two lovers.
        Args:
            lover1 (str): The first lover to pair.
            lover2 (str): The second lover to pair
        Returns:
            success (bool): Whether or not the process was executed successfully"""
        # Gathers the lovers player values
        try:
            player1Id = next((k for k, v in self.livingPlayersNames.items() if v == lover1), None)
            player2Id = next((k for k, v in self.livingPlayersNames.items() if v == lover2), None)
            if player1Id == None or player2Id == None:
                return False
            player1 = self.players[player1Id]
            player2 = self.players[player2Id]
            # Player 1 lover assignment
            player1.lovers.append(player2.member.id)
            player1.secondaryRoles.append("S-4")
            await player1.member.send(f"You are in love with {player2.member.name}")
            # Player 2 lover assignment
            player2.lovers.append(player1.member.id)
            player2.secondaryRoles.append("S-4")
            await player2.member.send(f"You are in love with {player1.member.name}")
            return True
        except Exception as e:
            print(f"{e}")

    ### Totems Functions --- Functions that process the application of totems

    async def addTotems(self,playerId):
        """Werewolf function to add a player's totems to their stats
        Args:
            playerId (int): The player's ID"""
        player = self.players[playerId]
        # Verifies the player has totems
        if len(player.receivedTotems) > 0:
            # Applies the effects of the totems or stores them in specific storage if they do not apply a strict stat change
            for totem in player.receivedTotems:
                match totem:
                    case "Protection":
                        player.lives += 1
                    case "Death":
                        player.lives -= 1
                    case "Influence":
                        player.votingPower += 1
                    case "Pacifism":
                        if player.votingPower > 0:
                            player.votingPower -= 1
                    case "Impatience":
                        self.impatientVoters.append(player.member.id)
                    case _:
                        player.specialTotems.append(totem)
                
    async def removeTotems(self,playerId):
        """Werewolf function to remove a player's totems. Does not handle special totems. Impatience is removed seperately
        Args:
            playerId (int): The player's ID"""
        player = self.players[playerId]
        if len(player.receivedTotems) > 0:
            for totem in player.receivedTotems:
                match totem:
                    case "Protection":
                        if player.lives == 1:
                            pass
                        else:
                            player.lives -= 1
                    case "Death":
                        if player.lives == 1:
                            pass
                        else:
                            player.lives += 1
                    case "Influence":
                        player.votingPower = 1
                    case "Pacifism":
                        player.votingPower = 1
            player.receivedTotems = []
    
    async def revealTotem(self,playerId):
        """Werewolf function to execute the reveal totem on a player and reveal their role."""
        player = self.players[playerId]
        if "Reveal" in player.specialTotems:
            # Applies the traitor effect
            if player.role == "W-2":
                return "V-1"
            else:
                return player.role

    ### Utility Functions --- Other Functions

    async def livingPlayersMessage(self, raw: bool = False):
        """Werewolf function that checks the list for alive players and returns them in two formats"""
        if raw:
            livingPlayersMessage = "**Living Players**\n"
            for id, name in self.livingPlayersNames.items():
                livingPlayersMessage += f"{name} ({id})\n"
        else:
            livingPlayersMessage = "**Living Players** ```\n"
            for id, name in self.livingPlayersNames.items():
                livingPlayersMessage += f"{name} ({id})\n"
            
            livingPlayersMessage += "```"
        return livingPlayersMessage

    async def livingPlayersPing(self):
        livingPlayersPing = ""
        for player in self.livingPlayersNames:
            livingPlayersPing += f"<@!{player}>"
        
        return livingPlayersPing
    
    async def closestMatch(self,msg):
        """Function to return the closest match for use in mid game commands\n
        Order of Search:
            - ID
            - Discord Username
            - Server Nickname
        Returns:
            closestMatch (str | None) - The user that is the closest match to the input.\n
            closestMatchId (int | None) - The id of the user that is the closest match to the input."""
        closestMatch = ""
        msg = msg.lower()

        ## Checking Ids
        validIds = list(self.livingPlayersNames.keys())
        try:
            if int(msg) in validIds:
                closestMatch = self.livingPlayersNames[int(msg)]
                return closestMatch, int(msg)
        except Exception as e:
            print(f"Closest Match ID Failure: {e}")
        
        ## Nickname Searching
        livingPlayerMatchesNics = []
        livingPlayersIds = []
        # Collating a list of server names
        for player in self.players.values():
            if player.alive:
                if player.member.display_name.startswith(msg):
                    livingPlayerMatchesNics.append(player.member.display_name)
                    livingPlayersIds.append(player.member.id)
        # Target Selection / Identification
        if len(livingPlayerMatchesNics) == 1:
            id = livingPlayersIds[0]
            closestMatch = self.livingPlayersNames[id]
            return closestMatch, id
        elif len(livingPlayerMatchesNics) > 1:
            closestOption = get_close_matches(msg,livingPlayerMatchesNics,1,cutoff=0.5)
            if closestOption != []:
                closestOption = closestOption[0]
                index = livingPlayerMatchesNics.index(closestOption)
                id = livingPlayersIds[index]
                closestMatch = self.livingPlayersNames[id]
                return closestMatch, id

        ## Discord Name Searching

        validMatches = list(self.livingPlayersNames.values())
        allMatches = []
        for possible in validMatches:
            if possible.startswith(msg):
                allMatches.append(possible)
        if len(allMatches) == 1:
            closestMatch = allMatches[0]
        elif allMatches == []:
            return None, None
        else:
            print(allMatches)
            closestMatch = allMatches[0]
        closestMatchId = next((k for k, v in self.livingPlayersNames.items() if v == closestMatch), None)
        return closestMatch, closestMatchId

    async def getModeRoles(self, mode: str, playerCount: int, visualList : bool=False):
        """Function to retrieve the roles for a game of specified size"""
        # Translating the text gamemode into the dict
        if mode == "default":
            rolesDict = self.default
        elif mode == "chaos":
            rolesDict = self.chaos
        elif mode == "orgy":
            rolesDict = self.orgy
        elif mode == "testing":
            rolesDict = self.testingMode
        # Defaults to default if there is an issue with the content passed into the mode parameter
        else:
            rolesDict = self.default 

        index = rolesDict["players"].index(playerCount)
        # Output mode selection
        if visualList:
            outputStr = ""
            for role in rolesDict:
                if role == "players":
                    pass
                else:
                    roleName = self.roles[role]
                    roleCount = rolesDict[role][index]
                    if roleCount > 0:
                        outputStr += f"{roleName} (x{roleCount}), "
            outputStr = outputStr[:-2]
            return outputStr
        else:
            roles = []
            secondaryRoles = []
            for role in rolesDict:
                if role == "players":
                    pass
                else:
                    roleName = role
                    roleCount = rolesDict[role][index]
                    if roleCount >= 1:
                        # Split off the secondary roles into their own list
                        if roleName[0] == "S":
                            for i in range(0,roleCount):
                                secondaryRoles.append(roleName)
                        else:
                            for i in range(0,roleCount):
                                roles.append(roleName)

            return roles, secondaryRoles

    ### Stats Functions --- Functions to process and save statistics

    ## Stats View Command
    # These are SLASH COMMANDS in contrast to every other commands in this server
    @app_commands.command(name="ww_playerstats",description="Command to view your werewolf stats")
    @app_commands.choices(type=[app_commands.Choice(name="Overview",value=1),app_commands.Choice(name="Deaths",value=2),
                                app_commands.Choice(name="Roles",value=3)])
    async def playerStats(self, interaction: discord.Interaction,player: discord.User, type: app_commands.Choice[int]):
        deathsDict = {
            "alive" : "Survived",
            "lover" : "Lover Suicide",
            "assassin" : "Assassinated",
            "wolf-target" : "Killed in the night by wolves",
            "wolf-victim-visit" : "Visited a wolf's victim",
            "wolf-visit" : "Visited a wolf",
            "totem-death" : "Magic (Death Totem)",
            "totem-desp" : "Magical lynching mishaps (Desperation Totem)",
            "shot-night" : "Shot trying to take someone's gun",
            "shot-day" : "Was shot during the day",
            "shot-accident" : "Their gun exploded",
            "lynch" : "Lynched by the village",
            "quit" : "Quit the game"
        }
        try:
            await interaction.response.defer()
            match type.value:
                # Overview
                case 1:
                    winCount, lastGame, mostCommonRole, mostCommonDeath, gamesPlayed, allDeaths = await self.viewPlayerStatsGeneral(player.id)
                    if winCount == None:
                        await interaction.response.send_message("User has no game stats",ephemeral=True)
                        return
                    gamesWonPercentage = round((winCount/gamesPlayed)*100,2)
                    deathPercentage = round((len(allDeaths)/gamesPlayed)*100,2)
                    statsEmbed = discord.Embed(title="Werewolf Statistics",description="An overview of player stats",color=discord.Color.dark_purple())
                    statsEmbed.set_author(name=player.display_name,icon_url=player.display_avatar)
                    statsEmbed.add_field(name="Statistics",value=f"**Games Played:** `{gamesPlayed}`\n"+
                                                                f"**Games Won:** `{winCount} ({gamesWonPercentage}%)`\n"+
                                                                f"**Death Count:** `{len(allDeaths)} ({deathPercentage}%)`",inline=True)
                    statsEmbed.add_field(name="\u200b",value=f"**Most Common Role:** {self.roles[mostCommonRole]}\n"+
                                                    f"**Most Common Death:** {deathsDict[mostCommonDeath]}\n",inline=True)
                    winStat = "Lost"
                    if lastGame[4] == 1:
                        winStat = "Won"
                    statsEmbed.add_field(name=f"Last Game [{lastGame[1]}]",value=f"**Game Result:** Player {winStat}\n"+
                                        f"**Role:** {self.roles[lastGame[2]]}\n"+
                                        f"**Death Status:** {deathsDict[lastGame[3]]}",inline=False)

                    statsEmbed.set_footer(text="Report any issues to your bot's host")
                    await interaction.followup.send(embed=statsEmbed)
                # Deaths
                case 2:
                    statsEmbed = discord.Embed(title="Werewolf Death Statistics",description="An overview of how a player has died",color=discord.Color.dark_red())
                    statsEmbed.set_author(name=player.display_name,icon_url=player.display_avatar)
                    statsEmbed.set_footer(text="Report any issues to your bot's host")
                    deathStats = await self.viewPlayerStatsDeaths(player.id)
                    if deathStats == None:
                        await interaction.followup.send("This user has no game stats",ephemeral=True)
                        return
                    outputMessage = ""
                    for reason, count in deathStats:
                        outputMessage += f"{deathsDict[reason]} (x{count})\n"
                    
                    statsEmbed.add_field(name="Reasons for Death",value=outputMessage)
                    await interaction.followup.send(embed=statsEmbed)
                # Roles
                case 3:
                    statsEmbed = discord.Embed(title="Werewolf Role Statistics",description="An overview of the roles a player has held",color=discord.Color.dark_blue())
                    statsEmbed.set_author(name=player.display_name,icon_url=player.display_avatar)
                    statsEmbed.set_footer(text="Report any issues to your bot's host")
                    rolesStats = await self.viewPlayerStatsRoles(player.id)
                    if rolesStats == None:
                        await interaction.followup.send("This user has no game stats",ephemeral=True)
                        return
                    outputMessage = ""
                    for role, count in rolesStats:
                        outputMessage += f"{self.roles[role]} (x{count})\n"
                    
                    statsEmbed.add_field(name="Roles Held",value=outputMessage)
                    await interaction.followup.send(embed=statsEmbed)
        except Exception as e:
            print(f"{e}")
            logs.warning(f"Player stats search failure, ID: {interaction.user.id}. Error: {e}")

    ## Saving Stats
    async def initialiseStats(self):
        """This creates the game in the database and updates the gameId for later use\n
        Returns True when it's successful, False when it isn't"""
        try:
            con = sqlite3.connect(statsDb)
            cur = con.cursor()
            res = cur.execute("INSERT INTO gameStats(daycount,nightCount,winningTeam,endTime,serverId,playerCount) VALUES (?,?,?,?,?,?);",(1,1,"initialised",0,self.guild.id,len(self.players)))
            con.commit()
            res = cur.execute("SELECT gameId FROM gameStats ORDER BY gameId DESC Limit 1")
            generatedGameId = res.fetchone()
            con.close()
            if generatedGameId == None:
                return False
            else:
                self.gameId = generatedGameId[0]
                logs.info(f"Game Stats Initialised: {self.gameId}")
                return True
        except Exception as e:
            print(f"{e}")
            logs.critical(f"Stats failed to Initialise, Error: {e}")
            return False

    async def endOfGameStats(self,winners,winningTeam):
        """Werewolf function to save the end of the game stats"""
        # Updates the proper game database
        with sqlite3.connect(statsDb) as con:
            cur = con.cursor()
            currentTime = int(time.time())
            res = cur.execute("UPDATE gameStats SET dayCount = ?, nightCount = ?, winningTeam = ?, endTime = ? WHERE gameID = ?",(self.dayCount,self.nightCount,winningTeam,currentTime,self.gameId))
            con.commit()

        for player in self.players.values():
            winning = False
            if player.member.id in winners:
                winning = True
            await player.saveStats(self.gameId,winning)

    ## Viewing Stats
    async def viewPlayerStatsGeneral(self, discordId: int):
        """Werewolf function to collate player stats
        Args:
            discordId (int): The discord id of the player whose stats you want to search for"""
        with sqlite3.connect(statsDb) as con:
            cur = con.cursor()
            res = cur.execute("SELECT * FROM playerStats WHERE playerID = ?",(discordId,))
            allPlayerStats = res.fetchall()
        
        if allPlayerStats == []:
            return None, None, None, None, None, None
        # Collating stats
        gamesPlayed = len(allPlayerStats)
        allRoles = []
        allDeaths = []
        winCount = 0
        lastGame = ()
        mostCommonRole = ""
        mostCommonDeath = ""
        for row in allPlayerStats:
            allRoles.append(row[2])
            allDeaths.append(row[3])
            if row[4] == 1:
                winCount += 1

        lastGame = allPlayerStats[-1]
        
        # Calculating the most commons
        mostDeathCounter = Counter(allDeaths)
        mostCommonTuple = mostDeathCounter.most_common(2)
        if len(mostCommonTuple) == 1:
            if mostCommonTuple[0][0] == "alive":
                mostCommonDeath = None
        else:
            if mostCommonTuple[0][0] == "alive":
                mostCommonDeath = mostCommonTuple[1][0]
            else:
                mostCommonDeath = mostCommonTuple[0][0]

        mostRoleCounter = Counter(allRoles)
        mostCommonTuple = mostRoleCounter.most_common(1)
        mostCommonRole = mostCommonTuple[0][0]

        return winCount, lastGame, mostCommonRole, mostCommonDeath, gamesPlayed, allDeaths

    async def viewPlayerStatsDeaths(self,discordId: int):
        """Werewolf function to collect information about a specific player's stats with regards to their death types
        Args:
            discordId (int): The discord if of the player whose stats you want to search for"""
        deathStatsReturn = []
        with sqlite3.connect(statsDb) as con:
            cur = con.cursor()
            res = cur.execute("SELECT causeOfDeath FROM playerStats WHERE playerID = ?",(discordId,))
            deathStats = res.fetchall()
            if deathStats == []:
                return None
            else:
                # Orders the results, makes them into a list that's easier to parse for future use
                deathStatsCounter = Counter(deathStats)
                deathStatsSorted = deathStatsCounter.most_common()
                for death, count in deathStatsSorted:
                    deathStatsReturn.append([death[0],count])
                return deathStatsReturn

    async def viewPlayerStatsRoles(self,discordId: int):
        """Werewolf function to collect information about a specific player's stats with regards to their role types
        Args:
            discordId (int): The discord if of the player whose stats you want to search for"""
        rolesToReturn = []
        with sqlite3.connect(statsDb) as con:
            cur = con.cursor()
            res = cur.execute("SELECT role FROM playerStats WHERE playerID = ?",(discordId,))
            roleStats = res.fetchall()
            if roleStats == []:
                return None
            else:
                # Orders the results, makes them into a list that's easier to parse for future use
                roleStatsCounter = Counter(roleStats)
                roleStatsSorted = roleStatsCounter.most_common()
                for role, count in roleStatsSorted:
                    rolesToReturn.append([role[0],count])
                print(rolesToReturn)
                return rolesToReturn

async def setup(bot):
    await bot.add_cog(werewolf(bot))