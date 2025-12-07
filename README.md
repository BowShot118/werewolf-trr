# Werewolf Bot v1.0.2
A Discord bot to run a game of "Werewolf", a variation of the "Town of Salem" game. Inspired by and intended to act as a replacement of https://github.com/belguawhale/Discord-Werewolf for the discord server for the NationStates region The Rejected Realms.

## Requirements
- Python 3.13+
- Discord.py
- SQLite 3.51+

## Features
- 3 Gamemodes (Default, Chaos, Orgy)
- 18 Unique Roles
- Per game and per player stats saving

A full breakdown of the bot's content can be found here: https://docs.google.com/document/d/1hkRtlS_WYfkbp0Q1lQLXpcJ4I5aVFPm9PuDvPkUpdr0/edit?tab=t.0#heading=h.k7x5ej1e1u3y

## Setup
- Download Python and the required library
- Download SQLite (https://sqlite.org/)
- Set up a discord application with a bot user, see instructions here: https://discordpy.readthedocs.io/en/stable/discord.html
- Download the repository
- Enter your server specific information into the "config.py.example" file and remove ".example" from its name
- Remove ".example" from the name of "werewolf.db.example" in the data folder

### Notes
- The entire werewolf game itself is contained entirely within the "werewolf.py" file in the "cogs" folder. This is because it is designed to seamlessly integrate into Sigil, TRR's existing discord bot. This is also why the database is in a "data" folder. This may allow you to integrate it into your own discord bot with relative ease, depending on how it is set up. The bot does work on its own, however, by running the "bot.py" file.
- Creating your own gamemode using existing roles can be done relatively easily. You will need to update the code in 3 areas:
  - Create your own gamemode dict (I recommend copying, pasting and renaming (keep the 'self.'!) "self.testing" as it is empty) and filling out the roles in the combinations you wish to see them appear in
  - Updating the "self.gamemodes" list (line 200) to add the name of your gamemode in all lower case
  - Update the "getModeRoles" function (line 2010) to associate the mode's name used in voting with the roles dictionary.
  - If there are any issues, check first that your roles dictionary/matrix looks like the others (self.default, self.chaos & self.orgy), then make sure you have used the same name in the changes to "getModeRoles" as you have for the changes to "self.gamemodes".
- May contain spelling mistakes


